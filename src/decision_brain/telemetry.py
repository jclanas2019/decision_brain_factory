"""Real OpenTelemetry spans, W3C propagation, local query store and optional OTLP/HTTP."""
import json
import os
from pathlib import Path
import sqlite3
import time
from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult, SimpleSpanProcessor, BatchSpanProcessor

PROPAGATOR=TraceContextTextMapPropagator()
SAFE={'brain.id','model.version','decision.action','decision.needs_review','decision.rule','request.id','http.request.method','http.response.status_code','http.route','error.type','gate.replayed'}

def database():return Path(os.environ.get('BRAIN_TELEMETRY_DB','registry/telemetry.sqlite3')).resolve()

def connect(path):
    db=sqlite3.connect(path,timeout=2);db.row_factory=sqlite3.Row
    return db

def initialize(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with connect(path) as db:
        db.executescript('PRAGMA journal_mode=WAL; CREATE TABLE IF NOT EXISTS spans(trace_id TEXT,span_id TEXT,parent_id TEXT,service TEXT,name TEXT,start_ns INTEGER,end_ns INTEGER,status TEXT,attributes TEXT,PRIMARY KEY(trace_id,span_id)); CREATE INDEX IF NOT EXISTS trace_time ON spans(start_ns);')
    db.close()

class SQLiteSpanExporter(SpanExporter):
    """Bounded to seven days; best effort telemetry is distinct from durable decision audit."""
    def __init__(self,path):self.path=Path(path);initialize(self.path);self.failures=0;self.last_prune=0
    def export(self,spans):
        try:
            with connect(self.path) as db:
                for s in spans:
                    attrs={k:v for k,v in s.attributes.items() if k in SAFE}
                    db.execute('INSERT OR REPLACE INTO spans VALUES(?,?,?,?,?,?,?,?,?)',(
                        format(s.context.trace_id,'032x'),format(s.context.span_id,'016x'),format(s.parent.span_id,'016x') if s.parent else None,
                        s.resource.attributes.get('service.name','unknown'),s.name,s.start_time,s.end_time,s.status.status_code.name,json.dumps(attrs)))
                if time.time()-self.last_prune>60:
                    db.execute('DELETE FROM spans WHERE start_ns<?',(time.time_ns()-7*86400*10**9,));self.last_prune=time.time()
            db.close();return SpanExportResult.SUCCESS
        except Exception:self.failures+=1;return SpanExportResult.FAILURE
    def shutdown(self):pass

def provider(service):
    p=TracerProvider(resource=Resource.create({'service.name':service,'service.version':'0.9.0'}))
    local=SQLiteSpanExporter(database());p.add_span_processor(SimpleSpanProcessor(local))
    endpoint=os.environ.get('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT')
    base=os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT')
    if endpoint or base:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        p.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint or base.rstrip('/')+'/v1/traces',timeout=3)))
    return p,local

def annotate(**values):
    span=trace.get_current_span()
    for key,value in values.items():
        if key in SAFE and value is not None:span.set_attribute(key,value)

def outgoing_headers():
    result={};PROPAGATOR.inject(result);return result

class TraceBoundary:
    def __init__(self,app,tracer,component):self.app=app;self.tracer=tracer;self.component=component
    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope['path'] in ('/health','/ready') or scope['path'].startswith('/assets/') or (self.component=='observer' and scope['path'] in ('/','/v1/dashboard','/v1/traces')):
            return await self.app(scope,receive,send)
        headers={k.decode('latin1'):v.decode('latin1') for k,v in scope['headers']}
        path=scope['path']
        route='/v1/events/{event_id}/predict' if path.startswith('/v1/events/') else '/v1/traces/{trace_id}' if path.startswith('/v1/traces/') else path if path in ('/','/metrics','/v1/predict','/v1/model','/v1/catalog','/v1/operations','/v1/dashboard','/v1/decisions','/v1/traces') else '/unknown'
        with self.tracer.start_as_current_span(self.component,context=PROPAGATOR.extract(headers),kind=SpanKind.SERVER,record_exception=False,set_status_on_exception=False) as span:
            span.set_attributes({'http.request.method':scope['method'],'http.route':route})
            async def traced_send(message):
                if message['type']=='http.response.start':
                    code=message['status'];span.set_attribute('http.response.status_code',code)
                    if code>=500:span.set_status(StatusCode.ERROR)
                await send(message)
            try:await self.app(scope,receive,traced_send)
            except BaseException:
                span.set_status(StatusCode.ERROR);span.set_attribute('error.type','request_failed');raise

def instrument(app,component):
    p,local=provider('decision-brain-'+component)
    tracer=p.get_tracer('decision_brain', '0.9.0')
    app.state.telemetry_provider=p;app.state.telemetry_exporter=local;app.state.tracer=tracer
    app.add_middleware(TraceBoundary,tracer=tracer,component=component)
    return tracer

def query_traces(path,trace_id=None):
    initialize(path)
    try:
        with connect(path) as db:
            if trace_id:
                rows=db.execute('SELECT * FROM spans WHERE trace_id=? ORDER BY start_ns LIMIT 1001',(trace_id,)).fetchall()
                return {'trace_id':trace_id,'truncated':len(rows)>1000,'spans':[dict(dict(r),attributes=json.loads(r['attributes'])) for r in rows[:1000]]}
            rows=db.execute("SELECT trace_id,MIN(start_ns) start_ns,MAX(end_ns) end_ns,COUNT(*) spans,MAX(status='ERROR') error FROM spans WHERE start_ns>=? GROUP BY trace_id ORDER BY start_ns DESC LIMIT 200",(time.time_ns()-3600*10**9,)).fetchall()
            return {'window_seconds':3600,'traces':[dict(r) for r in rows]}
    finally:db.close()
