import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import httpx
from decision_brain.brain import judge
from decision_brain.edge_contracts import contract_hash,canonical
from decision_brain.gate_scaffold import write_config
from decision_brain.gateway import create_app
from decision_brain.observer import Observer,export_audit
from decision_brain.releases import register,activate,verify,verify_quality,digest
from decision_brain.harness_suite_builder import build

ROOT=Path(__file__).resolve().parents[1]
TOKEN='orchestrator-test-'+'a'*40
WORKER='worker-test-'+'b'*40
OTHER='other-test-'+'c'*40
OBS='observer-test-'+'d'*40
TRACE='1'*32

def put(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def read(path):return json.loads(path.read_text(encoding='utf-8'))

class GateTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture=tempfile.TemporaryDirectory();cls.fixture_root=Path(cls.fixture.name)
        cls.model_run=cls.fixture_root/'model'
        result=subprocess.run([sys.executable,'-m','decision_brain.brain','--config',str(ROOT/'config/presets/retail.json'),'demo','--rows','240','--trials','1','--epochs','4','--output',str(cls.model_run)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        cls.spec=read(cls.model_run/'brain.json');cls.context=build(cls.spec)['cases'][0]['context']
    @classmethod
    def tearDownClass(cls):cls.fixture.cleanup()
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,{'BRAIN_ORCHESTRATOR_TOKEN':TOKEN,'BRAIN_WORKER_TOKEN':WORKER,'BRAIN_RETAIL_TRIAJE_TOKEN':WORKER,'BRAIN_POSTVENTA_TOKEN':OTHER,'BRAIN_OBSERVER_TOKEN':OBS});self.env.start()
        write_config(self.root,self.spec,'retail.triaje')
        self.folder=self.root/'config/gates'
        gate=read(self.folder/'interop_gate.json');gate['pin_version_from']='registry.development';gate['event_facts']=['dias_desde_compra'];put(self.folder/'interop_gate.json',gate);put(self.folder/'interop_gate.development.json',gate)
        config=read(self.folder/'gateway.json');config['environment']='development';config['require_tls']=False;put(self.folder/'gateway.json',config)
        obs=read(self.folder/'observer.json');obs['environment']='development';put(self.folder/'observer.json',obs)
        self.registry=self.root/'registry/development';register(self.registry,self.model_run,'v1','development');activate(self.registry,'v1','development')
        self.calls=[];self.bad=None;self.delay=0
        async def upstream(request):
            if request.url.path=='/ready':return httpx.Response(200,json={'status':'ready'})
            self.calls.append(request)
            if self.delay:await asyncio.sleep(self.delay)
            value=judge(self.spec,[[1.,0,0],[1.,0],[1.,0,0]])
            value.update(brain_id=request.headers['x-brain-id'],contract_hash=contract_hash(self.spec),model_version=request.headers['accept-version'],request_id=request.headers['x-request-id'],trace_id=request.headers['traceparent'].split('-')[1])
            if self.bad:self.bad(value)
            return httpx.Response(200,json=value)
        self.transport=httpx.MockTransport(upstream)
        self.app=create_app(self.folder/'gateway.json',self.transport)
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://gate')
    async def asyncTearDown(self):
        await self.client.aclose();self.env.stop();self.tmp.cleanup()
    def headers(self,key='case-1',token=TOKEN):return {'Authorization':'Bearer '+token,'Accept-Version':'v1','Idempotency-Key':key,'traceparent':f'00-{TRACE}-2222222222222222-01'}
    async def predict(self,context=None,headers=None):return await self.client.post('/v1/predict',json={'brain_id':'retail.triaje','context':self.context if context is None else context},headers=headers or self.headers())
    async def test_envelope_trace_and_no_pii(self):
        r=await self.predict();self.assertEqual(r.status_code,200,r.text);value=r.json()
        self.assertEqual(value['trace_id'],TRACE);self.assertEqual(value['context'],{});self.assertEqual(value['action'],'cola_informacion')
        self.assertEqual(value['request_id'],value['correlation_id']);self.assertEqual(len(self.calls),1)
        with self.app.state.edge.store.connect() as db:record=dict(db.execute('SELECT * FROM decisions').fetchone())
        self.assertNotIn(self.context['mensaje'],str(record));self.assertEqual(json.loads(record['payload'])['routing_rule'],'rule:2')
    async def test_auth_and_brain_authorization(self):
        h=self.headers();h['Authorization']='Bearer invalid';self.assertEqual((await self.predict(headers=h)).status_code,401)
        gate=read(self.folder/'interop_gate.json');gate['allowed_callers']=['orchestrator'];put(self.folder/'interop_gate.json',gate);put(self.folder/'interop_gate.development.json',gate)
        self.assertEqual((await self.predict(headers=self.headers(token=OTHER))).status_code,403);self.assertEqual(len(self.calls),0)
    async def test_schema_size_and_version(self):
        self.assertEqual((await self.predict({'unknown':'x'})).status_code,422)
        c=dict(self.context,mensaje='a'*12001);self.assertEqual((await self.predict(c)).status_code,413)
        c=dict(self.context,dias_desde_compra=1e13);self.assertEqual((await self.predict(c)).status_code,413)
        h=self.headers();h['Accept-Version']='v0';self.assertEqual((await self.predict(headers=h)).status_code,409)
        self.assertEqual(len(self.calls),0)
    async def test_streamed_body_limit(self):
        async def chunks():
            yield b'x'*40000;yield b'x'*40000
        response=await self.client.post('/v1/predict',content=chunks(),headers={**self.headers(),'Content-Type':'application/json'})
        self.assertEqual(response.status_code,413)
    async def test_trace_required(self):
        h=self.headers();del h['traceparent'];self.assertEqual((await self.predict(headers=h)).status_code,422)
    async def test_idempotent_replay_and_conflict(self):
        a=await self.predict();b=await self.predict();self.assertEqual(a.json(),b.json());self.assertEqual(b.headers['Idempotency-Replayed'],'true');self.assertEqual(len(self.calls),1)
        self.assertEqual((await self.predict(dict(self.context,dias_desde_compra=999))).status_code,409)
    async def test_concurrent_same_key(self):
        self.delay=.05
        responses=await asyncio.gather(self.predict(),self.predict())
        self.assertEqual(sorted(r.status_code for r in responses),[200,409]);self.assertEqual(len(self.calls),1)
        self.assertEqual((await self.predict()).status_code,200);self.assertEqual(len(self.calls),1)
    async def test_idempotency_survives_restart(self):
        first=await self.predict()
        app=create_app(self.folder/'gateway.json',self.transport)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://gate') as client:
            response=await client.post('/v1/predict',json={'brain_id':'retail.triaje','context':self.context},headers=self.headers())
        self.assertEqual(first.json(),response.json());self.assertEqual(len(self.calls),1)
    async def test_pending_after_crash_not_reexecuted(self):
        edge=self.app.state.edge
        scope=canonical(['development','orchestrator','retail.triaje','case-1'])
        fingerprint=hashlib.sha256(canonical({'version':'v1','context':self.context,'event':None}).encode()).hexdigest()
        edge.store.reserve(scope,fingerprint)
        self.assertEqual((await self.predict()).status_code,409);self.assertEqual(len(self.calls),0)
    async def test_invalid_response_never_becomes_fallback(self):
        self.bad=lambda value:value.update(proposed_action='invented_queue')
        response=await self.predict();self.assertEqual(response.status_code,500);self.assertNotIn('action',response.json())
        with self.app.state.edge.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],0)
    async def test_invalid_probabilities(self):
        self.bad=lambda v:v['answers']['clasificacion']['probabilities'].update(consulta=.7)
        self.assertEqual((await self.predict()).status_code,500)
    async def test_wrong_response_correlation(self):
        self.bad=lambda v:v.update(trace_id='0'*32)
        self.assertEqual((await self.predict()).status_code,500)
    async def test_active_version_pin(self):
        register(self.registry,self.model_run,'v2','development');activate(self.registry,'v2','development')
        self.assertEqual((await self.predict()).status_code,409)
        h=self.headers();h['Accept-Version']='v2';r=await self.predict(headers=h);self.assertEqual(r.status_code,200);self.assertEqual(r.json()['model_version'],'v2')
    async def test_contract_drift(self):
        catalog=read(self.folder/'catalog.json');catalog['brains'][0]['contract_hash']='bad';put(self.folder/'catalog.json',catalog)
        self.assertEqual((await self.predict()).status_code,503);self.assertEqual(len(self.calls),0)
    async def test_immutable_audit_export_and_metrics(self):
        await self.predict();await self.predict()
        observer=Observer(self.folder/'observer.json');self.assertEqual(export_audit(observer.store,observer.audit),1);self.assertEqual(export_audit(observer.store,observer.audit),0)
        self.assertEqual(len(observer.audit.read_text().splitlines()),1);self.assertNotIn(self.context['mensaje'],observer.audit.read_text())
        self.assertIn('brain_predict_total{brain="retail.triaje",version="v1",action="cola_informacion",needs_review="false"} 1',observer.metrics())
        with self.assertRaises(sqlite3.DatabaseError):
            with observer.store.connect() as db:db.execute('DELETE FROM decisions')
    async def test_audit_tamper_detected(self):
        await self.predict();observer=Observer(self.folder/'observer.json');export_audit(observer.store,observer.audit)
        observer.audit.write_text(observer.audit.read_text().replace('cola_informacion','otra_cola'))
        with self.assertRaises(ValueError):export_audit(observer.store,observer.audit)
    async def test_event_maps_target_state(self):
        first=(await self.predict()).json()
        catalog=read(self.folder/'catalog.json');entry=copy.deepcopy(catalog['brains'][0]);entry['brain_id']='retail.destino';entry['endpoint']='http://worker-b';entry['interop_config']='target_gate.json';entry['environments']['development']['interop_config']='target_gate.json';catalog['brains'].append(entry);put(self.folder/'catalog.json',catalog)
        gate=read(self.folder/'interop_gate.json');gate['brain_id']='retail.destino';put(self.folder/'target_gate.json',gate)
        config=read(self.folder/'gateway.json');config['callers']['orchestrator']['brains'].append('retail.destino');put(self.folder/'gateway.json',config)
        put(self.folder/'routes.json',{'routes':[{'id':'route-1','source_brain':'retail.triaje','target_brain':'retail.destino','action':'cola_informacion','mapping':{'dias_desde_compra':{'fact':'dias_desde_compra'},'mensaje':{'literal':'Nuevo estado reconstruido'},'contexto':{'literal':'Proceso destino'}}}]})
        app=create_app(self.folder/'gateway.json',self.transport)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://gate') as client:
            r=await client.post('/v1/events/'+first['event_id']+'/predict',json={'brain_id':'retail.destino','route_id':'route-1'},headers=self.headers('event-1'))
        self.assertEqual(r.status_code,200,r.text)
        received=json.loads(self.calls[-1].content)['context'];self.assertEqual(received['mensaje'],'Nuevo estado reconstruido');self.assertEqual(received['dias_desde_compra'],self.context['dias_desde_compra'])
        self.assertNotIn('answers',received);self.assertEqual(r.json()['trace_id'],first['trace_id'])
    async def test_tls_required(self):
        config=read(self.folder/'gateway.json');config['require_tls']=True;put(self.folder/'gateway.json',config)
        app=create_app(self.folder/'gateway.json',self.transport)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://gate') as client:
            r=await client.post('/v1/predict',json={},headers=self.headers())
        self.assertEqual(r.status_code,426)
    async def test_harness_promotion_binds_artifacts(self):
        quality={'passed':True,'regressions':[],'pass_rate':1.0,'cases_count':1,'cases':[{'passed':True,'checks':{'fixture':True}}],
                 'model_sha256':{name:digest(self.model_run/name) for name in ('brain.json','model.json','encoder.json','weights.npz')},'suite_sha256':'a'*64}
        policy={'harness':{'min_pass_rate':1.0,'require_baseline':False,'approved_suite_sha256':['a'*64]}}
        self.assertTrue(verify_quality(self.model_run,quality,policy))
        bad=copy.deepcopy(quality);bad['passed']=False
        with self.assertRaises(ValueError):verify_quality(self.model_run,bad,policy)
        bad=copy.deepcopy(quality);bad['model_sha256']['weights.npz']='wrong'
        with self.assertRaises(ValueError):verify_quality(self.model_run,bad,policy)
        bad=copy.deepcopy(quality);bad['regressions']=['case']
        with self.assertRaises(ValueError):verify_quality(self.model_run,bad,policy)
        quality_path=self.root/'quality.json';put(quality_path,dict(quality,passed=False))
        with self.assertRaises(ValueError):register(self.root/'production',self.model_run,'bad','production',policy,{},quality_path)
        self.assertFalse((self.root/'production/versions/bad').exists())

    async def test_production_rechecks_quality_at_activation(self):
        # Controlled rule-engine fixture, not a production-quality data claim.
        model=self.root/'production-fixture';shutil.copytree(self.model_run,model)
        report=read(model/'report.json');report['data_origin']='user_supplied'
        # Explicit successful metrics fixture: this test verifies rechecking integrity,
        # not whether the tiny 4-epoch model is fit for production.
        report['selective_decisions']['joint_set_coverage']=1.
        report['selective_decisions']['conformal_policy']['automated']=1
        for metrics in report['metrics'].values():metrics['selective_accuracy']=1.
        put(model/'report.json',report)
        quality={'passed':True,'regressions':[],'pass_rate':1.,'cases_count':1,'cases':[{'passed':True,'checks':{'fixture':True}}],
                 'model_sha256':{name:digest(model/name) for name in ('brain.json','model.json','encoder.json','weights.npz')},'suite_sha256':'a'*64}
        qpath=self.root/'quality-pass.json';put(qpath,quality)
        policy={'min_test_rows':1,'min_rows_per_class':1,'default':{'min_accuracy':0,'max_log_loss':100,'min_baseline_gain':-1,'max_ece':1,'min_coverage':0,'min_selective_accuracy':0,'min_class_recall':0},
                'harness':{'min_pass_rate':1.,'require_baseline':False,'approved_suite_sha256':['a'*64]}}
        evidence={'dataset_sha256':report['dataset_sha256'],'harness_sha256':digest(qpath),'reviewer':'fixture','reviewed_at':'fixture','split_method':'fixture','business_acceptance':'fixture','real_data_confirmed':True}
        registry=self.root/'production'
        register(registry,model,'passed','production',policy,evidence,qpath);activate(registry,'passed','production');verify(registry,'passed','production')
        version=registry/'versions/passed';quality['passed']=False;put(version/'harness_report.json',quality)
        manifest=read(version/'manifest.json');manifest['hashes']['harness_report.json']=digest(version/'harness_report.json');put(version/'manifest.json',manifest)
        with self.assertRaises(ValueError):activate(registry,'passed','production')
        self.assertEqual(read(registry/'active.json')['version'],'passed') # no new pointer was written

    async def test_typed_state_and_duplicate_json(self):
        context=dict(self.context,dias_desde_compra=True)
        self.assertEqual((await self.predict(context)).status_code,422)
        response=await self.client.post('/v1/predict',content=b'{"brain_id":"retail.triaje","brain_id":"retail.triaje","context":{}}',headers={**self.headers(),'Content-Type':'application/json'})
        self.assertEqual(response.status_code,422)

    async def test_backend_version_race_rejected(self):
        async def changed(request):return httpx.Response(409,json={'error':'active_version_changed'})
        app=create_app(self.folder/'gateway.json',httpx.MockTransport(changed))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://gate') as client:
            response=await client.post('/v1/predict',json={'brain_id':'retail.triaje','context':self.context},headers=self.headers())
        self.assertEqual(response.status_code,409)

    async def test_low_confidence_keeps_safe_interop(self):
        def uncertain(value):
            value.update(judge(self.spec,[[.34,.33,.33],[.5,.5],[.34,.33,.33]]))
        self.bad=uncertain
        response=await self.predict();self.assertEqual(response.status_code,200);self.assertEqual(response.json()['action'],'revision_humana');self.assertTrue(response.json()['needs_review'])


    async def test_catalog_filters_authorized_brains(self):
        response=await self.client.get('/v1/catalog',headers=self.headers())
        self.assertEqual(response.status_code,200);entry=response.json()['brains'][0]
        self.assertEqual(entry['model_version'],'v1');self.assertNotIn('endpoint',entry)
        self.assertEqual((await self.client.get('/v1/catalog')).status_code,401)

    async def test_observer_marks_failed_quality_red(self):
        quality={'passed':False,'regressions':[],'model_sha256':{name:digest(self.model_run/name) for name in ('brain.json','model.json','encoder.json','weights.npz')}}
        q=self.root/'failed.json';put(q,quality)
        register(self.registry,self.model_run,'failed','development',harness=q);activate(self.registry,'failed','development')
        observer=Observer(self.folder/'observer.json',self.transport)
        status=(await observer.operations())[0]
        self.assertEqual(status['color'],'red');self.assertEqual(status['quality'],'fail')

    async def test_idempotency_scope_is_per_caller(self):
        one=await self.predict();two=await self.predict(headers=self.headers(token=OTHER))
        self.assertEqual(two.status_code,200);self.assertNotEqual(one.json()['request_id'],two.json()['request_id']);self.assertEqual(len(self.calls),2)

    async def test_per_brain_size_limit(self):
        gate=read(self.folder/'interop_gate.development.json');gate['limits']['max_body_bytes']=100;put(self.folder/'interop_gate.development.json',gate)
        self.assertEqual((await self.predict()).status_code,413);self.assertEqual(len(self.calls),0)


    async def test_handoff_contract_required_and_idempotent(self):
        gate=read(self.folder/'interop_gate.development.json');gate['handoff_fields']=[{'id':'purchase_age','type':'number'}];put(self.folder/'interop_gate.development.json',gate)
        self.assertEqual((await self.predict()).status_code,422)
        body={'brain_id':'retail.triaje','context':self.context,'handoff':{'purchase_age':7}}
        response=await self.client.post('/v1/predict',json=body,headers=self.headers());self.assertEqual(response.status_code,200)
        event=self.app.state.edge.store.event(response.json()['event_id']);self.assertEqual(event['facts']['purchase_age'],7)
        body['handoff']['purchase_age']=8
        self.assertEqual((await self.client.post('/v1/predict',json=body,headers=self.headers())).status_code,409)

    async def test_handoff_rejects_pii_extra_and_negative(self):
        gate=read(self.folder/'interop_gate.development.json');gate['handoff_fields']=[{'id':'purchase_age','type':'number'}];put(self.folder/'interop_gate.development.json',gate)
        for values in ({'purchase_age':-1},{'purchase_age':'personal text'},{'purchase_age':7,'note':'PII'}):
            response=await self.client.post('/v1/predict',json={'brain_id':'retail.triaje','context':self.context,'handoff':values},headers=self.headers())
            self.assertEqual(response.status_code,422)


if __name__=='__main__':unittest.main()
