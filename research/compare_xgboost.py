"""Controlled optional XGBoost experiment. Does not replace the production backend.
Run with PYTHONPATH=src:sdk/src python research/compare_xgboost.py --help.
Requires xgboost 3.1.3 in the experiment environment.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import xgboost as xgb
from decision_brain.brain import read_dataset, encode, load_model, evaluate, save
from decision_brain.network import softmax, loss
from decision_brain.uncertainty import calibrate, diagnostics, quality_gate
from decision_brain.harness import evaluate as harness_evaluate

class TreeHeads:
    def __init__(self,models,counts):
        self.models=models;self.counts=counts;self.temperature=[1.]*len(counts)
    def _raw_prob(self,x,i,t):
        p=self.models[i].predict_proba(x).astype(np.float64)
        return softmax(np.log(np.clip(p,1e-15,1))/t)
    def predict(self,x):
        return [self._raw_prob(x,i,t) for i,t in enumerate(self.temperature)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--suite',type=Path,default=Path('config/harness_suite.json'))
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():raise ValueError('Choose a new experiment directory')
    spec,enc,reference=load_model(args.reference)
    parts=read_dataset(args.data,spec)
    x={s:encode([r[0] for r in rows],enc) for s,rows in parts.items()}
    y={s:[np.array([r[1][i] for r in rows]) for i in range(len(spec['decisions']))] for s,rows in parts.items()}
    configs=[{'max_depth':d,'learning_rate':.05,'n_estimators':300,'min_child_weight':3,'reg_lambda':1.,'subsample':.9,'colsample_bytree':.9} for d in (2,3,4)]
    candidates=[];selected=None;best=float('inf');winner=None
    start=time.perf_counter()
    for index,config in enumerate(configs):
        scores=[];first=None
        for seed in (42,43):
            models=[]
            for k,yt,yv in zip(reference.counts,y['train'],y['validation']):
                model=xgb.XGBClassifier(**config,n_jobs=1,tree_method='hist',random_state=seed,
                    objective='binary:logistic' if k==2 else 'multi:softprob',
                    eval_metric='logloss' if k==2 else 'mlogloss',early_stopping_rounds=20)
                model.fit(x['train'],yt,eval_set=[(x['validation'],yv)],verbose=False)
                models.append(model)
            net=TreeHeads(models,reference.counts)
            value=loss(net.predict(x['validation']),y['validation'])
            scores.append({'seed':seed,'validation_loss':value,'best_iterations':[m.best_iteration for m in models]})
            if first is None:first=net
        mean=float(np.mean([s['validation_loss'] for s in scores]))
        candidates.append({'configuration':config,'seeds':scores,'validation_loss':mean})
        print('candidate',index,'validation_loss',mean,flush=True)
        if mean<best:best=mean;selected=index;winner=first
    search_seconds=time.perf_counter()-start
    winner.uncertainty_policy,audit=calibrate(winner,x['calibration'],y['calibration'],42)
    suite=json.loads(args.suite.read_text())
    results={}
    for name,net in [('neural',reference),('xgboost',winner)]:
        p=net.predict(x['test'])
        selective=diagnostics(spec,p,y['test'],net.uncertainty_policy)
        harness=harness_evaluate((spec,enc,net),suite)
        times=[]
        for _ in range(30):
            start=time.perf_counter();net.predict(x['test'][:1]);times.append((time.perf_counter()-start)*1000)
        results[name]={'test_loss':loss(p,y['test']),
            'metrics':evaluate(spec,p,y['test'],y['train'],net.uncertainty_policy),
            'selective':selective,'uncertainty_quality_errors':quality_gate(selective,net.uncertainty_policy),
            'harness_passed':sum(c['passed'] for c in harness),'harness_total':len(harness),
            'harness_cases':harness,'warm_model_only_p50_ms':float(np.median(times)),
            'temperatures':net.temperature}
    args.out.mkdir(parents=True)
    for i,m in enumerate(winner.models):m.save_model(args.out/f'head_{i}.json')
    output={'xgboost_version':xgb.__version__,'dataset_sha256':hashlib.sha256(args.data.read_bytes()).hexdigest(),
       'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
       'suite_sha256':hashlib.sha256(args.suite.read_bytes()).hexdigest(),
       'feature_representation':'same train-fitted numeric scaling and word/bigram TF-IDF as neural baseline',
       'search':candidates,'selected':selected,'search_seconds':search_seconds,
       'calibration_audit':audit,'uncertainty_policy':winner.uncertainty_policy,'results':results,
       'limitations':'One synthetic dataset, two training seeds per configuration, first-seed artifact. Same historical test already inspected: development evidence, not untouched acceptance data. Harness is a known regression suite. Latency excludes encoding/HTTP.'}
    save(args.out/'comparison.json',output)
    for name,r in results.items():
        print(name,json.dumps({k:r[k] for k in ('test_loss','harness_passed','warm_model_only_p50_ms','uncertainty_quality_errors')}),flush=True)

if __name__=='__main__':main()
