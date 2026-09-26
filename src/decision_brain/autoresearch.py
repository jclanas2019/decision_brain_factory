"""Bounded adaptive experiment loop. Selection receives train and validation only."""
import csv
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np
from decision_brain.network import Config,MultiDecisionNet,loss,single_loss
from decision_brain.autoeval_quality import evaluate

DEFAULT_POLICY={'version':1,'max_experiments':12,'max_seconds':600,'experiment_seconds':120,'seed_offsets':[0,1],
 'min_loss_improvement':.0001,'max_head_loss_regression':.02,'max_exact_match_regression':.02,'max_seed_loss_regression':.02,
 'final_autoevals':{'exact_match':.85,'probability_quality':.85,'score_closeness':.8}}


def freeze_hash(value):return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()


def policy_read(path=None):
    p=json.loads(Path(path).read_text()) if path else dict(DEFAULT_POLICY)
    if set(p)!=set(DEFAULT_POLICY) or p['version']!=1:raise ValueError('Invalid research policy keys/version')
    for key,cap in [('max_experiments',100),('max_seconds',86400),('experiment_seconds',3600)]:
        if type(p[key]) is not int or not 1<=p[key]<=cap:raise ValueError('Invalid budget '+key)
    seeds=p['seed_offsets']
    if not isinstance(seeds,list) or not 2<=len(seeds)<=5 or seeds[0]!=0 or len(set(seeds))!=len(seeds) or any(type(x) is not int or not 0<=x<=10000 for x in seeds):raise ValueError('Need 2-5 distinct seed offsets starting at zero')
    for key in ('min_loss_improvement','max_head_loss_regression','max_exact_match_regression','max_seed_loss_regression'):
        if type(p[key]) not in (int,float) or not math.isfinite(p[key]) or not 0<=p[key]<=1:raise ValueError('Invalid tolerance '+key)
    if set(p['final_autoevals'])!=set(DEFAULT_POLICY['final_autoevals']):raise ValueError('Invalid AutoEvals policy')
    if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in p['final_autoevals'].values()):raise ValueError('Invalid AutoEvals threshold')
    return p


def validate_proposal(raw,epochs):
    if not isinstance(raw,dict) or set(raw)!={'hypothesis','hidden','lr','decay'}:raise ValueError('Proposal only permits hypothesis, hidden, lr, decay')
    if not isinstance(raw['hypothesis'],str) or not 1<=len(raw['hypothesis'])<=500 or '\n' in raw['hypothesis']:raise ValueError('Invalid hypothesis')
    if type(raw['hidden']) is not int or raw['hidden'] not in (32,64,128):raise ValueError('hidden must be 32, 64 or 128')
    for k,low,high in [('lr',.0005,.02),('decay',.0001,.03)]:
        if type(raw[k]) not in (int,float) or not math.isfinite(raw[k]) or not low<=raw[k]<=high:raise ValueError('Invalid '+k)
    return Config(hidden=raw['hidden'],lr=raw['lr'],decay=raw['decay'],epochs=epochs),raw['hypothesis']


def propose(incumbent,index):
    c=incumbent['configuration'];last=incumbent['epochs'][-1]
    gap=last['validation_loss']-last['train_loss']
    if index%3==1 and gap>.05:
        return {'hypothesis':'Reducir sobreajuste aumentando regularización; conservar el resto.',
                'hidden':c['hidden'],'lr':c['lr'],'decay':min(.03,c['decay']*3)}
    if index%3==2:
        return {'hypothesis':'Evaluar menor capacidad para mejorar generalización.',
                'hidden':32 if c['hidden']>32 else 64,'lr':c['lr'],'decay':c['decay']}
    return {'hypothesis':'Reducir el paso de optimización para estabilizar validación.',
            'hidden':c['hidden'],'lr':max(.0005,c['lr']*.7),'decay':c['decay']}


def acceptance(candidate,incumbent,p):
    reasons=[]
    if not math.isfinite(candidate['validation_loss']):return False,['nonfinite objective']
    if incumbent is None:return True,['baseline established; not a quality approval']
    if candidate['validation_loss']>=incumbent['validation_loss']-p['min_loss_improvement']:reasons.append('no_mean_loss_improvement')
    for c,b in zip(candidate['seeds'],incumbent['seeds']):
        if c['loss']>b['loss']+p['max_seed_loss_regression']:reasons.append('seed_loss_regression:'+str(c['seed']))
        for name,head in c['heads'].items():
            previous=b['heads'][name]
            if head['loss']>previous['loss']+p['max_head_loss_regression']:reasons.append('head_loss_regression:'+name)
            if head['exact_match']<previous['exact_match']-p['max_exact_match_regression']:reasons.append('autoevals_regression:'+name)
    return not reasons,sorted(set(reasons)) or ['improved_validation_without_exceeding_regression_tolerances']


