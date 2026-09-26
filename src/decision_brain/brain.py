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
from decision_brain.primitives import result_fields, describe_answer, question_type, distribution_confidence


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n', encoding='utf-8');tmp.replace(path)


def signature(spec):return hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()


def generate(spec,rows,seed,path):
    require(not Path(path).exists(),'Dataset already exists; choose another output path')
    scenes=spec.get('synthetic_scenarios',[])
    require(len(scenes)>0 or 'synthetic_design' in spec,'No synthetic scenarios: supply an annotated CSV for training')
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
            if 'synthetic_design' in spec:
                from decision_brain.synthetic import rows_for_split
                for state,labels in rows_for_split(spec,n,split,seed,fake):
                    validate_state(state,spec)
                    writer.writerow({**state,**{'target__'+k:v for k,v in labels.items()},'__split':split})
                continue
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
    parts={s:[] for s in SPLITS};groups={}
    allowed={f['id'] for f in spec['fields']}|{'target__'+d['id'] for d in spec['decisions']}|{'__split'}
    with open(path,newline='',encoding='utf-8') as f:
        reader=csv.DictReader(f)
        columns=set(reader.fieldnames or [])
        require(len(reader.fieldnames or [])==len(columns),'duplicate CSV headers')
        require(columns in (allowed,allowed|{'__group'}),'CSV columns must match contract plus target__<decision>, __split and optional __group')
        for row in reader:
            state={v['id']:float(row[v['id']]) if v['type']=='number' else row[v['id']] for v in spec['fields']}
            validate_state(state,spec)
            require(row['__split'] in parts,'invalid __split')
            if '__group' in columns:
                group=row['__group'].strip();require(bool(group),'__group must be nonempty')
                require(group not in groups or groups[group]==row['__split'],'same __group crosses data partitions')
                groups[group]=row['__split']
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


def judge(spec,probabilities,uncertainty_policy=None,selection_scores=None):
    require(len(probabilities)==len(spec['decisions']),'number of prediction heads does not match contract')
    for d,p in zip(spec['decisions'],probabilities):
        values=np.asarray(p)
        require(values.shape==(len(d['options']),) and np.isfinite(values).all() and
                (values>=0).all() and (values<=1).all() and np.isclose(values.sum(),1,atol=1e-5),'invalid probability distribution')
    from decision_brain.uncertainty import validate_policy, prediction_set
    validate_policy(uncertainty_policy,[len(d['options']) for d in spec['decisions']])
    if selection_scores is not None:
        require(len(selection_scores)==len(probabilities),'invalid selector heads')
        require(all(v is None or (type(v) in (int,float) and np.isfinite(v) and 0<=v<=1) for v in selection_scores),'invalid selection scores')
    answers={};uncertain=[]
    for head_index,(d,p) in enumerate(zip(spec['decisions'],probabilities)):
        winner=int(np.argmax(p));option=d['options'][winner];conf=float(p[winner])
        distribution={o['id']:float(v) for o,v in zip(d['options'],p)}
        answer={'kind':d['kind'],'question':d['question'],'choice':option['id'],
                'meaning':option['meaning'],'probabilities':distribution,'max_probability':conf}
        answer.update(result_fields(d,distribution))
        if d['kind']=='boolean':answer['probability_true']=float(p[1])
        if d['kind']=='score':answer['expected_score']=float(sum(o['value']*v for o,v in zip(d['options'],p)))
        answer['needs_review']=conf<d.get('min_probability',.6)
        if uncertainty_policy is not None:
            indices=prediction_set(p,uncertainty_policy['heads'][head_index])
            answer['prediction_set']=[d['options'][i]['id'] for i in indices]
            reasons=[]
            if answer['needs_review']:reasons.append('below_contract_threshold')
            if len(indices)!=1 or winner not in indices:reasons.append('non_singleton_prediction_set')
            answer['review_reasons']=reasons
            answer['needs_review']=bool(reasons)
        if selection_scores is not None and selection_scores[head_index] is not None:
            value=selection_scores[head_index]
            reasons=answer.get('review_reasons',['below_contract_threshold'] if answer['needs_review'] else [])
            answer['selection_score']=value;answer['selection_threshold']=.5
            if value<.5:reasons.append('learned_selector_rejected')
            answer['review_reasons']=reasons;answer['needs_review']=bool(reasons)
        if answer['needs_review']:uncertain.append(d['id'])
        answers[d['id']]=answer
    route=spec['routing']['fallback'];reason='Ninguna regla superó su umbral.'
    if uncertain:
        route=spec['routing'].get('review_action','revision_humana');reason='Revisión requerida por umbral, conjunto o selector en: '+', '.join(uncertain)
    else:
        for rule in spec['routing'].get('rules',[]):
            probability=answers[rule['decision']]['probabilities'][rule['option']]
            if probability>=rule.get('min_probability',.65):
                route=rule['action'];reason=f"Regla: {rule['decision']}={rule['option']}, probabilidad {probability:.1%}.";break
    return {'answers':answers,'proposed_action':route,'routing_reason':reason,
            'interpretation':' '.join(describe_answer(a) for a in answers.values()),
            'action_executed':False}


