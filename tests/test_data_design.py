import csv
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from faker import Faker
from decision_brain.brain import generate,read_dataset
from decision_brain.contracts import read_spec,validate
from decision_brain.data_quality import audit_dataset
from decision_brain.synthetic import uncertainty_rows
from decision_brain.network import single_loss
from decision_brain.prepare_data import prepare
ROOT=Path(__file__).resolve().parents[1]

class DataDesignChecks(unittest.TestCase):
    def setUp(self):self.spec=read_spec(ROOT/'config/presets/retail.json')
    def test_diversity_independence_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=generate(self.spec,1000,42,Path(tmp)/'a.csv');b=generate(self.spec,1000,42,Path(tmp)/'b.csv')
            self.assertEqual(a.read_bytes(),b.read_bytes())
            audit=audit_dataset(read_dataset(a,self.spec),self.spec)
            self.assertEqual(audit['target_combinations'],18)
            self.assertFalse(any(audit['task_text_overlap'].values()))
            self.assertTrue(all(v<.02 for v in audit['normalized_label_mutual_information'].values()))
            self.assertGreater(audit['splits']['train']['unique_task_texts'],450)
    def test_reused_wording_rejected(self):
        pool=self.spec['synthetic_design']['factors'][0]['phrases']['consulta']
        pool['test'][0]=pool['train'][0]
        with self.assertRaises(ValueError):validate(self.spec)
    def test_invalid_uncertainty_fraction(self):
        for value in (True,float('nan'),-.1,.8):
            self.spec['synthetic_design']['uncertainty_training_fraction']=value
            with self.assertRaises(ValueError):validate(self.spec)
    def test_uncertainty_targets_and_soft_loss(self):
        fake=Faker('es_ES');fake.seed_instance(4)
        rows=list(uncertainty_rows(self.spec,30,4,fake))
        for _,targets in rows:
            for values in targets:self.assertAlmostEqual(sum(values),1)
        self.assertTrue(all(max(y)<1 for y in rows[0][1]))
        p=np.array([[.2,.8],[.4,.6]]);hard=np.array([1,0]);soft=np.eye(2)[hard]
        self.assertAlmostEqual(single_loss(p,hard),single_loss(p,soft))
        self.assertAlmostEqual(single_loss(np.array([[.5,.5]]),np.array([[.5,.5]])),np.log(2))
    def test_grouped_preparation_and_leak_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);original=generate(self.spec,2000,42,folder/'generated.csv')
            with original.open() as file:
                reader=csv.DictReader(file);rows=list(reader);fields=[f for f in reader.fieldnames if f!='__split']+['__group']
            source=folder/'annotations.csv'
            with source.open('w',newline='') as file:
                writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader()
                for i,row in enumerate(rows):row.pop('__split');row['__group']=f'entity-{i//5}';writer.writerow(row)
            output=folder/'split.csv';counts=prepare(source,output,self.spec)
            self.assertEqual(sum(counts.values()),2000)
            with self.assertRaises(ValueError):prepare(source,output,self.spec)
            with output.open() as file:reader=csv.DictReader(file);rows=list(reader);fields=reader.fieldnames
            seen={}
            for row in rows:
                g=row['__group'];self.assertIn(seen.setdefault(g,row['__split']),[row['__split']])
            first=rows[0];other=next(row for row in rows if row['__split']!=first['__split']);other['__group']=first['__group']
            with output.open('w',newline='') as file:writer=csv.DictWriter(file,fieldnames=fields);writer.writeheader();writer.writerows(rows)
            with self.assertRaisesRegex(ValueError,'__group'):read_dataset(output,self.spec)
