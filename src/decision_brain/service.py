from decision_brain.telemetry import instrument, annotate
from opentelemetry import trace as otel_trace
from contextlib import nullcontext
"""Authenticated, bounded local inference service. No training/admin HTTP endpoints."""
import asyncio
from collections import deque
from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import threading
import time
import uuid
import sys
import re
from decision_brain.edge_contracts import trace_id,contract_hash

class VersionConflict(Exception):pass
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.concurrency import run_in_threadpool
from decision_brain.brain import load_model, encode, judge, infer_decision
from decision_brain.contracts import validate_state
from decision_brain.releases import verify

LOG=logging.getLogger('brain.audit')


@dataclass
class Settings:
    registry:Path
    api_key:str
    environment:str='production'
    max_body_bytes:int=65536
    max_text_chars:int=12000
    requests_per_minute:int=120
    max_inflight:int=4
    brain_id:str="local.brain"

    @classmethod
    def env(cls):
        secret=os.environ.get('BRAIN_API_KEY','')
        secret_file=os.environ.get('BRAIN_API_KEY_FILE')
        if secret_file:secret=Path(secret_file).read_text(encoding='utf-8').strip()
        return cls(Path(os.environ.get('BRAIN_REGISTRY','registry')),secret,
                   os.environ.get('BRAIN_MODE','production'),
                   int(os.environ.get('BRAIN_MAX_BODY_BYTES','65536')),
                   int(os.environ.get('BRAIN_MAX_TEXT_CHARS','12000')),
                   int(os.environ.get('BRAIN_REQUESTS_PER_MINUTE','120')),
                   int(os.environ.get('BRAIN_MAX_INFLIGHT','4')),
                   os.environ.get('BRAIN_ID','local.brain'))


class ModelManager:
    def __init__(self,settings):
        self.tracer=None;self.settings=settings;self.lock=threading.Lock();self.current=None
    def get(self):
        with self.lock:
            pointer=json.loads((self.settings.registry/'active.json').read_text(encoding='utf-8'))
            if pointer['environment']!=self.settings.environment:raise ValueError('environment mismatch')
            version=pointer['version']
            if self.current is None or self.current[0]!=version:
                folder,_=verify(self.settings.registry,version,self.settings.environment)
                spec,encoder,net=load_model(folder)
                self.current=(version,spec,encoder,net)
            return self.current
    def predict(self,state,expected_version=None):
        try:version,spec,enc,net=self.get()
        except Exception as error:raise RuntimeError('model_unavailable') from error
        if expected_version is not None and version!=expected_version:raise VersionConflict('active_version_changed')
        validate_state(state,spec)
        annotate(**{'brain.id':self.settings.brain_id,'model.version':version})
        with self.tracer.start_as_current_span('judge',record_exception=False,set_status_on_exception=False) if self.tracer else nullcontext():
            result=infer_decision(spec,enc,net,state)
            annotate(**{'brain.id':self.settings.brain_id,'model.version':version,'decision.action':result['proposed_action']})
        return {'model_version':version,'contract_hash':contract_hash(spec),**result}


class Boundary:
    """ASGI middleware bounds streamed bodies, authenticates and limits request rate."""
    def __init__(self,app,settings,counters):
        self.app=app;self.settings=settings;self.counters=counters;self.times=deque()
        self.key_hash=hashlib.sha256(settings.api_key.encode()).digest()
    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        start=time.perf_counter();request_id=uuid.uuid4().hex
        headers={k.lower():v for k,v in scope.get('headers',[])}
        supplied_id=headers.get(b'x-request-id',b'').decode('ascii',errors='ignore')
        if re.fullmatch('[0-9a-f]{32}',supplied_id):request_id=supplied_id
        trace=headers.get(b'traceparent',b'').decode('ascii',errors='ignore')
        try:trace_value=trace_id(trace) if trace else format(otel_trace.get_current_span().get_span_context().trace_id,'032x')
        except ValueError:trace_value=None
        annotate(**{'brain.id':self.settings.brain_id,'request.id':request_id})
        protected=scope['path'] not in ('/health','/ready')
        async def fail(code,message):
            self.counters['rejected']+=1
            LOG.info(json.dumps({'event':'request_rejected','request_id':request_id,'status':code,'reason':message}))
            return await JSONResponse({'error':message,'request_id':request_id},status_code=code,
                headers={'X-Request-ID':request_id,'Cache-Control':'no-store'})(scope,receive,send)
        if protected:
            supplied=headers.get(b'authorization',b'').decode('latin1')
            token=supplied[7:] if supplied.startswith('Bearer ') else ''
            if not hmac.compare_digest(hashlib.sha256(token.encode()).digest(),self.key_hash):
                return await fail(401,'authentication_required')
            now=time.monotonic()
            while self.times and self.times[0]<now-60:self.times.popleft()
            if len(self.times)>=self.settings.requests_per_minute:return await fail(429,'rate_limit')
            self.times.append(now)
        length=headers.get(b'content-length')
        if length:
            try:
                if int(length)>self.settings.max_body_bytes:return await fail(413,'body_too_large')
            except ValueError:return await fail(400,'invalid_content_length')
        chunks=[];size=0
        while True:
            try:message=await asyncio.wait_for(receive(),timeout=10)
            except asyncio.TimeoutError:return await fail(408,'request_body_timeout')
            if message['type']=='http.disconnect':return
            data=message.get('body',b'');size+=len(data)
            if size>self.settings.max_body_bytes:return await fail(413,'body_too_large')
            chunks.append(data)
            if not message.get('more_body',False):break
        body=b''.join(chunks);consumed=False;status=500
        async def bounded_receive():
            nonlocal consumed
            if not consumed:
                consumed=True;return {'type':'http.request','body':body,'more_body':False}
            return await receive()
        async def traced_send(message):
            nonlocal status
            if message['type']=='http.response.start':
                status=message['status'];message['headers']=list(message.get('headers',[]))+[
                    (b'x-request-id',request_id.encode()),(b'cache-control',b'no-store')]
            await send(message)
        scope.setdefault('state',{})['request_id']=request_id
        scope['state']['trace_id']=trace_value
        try:await self.app(scope,bounded_receive,traced_send)
        finally:
            self.counters['requests']+=1
            LOG.info(json.dumps({'request_id':request_id,'event':'http_request','status':status,
                                  'brain_id':self.settings.brain_id,'trace_id':trace_value,'span':'predict','duration_ms':round((time.perf_counter()-start)*1000,2)}))


