"""Integration checks train a fixture; synthetic releases stay development-only."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import asyncio
import time
from unittest.mock import patch
import httpx
class LocalClient:
    """Exercise the ASGI app directly; this app has no lifespan hooks."""
    def __init__(self,app): self.app=app
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def request(self,method,path,**kwargs):
        async def send():
            content=kwargs.get('content')
            if content is not None and not isinstance(content,(str,bytes)):
                async def chunks():
                    for chunk in content: yield chunk
                kwargs['content']=chunks()
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='http://test') as client:
                return await client.request(method,path,**kwargs)
        return asyncio.run(send())
    def get(self,path,**kwargs): return self.request('GET',path,**kwargs)
    def post(self,path,**kwargs): return self.request('POST',path,**kwargs)

from decision_brain.service import Settings,create_app,ModelManager
from decision_brain.releases import register,activate,verify,check_gate

ROOT=Path(__file__).resolve().parents[1]
KEY='integration-test-only-'+'x'*40


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.base=Path(cls.tmp.name)
        config=ROOT/'config/presets'/'retail.json'
        cls.spec=json.loads(config.read_text(encoding='utf-8'))
        cls.run_dir=cls.base/'run'
        command=[sys.executable,'-m','decision_brain.brain','--config',str(config),'demo',
                 '--rows','240','--trials','1','--epochs','4','--output',str(cls.run_dir)]
        result=subprocess.run(command,cwd=ROOT,text=True,encoding="utf-8",capture_output=True)
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        cls.context=json.loads((cls.run_dir/'report.json').read_text(encoding='utf-8'))['scenarios'][0]['state']
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.registry=Path(tempfile.mkdtemp(dir=self.base))
        register(self.registry,self.run_dir,'v1','development')
        activate(self.registry,'v1','development')
    def client(self,**kwargs):
        return LocalClient(create_app(Settings(self.registry,KEY,'development',**kwargs)))
    def headers(self):return {'Authorization':'Bearer '+KEY}
    def test_auth_and_prediction(self):
        with self.client() as c:
            self.assertEqual(c.get('/health').status_code,200)
            self.assertEqual(c.get('/ready').status_code,200)
            self.assertEqual(c.post('/v1/predict',json={'context':self.context}).status_code,401)
            result=c.post('/v1/predict',json={'context':self.context},headers=self.headers())
            self.assertEqual(result.status_code,200,result.text)
            body=result.json();self.assertEqual(body['model_version'],'v1')
            self.assertEqual(set(body['answers']),{d['id'] for d in self.spec['decisions']})
            self.assertFalse(body['action_executed']);self.assertIn('x-request-id',result.headers)
            self.assertNotIn(KEY,result.text)
            self.assertEqual(c.get('/metrics',headers=self.headers()).status_code,200)
    def test_invalid_and_oversized(self):
        with self.client(max_body_bytes=4096) as c:
            invalid=dict(self.context,target__leak='known label')
            self.assertEqual(c.post('/v1/predict',json={'context':invalid},headers=self.headers()).status_code,422)
            response=c.post('/v1/predict',content=b'x'*5000,headers={**self.headers(),'Content-Type':'application/json'})
            self.assertEqual(response.status_code,413)
    def test_rate_limit(self):
        with self.client(requests_per_minute=1) as c:
            self.assertEqual(c.get('/v1/model',headers=self.headers()).status_code,200)
            self.assertEqual(c.get('/v1/model',headers=self.headers()).status_code,429)
    def test_streamed_body_limit(self):
        with self.client(max_body_bytes=4096) as c:
            response=c.post('/v1/predict',content=(b'x'*3000 for _ in range(2)),
                            headers={**self.headers(),'Content-Type':'application/json'})
            self.assertEqual(response.status_code,413)
    def test_concurrency_limit(self):
        original=ModelManager.predict
        def slow(manager,state):
            time.sleep(.2)
            return original(manager,state)
        app=create_app(Settings(self.registry,KEY,'development',max_inflight=1))
        async def requests():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as c:
                return await asyncio.gather(*[c.post('/v1/predict',json={'context':self.context},headers=self.headers()) for _ in range(3)])
        with patch.object(ModelManager,'predict',slow):responses=asyncio.run(requests())
        self.assertEqual(sorted(r.status_code for r in responses),[200,503,503])
    def test_gate_threshold_logic(self):
        # Rule-engine fixture, not a claimed production-quality trained model.
        policy=json.loads((ROOT/'config/promotion_policy.json').read_text(encoding='utf-8'))
        report={'data_origin':'user_supplied','dataset_sha256':'test-fixture','split_sizes':{'test':2000},
                'functional_test':{'serialization_passed':True},'metrics':{'decision':{
                    'accuracy':.95,'log_loss':.1,'baseline_accuracy':.5,'ece':.02,'coverage':.9,
                    'selective_accuracy':.97,'confusion_matrix':[[950,50],[50,950]]}}}
        evidence={'dataset_sha256':'test-fixture','real_data_confirmed':True,'reviewer':'test',
                  'reviewed_at':'2026-09-25','split_method':'test','business_acceptance':'test'}
        report['assurance']={'engine':'autoevals','passed':True,'test_used_for_selection':False,'scores':{'engine':'autoevals','schema_passed':True,'rows':2000,'heads':{'decision':{'exact_match':.95,'probability_quality':.95}}}}
        self.assertEqual(check_gate(report,policy,evidence),[])
        report['metrics']['decision']['selective_accuracy']=.6
        self.assertTrue(check_gate(report,policy,evidence))
    def test_hot_activation_and_rollback(self):
        register(self.registry,self.run_dir,'v2','development')
        with self.client() as c:
            self.assertEqual(c.get('/v1/model',headers=self.headers()).json()['version'],'v1')
            activate(self.registry,'v2','development')
            self.assertEqual(c.get('/v1/model',headers=self.headers()).json()['version'],'v2')
            previous=json.loads((self.registry/'active.json').read_text(encoding='utf-8'))['previous']
            activate(self.registry,previous,'development')
            self.assertEqual(c.get('/v1/model',headers=self.headers()).json()['version'],'v1')
    def test_synthetic_production_rejected(self):
        policy=json.loads((ROOT/'config/promotion_policy.json').read_text(encoding='utf-8'))
        with self.assertRaises(ValueError):register(self.registry,self.run_dir,'production-v1','production',policy,{})
        with LocalClient(create_app(Settings(self.registry,KEY,'production'))) as c:
            self.assertEqual(c.get('/ready').status_code,503)
    def test_integrity_failure(self):
        path=self.registry/'versions'/'v1'/'encoder.json'
        path.write_text('{}', encoding='utf-8')
        with self.assertRaises(ValueError):verify(self.registry,'v1','development')
        with self.client() as c:self.assertEqual(c.get('/ready').status_code,503)
    def test_immutable_release(self):
        with self.assertRaises(ValueError):register(self.registry,self.run_dir,'v1','development')
        with self.assertRaises(ValueError):activate(self.registry,'../escape','development')
    def test_weak_key_rejected(self):
        with self.assertRaises(RuntimeError):create_app(Settings(self.registry,'short'))


if __name__=='__main__':unittest.main()
