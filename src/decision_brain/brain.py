#!/usr/bin/env python3
"""Train, evaluate and run a local industry-configured neural decision system."""
import argparse
import csv
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from decision_brain.artifacts import export_encoder, import_encoder
import numpy as np
from faker import Faker
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import confusion_matrix, accuracy_score
from decision_brain.contracts import SPLITS, read_spec, validate_state, require
from decision_brain.network import Config, MultiDecisionNet, loss, single_loss


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n', encoding='utf-8');tmp.replace(path)


def signature(spec):return hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()


def generate(spec,rows,seed,path):
    require(not Path(path).exists(),'Dataset already exists; choose another output path')
    scenes=spec.get('synthetic_scenarios',[])
    require(len(scenes)>0,'No synthetic scenarios: supply an annotated CSV for training')
    require(rows>=200,'Generate at least 200 rows')
    fake=Faker(spec.get('locale','es_ES'));fake.seed_instance(seed)
    rng=np.random.default_rng(seed)
    keys=[f['id'] for f in spec['fields']]+['target__'+d['id'] for d in spec['decisions']]+['__split']
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with open(path,'w',newline='',encoding='utf-8') as out:
        writer=csv.DictWriter(out,fieldnames=keys);writer.writeheader()
        sizes=[int(rows*.55),int(rows*.15),int(rows*.15)]
        sizes.append(rows-sum(sizes))
        for split,n in zip(SPLITS,sizes):
            for i in range(n):
                scene=scenes[i%len(scenes)]
                replacements={'company':fake.company(),'name':fake.name(),'city':fake.city(),'code':fake.bothify('??-####')}
                state={}
                for f in spec['fields']:
                    value=scene['context'][f['id']]
                    if f['type']=='number':state[f['id']]=round(float(rng.uniform(*value)),3)
                    elif f['type']=='category':state[f['id']]=value
                    else:state[f['id']]=value[split].format_map(replacements)
                validate_state(state,spec)
                writer.writerow({**state,**{'target__'+k:v for k,v in scene['targets'].items()},'__split':split})
    return Path(path)


def read_dataset(path,spec):
    parts={s:[] for s in SPLITS}
    allowed={f['id'] for f in spec['fields']}|{'target__'+d['id'] for d in spec['decisions']}|{'__split'}
    with open(path,newline='',encoding='utf-8') as f:
        reader=csv.DictReader(f)
        require(set(reader.fieldnames or [])==allowed,'CSV columns must match contract plus target__<decision> and __split')
        for row in reader:
            state={v['id']:float(row[v['id']]) if v['type']=='number' else row[v['id']] for v in spec['fields']}
            validate_state(state,spec)
            require(row['__split'] in parts,'invalid __split')
            targets=[]
            for d in spec['decisions']:
                options=[v['id'] for v in d['options']]
                require(row['target__'+d['id']] in options,'unknown target label')
                targets.append(options.index(row['target__'+d['id']]))
            parts[row['__split']].append((state,targets))
    seen=set()
    for split,rows in parts.items():
        require(len(rows)>=10,f'{split} must contain at least ten rows')
        hashes={json.dumps(x[0],sort_keys=True) for x in rows}
        require(not (seen & hashes),'identical contexts cross data partitions')
        seen|=hashes
        for i,d in enumerate(spec['decisions']):
            require(set(r[1][i] for r in rows)==set(range(len(d['options']))),f'{split}: missing classes in {d["id"]}')
    return parts


def documents(rows,names):return [' '.join(f'{k}: {r[k]}' for k in names) for r in rows]


def fit_encoder(rows,spec):
    numeric=[f['id'] for f in spec['fields'] if f['type']=='number']
    text=[f['id'] for f in spec['fields'] if f['type']!='number']
    vectorizer=TfidfVectorizer(max_features=600,ngram_range=(1,2),sublinear_tf=True,strip_accents='unicode') if text else None
    if vectorizer is not None:vectorizer.fit(documents(rows,text))
    scaler=StandardScaler().fit([[r[k] for k in numeric] for r in rows]) if numeric else None
    return {'numeric':numeric,'text':text,'vectorizer':vectorizer,'scaler':scaler}


def encode(rows,enc):
    blocks=[]
    if enc['numeric']:blocks.append(enc['scaler'].transform([[r[k] for k in enc['numeric']] for r in rows]))
    if enc['text']:blocks.append(enc['vectorizer'].transform(documents(rows,enc['text'])).toarray())
    return np.hstack(blocks).astype(np.float32)


