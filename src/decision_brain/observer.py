"""Separate observability process: consumes the durable outbox, exports audit and metrics."""
from contextlib import asynccontextmanager
import asyncio
import hashlib
import hmac
import json
import os
from pathlib import Path
import time
import re
import httpx
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import PlainTextResponse,JSONResponse,FileResponse
from decision_brain.telemetry import instrument, database, query_traces
from decision_brain.catalog import Catalog
from decision_brain.edge_store import Store
from decision_brain.edge_contracts import canonical

def quantile(values,p):
    if not values:return None
    ordered=sorted(values);index=(len(ordered)-1)*p;low=int(index);high=min(low+1,len(ordered)-1)
    return ordered[low]+(ordered[high]-ordered[low])*(index-low)

def export_audit(store,path):
    """Restart-safe export: DB is source of truth; JSONL chain is independently verifiable."""
    import fcntl
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        previous='0'*64;last=0
        if path.exists():
            with path.open('rb+') as stream:
                while True:
                    position=stream.tell();line=stream.readline()
                    if not line:break
                    if not line.endswith(b'\n'):
                        stream.truncate(position);break # only an incomplete crash tail
                    item=json.loads(line)
                    value={k:v for k,v in item.items() if k!='hash'}
                    expected=hashlib.sha256(canonical(value).encode()).hexdigest()
                    if item['hash']!=expected or item['previous_hash']!=previous or item['seq']<=last:raise ValueError('audit chain integrity failure')
                    previous=item['hash'];last=item['seq']
        with store.connect() as db:rows=db.execute('SELECT * FROM decisions WHERE seq>? ORDER BY seq',(last,)).fetchall()
        with path.open('a',encoding='utf-8') as stream:
            for row in rows:
                value={'seq':row['seq'],'timestamp':row['created'],'previous_hash':previous,**json.loads(row['payload'])}
                value['hash']=hashlib.sha256(canonical(value).encode()).hexdigest()
                stream.write(canonical(value)+'\n');stream.flush();os.fsync(stream.fileno());previous=value['hash']
        return len(rows)