def create_app(settings=None):
    settings=settings or Settings.env()
    if not LOG.handlers:
        handler=logging.StreamHandler(sys.stdout);handler.setFormatter(logging.Formatter('%(message)s'))
        LOG.addHandler(handler)
    LOG.setLevel(logging.INFO);LOG.propagate=False
    if len(settings.api_key)<32:raise RuntimeError('BRAIN_API_KEY must contain at least 32 characters')
    if settings.environment not in ('production','development'):raise RuntimeError('invalid BRAIN_MODE')
    if min(settings.max_body_bytes,settings.max_text_chars,settings.requests_per_minute,settings.max_inflight)<1:
        raise RuntimeError('limits must be positive')
    app=FastAPI(title='Decision Brain',docs_url=None,redoc_url=None,openapi_url=None)
    manager=ModelManager(settings);capacity=asyncio.Semaphore(settings.max_inflight)
    counters={'requests':0,'rejected':0,'predictions':0,'reviews':0}
    app.add_middleware(Boundary,settings=settings,counters=counters)
    manager.tracer=instrument(app,'predict')
    @app.get('/health')
    async def health():return {'status':'alive'}
    @app.get('/ready')
    async def ready():
        try:await run_in_threadpool(manager.get)
        except Exception:return JSONResponse({'status':'not_ready'},status_code=503)
        return {'status':'ready'}
    @app.get('/v1/model')
    async def model():
        try:version,spec,_,_=await run_in_threadpool(manager.get)
        except Exception:raise HTTPException(503,'model_unavailable')
        return {'version':version,'brain_id':settings.brain_id,'contract_hash':contract_hash(spec),'industry':spec['industry'],'fields':spec['fields'],'decisions':spec['decisions']}
    @app.get('/metrics',response_class=PlainTextResponse)
    async def metrics():
        return '\n'.join(f'brain_{k}_total {v}' for k,v in counters.items())+'\n'
    @app.post('/v1/predict')
    async def predict(request:Request):
        if request.headers.get('x-brain-id') and request.headers['x-brain-id']!=settings.brain_id:raise HTTPException(403,'wrong_brain')
        if request.headers.get('content-type','').split(';')[0].strip()!='application/json':raise HTTPException(415,'application/json required')
        try:
            value=await request.json()
            if not isinstance(value,dict) or set(value)!= {'context'} or not isinstance(value['context'],dict):
                raise ValueError('body must contain only a context object')
            if any(isinstance(v,str) and len(v)>settings.max_text_chars for v in value['context'].values()):
                raise ValueError('text field exceeds limit')
            if any(isinstance(v,(int,float)) and abs(v)>1e12 for v in value['context'].values()):
                raise ValueError('numeric magnitude exceeds service limit')
        except (ValueError,TypeError):raise HTTPException(422,'invalid_context')
        try:await asyncio.wait_for(capacity.acquire(),timeout=.05)
        except asyncio.TimeoutError:raise HTTPException(503,'inference_capacity_exceeded')
        try:
            try:
                if request.headers.get('accept-version'):
                    result=await run_in_threadpool(manager.predict,value['context'],expected_version=request.headers['accept-version'])
                else:result=await run_in_threadpool(manager.predict,value['context'])
            except VersionConflict:raise HTTPException(409,'active_version_changed')
            except ValueError:raise HTTPException(422,'context_does_not_match_contract')
            except Exception:raise HTTPException(503,'model_unavailable')
        finally:capacity.release()
        counters['predictions']+=1
        counters['reviews']+=int(any(a['needs_review'] for a in result['answers'].values()))
        result['request_id']=request.state.request_id
        result['trace_id']=request.state.trace_id
        result['brain_id']=settings.brain_id
        LOG.info(json.dumps({'event':'decision','brain_id':settings.brain_id,'span':'judge','trace_id':request.state.trace_id,'request_id':request.state.request_id,'model_version':result['model_version'],
                             'needs_review':any(a['needs_review'] for a in result['answers'].values())}))
        return result
    return app