def judge(spec,probabilities):
    require(len(probabilities)==len(spec['decisions']),'number of prediction heads does not match contract')
    for d,p in zip(spec['decisions'],probabilities):
        values=np.asarray(p)
        require(values.shape==(len(d['options']),) and np.isfinite(values).all() and
                (values>=0).all() and (values<=1).all() and np.isclose(values.sum(),1,atol=1e-5),'invalid probability distribution')
    answers={};uncertain=[]
    for d,p in zip(spec['decisions'],probabilities):
        winner=int(np.argmax(p));option=d['options'][winner];conf=float(p[winner])
        distribution={o['id']:float(v) for o,v in zip(d['options'],p)}
        answer={'kind':d['kind'],'question':d['question'],'choice':option['id'],
                'meaning':option['meaning'],'probabilities':distribution,'max_probability':conf}
        if d['kind']=='boolean':answer['probability_true']=float(p[1])
        if d['kind']=='score':answer['expected_score']=float(sum(o['value']*v for o,v in zip(d['options'],p)))
        answer['needs_review']=conf<d.get('min_probability',.6)
        if answer['needs_review']:uncertain.append(d['id'])
        answers[d['id']]=answer
    route=spec['routing']['fallback'];reason='Ninguna regla superó su umbral.'
    if uncertain:
        route=spec['routing'].get('review_action','revision_humana');reason='Probabilidad insuficiente en: '+', '.join(uncertain)
    else:
        for rule in spec['routing'].get('rules',[]):
            probability=answers[rule['decision']]['probabilities'][rule['option']]
            if probability>=rule.get('min_probability',.65):
                route=rule['action'];reason=f"Regla: {rule['decision']}={rule['option']}, probabilidad {probability:.1%}.";break
    return {'answers':answers,'proposed_action':route,'routing_reason':reason,
            'interpretation':' '.join(f"{a['question']} "
                f"{'Hipótesis que requiere revisión: ' if a['needs_review'] else 'Estimación del modelo: '}"
                f"{a['meaning']} ({a['max_probability']:.1%})." for a in answers.values()),
            'action_executed':False}


def load_model(run):
    spec=read_spec(run/'brain.json')
    meta=json.loads((run/'model.json').read_text(encoding='utf-8'))
    require(signature(spec)==meta['contract_hash'],'model and decision contract do not match')
    enc=import_encoder(run/'encoder.json')
    with np.load(run/'weights.npz',allow_pickle=False) as archive:
        net=MultiDecisionNet(meta['input_dim'],Config(**meta['configuration']),0,meta['counts'])
        require(meta['counts']==[len(d['options']) for d in spec['decisions']],'model head sizes do not match contract')
        params=[archive[f'p{i}'] for i in range(2+2*len(meta['counts']))]
        require(all(a.shape==b.shape and np.isfinite(a).all() for a,b in zip(params,net.params)),'invalid weight shapes or values')
        temperature=archive['temperature']
        require(temperature.shape==(len(meta['counts']),) and np.isfinite(temperature).all() and (temperature>0).all(),'invalid calibration temperatures')
        net.params=params
        net.temperature=temperature.tolist()
    return spec,enc,net


def evaluate(spec,probs,truth,train_truth):
    result={}
    for d,p,y,yt in zip(spec['decisions'],probs,truth,train_truth):
        k=len(d['options']);pred=p.argmax(axis=1)
        confidence=p.max(axis=1);correct=pred==y;ece=0.0
        for low,high in zip(np.linspace(0,1,11)[:-1],np.linspace(0,1,11)[1:]):
            selected=(confidence>=low)&(confidence<high if high<1 else confidence<=high)
            if selected.any():ece+=float(selected.mean()*abs(correct[selected].mean()-confidence[selected].mean()))
        automated=confidence>=d.get('min_probability',.6)
        prior=np.bincount(yt,minlength=k)/len(yt)
        baseline=np.tile(prior,(len(y),1))
        result[d['id']]={'question':d['question'],'accuracy':float(accuracy_score(y,pred)),
            'ece':ece,'coverage':float(automated.mean()),
            'selective_accuracy':float(correct[automated].mean()) if automated.any() else None,
            'log_loss':single_loss(p,y),'baseline_accuracy':float(np.mean(y==prior.argmax())),
            'baseline_log_loss':single_loss(baseline,y),
            'labels':[o['id'] for o in d['options']],
            'confusion_matrix':confusion_matrix(y,pred,labels=list(range(k))).tolist()}
    return result


