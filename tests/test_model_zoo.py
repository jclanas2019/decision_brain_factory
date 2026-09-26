import copy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from decision_brain.model_zoo import AdvancedNet,Ensemble,AlgorithmRouter,describe,restore
from decision_brain.network import Config,MultiDecisionNet
from decision_brain.multi_training import choose_routes
from decision_brain.brain import judge
from decision_brain.edge_contracts import check_response

class ModelZooChecks(unittest.TestCase):
    def test_objective_gradients_finite_difference(self):
        rng=np.random.default_rng(4);x=rng.normal(size=(5,3));y=[np.array([0,1,2,1,0]),np.array([1,0,1,0,1])]
        for kind in ('corn','selective'):
            net=AdvancedNet(3,Config(hidden=4,decay=.002),42,[3,2],kind,[0] if kind=='corn' else [])
            net.params=[p.astype(np.float64) for p in net.params]
            _,grads=net.objective_and_grad(x,y)
            for j,p in enumerate(net.params):
                for ix in (tuple(0 for _ in p.shape),tuple(v-1 for v in p.shape)):
                    old=p[ix];eps=1e-5;p[ix]=old+eps;a=net.objective_and_grad(x,y)[0]
                    p[ix]=old-eps;b=net.objective_and_grad(x,y)[0];p[ix]=old
                    self.assertAlmostEqual((a-b)/(2*eps),grads[j][ix],places=5,msg=f'{kind} parameter {j} {ix}')
    def test_ordinal_probabilities_are_valid(self):
        net=AdvancedNet(3,Config(hidden=4),1,[5], 'corn',[0]);x=np.random.default_rng(7).normal(size=(30,3))
        p=net.predict(x)[0];self.assertTrue((p>=0).all());np.testing.assert_allclose(p.sum(1),1,atol=1e-6)
        survival=1-np.cumsum(p,axis=1);self.assertTrue((np.diff(survival,axis=1)<=0).all())
    def test_graph_reloads_exactly_and_preserves_selector(self):
        candidates={'neural':MultiDecisionNet(3,Config(hidden=4),1,[3,2]),
                    'corn':AdvancedNet(3,Config(hidden=4),1,[3,2],'corn',[0]),
                    'selective':AdvancedNet(3,Config(hidden=4),1,[3,2],'selective')}
        candidates['ensemble']=Ensemble([copy.deepcopy(candidates['neural']),MultiDecisionNet(3,Config(hidden=4),2,[3,2])])
        net=AlgorithmRouter(candidates,['corn','selective']);arrays={};meta=describe(net,arrays)
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'weights.npz';np.savez(p,**arrays)
            with np.load(p,allow_pickle=False) as archive:restored=restore(json.loads(json.dumps(meta)),archive,3)
        x=np.ones((4,3));
        for a,b in zip(net.predict(x),restored.predict(x)):np.testing.assert_array_equal(a,b)
        np.testing.assert_array_equal(net.review_scores(x)[1],restored.review_scores(x)[1])
    def test_graph_rejects_nonfinite_and_unknown_models(self):
        net=MultiDecisionNet(3,Config(hidden=4),1,[2]);arrays={};meta=describe(net,arrays)
        arrays['root_p0'][0,0]=np.nan
        with self.assertRaises(ValueError):restore(meta,arrays,3)
        meta['kind']='python_code'
        with self.assertRaises(ValueError):restore(meta,arrays,3)
    def test_router_uses_validation_and_minimum_gain(self):
        class Model:
            counts=[2]
            def __init__(self,p):self.p=p
            def predict(self,x):return [np.tile(self.p,(len(x),1))]
        candidates={'neural':Model([.6,.4]),'corn':Model([.8,.2])}
        routes,_=choose_routes(candidates,np.zeros((20,2)),[np.zeros(20,dtype=int)])
        self.assertEqual(routes,['corn'])
        routes,_=choose_routes(candidates,np.zeros((20,2)),[np.ones(20,dtype=int)])
        self.assertEqual(routes,['neural'])
    def test_three_algorithms_survive_registry_service_path(self):
        from decision_brain.brain import fit_encoder,encode,save,signature
        from decision_brain.artifacts import export_encoder
        from decision_brain.harness_suite_builder import build
        from decision_brain.releases import register,activate
        from decision_brain.service import ModelManager,Settings
        from dataclasses import asdict
        spec=json.loads((Path(__file__).resolve().parents[1]/'config/brain.json').read_text())
        state=build(spec)['cases'][0]['context'];enc=fit_encoder([state],spec);dim=encode([state],enc).shape[1]
        cfg=Config(hidden=4);counts=[len(d['options']) for d in spec['decisions']]
        base=MultiDecisionNet(dim,cfg,1,counts)
        candidates={'neural':base,'ensemble':Ensemble([base,MultiDecisionNet(dim,cfg,2,counts)]),
                    'corn':AdvancedNet(dim,cfg,1,counts,'corn',[2]),'selective':AdvancedNet(dim,cfg,1,counts,'selective')}
        net=AlgorithmRouter(candidates,['corn','ensemble','selective']);arrays={};graph=describe(net,arrays)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);model=root/'model';model.mkdir()
            save(model/'brain.json',spec);export_encoder(enc,model/'encoder.json')
            save(model/'model.json',{'contract_hash':signature(spec),'input_dim':dim,'counts':counts,'configuration':asdict(cfg),'model_graph':graph})
            save(model/'report.json',{'data_origin':'synthetic_demo'})
            np.savez(model/'weights.npz',**arrays)
            registry=root/'registry';register(registry,model,'v1','development');activate(registry,'v1','development')
            manager=ModelManager(Settings(registry,'x'*40,'development'))
            result=manager.predict(state);clean,_,_,_=check_response(result,spec,'v1')
            self.assertEqual([a['algorithm'] for a in clean.values()],['corn','ensemble','selective'])
            self.assertIn('selection_score',clean[spec['decisions'][2]['id']])

    def test_learned_rejection_reaches_response_gate(self):
        spec=json.loads((Path(__file__).resolve().parents[1]/'config/brain.json').read_text())
        result=judge(spec,[[.99,.005,.005],[.99,.01],[.99,.005,.005]],selection_scores=[.2,None,None])
        self.assertEqual(result['proposed_action'],spec['routing']['review_action'])
        check_response({**result,'model_version':'v'},spec,'v')
        result['answers']['clasificacion']['needs_review']=False
        with self.assertRaises(ValueError):check_response({**result,'model_version':'v'},spec,'v')

if __name__=='__main__':unittest.main()
