#!/usr/bin/env python3
"""Offline decision evaluation harness; never trains or executes business actions."""
import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import sys
import time
import uuid
from datetime import datetime,timezone
from decision_brain.runtime_paths import latest_model
from decision_brain.brain import load_model, encode, judge, signature
from decision_brain.contracts import validate_state


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_suite(suite, spec):
    if not isinstance(suite,dict):raise ValueError('Suite must be an object')
    if suite.get('version') != 1 or not isinstance(suite.get('cases'), list) or not suite['cases']:
        raise ValueError('Suite version=1 and nonempty cases required')
    ids=set()
    decisions={d['id']: {o['id'] for o in d['options']} for d in spec['decisions']}
    actions={spec['routing']['fallback'], spec['routing'].get('review_action','revision_humana')}
    actions.update(r['action'] for r in spec['routing'].get('rules', []))
    for case in suite['cases']:
        if not isinstance(case,dict) or set(case)-{'id','context','expected','expect_error'}:raise ValueError('Invalid case keys')
        if 'expect_error' in case and type(case['expect_error']) is not bool:raise ValueError('expect_error must be boolean')
        cid=case.get('id')
        if not isinstance(cid,str) or not cid or cid in ids: raise ValueError('Case IDs must be unique nonempty strings')
        ids.add(cid)
        if case.get('expect_error') is True:
            if 'expected' in case: raise ValueError('Error cases cannot have expected decisions')
            if 'context' not in case: raise ValueError('Missing context')
            continue
        validate_state(case['context'], spec)
        expected=case.get('expected', {})
        if not expected or set(expected)-{'answers','action','needs_review'}: raise ValueError('Invalid or empty expected assertions')
        answers=expected.get('answers',{})
        if not isinstance(answers,dict): raise ValueError('answers must be an object')
        for key,value in answers.items():
            if key not in decisions:raise ValueError('Unknown expected decision')
            if isinstance(value,dict):
                d=next(d for d in spec['decisions'] if d['id']==key)
                field='noul' if d['kind'] in ('boolean','noul') else 'score' if d['kind']=='score' else None
                if field is None or set(value)!={field}:raise ValueError('Invalid numeric assertion')
                bounds=value[field];top=1 if field=='noul' else len(d['options'])-1
                if not isinstance(bounds,dict) or set(bounds)!={'min','max'}:raise ValueError('Range requires min and max')
                if any(type(v) not in (int,float) or not math.isfinite(v) for v in bounds.values()) or not 0<=bounds['min']<=bounds['max']<=top:raise ValueError('Invalid assertion range')
            elif not isinstance(value,str) or value not in decisions[key]:raise ValueError('Unknown expected option')
        if not answers and not any(k in expected for k in ('action','needs_review')): raise ValueError('No assertions')
        if 'action' in expected and expected['action'] not in actions: raise ValueError('Unknown action')
        if 'needs_review' in expected and type(expected['needs_review']) is not bool: raise ValueError('needs_review must be boolean')


def evaluate(model, suite):
    spec, enc, net=model
    rows=[]
    for case in suite['cases']:
        start=time.perf_counter()
        try:
            state=validate_state(case['context'],spec)
        except (ValueError,TypeError,KeyError) as exc:
            passed=case.get('expect_error') is True
            rows.append({'id':case['id'],'passed':passed,'checks':{'input_rejected':passed},'error':str(exc),'latency_ms':(time.perf_counter()-start)*1000})
            continue
        # Inference exceptions are infrastructure failures, never expected-input passes.
        probs=[p[0] for p in net.predict(encode([state],enc))]
        for d,p in zip(spec['decisions'],probs):
            if len(p)!=len(d['options']) or not all(math.isfinite(float(v)) and 0<=v<=1 for v in p) or abs(float(sum(p))-1)>1e-5:
                raise ValueError('Invalid probability distribution')
        answer=judge(spec,probs)
        expected=case.get('expected',{})
        checks={'no_action_executed':answer['action_executed'] is False}
        if case.get('expect_error'): checks['input_rejected']=False
        for key,value in expected.get('answers',{}).items():
            if isinstance(value,dict):
                field,bounds=next(iter(value.items()))
                checks['answer:'+key]=bounds['min']<=answer['answers'][key][field]<=bounds['max']
            else:checks['answer:'+key]=answer['answers'][key]['choice']==value
        if 'action' in expected: checks['action']=answer['proposed_action']==expected['action']
        if 'needs_review' in expected: checks['needs_review']=any(a['needs_review'] for a in answer['answers'].values())==expected['needs_review']
        rows.append({'id':case['id'],'passed':all(checks.values()),'checks':checks,'expected':expected,'actual':answer,'latency_ms':(time.perf_counter()-start)*1000})
    return rows


