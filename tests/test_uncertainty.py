import copy
import json
from pathlib import Path
import unittest
import numpy as np
from decision_brain.uncertainty import calibrate, prediction_set, validate_policy, diagnostics, quality_gate
from decision_brain.network import MultiDecisionNet, Config
from decision_brain.brain import judge
from decision_brain.edge_contracts import check_response

ROOT=Path(__file__).resolve().parents[1]

class UncertaintyChecks(unittest.TestCase):
    def setUp(self):
        self.spec=json.loads((ROOT/'config/brain.json').read_text())
        self.counts=[len(d['options']) for d in self.spec['decisions']]
        self.policy={'method':'class_conditional_split_conformal_v1','joint_alpha':.1,
                     'head_alpha':.1/len(self.counts),'temperature_rows':150,'conformal_rows':150,
                     'heads':[{'quantiles':[.45]*k,'class_counts':[150//k]*k} for k in self.counts]}
    def test_set_quantile_includes_boundary_and_rejects_empty(self):
        self.assertEqual(prediction_set([.55,.3,.15],{'quantiles':[.45]*3}),[0])
        self.assertEqual(prediction_set([.4,.3,.3],{'quantiles':[.45]*3}),[])
    def test_split_is_disjoint_and_complete(self):
        rng=np.random.default_rng(4);x=rng.normal(size=(150,4)).astype(np.float32)
        y=[rng.integers(k,size=150) for k in self.counts]
        net=MultiDecisionNet(4,Config(),1,self.counts)
        policy,audit=calibrate(net,x,y,42)
        self.assertFalse(set(audit['temperature_indices']) & set(audit['conformal_indices']))
        self.assertEqual(sorted(audit['temperature_indices']+audit['conformal_indices']),list(range(150)))
        self.assertTrue(all(a<=b+1e-8 for a,b in zip(audit['temperature_fit_loss_after'],audit['temperature_fit_loss_before'])))
        validate_policy(policy,self.counts)
    def test_rare_classes_stay_in_set(self):
        net=MultiDecisionNet(2,Config(),1,[3]);x=np.ones((10,2),np.float32)
        policy,_=calibrate(net,x,[np.zeros(10,dtype=int)],1)
        self.assertEqual(policy['heads'][0]['quantiles'],[1.,1.,1.])
        self.assertEqual(prediction_set([1.,0.,0.],policy['heads'][0]),[0,1,2])
    def test_ambiguous_set_routes_to_review_without_changing_probabilities(self):
        probabilities=[[.8,.1,.1],[.9,.1],[.8,.1,.1]]
        self.policy['heads'][0]['quantiles']=[.95]*3
        old=judge(self.spec,probabilities);new=judge(self.spec,probabilities,self.policy)
        self.assertFalse(any(v['needs_review'] for v in old['answers'].values()))
        self.assertEqual(new['proposed_action'],self.spec['routing']['review_action'])
        self.assertEqual(new['answers']['clasificacion']['probabilities'],old['answers']['clasificacion']['probabilities'])
        check_response({**new,'model_version':'v1'},self.spec,'v1')
    def test_clear_case_still_automates(self):
        value=judge(self.spec,[[.98,.01,.01],[.99,.01],[.98,.01,.01]],self.policy)
        self.assertFalse(any(a['needs_review'] for a in value['answers'].values()))
        check_response({**value,'model_version':'v1'},self.spec,'v1')
    def test_gate_cannot_erase_mandatory_review(self):
        value=judge(self.spec,[[.4,.3,.3],[.5,.5],[.4,.3,.3]],self.policy)
        value['answers']['clasificacion']['needs_review']=False
        with self.assertRaises(ValueError):check_response({**value,'model_version':'v1'},self.spec,'v1')
    def test_gate_rejects_fabricated_reason(self):
        value=judge(self.spec,[[.98,.01,.01],[.99,.01],[.98,.01,.01]],self.policy)
        value['answers']['clasificacion']['review_reasons']=['invented']
        with self.assertRaises(ValueError):check_response({**value,'model_version':'v1'},self.spec,'v1')
    def test_bad_saved_policy_fails_closed(self):
        for bad in (float('nan'),-1,2):
            policy=copy.deepcopy(self.policy);policy['heads'][0]['quantiles'][0]=bad
            with self.assertRaises(ValueError):validate_policy(policy,self.counts)
    def test_nominal_coverage_failure_blocks_quality(self):
        self.assertTrue(quality_gate({'joint_set_coverage':.74,'conformal_policy':{'automated':174}},self.policy))
        self.assertEqual(quality_gate({'joint_set_coverage':.95,'conformal_policy':{'automated':174}},self.policy),[])
    def test_zero_automation_has_no_fictitious_accuracy(self):
        policy=copy.deepcopy(self.policy)
        for h in policy['heads']:h['quantiles']=[1.]*len(h['quantiles'])
        p=[np.ones((5,k))/k for k in self.counts];y=[np.zeros(5,dtype=int) for k in self.counts]
        report=diagnostics(self.spec,p,y,policy)
        self.assertEqual(report['conformal_policy']['automated'],0)
        self.assertIsNone(report['conformal_policy']['selective_accuracy'])

if __name__=='__main__':unittest.main()