def infer_decision(spec,enc,net,state):
    from decision_brain.model_zoo import review_scores
    x=encode([state],enc)
    result=judge(spec,[p[0] for p in net.predict(x)],getattr(net,'uncertainty_policy',None),
                 [None if score is None else float(score[0]) for score in review_scores(net,x)])
    if hasattr(net,'routes'):
        for d,algorithm in zip(spec['decisions'],net.routes):result['answers'][d['id']]['algorithm']=algorithm
    return result


def load_model(run):
    spec=read_spec(run/'brain.json')
    meta=json.loads((run/'model.json').read_text(encoding='utf-8'))
    require(signature(spec)==meta['contract_hash'],'model and decision contract do not match')
    from decision_brain.uncertainty import validate_policy
    validate_policy(meta.get('uncertainty_policy'),meta['counts'])
    enc=import_encoder(run/'encoder.json')
    with np.load(run/'weights.npz',allow_pickle=False) as archive:
        if 'model_graph' in meta:
            from decision_brain.model_zoo import restore
            net=restore(meta['model_graph'],archive,meta['input_dim'])
            require(tuple(net.counts)==tuple(len(d['options']) for d in spec['decisions']),'model graph contract mismatch')
            net.uncertainty_policy=meta.get('uncertainty_policy')
            return spec,enc,net
        net=MultiDecisionNet(meta['input_dim'],Config(**meta['configuration']),0,meta['counts'])
        require(meta['counts']==[len(d['options']) for d in spec['decisions']],'model head sizes do not match contract')
        params=[archive[f'p{i}'] for i in range(2+2*len(meta['counts']))]
        require(all(a.shape==b.shape and np.isfinite(a).all() for a,b in zip(params,net.params)),'invalid weight shapes or values')
        temperature=archive['temperature']
        require(temperature.shape==(len(meta['counts']),) and np.isfinite(temperature).all() and (temperature>0).all(),'invalid calibration temperatures')
        net.params=params
        net.temperature=temperature.tolist()
        net.uncertainty_policy=meta.get('uncertainty_policy')
    return spec,enc,net


