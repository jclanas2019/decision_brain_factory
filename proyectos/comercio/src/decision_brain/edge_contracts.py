"""Pure interoperability contracts. No model execution or observability service."""
import hashlib
import json
import math
import re
from decision_brain.contracts import validate_state

TRACE=re.compile(r'^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$')
BRAIN=re.compile(r'^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*){1,5}$')
KEY=re.compile(r'^[A-Za-z0-9_.:-]{1,128}$')

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)
def contract_hash(spec):return hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
def actions(spec):return sorted({spec['routing']['fallback'],spec['routing'].get('review_action','revision_humana'),*[r['action'] for r in spec['routing'].get('rules',[])]})
def trace_id(value):
    match=TRACE.fullmatch(value or '')
    if not match or int(match[1],16)==0 or int(match[2],16)==0:raise ValueError('invalid_traceparent')
    return match[1]

def check_context(state,spec,limits):
    validate_state(state,spec)
    for value in state.values():
        if isinstance(value,str) and len(value)>limits['max_text_chars']:raise OverflowError('text_size')
        if isinstance(value,(float,int)) and abs(value)>limits['max_numeric_magnitude']:raise OverflowError('numeric_size')

def expected_route(spec,answers):
    if any(v['needs_review'] for v in answers.values()):return spec['routing'].get('review_action','revision_humana'),'review',False
    for i,rule in enumerate(spec['routing'].get('rules',[])):
        if answers[rule['decision']]['probabilities'][rule['option']]>=rule.get('min_probability',.65):return rule['action'],f'rule:{i}',False
    return spec['routing']['fallback'],'fallback',True

def check_response(value,spec,version):
    if not isinstance(value,dict) or value.get('model_version')!=version:raise ValueError('response_version')
    if value.get('action_executed') is not False:raise ValueError('unexpected_action_execution')
    answers=value.get('answers')
    if not isinstance(answers,dict) or set(answers)!={d['id'] for d in spec['decisions']}:raise ValueError('response_heads')
    for d in spec['decisions']:
        a=answers[d['id']];options=[o['id'] for o in d['options']]
        if not isinstance(a,dict) or a.get('kind')!=d['kind'] or a.get('choice') not in options:raise ValueError('response_type')
        p=a.get('probabilities')
        if not isinstance(p,dict) or set(p)!=set(options):raise ValueError('response_options')
        if any(type(v) not in (float,int) or not math.isfinite(v) or v<0 or v>1 for v in p.values()) or abs(sum(p.values())-1)>1e-5:raise ValueError('response_probabilities')
        winner=max(options,key=lambda k:p[k]);confidence=p[winner]
        if a['choice']!=winner or type(a.get('max_probability')) not in (float,int) or not math.isfinite(a['max_probability']) or abs(a['max_probability']-confidence)>1e-6:raise ValueError('response_winner')
        if type(a.get('needs_review')) is not bool or a['needs_review']!=(confidence<d.get('min_probability',.6)):raise ValueError('response_review')
        if d['kind']=='boolean' and (type(a.get('probability_true')) not in (float,int) or not math.isfinite(a['probability_true']) or abs(a['probability_true']-p['true'])>1e-6):raise ValueError('response_boolean')
        if d['kind']=='score':
            expected=sum(o['value']*p[o['id']] for o in d['options'])
            if type(a.get('expected_score')) not in (int,float) or not math.isfinite(a['expected_score']) or abs(a['expected_score']-expected)>1e-6:raise ValueError('response_score')
    action,rule,fallback=expected_route(spec,answers)
    if value.get('proposed_action') not in actions(spec) or value['proposed_action']!=action:raise ValueError('response_action')
    # Rebuild only validated fields: arbitrary upstream JSON cannot cross the edge.
    clean={}
    for d in spec['decisions']:
        a=answers[d['id']]
        clean[d['id']]={k:a[k] for k in ('kind','choice','probabilities','max_probability','needs_review')}
        if d['kind']=='boolean':clean[d['id']]['probability_true']=a['probability_true']
        if d['kind']=='score':clean[d['id']]['expected_score']=a['expected_score']
    return clean,action,rule,fallback