def persist(folder,records,policy):
    folder.mkdir(parents=True,exist_ok=True)
    payload={'method':'bounded_adaptive_configuration_research','selection_partition':'validation','test_used_for_selection':False,
             'policy':policy,'policy_sha256':freeze_hash(policy),'experiments':records}
    tmp=folder/'research.tmp';tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False));tmp.replace(folder/'research.json')
    with (folder/'results.tsv').open('w',newline='') as stream:
        w=csv.writer(stream,delimiter='\t');w.writerow(['experiment','config_sha256','mean_validation_loss','status','hypothesis','reasons'])
        for r in records:w.writerow([r['trial'],r['config_sha256'],r.get('validation_loss',''),r['status'],r['hypothesis'],'; '.join(r['reasons'])])


def search(spec,x,y,xv,yv,*,seed,epochs,trials,log_every,folder,policy,proposals=None):
    if not 1<=trials<=policy['max_experiments']:raise ValueError('trials exceeds research policy budget')
    if type(epochs) is not int or not 1<=epochs<=1000:raise ValueError('epochs must be in [1,1000]')
    if type(seed) is not int or not 0<=seed<2**32-10001:raise ValueError('invalid seed')
    if proposals is not None:
        if not isinstance(proposals,list) or len(proposals)!=trials-1:raise ValueError('Supply exactly trials-1 proposals; baseline is mandatory')
        for raw in proposals:validate_proposal(raw,epochs)
    decisions=spec['decisions'];counts=[len(d['options']) for d in decisions]
    records=[];incumbent=None;winner=None;selected=None;started=time.monotonic()
    policy=json.loads(json.dumps(policy));policy_hash=freeze_hash(policy)
    for index in range(trials):
        if time.monotonic()-started>=policy['max_seconds']:break
        if index==0:cfg=Config(epochs=epochs);hypothesis='Baseline con configuración original y semillas fijadas.'
        else:cfg,hypothesis=validate_proposal(proposals[index-1] if proposals is not None else propose(incumbent,index),epochs)
        record={'trial':index,'configuration':asdict(cfg),'config_sha256':freeze_hash(asdict(cfg)),
                'hypothesis':hypothesis,'accepted':False,'status':'running','reasons':[]}
        records.append(record);persist(folder,records,policy)
        deadline=min(started+policy['max_seconds'],time.monotonic()+policy['experiment_seconds'])
        try:
            seeds=[];primary=None;history=None
            for offset in policy['seed_offsets']:
                s=seed+offset;net=MultiDecisionNet(x.shape[1],cfg,s,counts)
                _,h=net.train(x,y,s,xv,yv,log_every,deadline=deadline)
                prob=net.predict(xv);scores=evaluate(decisions,prob,yv)
                seeds.append({'seed':s,'loss':loss(prob,yv),'heads':{d['id']:{'loss':single_loss(p,t),**scores['heads'][d['id']]} for d,p,t in zip(decisions,prob,yv)}})
                if offset==0:primary=net;history=h
            for e in history:
                for key in ('train_head_loss','validation_head_loss'):e[key]={d['id']:v for d,v in zip(decisions,e[key])}
            record.update(validation_loss=float(np.mean([v['loss'] for v in seeds])),validation_loss_std=float(np.std([v['loss'] for v in seeds])),seeds=seeds,epochs=history)
            record['accepted'],record['reasons']=acceptance(record,incumbent,policy)
            record['status']='keep' if record['accepted'] else 'discard'
            if record['accepted']:incumbent=record;winner=primary;selected=index
        except (ValueError,FloatingPointError,TimeoutError) as exc:
            record.update(status='timeout' if isinstance(exc,TimeoutError) else 'error',reasons=[str(exc)])
            if incumbent is None:
                persist(folder,records,policy);raise
        record['elapsed_seconds']=time.monotonic()-started
        if freeze_hash(policy)!=policy_hash:raise ValueError('Policy changed during research')
        persist(folder,records,policy)
        print(f"autoresearch={index} status={record['status']} validation_loss={record.get('validation_loss')} reasons={record['reasons']}",flush=True)
    if winner is None:raise ValueError('No completed baseline within budget')
    persist(folder,records,policy)
    durable=json.loads((folder/'research.json').read_text())
    if durable['experiments']!=records or any(r['status']=='running' for r in durable['experiments']):raise ValueError('Incomplete research checkpoint')
    return winner,Config(**incumbent['configuration']),records,selected