def evaluate(spec,probs,truth,train_truth,uncertainty_policy=None):
    result={}
    for head_index,(d,p,y,yt) in enumerate(zip(spec['decisions'],probs,truth,train_truth)):
        k=len(d['options']);pred=p.argmax(axis=1)
        confidence=p.max(axis=1);correct=pred==y;ece=0.0
        for low,high in zip(np.linspace(0,1,11)[:-1],np.linspace(0,1,11)[1:]):
            selected=(confidence>=low)&(confidence<high if high<1 else confidence<=high)
            if selected.any():ece+=float(selected.mean()*abs(correct[selected].mean()-confidence[selected].mean()))
        automated=confidence>=d.get('min_probability',.6)
        if uncertainty_policy is not None:
            from decision_brain.uncertainty import prediction_set
            automated &= np.array([prediction_set(row,uncertainty_policy['heads'][head_index])==[int(w)] for row,w in zip(p,pred)])
        prior=np.bincount(yt,minlength=k)/len(yt)
        baseline=np.tile(prior,(len(y),1))
        result[d['id']]={'question':d['question'],'accuracy':float(accuracy_score(y,pred)),
            'ece':ece,'coverage':float(automated.mean()),
            'selective_accuracy':float(correct[automated].mean()) if automated.any() else None,
            'log_loss':single_loss(p,y),'baseline_accuracy':float(np.mean(y==prior.argmax())),
            'baseline_log_loss':single_loss(baseline,y),
            'labels':[o['id'] for o in d['options']],
            'confusion_matrix':confusion_matrix(y,pred,labels=list(range(k))).tolist()}
        m=result[d['id']];kind=question_type(d)
        m.update(type=kind, loss_name='binary_cross_entropy' if kind=='noul' else 'categorical_cross_entropy',
                 brier=float(np.mean((p[:,1]-y)**2)) if kind=='noul' else float(np.mean(np.sum((p-np.eye(k)[y])**2,axis=1))))
        if kind=='score':
            scores=p@np.arange(k);baseline_scores=baseline@np.arange(k)
            m.update(score_mae=float(np.mean(abs(scores-y))),score_rmse=float(np.sqrt(np.mean((scores-y)**2))),
                     baseline_score_mae=float(np.mean(abs(baseline_scores-y))),score_range=[0,k-1])
        if kind!='noul':m['mean_confidence']=float(np.mean([distribution_confidence(row) for row in p]))
    return result


