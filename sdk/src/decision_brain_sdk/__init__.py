"""Synchronous SDK for Decision Brain 0.9. Never executes proposed actions."""
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit
import httpx

__version__='0.14.0'

class BrainError(Exception):
    """Controlled error without credential, context or server-body disclosure."""
    def __init__(self,code,status=None,request_id=None):
        self.code=code;self.status=status;self.request_id=request_id
        super().__init__(f'{code}'+(f' (HTTP {status})' if status is not None else ''))

class TransportError(BrainError):pass
class ProtocolError(BrainError):pass

@dataclass(frozen=True)
class PreparedDecision:
    body:bytes=field(repr=False)
    brain_id:str
    model_version:str
    idempotency_key:str
    traceparent:str
    path:str='v1/predict'

@dataclass(frozen=True)
class ChoiceAnswer:
    choice:str
    probabilities:dict
    confidence:float

@dataclass(frozen=True)
class ScoreAnswer:
    score:float
    probabilities:dict
    confidence:float
    legend:dict

@dataclass(frozen=True)
class NoulAnswer:
    noul:float

@dataclass(frozen=True)
class Decision:
    request_id:str
    brain_id:str
    model_version:str
    action:str
    needs_review:bool
    trace_id:str
    event_id:str
    answers:dict
    confidence:dict
    replayed:bool
    def question(self,name):
        a=self.answers[name]
        if a.get('type')=='choice':return ChoiceAnswer(a['choice'],a['probabilities'],a['confidence'])
        if a.get('type')=='score':return ScoreAnswer(a['score'],a['probabilities'],a['confidence'],a['legend'])
        if a.get('type')=='noul':return NoulAnswer(a['noul'])
        raise ProtocolError('typed_answer_unavailable_upgrade_server')
    def to_dict(self):
        from dataclasses import asdict
        return asdict(self)


def _identifier(value,pattern,label):
    if not isinstance(value,str) or not re.fullmatch(pattern,value):raise ValueError('invalid '+label)
    return value

def _fleet(path):
    folder=Path(path).resolve()
    return json.loads((folder/'fleet.json').read_text(encoding='utf-8')),json.loads((folder/'secrets.json').read_text(encoding='utf-8'))

class _Client:
    def __init__(self,url,token,*,timeout=15,verify=True,transport=None):
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:raise ValueError('invalid service URL')
        if parsed.scheme=='http' and parsed.hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('remote services require HTTPS')
        if not isinstance(token,str) or not token or any(ord(c)<33 or ord(c)>126 for c in token):raise ValueError('invalid token')
        if not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or timeout<=0:raise ValueError('invalid timeout')
        self._client=httpx.Client(base_url=url.rstrip('/')+'/',headers={'Authorization':'Bearer '+token},timeout=timeout,verify=verify,transport=transport,trust_env=False,follow_redirects=False)
    def close(self):self._client.close()
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def _request(self,method,path,**kwargs):
        try:r=self._client.request(method,path,**kwargs)
        except httpx.HTTPError:raise TransportError('transport_failure') from None
        if not 200<=r.status_code<300:
            # Never interpolate arbitrary server content into an exception.
            try:payload=r.json()
            except ValueError:payload={}
            if not isinstance(payload,dict):payload={}
            rid=r.headers.get('x-request-id') or payload.get('request_id')
            if not isinstance(rid,str) or not re.fullmatch('[0-9a-f]{32}',rid):rid=None
            allowed={'auth','authentication_required','caller_brain','version','idempotency_conflict','idempotency_pending',
                     'schema','size','traceparent','idempotency_key','event_mapping','event_trace','handoff_schema','handoff_range',
                     'handoff_collision','upstream_identity','upstream_rate_limit','upstream_unavailable','upstream_timeout',
                     'response_schema','response_size','catalog_or_quality','capacity','edge_unavailable','tls_required','content_type','body_timeout'}
            code=payload.get('error')
            raise BrainError(code if isinstance(code,str) and code in allowed else 'request_rejected',r.status_code,rid)
        return r
    def _json(self,path,**kwargs):
        r=self._request('GET',path,**kwargs)
        try:return r.json()
        except ValueError:raise ProtocolError('invalid_json') from None
    def ready(self):return self._json('ready')