class Observer:
    def __init__(self,path,transport=None):
        self.transport=transport
        self.path=Path(path).resolve();self.config=json.loads(self.path.read_text(encoding='utf-8'))
        self.store=Store(self.path.parent/self.config['database']);self.catalog=Catalog(self.path.parent/self.config['catalog'])
        self.audit=(self.path.parent/self.config['audit']).resolve();self.environment=self.config['environment']
        self.key=os.environ.get(self.config['token_env'],'')
        if len(self.key)<32:raise ValueError('missing observer secret')
        self.last_export_error=None
    def authorize(self,request):
        auth=request.headers.get('authorization','')
        supplied=auth[7:] if auth.startswith('Bearer ') else ''
        if not hmac.compare_digest(hashlib.sha256(supplied.encode()).digest(),hashlib.sha256(self.key.encode()).digest()):raise HTTPException(401,'auth')
    def snapshot(self):
        cutoff=time.time()-3600
        with self.store.connect() as db:
            decisions=[dict(r) for r in db.execute('SELECT * FROM decisions WHERE created>=?',(cutoff,))]
            traffic=[dict(r) for r in db.execute('SELECT * FROM traffic WHERE created>=?',(cutoff,))]
        return [dict(json.loads(r['payload']),timestamp=r['created']) for r in decisions],traffic
    def metrics(self):
        decisions,traffic=self.snapshot();lines=[];groups={}
        for r in decisions:
            key=(r['brain_id'],r['model_version'],r['action'],r['needs_review']);groups[key]=groups.get(key,0)+1
        def label(value):return json.dumps(str(value))
        lines+=['# TYPE brain_predict_total counter','# HELP brain_predict_total Unique committed decisions since gateway database creation.']
        # Counters are lifetime; gauges and quantiles use the last hour.
        with self.store.connect() as db:
            rows=db.execute("SELECT json_extract(payload,'$.brain_id') brain,json_extract(payload,'$.model_version') version,json_extract(payload,'$.action') action,json_extract(payload,'$.needs_review') review,COUNT(*) n FROM decisions GROUP BY brain,version,action,review").fetchall()
        totals={(r['brain'],r['version'],r['action'],bool(r['review'])):r['n'] for r in rows}
        for (brain,version,action,review),count in sorted(totals.items()):
            lines.append(f'brain_predict_total{{brain={label(brain)},version={label(version)},action={label(action)},needs_review={label(str(review).lower())}}} {count}')
        with self.store.connect() as db:rejections=db.execute("SELECT reason,COUNT(*) n FROM traffic WHERE status>=400 GROUP BY reason").fetchall()
        for r in rejections:lines.append(f'brain_reject_total{{reason={label(r[0])}}} {r[1]}')
        for brain in self.catalog.entries():
            selected=[r for r in decisions if r['brain_id']==brain];count=len(selected)
            timed=[r['seconds'] for r in traffic if r['brain']==brain and r['reason']!='replay']
            for p in (.5,.95):
                value=quantile(timed,p)
                if value is not None:lines.append(f'brain_latency_seconds{{brain={label(brain)},quantile="{p}"}} {value}')
            if count:
                lines.append(f'brain_review_rate{{brain={label(brain)}}} {sum(r["needs_review"] for r in selected)/count}')
                lines.append(f'brain_fallback_rate{{brain={label(brain)}}} {sum(r["fallback"] for r in selected)/count}')
                heads={}
                for r in selected:
                    for head,probs in r['probabilities'].items():heads.setdefault(head,[]).append(max(probs.values()))
                for head,values in heads.items():lines.append(f'brain_prob_max{{brain={label(brain)},head={label(head)}}} {sum(values)/len(values)}')
        return '\n'.join(lines)+'\n'
    async def operations(self):
        decisions,traffic=self.snapshot();result=[]
        async with httpx.AsyncClient(trust_env=False,timeout=3,transport=self.transport) as client:
            for bid,entry in self.catalog.entries().items():
                reasons=[];color='green';version=None;quality='unknown';slo_ok=False
                selected=[r for r in decisions if r['brain_id']==bid]
                calls=[r for r in traffic if r['brain']==bid and r['reason']!='replay']
                review=sum(r['needs_review'] for r in selected)/len(selected) if selected else None
                fallback=sum(r['fallback'] for r in selected)/len(selected) if selected else None
                p95=quantile([r['seconds'] for r in calls],.95)
                admitted=[r for r in calls if r['status']==200 or r['status']>=500]
                availability=sum(r['status']==200 for r in admitted)/len(admitted) if admitted else None
                try:
                    resolved=self.catalog.resolve(bid,self.environment);version=resolved['version'];quality=resolved['manifest'].get('quality') or 'unknown'
                    ready=await client.get(entry['endpoint'].rstrip('/')+'/ready')
                    if ready.status_code!=200:raise ValueError('upstream_not_ready')
                    slo=resolved['observe']['slo']
                    if quality=='fail':color='red';reasons.append('harness_fail')
                    elif quality!='pass':color='yellow';reasons.append('quality_unknown')
                    if not admitted:
                        if color!='red':color='yellow'
                        reasons.append('no_traffic')
                    else:
                        slo_ok=availability>=slo['availability'] and (p95 or 0)*1000<=min(slo['p95_ms'],entry['latency_sla_ms']) and (review or 0)<=slo['review_rate_max'] and (fallback or 0)<=slo.get('fallback_rate_max',.25)
                        if not slo_ok and color!='red':color='yellow';reasons.append('slo_degraded')
                    if any(r['reason'] in ('response_schema','catalog_or_quality','response_size') for r in calls):color='red';reasons.append('schema_or_contract_drift')
                    if entry.get('mode','active') in ('shadow','canary') and color!='red':color='yellow';reasons.append(entry['mode'])
                except Exception:color='red';reasons.append('pin_quality_contract_or_readiness')
                result.append({'brain_id':bid,'version':version,'color':color,'quality':quality,'slo_ok':slo_ok,'reasons':reasons,'window_seconds':3600,'decisions':len(selected),
                               'review_rate':review,'fallback_rate':fallback,'p95_ms':p95*1000 if p95 is not None else None,'availability':availability,
                               'online_ece':None,'online_ece_reason':'requires labelled outcomes',
                               'recommended_operation':'rollback_to_verified_previous' if color=='red' else 'inspect' if color=='yellow' else 'none'})
        return result

