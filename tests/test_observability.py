import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from decision_brain.telemetry import instrument,query_traces,provider,annotate,outgoing_headers,database
from decision_brain.observer import create_app

class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,{'BRAIN_TELEMETRY_DB':str(self.root/'traces.sqlite3'),'BRAIN_OBSERVER_TOKEN':'x'*40,'OTEL_TRACES_SAMPLER':'parentbased_always_on'});self.env.start()
        self.old={k:os.environ.pop(k,None) for k in ('OTEL_EXPORTER_OTLP_ENDPOINT','OTEL_EXPORTER_OTLP_TRACES_ENDPOINT')}
    def tearDown(self):
        for k,v in self.old.items():
            if v is not None:os.environ[k]=v
            else:os.environ.pop(k,None)
        self.env.stop();self.tmp.cleanup()
    def observer(self):
        (self.root/'catalog.json').write_text('{"version":1,"brains":[]}')
        (self.root/'observer.json').write_text(json.dumps({'environment':'development','catalog':'catalog.json','database':'edge.sqlite3','audit':'audit.jsonl','token_env':'BRAIN_OBSERVER_TOKEN'}))
        return create_app(self.root/'observer.json')
    def test_web_shell_assets_and_protected_data(self):
        with TestClient(self.observer()) as client:
            page=client.get('/');self.assertEqual(page.status_code,200);self.assertIn('frame-ancestors',page.headers['content-security-policy'])
            self.assertIn('Decisiones bajo observación',page.text)
            for path in ('/assets/app.js','/assets/style.css'):self.assertEqual(client.get(path).status_code,200)
            self.assertEqual(client.get('/assets/secret.json').status_code,404)
            for path in ('/v1/dashboard','/v1/traces','/v1/traces/'+'a'*32):self.assertEqual(client.get(path).status_code,401)
    def test_empty_dashboard_is_not_fake_green(self):
        with TestClient(self.observer()) as c:
            response=c.get('/v1/dashboard',headers={'Authorization':'Bearer '+'x'*40});self.assertEqual(response.status_code,200)
            d=response.json();self.assertEqual(d['operations'],[]);self.assertEqual(d['summary']['total'],0);self.assertIsNone(d['summary']['review_rate']);self.assertEqual(len(d['summary']['buckets']),60)
            self.assertEqual(response.headers['cache-control'],'no-store')
    def test_trace_id_validated(self):
        with TestClient(self.observer()) as c:
            h={'Authorization':'Bearer '+'x'*40}
            self.assertEqual(c.get('/v1/traces/not-a-trace',headers=h).status_code,422)
            self.assertEqual(c.get('/v1/traces/'+'a'*32,headers=h).json()['spans'],[])
    def test_w3c_parent_child_propagation_and_redaction(self):
        app=FastAPI();tracer=instrument(app,'gate');captured={}
        @app.post('/v1/predict')
        def predict():
            annotate(**{'brain.id':'test.brain','customer_note':'SECRET_PII'})
            with tracer.start_as_current_span('judge',record_exception=False):captured.update(outgoing_headers())
            return {'ok':True}
        with TestClient(app) as c:
            self.assertEqual(c.post('/v1/predict',headers={'traceparent':'00-'+'1'*32+'-'+'2'*16+'-01','Authorization':'Bearer SECRET_AUTH'},json={'context':'SECRET_PII'}).status_code,200)
        rows=query_traces(database(),'1'*32)['spans'];self.assertEqual(len(rows),2)
        parent=next(s for s in rows if s['name']=='gate');child=next(s for s in rows if s['name']=='judge')
        self.assertEqual(parent['parent_id'],'2'*16);self.assertEqual(child['parent_id'],parent['span_id'])
        self.assertEqual(captured['traceparent'].split('-')[1],'1'*32)
        self.assertNotIn('SECRET',json.dumps(rows));app.state.telemetry_provider.shutdown()
    def test_unsampled_parent_respected(self):
        app=FastAPI();instrument(app,'gate')
        @app.get('/v1/model')
        def model():return {}
        with TestClient(app) as c:c.get('/v1/model',headers={'traceparent':'00-'+'3'*32+'-'+'4'*16+'-00'})
        self.assertEqual(query_traces(database(),'3'*32)['spans'],[]);app.state.telemetry_provider.shutdown()
    def test_server_error_marks_span_without_recording_payload(self):
        app=FastAPI();instrument(app,'gate')
        @app.get('/v1/model')
        def model():raise ValueError('SECRET_PII')
        with TestClient(app,raise_server_exceptions=False) as c:self.assertEqual(c.get('/v1/model').status_code,500)
        traces=query_traces(database())['traces'];self.assertTrue(traces[0]['error']);self.assertNotIn('SECRET',json.dumps(query_traces(database(),traces[0]['trace_id'])))
        app.state.telemetry_provider.shutdown()
    def test_otlp_http_protobuf_export(self):
        received=[]
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append((self.path,self.rfile.read(int(self.headers['Content-Length']))));self.send_response(200);self.end_headers()
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        os.environ['OTEL_EXPORTER_OTLP_TRACES_ENDPOINT']=f'http://127.0.0.1:{server.server_port}/v1/traces'
        p=None
        try:
            p,_=provider('test-export')
            with p.get_tracer('test').start_as_current_span('gate'):annotate(**{'brain.id':'test.brain'})
            self.assertTrue(p.force_flush(10000));self.assertTrue(received);self.assertEqual(received[0][0],'/v1/traces')
            message=ExportTraceServiceRequest();message.ParseFromString(received[0][1]);self.assertEqual(message.resource_spans[0].scope_spans[0].spans[0].name,'gate')
        finally:
            if p:p.shutdown()
            server.shutdown();server.server_close();thread.join()
