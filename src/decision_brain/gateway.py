"""Global interoperability proxy. No training and no quality/metrics processing loop."""
import asyncio
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import time
import uuid
import httpx
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from decision_brain.catalog import Catalog
from decision_brain.edge_contracts import canonical,check_context,check_response,trace_id,KEY
from decision_brain.edge_store import Store
from decision_brain.telemetry import instrument, annotate, outgoing_headers

class Reject(Exception):
    def __init__(self,status,reason):self.status=status;self.reason=reason

class Edge:
    def __init__(self,config_path,transport=None):
        self.path=Path(config_path).resolve();self.config=json.loads(self.path.read_text(encoding='utf-8'))
        c=self.config
        if c.get('version')!=1:raise ValueError('unsupported_gateway_version')
        if c.get('max_inflight',0)<1:raise ValueError('invalid_concurrency_limit')
        if set(c['limits'])!={'max_body_bytes','max_text_chars','max_numeric_magnitude'} or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in c['limits'].values()):raise ValueError('invalid_global_limits')
        self.catalog=Catalog(self.path.parent/c['catalog']);self.store=Store(self.path.parent/c['database'])
        self.environment=c['environment'];self.transport=transport
        if self.environment not in ('production','development'):raise ValueError('invalid_environment')
        self.identities=[]
        for name,info in c['callers'].items():
            token=os.environ.get(info['token_env'],'')
            if len(token)<32:raise ValueError('missing or weak caller secret: '+info['token_env'])
            self.identities.append((name,hashlib.sha256(token.encode()).digest(),info['brains']))
        if len({digest for _,digest,_ in self.identities})!=len(self.identities):raise ValueError('caller tokens must be distinct')
        self.capacity=asyncio.Semaphore(c.get('max_inflight',16))
    def identity(self,request):
        auth=request.headers.get('authorization','');token=auth[7:] if auth.startswith('Bearer ') else ''
        supplied=hashlib.sha256(token.encode()).digest()
        for name,digest,brains in self.identities:
            if hmac.compare_digest(supplied,digest):return name,brains
        raise Reject(401,'auth')
    async def body(self,request):
        size=0;chunks=[]
        try:
            async with asyncio.timeout(10):
                async for part in request.stream():
                    size+=len(part)
                    if size>self.config['limits']['max_body_bytes']:raise Reject(413,'size')
                    chunks.append(part)
        except TimeoutError:raise Reject(408,'body_timeout')
        request.state.body_bytes=size
        if request.headers.get('content-type','').split(';')[0]!='application/json':raise Reject(415,'content_type')
        try:
            def reject_constant(value):raise ValueError(value)
            def unique(pairs):
                obj={}
                for k,v in pairs:
                    if k in obj:raise ValueError('duplicate_key')
                    obj[k]=v
                return obj
            result=json.loads(b''.join(chunks),parse_constant=reject_constant,object_pairs_hook=unique)
            if not isinstance(result,dict):raise ValueError()
            return result
        except (ValueError,UnicodeError):raise Reject(422,'schema')
    def mapped_context(self,event_id,body,bid,caller,route_hash=None):
        if set(body)!={'brain_id','route_id'}:raise Reject(422,'schema')
        try:
            event=self.store.event(event_id)
            if event['caller']!=caller:raise ValueError('event_identity')
            routes=json.loads((self.path.parent/self.config['routes']).read_text(encoding='utf-8'))['routes']
            route=next(r for r in routes if r['id']==body['route_id'])
            if route['source_brain']!=event['brain_id'] or route['action']!=event['action'] or route['target_brain']!=bid:raise ValueError()
            if route_hash and hashlib.sha256(json.dumps(route,sort_keys=True).encode()).hexdigest()!=route_hash:raise ValueError('route_changed')
            state={}
            for target,mapping in route['mapping'].items():
                if set(mapping)=={'fact'}:state[target]=event['facts'][mapping['fact']]
                elif set(mapping)=={'literal'}:state[target]=mapping['literal']
                elif set(mapping)=={'answer'}:state[target]=event['answers'][mapping['answer']]
                else:raise ValueError()
            return state,event
        except (KeyError,ValueError,StopIteration):raise Reject(422,'event_mapping')
    async def dispatch(self,request,event_id=None):
        started=time.perf_counter();bid=None;version=None;scope=None;request_id=uuid.uuid4().hex;trace=None
        try:
            if self.config.get('require_tls',self.environment=='production') and request.url.scheme!='https':raise Reject(426,'tls_required')
            caller,authorized=self.identity(request)
            body=await self.body(request)
            requested=body.get('brain_id')
            if not isinstance(requested,str):raise Reject(422,'schema')
            entries=self.catalog.entries()
            if requested not in entries:raise Reject(404,'brain')
            if requested not in authorized:raise Reject(403,'caller_brain')
            bid=requested
            try:snapshot=self.catalog.resolve(bid,self.environment)
            except Exception:raise Reject(503,'catalog_or_quality')
            gate=snapshot['gate'];spec=snapshot['spec'];version=snapshot['version']
            if caller not in gate['allowed_callers']:raise Reject(403,'caller_brain')
            try:trace=trace_id(request.headers.get('traceparent'))
            except ValueError:raise Reject(422,'traceparent')
            accepted=request.headers.get('accept-version')
            if accepted!=version:raise Reject(409,'version')
            idem=request.headers.get('idempotency-key','')
            if not KEY.fullmatch(idem):raise Reject(422,'idempotency_key')
            source_event=None
            if event_id:
                context,source_event=self.mapped_context(event_id,body,bid,caller,request.headers.get('x-route-hash'))
                if source_event['trace_id']!=trace:raise Reject(422,'event_trace')
            else:
                expected={'brain_id','context'}|({'handoff'} if gate.get('handoff_fields') else set())
                if set(body)!=expected:raise Reject(422,'schema')
                context=body['context']
            limits={k:min(self.config['limits'][k],gate.get('limits',{}).get(k,self.config['limits'][k])) for k in self.config['limits']}
            if request.state.body_bytes>limits['max_body_bytes']:raise Reject(413,'size')
            try:check_context(context,spec,limits)
            except OverflowError:raise Reject(413,'size')
            except (ValueError,TypeError):raise Reject(422,'schema')
            handoff={}
            if not event_id and gate.get('handoff_fields'):
                handoff=body['handoff']
                try:check_context(handoff,{'fields':gate['handoff_fields']},limits)
                except OverflowError:raise Reject(413,'size')
                except (ValueError,TypeError):raise Reject(422,'handoff_schema')
                if any(v<0 for v in handoff.values()):raise Reject(422,'handoff_range')
                if set(handoff)&set(context):raise Reject(422,'handoff_collision')
            scope=canonical([self.environment,caller,bid,idem])
            fingerprint=hashlib.sha256(canonical({'version':version,'context':context,'handoff':handoff,'event':event_id}).encode()).hexdigest()
            state,cached=self.store.reserve(scope,fingerprint)
            if state=='conflict':scope=None;raise Reject(409,'idempotency_conflict')
            if state=='pending':scope=None;raise Reject(409,'idempotency_pending')
            if state=='replay':
                scope=None;self.store.traffic(bid,version,cached[0],'replay',time.perf_counter()-started)
                return JSONResponse(cached[1],status_code=cached[0],headers={'Idempotency-Replayed':'true','X-Request-ID':cached[1]['request_id'],'Cache-Control':'no-store'})
            upstream_key=os.environ.get(snapshot['entry']['upstream_token_env'],'')
            if len(upstream_key)<32:raise Reject(503,'upstream_identity')
            annotate(**{'brain.id':bid,'model.version':version,'request.id':request_id})
            propagated=outgoing_headers()
            span=propagated.get('traceparent',f'00-{trace}-{uuid.uuid4().hex[:16]}-01').split('-')[2]
            headers={'Authorization':'Bearer '+upstream_key,'Accept-Version':version,'X-Request-ID':request_id,'X-Brain-ID':bid,'traceparent':propagated.get('traceparent',f'00-{trace}-{span}-01')}
            try:
                await asyncio.wait_for(self.capacity.acquire(),.1)
            except TimeoutError:raise Reject(503,'capacity')
            try:
                async with httpx.AsyncClient(trust_env=False,transport=self.transport,timeout=self.config.get('upstream_timeout_seconds',10),follow_redirects=False) as client:
                    async with client.stream('POST',snapshot['entry']['endpoint'].rstrip('/')+'/v1/predict',headers=headers,json={'context':context}) as response:
                        if response.status_code==429:raise Reject(429,'upstream_rate_limit')
                        if response.status_code==409:raise Reject(409,'version')
                        if response.status_code!=200:raise Reject(503,'upstream_unavailable')
                        raw=bytearray()
                        async for part in response.aiter_bytes():
                            raw.extend(part)
                            if len(raw)>self.config.get('max_response_bytes',262144):raise Reject(500,'response_size')
                        result=json.loads(raw)
            except httpx.TimeoutException:raise Reject(504,'upstream_timeout')
            except httpx.HTTPError:raise Reject(503,'upstream_unavailable')
            except (ValueError,UnicodeError):raise Reject(500,'response_schema')
            finally:self.capacity.release()
            try:
                answers,action,rule,fallback=check_response(result,spec,version)
                if result.get('brain_id')!=bid or result.get('contract_hash')!=snapshot['entry']['contract_hash']:raise ValueError('worker_identity_contract')
                if result.get('request_id')!=request_id or result.get('trace_id')!=trace:raise ValueError('correlation')
            except (ValueError,TypeError,KeyError):raise Reject(500,'response_schema')
            # Never convert an invalid response into a fabricated fallback action.
            review=any(a['needs_review'] for a in answers.values())
            envelope={'request_id':request_id,'correlation_id':request_id,'brain_id':bid,'model_version':version,
                      'context':{},'answers':answers,'action':action,'needs_review':review,
                      'confidence':{k:a['max_probability'] for k,a in answers.items()},'trace_id':trace,'event_id':request_id}
            event={'caller':caller,'type':'decision.made','event_id':request_id,'brain_id':bid,'model_version':version,'trace_id':trace,'action':action,
                   'facts':{**{k:context[k] for k in gate.get('event_facts',[])},**handoff},'answers':{k:a['choice'] for k,a in answers.items()}}
            if rule.startswith('rule:'):
                fired=spec['routing']['rules'][int(rule.split(':')[1])]
                routing_evidence={'decision':fired['decision'],'option':fired['option'],'probability':answers[fired['decision']]['probabilities'][fired['option']],'threshold':fired.get('min_probability',.65)}
            elif rule=='review':routing_evidence={'uncertain_heads':{d['id']:{'confidence':answers[d['id']]['max_probability'],'threshold':d.get('min_probability',.6)} for d in spec['decisions'] if answers[d['id']]['needs_review']}}
            else:routing_evidence={'reason':'no_rule_reached_threshold'}
            audit={'routing_evidence':routing_evidence,'request_id':request_id,'trace_id':trace,'span':'gate','gate_span_id':span,'upstream_parent_span_id':span,'brain_id':bid,'model_version':version,
                   'contract_hash':snapshot['entry']['contract_hash'],'action':action,'needs_review':review,'fallback':fallback,
                   'probabilities':{k:a['probabilities'] for k,a in answers.items()},'routing_rule':rule,
                   'quality':snapshot['manifest'].get('quality') or 'unknown','shadow':None,
                   'source_event_id':event_id,'latency_seconds':time.perf_counter()-started}
            annotate(**{'decision.action':action,'decision.needs_review':review,'decision.rule':rule})
            self.store.complete(scope,200,envelope,audit,event);scope=None
            self.store.traffic(bid,version,200,'accepted',time.perf_counter()-started)
            return JSONResponse(envelope,headers={'X-Request-ID':request_id,'Cache-Control':'no-store'})
        except Reject as exc:
            payload={'error':exc.reason,'correlation_id':request_id,'request_id':request_id,'brain_id':bid,'model_version':version,'trace_id':trace}
            if scope:self.store.complete(scope,exc.status,payload)
            self.store.traffic(bid,version,exc.status,exc.reason,time.perf_counter()-started)
            return JSONResponse(payload,status_code=exc.status,headers={'Cache-Control':'no-store'})
        except Exception:
            # A reserved request stays pending after uncertain persistence: do not repeat inference.
            return JSONResponse({'error':'edge_unavailable','request_id':request_id,'correlation_id':request_id,'brain_id':bid,'model_version':version,'trace_id':trace},status_code=503)