def create_app(config_path=None):
    observer=Observer(config_path or os.environ.get('BRAIN_OBSERVER_CONFIG','config/gates/observer.json'))
    async def export_loop():
        while True:
            try:await asyncio.to_thread(export_audit,observer.store,observer.audit);observer.last_export_error=None
            except Exception:observer.last_export_error='audit_export_failed'
            await asyncio.sleep(1)
    @asynccontextmanager
    async def lifespan(app):
        task=asyncio.create_task(export_loop())
        try:yield
        finally:
            task.cancel()
            try:await task
            except asyncio.CancelledError:pass
    app=FastAPI(title='Decision Brain Observer',docs_url=None,redoc_url=None,openapi_url=None,lifespan=lifespan);app.state.observer=observer
    instrument(app,'observer')
    web=Path(__file__).parent/'web'
    safe_headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
                  'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}
    @app.get('/')
    async def dashboard_page():return FileResponse(web/'index.html',headers=safe_headers)
    @app.get('/assets/{name}')
    async def asset(name:str):
        if name not in ('app.js','style.css'):raise HTTPException(404)
        return FileResponse(web/name,media_type='text/javascript' if name.endswith('.js') else 'text/css',headers=safe_headers)
    @app.get('/v1/dashboard')
    async def dashboard_data(request:Request):
        observer.authorize(request)
        operations=await observer.operations()
        decisions,traffic=observer.snapshot();now=time.time();minute=int(now//60)
        def aggregate(selected,calls):
            timed=[r['seconds'] for r in calls if r['reason']!='replay']
            p95=quantile(timed,.95)
            buckets=[{'minute':(minute-59+i)*60,'accepted':0,'rejected':0} for i in range(60)]
            for r in calls:
                index=int(r['created']//60)-(minute-59)
                if 0<=index<60:buckets[index]['rejected' if r['status']>=400 else 'accepted']+=1
            return {'total':len(selected),'rejected':sum(r['status']>=400 for r in calls),'p95_ms':p95*1000 if p95 is not None else None,
                    'review_rate':sum(r['needs_review'] for r in selected)/len(selected) if selected else None,'buckets':buckets}
        by_brain={o['brain_id']:aggregate([d for d in decisions if d['brain_id']==o['brain_id']],[r for r in traffic if r['brain']==o['brain_id']]) for o in operations}
        with observer.store.connect() as db:
            tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            deliveries=[dict(r) for r in db.execute('SELECT * FROM deliveries ORDER BY rowid DESC LIMIT 100')] if 'deliveries' in tables else []
            heartbeat=db.execute('SELECT last_seen FROM consumer_health WHERE id=1').fetchone()[0] if 'consumer_health' in tables else None
        consumer={'configured':heartbeat is not None,'alive':heartbeat is not None and now-heartbeat<60,'last_seen':heartbeat}
        return JSONResponse({'consumer':consumer,'deliveries':deliveries,'generated_at':now,'window_seconds':3600,'operations':operations,'summary':aggregate(decisions,traffic),'by_brain':by_brain,
                'decisions':sorted(decisions,key=lambda d:d['timestamp'],reverse=True)[:100]},headers={'Cache-Control':'no-store'})
    @app.get('/v1/traces')
    async def traces(request:Request):
        observer.authorize(request)
        return JSONResponse(await asyncio.to_thread(query_traces,database()),headers={'Cache-Control':'no-store'})
    @app.get('/v1/traces/{trace_value}')
    async def trace_detail(trace_value:str,request:Request):
        observer.authorize(request)
        if not re.fullmatch('[0-9a-f]{32}',trace_value):raise HTTPException(422,'invalid_trace_id')
        return JSONResponse(await asyncio.to_thread(query_traces,database(),trace_value),headers={'Cache-Control':'no-store'})
    @app.get('/health')
    async def health():return {'status':'alive','component':'observer'}
    @app.get('/ready')
    async def ready():
        try:
            with observer.store.connect() as db:db.execute('SELECT 1')
            if observer.last_export_error:raise ValueError()
        except Exception:return JSONResponse({'status':'not_ready'},status_code=503)
        return {'status':'ready'}
    @app.get('/metrics',response_class=PlainTextResponse)
    async def metrics(request:Request):observer.authorize(request);return observer.metrics()
    @app.get('/v1/operations')
    async def operations(request:Request):observer.authorize(request);return await observer.operations()
    @app.get('/v1/decisions')
    async def decisions(request:Request,brain_id:str,action:str=''):
        observer.authorize(request)
        if brain_id not in observer.catalog.entries():raise HTTPException(404,'brain')
        rows,_=observer.snapshot();matched=[r for r in rows if r['brain_id']==brain_id and (not action or r['action']==action)]
        return {'window_seconds':3600,'total':len(matched),'decisions':matched[-100:]}
    return app
