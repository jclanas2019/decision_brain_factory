"""Cross-platform regression checks for contracts, artifact loading and reports."""
import contextlib
import copy
from dataclasses import asdict
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from decision_brain import brain
from decision_brain.contracts import read_spec,validate,validate_state
from decision_brain.artifacts import export_encoder
from decision_brain.harness_suite_builder import build
from decision_brain.network import MultiDecisionNet,Config
from decision_brain.releases import check_gate
from decision_brain import launch
ROOT=Path(__file__).resolve().parents[1]

class CoreChecks(unittest.TestCase):
    def setUp(self):
        self.spec=read_spec(ROOT/'config/presets/retail.json')
    def test_all_presets(self):
        for path in (ROOT/'config/presets').glob('*.json'):read_spec(path)
    def test_labels_cannot_be_inputs(self):
        state=build(self.spec)['cases'][0]['context'];state['target__clasificacion']='consulta'
        with self.assertRaises(ValueError):validate_state(state,self.spec)
    def test_ordinal_values_ordered(self):
        self.spec['decisions'][2]['options'][1]['value']=-1
        with self.assertRaises(ValueError):validate(self.spec)
    def test_distinct_partition_templates(self):
        t=self.spec['synthetic_scenarios'][0]['context']['mensaje'];t['test']=t['train']
        with self.assertRaises(ValueError):validate(self.spec)
    def test_uncertainty_routes_to_review(self):
        result=brain.judge(self.spec,[[.34,.33,.33],[.5,.5],[.34,.33,.33]])
        self.assertEqual(result['proposed_action'],'revision_humana');self.assertFalse(result['action_executed'])
    def test_typed_outputs(self):
        r=brain.judge(self.spec,[[.01,.01,.98],[.05,.95],[.01,.09,.90]])
        self.assertEqual(r['proposed_action'],'revision_cancelacion')
        self.assertAlmostEqual(r['answers']['nivel']['expected_score'],1.89)
    def test_probability_contract(self):
        for probs in ([],[[float('nan')]*3,[.5,.5],[.34,.33,.33]],[[1,0,0],[1,0],[2,0,0]]):
            with self.assertRaises(ValueError):brain.judge(self.spec,probs)
    def test_empty_production_metrics_rejected(self):
        self.assertTrue(check_gate({'metrics':{}},{},{}))
    def test_invalid_artifact_temperature(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);state=build(self.spec)['cases'][0]['context']
            encoder=brain.fit_encoder([state],self.spec);dim=brain.encode([state],encoder).shape[1]
            counts=[len(d['options']) for d in self.spec['decisions']];cfg=Config()
            net=MultiDecisionNet(dim,cfg,42,counts)
            brain.save(folder/'brain.json',self.spec)
            brain.save(folder/'model.json',{'contract_hash':brain.signature(self.spec),'counts':counts,'input_dim':dim,'configuration':asdict(cfg)})
            export_encoder(encoder,folder/'encoder.json')
            np.savez(folder/'weights.npz',**{f'p{i}':p for i,p in enumerate(net.params)},temperature=[0,1,1])
            with self.assertRaises(ValueError):brain.load_model(folder)
    def test_utf8_log_and_relative_report_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'runs/session';folder.mkdir(parents=True)
            (folder/'checks.log').write_text('Configuración: revisión de decisión',encoding='utf-8')
            with patch.object(launch,'ROOT',root):launch.dashboard(folder,'Evaluación completada','APROBADAS',False,False)
            self.assertIn('Evaluación', (folder/'index.html').read_text(encoding='utf-8'))
            self.assertIn('runs/session/index.html',(root/'report.html').read_text(encoding='utf-8'))
    def test_utf8_subprocess_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            log=Path(tmp)/'log.txt'
            with contextlib.redirect_stdout(io.StringIO()):
                result=launch.step([__import__('sys').executable,'-c','print("Configuración y decisión")'],log,True)
            self.assertEqual(result,0);self.assertIn('decisión',log.read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
