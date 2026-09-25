"""Declarative contract validation. Configuration is data, never executable code."""
import json
import math
import re
import string
from pathlib import Path

IDENT = re.compile(r'^[a-z][a-z0-9_]{0,63}$')
SPLITS = ('train','validation','calibration','test')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(spec):
    require(spec.get('version') == 1, 'version must be 1')
    require(isinstance(spec.get('industry'),str) and spec['industry'].strip(), 'industry is required')
    for group in ('fields','decisions'):
        require(isinstance(spec.get(group),list) and len(spec[group])>0, f'{group} must be nonempty')
        ids=[v.get('id','') for v in spec[group]]
        require(all(IDENT.fullmatch(k) for k in ids),f'invalid identifier in {group}')
        require(len(set(ids))==len(ids),f'duplicate identifier in {group}')
    for field in spec['fields']:
        require(not field['id'].startswith('target__'),'context fields cannot use the target__ prefix')
        require(field.get('type') in ('number','text','category'),'unknown field type')
        require(bool(field.get('description')),'field description is required')
        if field['type']=='category':
            require(isinstance(field.get('values'),list) and len(field['values'])>0,'category values required')
    for d in spec['decisions']:
        require(d.get('kind') in ('choice','boolean','score','noul'),'invalid decision kind')
        require(bool(d.get('question')),'each decision needs a question')
        options=d.get('options',[])
        require(2<=len(options)<=64,'each decision needs 2 to 64 options')
        ids=[o.get('id','') for o in options]
        require(len(set(ids))==len(ids) and all(IDENT.fullmatch(k) for k in ids),'invalid option identifiers')
        require(all(bool(o.get('meaning')) for o in options),'option meanings required')
        if d['kind'] in ('boolean','noul'):require(ids==['false','true'],'noul/boolean options must be false, true in that order')
        if d['kind']=='score':
            values=[o.get('value') for o in options]
            require(all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in values),'score values must be finite numbers')
            require(all(a<b for a,b in zip(values,values[1:])),'score values must increase')
        require(0<=d.get('min_probability',.6)<=1,'invalid probability threshold')
    decision_map={d['id']:d for d in spec['decisions']}
    policy=spec.get('routing',{})
    require(bool(policy.get('fallback')),'routing fallback required')
    for rule in policy.get('rules',[]):
        require(rule.get('decision') in decision_map,'routing refers to unknown decision')
        require(rule.get('option') in [o['id'] for o in decision_map[rule['decision']]['options']], 'routing refers to unknown option')
        require(0<=rule.get('min_probability',.65)<=1 and bool(rule.get('action')),'invalid routing rule')
    for scenario in spec.get('synthetic_scenarios',[]):
        require(set(scenario.get('context',{}))=={f['id'] for f in spec['fields']},'scenario fields mismatch')
        require(set(scenario.get('targets',{}))==set(decision_map),'scenario targets mismatch')
        for d in spec['decisions']:
            require(scenario['targets'][d['id']] in [o['id'] for o in d['options']],'unknown scenario target')
        for f in spec['fields']:
            v=scenario['context'][f['id']]
            if f['type']=='text':
                require(isinstance(v,dict) and set(v)==set(SPLITS),'synthetic text needs four separate split templates')
                require(all(isinstance(x,str) and x.strip() for x in v.values()),'empty text template')
                require(len(set(v.values()))==4,'do not reuse text templates across splits')
                for template in v.values():
                    require(all(key is None or key in ('company','name','city','code') and not fmt and not conversion
                                for _,key,fmt,conversion in string.Formatter().parse(template)),
                            'templates support only {company}, {name}, {city}, {code}')
            elif f['type']=='number':
                require(isinstance(v,list) and len(v)==2 and all(isinstance(x,(int,float)) and math.isfinite(x) for x in v) and v[0]<=v[1],'number template must be [min,max]')
            else:require(v in f['values'],'invalid category template')
    return spec


def read_spec(path):
    return validate(json.loads(Path(path).read_text(encoding='utf-8')))


def validate_state(state,spec):
    require(isinstance(state,dict),'context must be an object')
    names={f['id'] for f in spec['fields']}
    require(set(state)==names,f'context fields must be exactly {sorted(names)}; labels are not inputs')
    for f in spec['fields']:
        v=state[f['id']]
        if f['type']=='number':
            require(not isinstance(v,bool) and isinstance(v,(int,float)) and math.isfinite(v),f'{f["id"]} must be finite numeric')
        else:
            require(isinstance(v,str) and bool(v.strip()),f'{f["id"]} must be nonempty text')
            if f['type']=='category':require(v in f['values'],f'invalid category in {f["id"]}')
    return state
