"""Compare local algorithms; freeze a per-head router before calibration and test."""
import copy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time
import numpy as np
from decision_brain.network import Config,MultiDecisionNet,loss,single_loss
from decision_brain.model_zoo import AdvancedNet,Ensemble,AlgorithmRouter,describe,review_scores
from decision_brain.uncertainty import calibrate,diagnostics,quality_gate


def choose_routes(candidates,x,y,min_gain=.001,min_selector_coverage=.5):
    """Only routing-validation inputs are accepted by this function."""
    if not 0<=min_gain<=1 or not 0<=min_selector_coverage<=1:raise ValueError('invalid routing thresholds')
    if 'neural' not in candidates:raise ValueError('router requires baseline')
    values={name:net.predict(x) for name,net in candidates.items()};scores={name:review_scores(net,x) for name,net in candidates.items()}
    routes=[];evidence=[]
    for i,target in enumerate(y):
        rows=[]
        for name,probs in values.items():
            if probs[i].shape[0]!=len(target) or not np.isfinite(probs[i]).all() or (probs[i]<0).any() or not np.allclose(probs[i].sum(1),1):raise ValueError('invalid routing probabilities')
            gate=scores[name][i];coverage=1. if gate is None else float(np.mean(gate>=.5))
            rows.append({'algorithm':name,'log_loss':single_loss(probs[i],target),
                         'brier':float(np.mean(np.sum((probs[i]-np.eye(probs[i].shape[1])[target])**2,axis=1))),
                         'selector_coverage':coverage,'eligible':coverage>=min_selector_coverage})
        baseline=next(r for r in rows if r['algorithm']=='neural')
        best=min((r for r in rows if r['eligible']),key=lambda r:r['log_loss'])
        chosen=best['algorithm'] if best['log_loss']<baseline['log_loss']-min_gain else 'neural'
        routes.append(chosen);evidence.append({'head_index':i,'selected':chosen,'candidates':rows})
    return routes,evidence


def train_candidates(spec,x,y,xv,yv,seed,epochs,log_every,deadline,routing_policy=None):
    count=[len(d['options']) for d in spec['decisions']];cfg=Config(epochs=epochs)
    order=np.random.default_rng(seed+1701).permutation(len(xv));early,route=np.array_split(order,2)
    if min(len(early),len(route))<5:raise ValueError('Need at least ten validation rows')
    histories={};models={};timing={};members=[]
    for offset in (0,1,2):
        name='neural' if offset==0 else 'ensemble_member_'+str(offset)
        net=MultiDecisionNet(x.shape[1],cfg,seed+offset,count);start=time.perf_counter()
        print('ALGORITMO '+name,flush=True)
        _,history=net.train(x,y,seed+offset,xv[early],[t[early] for t in yv],log_every,deadline)
        members.append(net);histories[name]=history;timing[name]=time.perf_counter()-start
    models['neural']=members[0];models['ensemble']=Ensemble(members)
    for kind in ('corn','selective'):
        ordinal=[i for i,d in enumerate(spec['decisions']) if d['kind']=='score'] if kind=='corn' else []
        net=AdvancedNet(x.shape[1],cfg,seed,count,kind,ordinal);start=time.perf_counter()
        print('ALGORITMO '+kind,flush=True)
        _,histories[kind]=net.train(x,y,seed,xv[early],[t[early] for t in yv],log_every,deadline)
        models[kind]=net;timing[kind]=time.perf_counter()-start
    routing_policy=routing_policy or {'min_validation_loss_gain':.001,'min_selector_coverage':.5}
    routes,evidence=choose_routes(models,xv[route],[t[route] for t in yv],routing_policy['min_validation_loss_gain'],routing_policy['min_selector_coverage'])
    router=AlgorithmRouter(copy.deepcopy(models),routes)
    selection={'method':'fixed_per_head_validation_log_loss','min_gain':routing_policy['min_validation_loss_gain'],'min_selector_coverage':routing_policy['min_selector_coverage'],
               'validation_early_stop_indices':early.tolist(),'validation_router_indices':route.tolist(),
               'test_used':False,'calibration_used':False,'heads':evidence,
               'routes':{d['id']:r for d,r in zip(spec['decisions'],routes)},'training_seconds':timing,
               'limitations':'One development split; routing losses are uncalibrated. Three seeds for ensemble, one for CORN and selective. Not an exhaustive or equal-compute search.'}
    return models,router,histories,selection,cfg