def train(args,spec):
    if getattr(args,'engine','neural')=='multi':
        from decision_brain.multi_training import train_multi
        return train_multi(args,spec)
    out=args.output
    require(not out.exists(),'Output directory already exists; choose a new run directory')
    protected={str(args.data.resolve()):hashlib.sha256(args.data.read_bytes()).hexdigest()}
    for name in ('brain.py','network.py','autoeval_quality.py','autoresearch.py','uncertainty.py'):
        path=Path(__file__).with_name(name);protected[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    parts=read_dataset(args.data,spec)
    states={s:[r[0] for r in rows] for s,rows in parts.items()}
    targets={s:[np.array([r[1][i] for r in rows]) for i in range(len(spec['decisions']))] for s,rows in parts.items()}
    enc=fit_encoder(states['train'],spec)
    features={s:encode(rows,enc) for s,rows in states.items()}
    counts=[len(d['options']) for d in spec['decisions']]
    optimization_features=features['train'];optimization_targets=targets['train'];uncertainty_count=0
    # Synthetic uncertainty exposure is explicit and used ONLY for synthetic demos.
    fraction=spec.get('synthetic_design',{}).get('uncertainty_training_fraction',0)
    if getattr(args,'origin','user_supplied')=='synthetic_demo' and fraction:
        from decision_brain.synthetic import uncertainty_rows
        fake=Faker(spec.get('locale','es_ES'));fake.seed_instance(args.seed+991)
        extra=list(uncertainty_rows(spec,int(len(states['train'])*fraction),args.seed,fake))
        uncertainty_count=len(extra)
        optimization_features=np.vstack([features['train'],encode([s for s,_ in extra],enc)])
        optimization_targets=[np.vstack([np.eye(count)[targets['train'][i]],np.array([y[i] for _,y in extra])]).astype(np.float32) for i,count in enumerate(counts)]
    from decision_brain.autoresearch import policy_read,search,freeze_hash
    from decision_brain.layout import project_root
    policy_path=getattr(args,'research_policy',None) or project_root()/'config/research_policy.json'
    research_policy=policy_read(policy_path)
    proposals_path=getattr(args,'proposals',None)
    proposals=json.loads(Path(proposals_path).read_text()) if proposals_path else None
    winner,config,trace,selected=search({'decisions':spec['decisions']},optimization_features,optimization_targets,
        features['validation'],targets['validation'],seed=args.seed,epochs=args.epochs,trials=args.trials,
        log_every=args.log_every,folder=out/'research',policy=research_policy,proposals=proposals)
    require(all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest for path,digest in protected.items()),'Data or training/evaluation code changed during research')
    # Split calibration again so fitted temperatures cannot leak into conformal scores.
    from decision_brain.uncertainty import calibrate,diagnostics,quality_gate
    winner.uncertainty_policy,calibration_audit=calibrate(winner,features['calibration'],targets['calibration'],args.seed)
    test=winner.predict(features['test'])
    metrics=evaluate(spec,test,targets['test'],targets['train'],winner.uncertainty_policy)
    selective=diagnostics(spec,test,targets['test'],winner.uncertainty_policy)
    uncertainty_errors=quality_gate(selective,winner.uncertainty_policy)
    from decision_brain.autoeval_quality import evaluate as autoevaluate,gate as autogate
    autoevals=autoevaluate(spec['decisions'],test,targets['test'],include_cases=True)
    autoeval_errors=autogate(autoevals,research_policy['final_autoevals'])
    assurance_errors=autoeval_errors+uncertainty_errors
    out.mkdir(parents=True,exist_ok=True)
    save(out/'brain.json',spec)
    save(out/'model.json',{'contract_hash':signature(spec),'input_dim':features['train'].shape[1],
                         'counts':counts,'configuration':asdict(config),'uncertainty_policy':winner.uncertainty_policy})
    np.savez(out/'weights.npz',**{f'p{i}':p for i,p in enumerate(winner.params)},temperature=winner.temperature)
    export_encoder(enc,out/'encoder.json')
    saved_spec,saved_enc,saved_net=load_model(out)
    replay=saved_net.predict(encode(states['test'],saved_enc))
    require(all(np.allclose(x,y,atol=1e-7,rtol=1e-6) for x,y in zip(test,replay)),'persisted model differs')
    require(all(np.isfinite(p).all() and np.allclose(p.sum(axis=1),1) for p in replay),'invalid probabilities')
    from decision_brain.edge_contracts import check_response
    for index in range(len(states['test'])):
        check_response({**judge(saved_spec,[p[index] for p in replay],saved_net.uncertainty_policy),'model_version':'functional'},saved_spec,'functional')
    examples=[]
    for index,state in enumerate(states['test'][:5]):
        examples.append({'state':state,**judge(saved_spec,[p[index] for p in replay],saved_net.uncertainty_policy)})
    from decision_brain.data_quality import audit_dataset
    dataset_audit=audit_dataset(parts,spec)
    ablations={}
    for name,disabled in [('without_text',bool(enc['text'])),('without_numeric',bool(enc['numeric']))]:
        if not disabled:continue
        x=features['test'].copy();n_numeric=len(enc['numeric'])
        if name=='without_text':x[:,n_numeric:]=0
        else:x[:,:n_numeric]=0
        ablations[name]=evaluate(spec,winner.predict(x),targets['test'],targets['train'])
    report={'industry':spec['industry'],'seed':args.seed,'dataset_sha256':hashlib.sha256(args.data.read_bytes()).hexdigest(),
        'split_sizes':{s:len(rows) for s,rows in parts.items()},'selected_trial':selected,'search':trace,
        'test_loss':loss(test,targets['test']),'metrics':metrics,'temperatures':winner.temperature,
        'uncertainty_policy':winner.uncertainty_policy,'calibration_audit':calibration_audit,
        'selective_decisions':selective,'uncertainty_assurance':{'passed':not uncertainty_errors,'reasons':uncertainty_errors},
        'dataset_audit':dataset_audit,'input_ablation':ablations,
        'uncertainty_training':{'rows':uncertainty_count,'targets':'soft distributions; train wording only; synthetic_demo only'},
        'assurance':{'engine':'autoevals','version':autoevals['version'],'passed':not assurance_errors,
          'reasons':assurance_errors,'policy':research_policy['final_autoevals'],
          'scores':{k:v for k,v in autoevals.items() if k!='cases'},
          'research_policy_sha256':freeze_hash(research_policy),'test_used_for_selection':False,
          'protected_inputs_sha256':{Path(k).name:v for k,v in protected.items()},
          'artifact_sha256':{name:hashlib.sha256((out/name).read_bytes()).hexdigest() for name in ('brain.json','model.json','encoder.json','weights.npz')}},
        'question_types':{d['id']:question_type(d) for d in spec['decisions']},
        'confidence_method':'1 - normalized Shannon entropy; not Jev proprietary confidence',
        'functional_test':{'serialization_passed':True,'typed_response_gate_passed':True,'rows':len(states['test'])},
        'scenarios':examples,'data_origin':getattr(args,'origin','user_supplied')}
    save(out/'report.json',report)
    save(out/'autoevals.json',{'passed':not autoeval_errors,'reasons':autoeval_errors,**autoevals})
    with (out/'predictions.jsonl').open('w',encoding='utf-8') as stream:
        for index in range(len(states['test'])):
            result=judge(saved_spec,[p[index] for p in replay],saved_net.uncertainty_policy)
            stream.write(json.dumps({'row':index,'targets':{d['id']:d['options'][int(targets['test'][i][index])]['id'] for i,d in enumerate(spec['decisions'])},**result},ensure_ascii=False,allow_nan=False)+'\n')
    for name,m in metrics.items():
        with (out/f'confusion_{name}.csv').open('w',newline='', encoding='utf-8') as f:
            w=csv.writer(f);w.writerow(['real/predicha',*m['labels']])
            for label,row in zip(m['labels'],m['confusion_matrix']):w.writerow([label,*row])
    from decision_brain.reporting import render
    render(report,out)
    print('CALIDAD INCERTIDUMBRE '+('PASS' if not uncertainty_errors else 'FAIL')+'; '+str(uncertainty_errors),flush=True)
    print('ABSTENCIÓN: '+json.dumps(report['selective_decisions']['conformal_policy'],ensure_ascii=False),flush=True)
    print('AUTOEVALS '+('PASS' if not autoeval_errors else 'FAIL')+'; '+str(autoeval_errors),flush=True)
    print(f'FUNCTIONAL TEST PASSED; test_loss={report["test_loss"]:.6g}',flush=True)
    for name,m in metrics.items():
        print(f'{name} [{m["type"]}]: exactitud={m["accuracy"]:.1%}; referencia={m["baseline_accuracy"]:.1%}; loss={m["log_loss"]:.5f}',flush=True)
        print(f'  {m["loss_name"]}={m["log_loss"]:.5f}; brier={m["brier"]:.5f}'+(f'; score_MAE={m["score_mae"]:.5f}' if m['type']=='score' else ''),flush=True)
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
        t.add_argument('--engine',choices=['neural','multi'],default='neural')
        t.add_argument('--log-every',type=int,default=10)
        t.add_argument('--research-policy',type=Path)
        t.add_argument('--proposals',type=Path,help='JSON list of bounded hypotheses; baseline always runs first')
        if name=='demo':t.add_argument('--rows',type=int,default=1000)
    inf=sub.add_parser('predict');inf.add_argument('--run',type=Path);inf.add_argument('--state',type=Path,required=True)
    a=p.parse_args()
    try:
        if a.command=='predict':
            from decision_brain.runtime_paths import latest_model
            if a.run is None:a.run=latest_model(Path.cwd())
            spec,enc,net=load_model(a.run);state=validate_state(json.loads(a.state.read_text(encoding='utf-8')),spec)
            print(json.dumps({'state':state,**infer_decision(spec,enc,net,state)},indent=2,ensure_ascii=False));return
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