def run(run_dir,suite_path,out,baseline=None,min_pass_rate=1.0):
    if out.exists(): raise ValueError('Output exists; choose a new directory')
    if not math.isfinite(min_pass_rate) or not 0<=min_pass_rate<=1: raise ValueError('min-pass-rate must be in [0,1]')
    model=load_model(run_dir)
    suite=json.loads(suite_path.read_text(encoding='utf-8'))
    validate_suite(suite,model[0])
    rows=evaluate(model,suite)
    regressions=[]
    if baseline:
        previous=load_model(baseline)
        if signature(previous[0])!=signature(model[0]): raise ValueError('Baseline contract differs')
        old=evaluate(previous,suite)
        regressions=[a['id'] for a,b in zip(old,rows) if a['passed'] and not b['passed']]
    rate=sum(r['passed'] for r in rows)/len(rows)
    passed=rate>=min_pass_rate and not regressions
    fingerprints=lambda folder:{f:digest(folder/f) for f in ('brain.json','model.json','encoder.json','weights.npz')}
    report={'version':1,'passed':passed,'suite_sha256':digest(suite_path),'suite_origin':suite.get('origin','unspecified'),
            'model_sha256':fingerprints(run_dir),'baseline_sha256':fingerprints(baseline) if baseline else None,
            'cases_count':len(rows),'pass_rate':rate,'min_pass_rate':min_pass_rate,'regressions':regressions,'cases':rows,
            'interpretation':f'{sum(r["passed"] for r in rows)} de {len(rows)} casos cumplen todas sus expectativas. '+
            ('Cumple el umbral y no hay regresiones frente a la referencia evaluada.' if passed and baseline else 'Cumple el umbral; no se comparó con una referencia.' if passed else 'No cumple el criterio: revisar los casos fallidos o las regresiones.'),
            'limitations':'Prueba offline de casos declarados. No demuestra rendimiento en producción, carga ni independencia de los datos sintéticos. No autoriza despliegues.'}
    out.mkdir(parents=True)
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
    esc=lambda x:html.escape(str(x))
    body=''.join('<tr><td>'+esc(r['id'])+'</td><td>'+('PASS' if r['passed'] else 'FAIL')+'</td><td>'+esc(', '.join(k for k,v in r['checks'].items() if not v) or 'Todas las comprobaciones satisfechas')+'</td><td>'+esc(r.get('actual',{}).get('interpretation',r.get('error','')))+'</td></tr>' for r in rows)
    (out/'report.html').write_text('<!doctype html><html lang="es"><meta charset="utf-8"><title>Harness de decisiones</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px}td,th{padding:12px;border:1px solid #ccc;text-align:left}table{border-collapse:collapse}meter{width:100%}</style><h1>Evaluación de decisiones: '+('PASS' if passed else 'FAIL')+'</h1><p>'+esc(report['interpretation'])+'</p><label>Cumplimiento de casos: '+f'{rate:.1%}'+'</label><meter min="0" max="1" value="'+str(rate)+'"></meter><p>Origen: '+esc(report['suite_origin'])+' · Regresiones: '+esc(', '.join(regressions) or 'ninguna detectada')+'</p><table><tr><th>Caso</th><th>Resultado</th><th>Comprobaciones fallidas</th><th>Interpretación</th></tr>'+body+'</table><p>'+esc(report['limitations'])+'</p></html>', encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,help='Explicit TOML file; otherwise ./project.toml if present')
    p.add_argument('--run',type=Path)
    p.add_argument('--suite',type=Path)
    p.add_argument('--output',type=Path)
    p.add_argument('--baseline',type=Path)
    p.add_argument('--min-pass-rate',type=float)
    a=p.parse_args()
    try:
        from decision_brain.project_config import load_project
        config_path=a.project or Path('project.toml')
        config=load_project(config_path) if a.project or config_path.exists() else {}
        values={'suite':Path('config/harness_suite.json'),'min_pass_rate':1.0,**config}
        for key in ('run','suite','output','baseline','min_pass_rate'):
            if getattr(a,key) is not None: values[key]=getattr(a,key)
            setattr(a,key,values.get(key))
        base=config_path.resolve().parent
        if a.run is None:a.run=latest_model(base)
        if a.output is None:a.output=base/'runs'/('harness_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
        report=run(a.run,a.suite,a.output,a.baseline,a.min_pass_rate)
    except Exception as exc:
        print(f'HARNESS ERROR: {exc}',file=sys.stderr);return 2
    print(report['interpretation']);print(f'HTML: {a.output.resolve()}/report.html')
    return 0 if report['passed'] else 1

if __name__=='__main__':sys.exit(main())