def train(args,spec):
    out=args.output
    require(not out.exists(),'Output directory already exists; choose a new run directory')
    parts=read_dataset(args.data,spec)
    states={s:[r[0] for r in rows] for s,rows in parts.items()}
    targets={s:[np.array([r[1][i] for r in rows]) for i in range(len(spec['decisions']))] for s,rows in parts.items()}
    enc=fit_encoder(states['train'],spec)
    features={s:encode(rows,enc) for s,rows in states.items()}
    counts=[len(d['options']) for d in spec['decisions']]
    rng=np.random.default_rng(args.seed);config=Config(epochs=args.epochs)
    trace=[];best=float('inf');winner=None;selected=None
    for trial in range(args.trials):
        candidate=config if trial==0 else Config(hidden=int(rng.choice([32,64,128])),
            lr=float(np.clip(config.lr*np.exp(rng.normal(0,.3)),.001,.02)),decay=config.decay,epochs=args.epochs)
        net=MultiDecisionNet(features['train'].shape[1],candidate,args.seed,counts)
        _,history=net.train(features['train'],targets['train'],args.seed,features['validation'],targets['validation'],args.log_every)
        value=loss(net.predict(features['validation']),targets['validation']);accepted=value<best-1e-5
        if accepted:config,best,winner,selected=candidate,value,net,trial
        trace.append({'trial':trial,'configuration':asdict(candidate),'validation_loss':value,'accepted':accepted,'epochs':history})
        print(f'propuesta={trial} validation_loss={value:.6g} accepted={accepted}',flush=True)
    # Calibration set is independent of both optimization and final testing.
    winner.temperature=[min((.7,1.,1.4,2.,3.),key=lambda t:single_loss(
        winner._raw_prob(features['calibration'],i,t),targets['calibration'][i])) for i in range(len(counts))]
    test=winner.predict(features['test'])
    metrics=evaluate(spec,test,targets['test'],targets['train'])
    out.mkdir(parents=True)
    save(out/'brain.json',spec)
    save(out/'model.json',{'contract_hash':signature(spec),'input_dim':features['train'].shape[1],
                         'counts':counts,'configuration':asdict(config)})
    np.savez(out/'weights.npz',**{f'p{i}':p for i,p in enumerate(winner.params)},temperature=winner.temperature)
    export_encoder(enc,out/'encoder.json')
    saved_spec,saved_enc,saved_net=load_model(out)
    replay=saved_net.predict(encode(states['test'],saved_enc))
    require(all(np.allclose(x,y,atol=1e-7,rtol=1e-6) for x,y in zip(test,replay)),'persisted model differs')
    require(all(np.isfinite(p).all() and np.allclose(p.sum(axis=1),1) for p in replay),'invalid probabilities')
    examples=[]
    for index,state in enumerate(states['test'][:5]):
        examples.append({'state':state,**judge(saved_spec,[p[index] for p in replay])})
    report={'industry':spec['industry'],'seed':args.seed,'dataset_sha256':hashlib.sha256(args.data.read_bytes()).hexdigest(),
        'split_sizes':{s:len(rows) for s,rows in parts.items()},'selected_trial':selected,'search':trace,
        'test_loss':loss(test,targets['test']),'metrics':metrics,'temperatures':winner.temperature,
        'functional_test':{'serialization_passed':True,'rows':len(states['test'])},
        'scenarios':examples,'data_origin':getattr(args,'origin','user_supplied')}
    save(out/'report.json',report)
    for name,m in metrics.items():
        with (out/f'confusion_{name}.csv').open('w',newline='', encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['real/predicha',*m['labels']])
            for label,row in zip(m['labels'],m['confusion_matrix']):w.writerow([label,*row])
    from decision_brain.reporting import render
    render(report,out)
    print(f'FUNCTIONAL TEST PASSED; test_loss={report["test_loss"]:.6g}',flush=True)
    for name,m in metrics.items():
        print(f'{name}: exactitud={m["accuracy"]:.1%}; referencia={m["baseline_accuracy"]:.1%}; loss={m["log_loss"]:.5f}',flush=True)
    print('Informe interpretado:',(out/'report.html').resolve(),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=Path('config/brain.json'))
    sub=p.add_subparsers(dest='command',required=True)
    g=sub.add_parser('generate');g.add_argument('--rows',type=int,default=1000);g.add_argument('--seed',type=int,default=42);g.add_argument('--output',type=Path,default=Path('data/demo.csv'))
    for name in ('train','demo'):
        t=sub.add_parser(name);t.add_argument('--data',type=Path,default=Path('data/demo.csv'))
        t.add_argument('--output',type=Path,default=Path('runs/default'));t.add_argument('--seed',type=int,default=42)
        t.add_argument('--trials',type=int,default=3);t.add_argument('--epochs',type=int,default=40)
        t.add_argument('--log-every',type=int,default=10)
        if name=='demo':t.add_argument('--rows',type=int,default=1000)
    inf=sub.add_parser('predict');inf.add_argument('--run',type=Path);inf.add_argument('--state',type=Path,required=True)
    a=p.parse_args()
    try:
        if a.command=='predict':
            from decision_brain.runtime_paths import latest_model
            if a.run is None:a.run=latest_model(Path.cwd())
            spec,enc,net=load_model(a.run);state=validate_state(json.loads(a.state.read_text(encoding='utf-8')),spec)
            print(json.dumps({'state':state,**judge(spec,[p[0] for p in net.predict(encode([state],enc))])},indent=2,ensure_ascii=False));return
        spec=read_spec(a.config)
        if a.command=='generate':generate(spec,a.rows,a.seed,a.output);print(a.output);return
        require(a.trials>=1 and a.epochs>=1 and a.log_every>=1,'trials, epochs and log-every must be positive')
        if a.command=='demo':
            require(not a.output.exists(),'Output already exists; choose a new directory')
            if a.data==Path('data/demo.csv'):a.data=a.output.with_name(a.output.name+'_synthetic.csv')
            generate(spec,a.rows,a.seed,a.data);a.origin='synthetic_demo'
        train(a,spec)
    except (ValueError,KeyError,TypeError) as e:p.error(str(e))


if __name__=='__main__':main()