def create_app(config_path=None,transport=None):
    edge=Edge(config_path or os.environ.get('BRAIN_GATEWAY_CONFIG','config/gates/gateway.json'),transport)
    app=FastAPI(title='Decision Brain Interop Gate',docs_url=None,redoc_url=None,openapi_url=None);app.state.edge=edge
    instrument(app,'gate')
    @app.get('/health')
    async def health():return {'status':'alive','component':'interop'}
    @app.get('/ready')
    async def ready():
        try:
            entries=edge.catalog.entries()
            if not entries:raise ValueError()
            with edge.store.connect() as db:db.execute('SELECT 1')
            async with httpx.AsyncClient(trust_env=False,transport=transport,timeout=3) as client:
                for bid in entries:
                    snapshot=edge.catalog.resolve(bid,edge.environment)
                    response=await client.get(snapshot['entry']['endpoint'].rstrip('/')+'/ready')
                    if response.status_code!=200:raise ValueError()
                    secret=os.environ.get(snapshot['entry']['upstream_token_env'],'')
                    model=await client.get(snapshot['entry']['endpoint'].rstrip('/')+'/v1/model',headers={'Authorization':'Bearer '+secret})
                    data=model.json()
                    if model.status_code!=200 or data.get('version')!=snapshot['version'] or data.get('brain_id')!=bid or data.get('contract_hash')!=snapshot['entry']['contract_hash']:raise ValueError()
        except Exception:return JSONResponse({'status':'not_ready'},status_code=503)
        return {'status':'ready'}
    @app.get('/v1/catalog')
    async def catalog(request:Request):
        try:
            if edge.config.get('require_tls',edge.environment=='production') and request.url.scheme!='https':raise Reject(426,'tls_required')
            caller,allowed=edge.identity(request);items=[]
            for bid in allowed:
                try:
                    resolved=edge.catalog.resolve(bid,edge.environment)
                    if caller not in resolved['gate']['allowed_callers']:continue
                    entry=resolved['entry']
                    items.append({'brain_id':bid,'model_version':resolved['version'],'contract_hash':entry['contract_hash'],'owner':entry['owner'],'latency_sla_ms':entry['latency_sla_ms'],'actions':entry['actions']})
                except (KeyError,ValueError,OSError):continue
            return {'environment':edge.environment,'brains':items}
        except Reject as exc:return JSONResponse({'error':exc.reason},status_code=exc.status)

    @app.post('/v1/predict')
    async def predict(request:Request):return await edge.dispatch(request)
    @app.post('/v1/events/{event_id}/predict')
    async def from_event(event_id:str,request:Request):return await edge.dispatch(request,event_id)
    return app
