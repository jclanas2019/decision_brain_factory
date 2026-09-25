"""Behavior checks for local Choice, Score and Noul through training and edges."""
import copy
import json
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx
import numpy as np
from decision_brain import brain
from decision_brain.contracts import read_spec,validate
from decision_brain.edge_contracts import check_response
from decision_brain.gate_scaffold import envelope_schemas
from decision_brain.harness import validate_suite,evaluate
from decision_brain.harness_suite_builder import build
from decision_brain_sdk import DecisionClient,ChoiceAnswer,ScoreAnswer,NoulAnswer,ProtocolError
ROOT=Path(__file__).resolve().parents[1]

class PrimitiveChecks(unittest.TestCase):
    def setUp(self):
        self.spec=read_spec(ROOT/'config/presets/retail.json')
        self.probs=[[.1,.7,.2],[.2,.8],[0,.57,.43]]
    def result(self):return brain.judge(self.spec,self.probs)
    def test_choice_confidence_is_not_max_probability(self):
        a=self.result()['answers']['clasificacion']
        expected=1+sum(p*math.log(p) for p in [.1,.7,.2])/math.log(3)
        self.assertAlmostEqual(a['confidence'],expected);self.assertEqual(a['choice'],'reclamacion')
        self.assertNotAlmostEqual(a['confidence'],a['max_probability'])
    def test_score_fractional_and_custom_value_compatibility(self):
        for i,o in enumerate(self.spec['decisions'][2]['options']):o['value']=10*(i+1)
        a=self.result()['answers']['nivel']
        self.assertAlmostEqual(a['score'],1.43);self.assertAlmostEqual(a['expected_score'],24.3)
        self.assertEqual(a['legend']['alto']['level'],2)
    def test_noul_extremes_and_ambiguity(self):
        for p in [0,.5,1]:
            self.probs[1]=[1-p,p];a=self.result()['answers']['atencion_prioritaria']
            self.assertEqual(a['noul'],p);self.assertNotIn('confidence',a)
            self.assertEqual(a['needs_review'],p==.5)
    def test_boolean_contract_stays_unchanged(self):
        self.spec['decisions'][1]['kind']='boolean';before=brain.signature(self.spec)
        validate(self.spec);a=self.result()['answers']['atencion_prioritaria']
        self.assertEqual(before,brain.signature(self.spec));self.assertEqual(a['kind'],'boolean')
        self.assertEqual(a['type'],'noul');self.assertEqual(a['probability_true'],a['noul'])
    def test_noul_rejects_nonbinary_contract(self):
        self.spec['decisions'][1]['options'][0]['id']='maybe'
        with self.assertRaises(ValueError):validate(self.spec)
    def test_gate_checks_all_typed_values(self):
        value={**self.result(),'model_version':'v1'}
        clean,*_=check_response(value,self.spec,'v1')
        self.assertAlmostEqual(clean['nivel']['score'],1.43)
        for head,key,bad in [('nivel','score',1.8),('nivel','legend',{}),('clasificacion','confidence',.7),('atencion_prioritaria','noul',float('nan')),('atencion_prioritaria','type','choice')]:
            broken=copy.deepcopy(value);broken['answers'][head][key]=bad
            with self.subTest(key=key),self.assertRaises(ValueError):check_response(broken,self.spec,'v1')
    def test_harness_numeric_ranges(self):
        suite={'version':1,'cases':[{'id':'mixed','context':build(self.spec)['cases'][0]['context'],
                 'expected':{'answers':{'nivel':{'score':{'min':1.4,'max':1.5}},'atencion_prioritaria':{'noul':{'min':.7,'max':.9}}}}}]}
        validate_suite(suite,self.spec)
        class Net:
            def predict(_self,x):return [np.array([p]) for p in self.probs]
        with patch('decision_brain.harness.encode',return_value=np.zeros((1,1))):
            self.assertTrue(evaluate((self.spec,None,Net()),suite)[0]['passed'])
            suite['cases'][0]['expected']['answers']['nivel']['score']['min']=1.45
            self.assertFalse(evaluate((self.spec,None,Net()),suite)[0]['passed'])
        suite['cases'][0]['expected']['answers']['nivel']['score']['max']=float('inf')
        with self.assertRaises(ValueError):validate_suite(suite,self.spec)
    def test_metrics_use_binary_brier_and_continuous_score_error(self):
        ps=[np.array([p]) for p in self.probs];ys=[np.array([1]),np.array([1]),np.array([2])]
        m=brain.evaluate(self.spec,ps,ys,ys)
        self.assertAlmostEqual(m['atencion_prioritaria']['brier'],.04)
        self.assertAlmostEqual(m['atencion_prioritaria']['log_loss'],-math.log(.8))
        self.assertAlmostEqual(m['nivel']['score_mae'],.57)
    def test_sdk_roundtrip_and_rejects_corruption(self):
        clean,action,*_=check_response({**self.result(),'model_version':'v1'},self.spec,'v1')
        def handler(r):
            payload={'request_id':'1'*32,'brain_id':'retail.triaje','model_version':'v1','action':action,'needs_review':True,
                     'trace_id':r.headers['traceparent'].split('-')[1],'event_id':'1'*32,'answers':clean,'confidence':{k:a['max_probability'] for k,a in clean.items()}}
            return httpx.Response(200,json=payload)
        with DecisionClient('http://localhost','test',transport=httpx.MockTransport(handler)) as client:
            kwargs={'version':'v1','idempotency_key':'typed'}
            d=client.predict('retail.triaje',{},**kwargs)
            self.assertIsInstance(d.question('clasificacion'),ChoiceAnswer)
            self.assertIsInstance(d.question('nivel'),ScoreAnswer)
            self.assertIsInstance(d.question('atencion_prioritaria'),NoulAnswer)
            self.assertAlmostEqual(d.question('nivel').score,1.43)
            clean['atencion_prioritaria']['noul']=.9
            with self.assertRaises(ProtocolError):client.predict('retail.triaje',{},**kwargs)
    def test_generated_schema_declares_typed_fields(self):
        schema=envelope_schemas(self.spec,'retail.triaje')[1]['properties']['answers']['properties']
        for head,key in [('clasificacion','confidence'),('nivel','score'),('atencion_prioritaria','noul')]:self.assertIn(key,schema[head]['required'])
    def test_training_reload_metrics_and_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);data=brain.generate(self.spec,200,12,folder/'data.csv')
            args=SimpleNamespace(output=folder/'run',data=data,seed=12,epochs=2,trials=1,log_every=2,origin='synthetic_demo')
            report=brain.train(args,self.spec)
            self.assertEqual(report['question_types']['atencion_prioritaria'],'noul')
            spec,enc,net=brain.load_model(args.output)
            parts=brain.read_dataset(data,spec);states=[r[0] for r in parts['test']]
            ps=net.predict(brain.encode(states,enc))
            ys=[np.array([row[1][i] for row in parts['test']]) for i in range(3)]
            expected=brain.evaluate(spec,ps,ys,ys)
            self.assertAlmostEqual(report['metrics']['nivel']['score_mae'],expected['nivel']['score_mae'])
            for e in report['search'][0]['epochs']:
                self.assertEqual(set(e['train_head_loss']),set(report['question_types']))
                self.assertAlmostEqual(e['train_loss'],np.mean(list(e['train_head_loss'].values())))
            rows=[json.loads(line) for line in (args.output/'predictions.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows),len(states));self.assertIn('noul',rows[0]['answers']['atencion_prioritaria'])
            html=(args.output/'report.html').read_text()
            self.assertIn('Choice, Score y Noul',html);self.assertIn('MAE de score',html)
            for head in report['question_types']:self.assertTrue((args.output/f'loss_{head}.png').is_file())