def train_multi(args,spec):
    from decision_brain.brain import read_dataset,fit_encoder,encode,save,signature,evaluate,load_model,infer_decision
    from decision_brain.artifacts import export_encoder
    from decision_brain.autoresearch import policy_read,freeze_hash
    from decision_brain.autoeval_quality import evaluate as autoevaluate,gate as autogate
    from decision_brain.layout import project_root
    from decision_brain.harness import evaluate as harness_evaluate,validate_suite
    from decision_brain.data_quality import audit_dataset
    from decision_brain.edge_contracts import check_response
    from decision_brain.reporting import render
    if args.output.exists():raise ValueError('Choose a new output directory')
    if getattr(args,'proposals',None):raise ValueError('JSON hyperparameter proposals are supported by the neural engine; multi uses its documented fixed comparison')
    if spec.get('synthetic_design',{}).get('uncertainty_training_fraction',0):raise ValueError('Multi-engine currently requires hard labels without uncertainty augmentation')
    out=args.output;parts=read_dataset(args.data,spec)
    states={s:[r[0] for r in rows] for s,rows in parts.items()}
    targets={s:[np.array([r[1][i] for r in rows]) for i in range(len(spec['decisions']))] for s,rows in parts.items()}
    enc=fit_encoder(states['train'],spec);x={s:encode(rows,enc) for s,rows in states.items()}
    policy=policy_read(getattr(args,'research_policy',None) or project_root()/'config/research_policy.json')
    if policy['max_experiments']<5:raise ValueError('Multi-engine requires budget for five fitted networks')
    protected={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ('multi_training.py','model_zoo.py','network.py','uncertainty.py','brain.py')}
    data_hash=hashlib.sha256(args.data.read_bytes()).hexdigest()
    router_path=project_root()/'config/algorithm_router.json'
    routing_policy=json.loads(router_path.read_text())
    if set(routing_policy)!={'version','method','candidates','min_validation_loss_gain','min_selector_coverage'} or routing_policy['version']!=1 or routing_policy['method']!='fixed_per_head_validation_log_loss' or routing_policy['candidates']!=['neural','ensemble','corn','selective']:raise ValueError('Invalid algorithm router policy')
    for key in ('min_validation_loss_gain','min_selector_coverage'):
        if type(routing_policy[key]) not in (int,float) or not np.isfinite(routing_policy[key]) or not 0<=routing_policy[key]<=1:raise ValueError('Invalid router threshold')
    routing_hash=hashlib.sha256(router_path.read_bytes()).hexdigest()
    models,router,histories,selection,cfg=train_candidates(spec,x['train'],targets['train'],x['validation'],targets['validation'],args.seed,args.epochs,args.log_every,time.monotonic()+policy['max_seconds'],routing_policy)
    selection['policy']=routing_policy;selection['policy_sha256']=routing_hash
    models['router']=router
    # The routing table is frozen above. The following test/harness results cannot change it.
    suite_path=project_root()/'config/harness_suite.json';suite=json.loads(suite_path.read_text())
    validate_suite(suite,spec)
    measured={};reports={};calibrated={}
    for name,raw in models.items():
        net=copy.deepcopy(raw)
        net.uncertainty_policy,audit=calibrate(net,x['calibration'],targets['calibration'],args.seed)
        p=net.predict(x['test']);selection_scores=review_scores(net,x['test'])
        selective=diagnostics(spec,p,targets['test'],net.uncertainty_policy,selection_scores)
        metrics=evaluate(spec,p,targets['test'],targets['train'],net.uncertainty_policy)
        decisions=[infer_decision(spec,enc,net,state) for state in states['test']]
        for i,d in enumerate(spec['decisions']):
            auto=np.array([not r['answers'][d['id']]['needs_review'] for r in decisions]);correct=p[i].argmax(1)==targets['test'][i]
            metrics[d['id']]['coverage']=float(auto.mean());metrics[d['id']]['selective_accuracy']=float(correct[auto].mean()) if auto.any() else None
        autoevals=autoevaluate(spec['decisions'],p,targets['test'],include_cases=True)
        quality_errors=quality_gate(selective,net.uncertainty_policy);auto_errors=autogate(autoevals,policy['final_autoevals'])
        cases=harness_evaluate((spec,enc,net),suite)
        latency=[]
        for _ in range(30):
            begin=time.perf_counter();net.predict(x['test'][:1]);latency.append((time.perf_counter()-begin)*1000)
        rejected=np.zeros(len(x['test']),dtype=bool)
        for v in selection_scores:
            if v is not None:rejected|=v<.5
        measured[name]={'learned_selector_rejected_cases':int(rejected.sum()),'warm_model_p50_ms':float(np.median(latency)),'warm_model_p95_ms':float(np.percentile(latency,95)),'latency_scope':'model only, local CPU, 30 warmed single-row calls, excludes encoder and HTTP','test_loss':loss(p,targets['test']),'metrics':metrics,'selective':selective,
            'harness_passed':sum(c['passed'] for c in cases),'harness_total':len(cases),'harness_cases':cases,
            'autoevals_passed':not auto_errors,'uncertainty_passed':not quality_errors,
            'quality_reasons':auto_errors+quality_errors,'temperatures':net.temperature}
        calibrated[name]=net;reports[name]=(audit,autoevals,p,decisions)
        print('COMPARACIÓN '+name+' '+json.dumps({k:measured[name][k] for k in ('test_loss','harness_passed','autoevals_passed','uncertainty_passed')}),flush=True)
    require_unchanged=all(hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()==h for name,h in protected.items())
    if not require_unchanged or hashlib.sha256(args.data.read_bytes()).hexdigest()!=data_hash or hashlib.sha256(router_path.read_bytes()).hexdigest()!=routing_hash:raise ValueError('Protected experiment inputs changed')
    net=calibrated['router'];audit,autoevals,p,decisions=reports['router'];result=measured['router']
    out.mkdir(parents=True);arrays={};graph=describe(net,arrays)
    save(out/'brain.json',spec);export_encoder(enc,out/'encoder.json')
    save(out/'model.json',{'contract_hash':signature(spec),'input_dim':x['train'].shape[1],
        'counts':list(net.counts),'configuration':asdict(cfg),'model_graph':graph,
        'uncertainty_policy':net.uncertainty_policy,'algorithm_routes':selection['routes']})
    np.savez(out/'weights.npz',**arrays)
    saved_spec,saved_enc,saved_net=load_model(out)
    replay=saved_net.predict(encode(states['test'],saved_enc))
    if not all(np.allclose(a,b,atol=1e-7,rtol=1e-6) for a,b in zip(p,replay)):raise ValueError('Router reload probability mismatch')
    for state,expected in zip(states['test'],decisions):
        actual=infer_decision(saved_spec,saved_enc,saved_net,state)
        if actual!=expected:raise ValueError('Router reload decision mismatch')
        check_response({**actual,'model_version':'functional'},spec,'functional')
    # Compatibility chart: explicitly show baseline history, not an invented router loss curve.
    history=copy.deepcopy(histories['neural'])
    for row in history:
        for key in ('train_head_loss','validation_head_loss'):row[key]={d['id']:v for d,v in zip(spec['decisions'],row[key])}
    trace=[{'trial':0,'configuration':asdict(cfg),'epochs':history,'validation_loss':history[-1]['validation_loss'],
            'accepted':True,'status':'reference','hypothesis':'Baseline learning curve; router has separate validation selection','reasons':['reference curve only']}]
    ablations={}
    for name,enabled in [('without_text',bool(enc['text'])),('without_numeric',bool(enc['numeric']))]:
        if enabled:
            ablated=x['test'].copy();n=len(enc['numeric'])
            if name=='without_text':ablated[:,n:]=0
            else:ablated[:,:n]=0
            ablations[name]=evaluate(spec,net.predict(ablated),targets['test'],targets['train'],net.uncertainty_policy)
    summary={'industry':spec['industry'],'seed':args.seed,'dataset_sha256':data_hash,'split_sizes':{s:len(v) for s,v in states.items()},
        'selected_trial':0,'search':trace,'test_loss':result['test_loss'],'metrics':result['metrics'],
        'temperatures':net.temperature,'uncertainty_policy':net.uncertainty_policy,'calibration_audit':audit,
        'selective_decisions':result['selective'],'uncertainty_assurance':{'passed':result['uncertainty_passed'],'reasons':quality_gate(result['selective'],net.uncertainty_policy)},
        'dataset_audit':audit_dataset(parts,spec),'input_ablation':ablations,'uncertainty_training':{'rows':0},
        'data_origin':getattr(args,'origin','user_supplied'),'algorithm_comparison':measured,'router_selection':selection,
        'confidence_method':'1 - normalized entropy; selector score is not probability of correctness',
        'functional_test':{'serialization_passed':True,'typed_response_gate_passed':True,'rows':len(decisions),'router_decisions_equal_after_reload':True},
        'scenarios':[{'state':s,**r} for s,r in zip(states['test'][:5],decisions[:5])],
        'assurance':{'engine':'autoevals','version':autoevals['version'],'passed':not result['quality_reasons'],
           'reasons':result['quality_reasons'],'policy':policy['final_autoevals'],
           'scores':{k:v for k,v in autoevals.items() if k!='cases'},'test_used_for_selection':False,
           'research_policy_sha256':freeze_hash(policy),'protected_inputs_sha256':protected,
           'artifact_sha256':{n:hashlib.sha256((out/n).read_bytes()).hexdigest() for n in ('brain.json','model.json','encoder.json','weights.npz')}}}
    save(out/'report.json',summary);save(out/'comparison.json',{'selection':selection,'results':measured})
    save(out/'autoevals.json',autoevals)
    save(out/'research/research.json',{'selection':selection,'histories':histories,'policy':policy})
    with (out/'predictions.jsonl').open('w',encoding='utf-8') as f:
        for i,r in enumerate(decisions):f.write(json.dumps({'row':i,**r},ensure_ascii=False,allow_nan=False)+'\n')
    render(summary,out)
    from decision_brain.multi_reporting import render_comparison
    render_comparison(summary,out)
    print('ROUTER '+json.dumps(selection['routes'],ensure_ascii=False),flush=True)
    print(f'FUNCTIONAL TEST PASSED; {len(decisions)} rows, router and gates reloaded',flush=True)
    print('ASEGURAMIENTO '+('PASS' if summary['assurance']['passed'] else 'FAIL')+' '+str(result['quality_reasons']),flush=True)
    print('Informe:',(out/'report.html').resolve(),flush=True)
    return summary
