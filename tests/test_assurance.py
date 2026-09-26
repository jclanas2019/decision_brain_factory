"""Assurance checks using installed AutoEvals and the real bounded search loop."""
import copy
import inspect
import json
from pathlib import Path
import socket
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
from autoevals import ExactMatch
from decision_brain.autoeval_quality import exact,evaluate,gate
from decision_brain.autoresearch import policy_read,validate_proposal,acceptance,search,freeze_hash
from decision_brain.network import MultiDecisionNet,Config
from decision_brain.releases import check_gate,verify_quality,digest
from decision_brain.contracts import read_spec
ROOT=Path(__file__).resolve().parents[1]

class AssuranceChecks(unittest.TestCase):
    def setUp(self):
        self.spec=read_spec(ROOT/'config/presets/retail.json');self.policy=policy_read(ROOT/'config/research_policy.json')
    def test_real_autoevals_offline(self):
        with patch.object(socket.socket,'connect',side_effect=AssertionError('Network forbidden')):
            self.assertEqual(exact('consulta','consulta'),ExactMatch().eval(output='consulta',expected='consulta').score)
            self.assertEqual(exact('consulta','cancelacion'),0)
            scores=evaluate(self.spec['decisions'],[np.array([[0,1,0]]),np.array([[.2,.8]]),np.array([[0,.5,.5]])],[np.array([1]),np.array([1]),np.array([2])],True)
        self.assertEqual(scores['engine'],'autoevals');self.assertEqual(scores['heads']['clasificacion']['exact_match'],1)
        self.assertAlmostEqual(scores['heads']['atencion_prioritaria']['probability_quality'],.96)
        self.assertAlmostEqual(scores['heads']['nivel']['score_closeness'],.75)
        self.assertEqual(len(scores['cases']),3)
    def test_invalid_probabilities_fail_closed(self):
        with self.assertRaises(ValueError):evaluate(self.spec['decisions'],[np.array([[float('nan'),0,1]]),np.array([[.2,.8]]),np.array([[0,.5,.5]])],[np.array([1])]*3)
        self.assertTrue(gate({},self.policy['final_autoevals']))
    def test_policy_and_proposal_validation(self):
        for proposal in [{'hidden':64,'lr':.001,'decay':.001,'hypothesis':'x','test_threshold':0}, {'hidden':64,'lr':float('nan'),'decay':.001,'hypothesis':'x'}, {'hidden':999999,'lr':.001,'decay':.001,'hypothesis':'x'}]:
            with self.assertRaises(ValueError):validate_proposal(proposal,10)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'policy.json';bad=copy.deepcopy(self.policy);bad['seed_offsets']=[0];p.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):policy_read(p)
    def record(self,loss,head_loss=.4,exact_score=.9):
        return {'validation_loss':loss,'seeds':[{'seed':42,'loss':loss,'heads':{'q':{'loss':head_loss,'exact_match':exact_score}}}]}
    def test_reject_improvement_with_head_or_autoevals_regression(self):
        base=self.record(.5)
        self.assertFalse(acceptance(self.record(.4,head_loss=.5),base,self.policy)[0])
        self.assertFalse(acceptance(self.record(.4,exact_score=.8),base,self.policy)[0])
        self.assertTrue(acceptance(self.record(.4),base,self.policy)[0])
        self.assertFalse(acceptance(self.record(.5),base,self.policy)[0])
    def test_seed_regression_rejected(self):
        base=self.record(.5);c=self.record(.4);c['seeds'][0]['loss']=.6
        self.assertFalse(acceptance(c,base,self.policy)[0])
    def test_deadline(self):
        net=MultiDecisionNet(2,Config(epochs=1),42,[2]);x=np.ones((10,2));y=[np.zeros(10,dtype=int)]
        with self.assertRaises(TimeoutError):net.train(x,y,42,x,y,deadline=time.monotonic()-1)
    def test_search_receives_no_final_partitions_and_has_audit(self):
        self.assertNotIn('test',inspect.signature(search).parameters)
        self.assertNotIn('calibration',inspect.signature(search).parameters)
        x=np.array([[0,0],[1,0],[0,1],[1,1]]*8,dtype=np.float32)
        y=[np.array([0,1,0,1]*8)]
        spec={'decisions':[{'id':'q','kind':'choice','options':[{'id':'no'},{'id':'yes'}]}]}
        with tempfile.TemporaryDirectory() as tmp:
            net,cfg,records,selected=search(spec,x,y,x,y,seed=42,epochs=2,trials=2,log_every=100,folder=Path(tmp),policy=self.policy)
            self.assertIsNotNone(net);self.assertTrue(records[selected]['accepted'])
            self.assertEqual(len(records[0]['seeds']),2)
            evidence=json.loads((Path(tmp)/'research.json').read_text())
            self.assertEqual(evidence['experiments'],records)
            self.assertTrue(all(e['status']!='running' for e in evidence['experiments']))
            self.assertFalse(evidence['test_used_for_selection']);self.assertEqual(evidence['policy_sha256'],freeze_hash(self.policy))
            self.assertTrue((Path(tmp)/'results.tsv').is_file())
    def test_failed_candidate_preserves_incumbent(self):
        x=np.ones((10,2));y=[np.zeros(10,dtype=int)]
        spec={'decisions':[{'id':'q','kind':'choice','options':[{'id':'no'},{'id':'yes'}]}]}
        original=MultiDecisionNet.train;calls=[]
        def train(net,*args,**kwargs):
            calls.append(1)
            if len(calls)>2:raise ValueError('candidate failed')
            return original(net,*args,**kwargs)
        with tempfile.TemporaryDirectory() as tmp,patch.object(MultiDecisionNet,'train',train):
            _,_,records,selected=search(spec,x,y,x,y,seed=42,epochs=1,trials=2,log_every=100,folder=Path(tmp),policy=self.policy)
            self.assertEqual(selected,0);self.assertEqual(records[1]['status'],'error')
            self.assertFalse(records[1]['accepted'])
    def test_promotion_checks_assurance_model_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            for name in ('brain.json','model.json','encoder.json','weights.npz'):(folder/name).write_text('fixture')
            hashes={name:digest(folder/name) for name in ('brain.json','model.json','encoder.json','weights.npz')}
            (folder/'report.json').write_text(json.dumps({'assurance':{'artifact_sha256':hashes}}))
            quality={'passed':True,'regressions':[],'pass_rate':1.,'cases_count':1,'cases':[{'passed':True,'checks':{'fixture':True}}],
                     'model_sha256':hashes,'suite_sha256':'a'*64,'autoevals':{'engine':'autoevals'}}
            policy={'require_autoevals':True,'harness':{'require_baseline':False,'approved_suite_sha256':['a'*64]}}
            self.assertTrue(verify_quality(folder,quality,policy))
            corrupted=dict(hashes);corrupted['weights.npz']='0'*64
            (folder/'report.json').write_text(json.dumps({'assurance':{'artifact_sha256':corrupted}}))
            with self.assertRaisesRegex(ValueError,'assurance belongs'):verify_quality(folder,quality,policy)
    def test_promotion_requires_autoevals_harness(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError,'requires AutoEvals'):
                verify_quality(Path(tmp),{'passed':True,'regressions':[]},{'require_autoevals':True})
    def test_promotion_cannot_skip_autoevals(self):
        report={'metrics':{'q':{}},'split_sizes':{'test':1000}}
        policy=json.loads((ROOT/'config/promotion_policy.json').read_text())
        self.assertIn('AutoEvals assurance missing or failed',check_gate(report,policy,{}))
