"""Offline AutoEvals integration for typed neural outputs; no remote judge."""
from importlib.metadata import version
import math
import numpy as np
from autoevals import ExactMatch,Score


def exact(output,expected):
    result=ExactMatch().eval(output=output,expected=expected)
    if result.error is not None or result.score not in (0,1):raise ValueError('AutoEvals ExactMatch failed')
    return float(result.score)


def custom(name,value):
    if not math.isfinite(value) or not 0<=value<=1:raise ValueError('Invalid AutoEvals custom score')
    result=Score(name=name,score=float(value))
    return {'name':result.name,'score':result.score,'implementation':'decision_brain custom AutoEvals Score'}


def evaluate(decisions,probabilities,targets,include_cases=False):
    if len(probabilities)!=len(decisions) or len(targets)!=len(decisions):raise ValueError('AutoEvals head mismatch')
    n=len(targets[0]);heads={};case_scores=[];joint=np.ones(n,dtype=bool)
    if n==0:raise ValueError('AutoEvals empty evaluation')
    for d,p,y in zip(decisions,probabilities,targets):
        k=len(d['options']);p=np.asarray(p);y=np.asarray(y)
        if p.shape!=(n,k) or y.shape!=(n,) or not np.issubdtype(y.dtype,np.integer) or (y<0).any() or (y>=k).any():raise ValueError('AutoEvals shape/target mismatch')
        if not np.isfinite(p).all() or (p<0).any() or (p>1).any() or not np.allclose(p.sum(axis=1),1,atol=1e-5):raise ValueError('AutoEvals invalid probabilities')
        ids=[o['id'] for o in d['options']];pred=p.argmax(axis=1)
        matches=[exact(ids[int(a)],ids[int(b)]) for a,b in zip(pred,y)]
        joint&=np.asarray(matches,dtype=bool)
        kind='noul' if d['kind']=='boolean' else d['kind']
        if kind=='noul':quality=1-(p[:,1]-y)**2
        else:quality=1-np.sum((p-np.eye(k)[y])**2,axis=1)/2
        summary={'exact_match':float(np.mean(matches)),'probability_quality':custom('BrierQuality',float(np.mean(quality)))['score']}
        if kind=='score':summary['score_closeness']=custom('OrdinalCloseness',float(np.mean(1-abs(p@np.arange(k)-y)/(k-1))))['score']
        heads[d['id']]=summary
        if include_cases:
            for i,(match,q) in enumerate(zip(matches,quality)):
                case_scores.append({'row':i,'question':d['id'],'ExactMatch':match,'BrierQuality':float(q)})
    return {'engine':'autoevals','version':version('autoevals'),'mode':'local_no_remote_judge','rows':n,
            'heads':heads,'all_heads_exact':float(joint.mean()),'schema_passed':True,
            **({'cases':case_scores} if include_cases else {})}


def gate(result,policy):
    reasons=[]
    if not isinstance(result,dict):return ['missing AutoEvals results']
    if result.get('engine')!='autoevals' or result.get('schema_passed') is not True or not isinstance(result.get('heads'),dict) or not result['heads'] or type(result.get('rows')) is not int or result['rows']<1:return ['missing AutoEvals results']
    for name,m in result['heads'].items():
        for metric,limit in policy.items():
            if metric=='score_closeness' and metric not in m:continue
            value=m.get(metric)
            if type(value) not in (float,int) or not math.isfinite(value) or value<limit:reasons.append(name+': '+metric+' below threshold')
    return reasons
