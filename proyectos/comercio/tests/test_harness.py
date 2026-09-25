import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from decision_brain import harness
from decision_brain.harness_suite_builder import build

ROOT=Path(__file__).resolve().parents[1]

class HarnessChecks(unittest.TestCase):
    def setUp(self):
        path=ROOT/'config/presets/retail.json'
        self.spec=json.loads(path.read_text(encoding='utf-8'))
        self.suite=build(self.spec)
        self.good=[]
        for d in self.spec['decisions']:
            target=self.suite['cases'][0]['expected']['answers'][d['id']]
            self.good.append(np.array([[float(o['id']==target) for o in d['options']]]))
        class Net:
            def __init__(self,probs):self.probs=probs
            def predict(self,x):return self.probs
        self.model=(self.spec,None,Net(self.good))
        self.suite['cases']=self.suite['cases'][:1]+self.suite['cases'][-1:]
    def test_invalid_suite(self):
        for modify in (lambda s:s.update(cases=[]),lambda s:s['cases'].append(s['cases'][0]),lambda s:s['cases'][0].update(expected={})):
            s=copy.deepcopy(self.suite);modify(s)
            with self.assertRaises(ValueError):harness.validate_suite(s,self.spec)
    @patch('decision_brain.harness.encode',return_value=None)
    def test_decisions_and_rejection(self,_):
        harness.validate_suite(self.suite,self.spec)
        self.assertTrue(all(r['passed'] for r in harness.evaluate(self.model,self.suite)))
    @patch('decision_brain.harness.encode',return_value=None)
    def test_wrong_action_fails(self,_):
        self.suite['cases'][0]['expected']['action']='not_the_route'
        self.assertFalse(harness.evaluate(self.model,self.suite)[0]['passed'])
    @patch('decision_brain.harness.encode',return_value=None)
    def test_invalid_probabilities_error(self,_):
        self.good[0][0][0]=float('nan')
        with self.assertRaises(ValueError):harness.evaluate(self.model,self.suite)
    @patch('decision_brain.harness.encode',return_value=None)
    def test_report_and_regression(self,_):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);suite=root/'suite.json';suite.write_text(json.dumps(self.suite), encoding='utf-8')
            for file in ('brain.json','model.json','encoder.json','weights.npz'):(root/file).write_text('fixture', encoding='utf-8')
            bad=copy.deepcopy(self.model)
            bad[2].probs[0]=np.roll(bad[2].probs[0],1)
            with patch('decision_brain.harness.load_model',side_effect=[bad,self.model]):
                report=harness.run(root,suite,root/'out',root,min_pass_rate=0)
            self.assertFalse(report['passed']);self.assertEqual(len(report['regressions']),1)
            self.assertTrue((root/'out/report.html').exists())
            with self.assertRaises(ValueError):harness.run(root,suite,root/'out')

if __name__=='__main__':unittest.main()