class DecisionClient(_Client):
    @classmethod
    def from_fleet(cls,path='runtime/commerce-logistics',**kwargs):
        conf,keys=_fleet(path)
        return cls(f"http://127.0.0.1:{conf['gateway_port']}",keys['BRAIN_ORCHESTRATOR_TOKEN'],**kwargs)
    def catalog(self):
        data=self._json('v1/catalog')
        if not isinstance(data,dict) or not isinstance(data.get('brains'),list):raise ProtocolError('invalid_catalog')
        if any(not isinstance(row,dict) or not isinstance(row.get('brain_id'),str) or not isinstance(row.get('model_version'),str) for row in data['brains']):raise ProtocolError('invalid_catalog')
        return data['brains']
    def _version(self,brain_id,version):
        if version is not None:return _identifier(version,r'[a-zA-Z0-9_.-]{1,80}','version')
        match=next((x for x in self.catalog() if x.get('brain_id')==brain_id),None)
        if not match:raise BrainError('brain_not_active_or_authorized')
        return _identifier(match.get('model_version'),r'[a-zA-Z0-9_.-]{1,80}','version')
    def prepare(self,brain_id,context,*,idempotency_key,version=None,trace_id=None,handoff=None):
        _identifier(brain_id,r'[a-z][a-z0-9_.-]*','brain_id')
        _identifier(idempotency_key,r'[a-zA-Z0-9_.:-]{1,128}','idempotency_key')
        trace_id=trace_id or uuid.uuid4().hex
        _identifier(trace_id,r'[0-9a-f]{32}','trace_id')
        if int(trace_id,16)==0:raise ValueError('zero trace_id')
        if not isinstance(context,dict):raise ValueError('context must be an object')
        body={'brain_id':brain_id,'context':context}
        if handoff is not None:body['handoff']=handoff
        try:encoded=json.dumps(body,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
        except (ValueError,TypeError):raise ValueError('context must contain finite JSON values') from None
        if len(encoded)>65536:raise ValueError('request exceeds 64 KiB')
        return PreparedDecision(encoded,brain_id,self._version(brain_id,version),idempotency_key,f'00-{trace_id}-{uuid.uuid4().hex[:16]}-01')
    def send(self,prepared):
        if not isinstance(prepared,PreparedDecision):raise TypeError('PreparedDecision required')
        if prepared.path!='v1/predict' and not re.fullmatch(r'v1/events/[a-zA-Z0-9_.:-]{1,128}/predict',prepared.path):raise ValueError('invalid prepared path')
        headers={'Content-Type':'application/json','Accept-Version':prepared.model_version,'Idempotency-Key':prepared.idempotency_key,'traceparent':prepared.traceparent}
        r=self._request('POST',prepared.path,content=prepared.body,headers=headers)
        try:
            d=r.json()
            for key in ('request_id','brain_id','model_version','action','trace_id','event_id'):
                if not isinstance(d[key],str) or not d[key]:raise ValueError()
            if d['brain_id']!=prepared.brain_id or d['model_version']!=prepared.model_version or type(d['needs_review']) is not bool:raise ValueError()
            _identifier(d['trace_id'],r'[0-9a-f]{32}','trace_id')
            if not isinstance(d['answers'],dict) or not d['answers'] or not isinstance(d['confidence'],dict) or set(d['confidence'])!=set(d['answers']):raise ValueError()
            for name,answer in d['answers'].items():
                probs=answer['probabilities']
                if not isinstance(probs,dict) or not probs:raise ValueError()
                if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in probs.values()) or abs(sum(probs.values())-1)>1e-5:raise ValueError()
                if answer['choice'] not in probs or not math.isclose(probs[answer['choice']],max(probs.values()),abs_tol=1e-5):raise ValueError()
                kind=answer.get('type')
                if kind is not None:
                    if kind not in ('choice','score','noul'):raise ValueError()
                    if kind=='noul':
                        n=answer['noul']
                        if set(probs)!={'false','true'} or type(n) not in (int,float) or not math.isfinite(n) or not math.isclose(n,probs['true'],abs_tol=1e-6) or 'confidence' in answer:raise ValueError()
                    else:
                        total=sum(probs.values())
                        expected=max(0.0,min(1.0,1+sum((v/total)*math.log(v/total) for v in probs.values() if v>0)/math.log(len(probs))))
                        c=answer['confidence']
                        if type(c) not in (int,float) or not math.isfinite(c) or not math.isclose(c,expected,abs_tol=1e-6):raise ValueError()
                        if kind=='score':
                            legend=answer['legend'];score=answer['score']
                            if set(legend)!=set(probs):raise ValueError()
                            levels=[entry['level'] for entry in legend.values()]
                            if any(type(level) is not int for level in levels) or sorted(levels)!=list(range(len(probs))):raise ValueError()
                            if any(not isinstance(entry['description'],str) for entry in legend.values()):raise ValueError()
                            expected_score=sum(legend[key]['level']*v for key,v in probs.items())
                            if type(score) not in (int,float) or not math.isfinite(score) or not math.isclose(score,expected_score,abs_tol=1e-6):raise ValueError()
                value=d['confidence'][name]
                if type(value) not in (int,float) or not math.isfinite(value) or not math.isclose(value,max(probs.values()),abs_tol=1e-5):raise ValueError()
            replayed=r.headers.get('Idempotency-Replayed')=='true'
            if not replayed and d['trace_id']!=prepared.traceparent.split('-')[1]:raise ValueError()
            return Decision(**{k:d[k] for k in ('request_id','brain_id','model_version','action','needs_review','trace_id','event_id','answers','confidence')},replayed=replayed)
        except (ValueError,TypeError,KeyError,ZeroDivisionError,AttributeError):raise ProtocolError('invalid_decision_response') from None
    def predict(self,brain_id,context,**kwargs):return self.send(self.prepare(brain_id,context,**kwargs))
    def prepare_event(self,event_id,route_id,brain_id,*,idempotency_key,trace_id,version=None):
        _identifier(event_id,r'[a-zA-Z0-9_.:-]{1,128}','event_id')
        _identifier(route_id,r'[a-zA-Z0-9_.:-]{1,128}','route_id')
        request=self.prepare(brain_id,{},idempotency_key=idempotency_key,trace_id=trace_id,version=version)
        return PreparedDecision(json.dumps({'brain_id':brain_id,'route_id':route_id}).encode(),brain_id,request.model_version,idempotency_key,request.traceparent,f'v1/events/{event_id}/predict')

class ObserverClient(_Client):
    @classmethod
    def from_fleet(cls,path='runtime/commerce-logistics',**kwargs):
        conf,keys=_fleet(path)
        return cls(f"http://127.0.0.1:{conf['observer_port']}",keys['BRAIN_OBSERVER_TOKEN'],**kwargs)
    def dashboard(self):return self._json('v1/dashboard')
    def operations(self):return self._json('v1/operations')
    def decisions(self,brain_id,action=None):
        params={'brain_id':brain_id}
        if action is not None:params['action']=action
        return self._json('v1/decisions',params=params)
    def traces(self):return self._json('v1/traces')
    def trace(self,trace_id):
        _identifier(trace_id,r'[0-9a-f]{32}','trace_id')
        return self._json('v1/traces/'+trace_id)
    def metrics(self):return self._request('GET','metrics').text
    def deliveries(self,event_id=None):
        # Dashboard exposes the last 100 deliveries, not an unlimited history.
        rows=self.dashboard().get('deliveries',[])
        return rows if event_id is None else [r for r in rows if r['event_id']==event_id]

__all__=['ChoiceAnswer','ScoreAnswer','NoulAnswer','DecisionClient','ObserverClient','PreparedDecision','Decision','BrainError','TransportError','ProtocolError']
