"""Local research implementations: CORN and a multihead SelectiveNet adaptation.

These implement published objectives, not the original authors' architectures.
All artifacts remain numeric NPZ + JSON; no arbitrary model code is loaded.
"""
import time
from dataclasses import asdict
import numpy as np
from scipy.special import expit
from decision_brain.network import MultiDecisionNet, Config, softmax, loss, single_loss


def tempered(p, temperature):
    return softmax(np.log(np.clip(p.astype(np.float64), 1e-15, 1.)) / temperature)


class AdvancedNet(MultiDecisionNet):
    def __init__(self, dim, cfg, seed, counts, kind, ordinal_heads=()):
        super().__init__(dim,cfg,seed,counts)
        if kind not in ('corn','selective'):raise ValueError('unknown advanced architecture')
        self.kind=kind;self.ordinal_heads=tuple(ordinal_heads);rng=np.random.default_rng(seed+811)
        if kind=='corn':
            for i in self.ordinal_heads:
                self.params[2+2*i]=rng.normal(0,np.sqrt(2/cfg.hidden),(cfg.hidden,counts[i]-1)).astype(np.float32)
                self.params[3+2*i]=np.zeros(counts[i]-1,dtype=np.float32)
        else:
            self.params.extend([rng.normal(0,.05,(cfg.hidden,1)).astype(np.float32),np.zeros(1,np.float32)])
            for count in counts:
                self.params.extend([rng.normal(0,np.sqrt(2/cfg.hidden),(cfg.hidden,count)).astype(np.float32),np.zeros(count,np.float32)])
        self.coverage_target=.8;self.penalty=32.;self.mix=.5

    def raw(self,x):
        p=self.params;h=np.tanh(x@p[0]+p[1]);probs=[]
        for i in range(len(self.counts)):
            z=h@p[2+2*i]+p[3+2*i]
            if self.kind=='corn' and i in self.ordinal_heads:
                survival=np.cumprod(expit(z),axis=1)
                prob=np.column_stack([1-survival[:,0],survival[:,:-1]-survival[:,1:],survival[:,-1]])
            else:prob=softmax(z)
            probs.append(prob)
        return h,probs

    def predict(self,x):return [tempered(p,t) for p,t in zip(self.raw(x)[1],self.temperature)]
    def _raw_prob(self,x,i,t):return tempered(self.raw(x)[1][i],t)
    def review_scores(self,x):
        if self.kind!='selective':return [None]*len(self.counts)
        h=np.tanh(x@self.params[0]+self.params[1]);j=2+2*len(self.counts)
        score=expit(h@self.params[j]+self.params[j+1])[:,0]
        return [score]*len(self.counts)

    def objective_and_grad(self,x,y):
        p=self.params;n=len(x);heads=len(y);h,probs=self.raw(x)
        grad=[np.zeros_like(a) for a in p];dh=np.zeros_like(h);objective=0.
        if self.kind=='selective':
            j=2+2*heads;g=expit(h@p[j]+p[j+1])[:,0];den=max(float(g.sum()),1e-12)
            row_loss=np.mean([-np.log(np.clip(v[np.arange(n),t],1e-15,1)) for v,t in zip(probs,y)],axis=0)
            risk=float(g@row_loss/den);shortfall=max(0,self.coverage_target-float(g.mean()))
            objective=self.mix*(risk+self.penalty*shortfall**2)
            dg=self.mix*((row_loss-risk)/den-2*self.penalty*shortfall/n)
            dzg=(dg*g*(1-g))[:,None];grad[j]=h.T@dzg;grad[j+1]=dzg.sum(0);dh+=dzg@p[j].T
            for i,(prob,target) in enumerate(zip(probs,y)):
                dz=prob.copy();dz[np.arange(n),target]-=1;dz*=self.mix*g[:,None]/(den*heads)
                grad[2+2*i]=h.T@dz;grad[3+2*i]=dz.sum(0);dh+=dz@p[2+2*i].T
                a=j+2+2*i;aux=softmax(h@p[a]+p[a+1]);objective+=(1-self.mix)*single_loss(aux,target)/heads
                da=aux.copy();da[np.arange(n),target]-=1;da*=(1-self.mix)/(n*heads)
                grad[a]=h.T@da;grad[a+1]=da.sum(0);dh+=da@p[a].T
        else:
            for i,(prob,target) in enumerate(zip(probs,y)):
                if i in self.ordinal_heads:
                    z=h@p[2+2*i]+p[3+2*i];levels=np.arange(self.counts[i]-1)
                    mask=(target[:,None]>=levels);binary=(target[:,None]>levels)
                    denom=max(int(mask.sum()),1)*heads
                    objective+=float(np.sum((np.logaddexp(0,z)-binary*z)*mask)/denom)
                    dz=(expit(z)-binary)*mask/denom
                else:
                    objective+=single_loss(prob,target)/heads
                    dz=prob.copy();dz[np.arange(n),target]-=1;dz/=(n*heads)
                grad[2+2*i]=h.T@dz;grad[3+2*i]=dz.sum(0);dh+=dz@p[2+2*i].T
        da=dh*(1-h*h);grad[0]=x.T@da;grad[1]=da.sum(0)
        for i,a in enumerate(p):
            if a.ndim==2:
                objective+=.5*self.cfg.decay*float(np.sum(a*a));grad[i]+=self.cfg.decay*a
        return float(objective),grad

    def train(self,x,y,seed,xv,yv,log_every=10,deadline=None):
        if any(t.ndim!=1 for t in y):raise ValueError('Advanced models require hard labels')
        rng=np.random.default_rng(seed);m=[np.zeros_like(p) for p in self.params];v=[a.copy() for a in m]
        best=float('inf');wait=0;step=0;saved=None;history=[]
        for epoch in range(self.cfg.epochs):
            for ix in np.array_split(rng.permutation(len(x)),max(1,int(np.ceil(len(x)/64)))):
                if deadline and time.monotonic()>=deadline:raise TimeoutError('Multi-model training budget exceeded')
                _,grad=self.objective_and_grad(x[ix],[t[ix] for t in y]);step+=1
                for i,g in enumerate(grad):
                    m[i]=.9*m[i]+.1*g;v[i]=.999*v[i]+.001*g*g
                    self.params[i]-=self.cfg.lr*(m[i]/(1-.9**step))/(np.sqrt(v[i]/(1-.999**step))+1e-8)
            train_p=self.predict(x);val_p=self.predict(xv);objective,_=self.objective_and_grad(xv,yv)
            row={'epoch':epoch+1,'train_loss':loss(train_p,y),'validation_loss':loss(val_p,yv),
                 'train_head_loss':[single_loss(a,b) for a,b in zip(train_p,y)],
                 'validation_head_loss':[single_loss(a,b) for a,b in zip(val_p,yv)],'validation_objective':objective}
            if not np.isfinite(objective):raise ValueError('Nonfinite training objective')
            history.append(row)
            if epoch==0 or (epoch+1)%log_every==0:print(f"  {self.kind} epoch={epoch+1} train_loss={row['train_loss']:.5f} validation_loss={row['validation_loss']:.5f}",flush=True)
            if objective<best-1e-4:best=objective;saved=[p.copy() for p in self.params];wait=0
            else:wait+=1
            if wait>=9:break
        self.params=saved
        return loss(self.predict(xv),yv),history


class Ensemble:
    def __init__(self,members):
        self.members=members;self.counts=members[0].counts;self.temperature=[1.]*len(self.counts);self.cfg=members[0].cfg
    def raw(self,x):
        values=[m.predict(x) for m in self.members]
        return [np.mean([p[i] for p in values],axis=0) for i in range(len(self.counts))]
    def predict(self,x):return [tempered(p,t) for p,t in zip(self.raw(x),self.temperature)]
    def _raw_prob(self,x,i,t):return tempered(self.raw(x)[i],t)
    def review_scores(self,x):return [None]*len(self.counts)


class AlgorithmRouter:
    """Static per-head routing fitted on routing validation, never per-request certainty."""
    def __init__(self,candidates,routes):
        if not candidates or any(name not in candidates for name in routes):raise ValueError('unknown routed algorithm')
        counts=next(iter(candidates.values())).counts
        if len(routes)!=len(counts) or any(tuple(m.counts)!=tuple(counts) for m in candidates.values()):raise ValueError('router head mismatch')
        self.candidates=candidates;self.routes=list(routes);self.counts=counts
        self.temperature=[1.]*len(counts);self.cfg=next(iter(candidates.values())).cfg
    def raw(self,x):
        predictions={name:self.candidates[name].predict(x) for name in set(self.routes)}
        return [predictions[name][i] for i,name in enumerate(self.routes)]
    def predict(self,x):return [tempered(p,t) for p,t in zip(self.raw(x),self.temperature)]
    def _raw_prob(self,x,i,t):return tempered(self.raw(x)[i],t)
    def review_scores(self,x):
        values={name:review_scores(self.candidates[name],x) for name in set(self.routes)}
        return [values[name][i] for i,name in enumerate(self.routes)]


def review_scores(net,x):
    return net.review_scores(x) if hasattr(net,'review_scores') else [None]*len(net.counts) if hasattr(net,'counts') else [None]*len(net.predict(x))


def describe(net,arrays,prefix='root'):
    base={'temperature':list(net.temperature),'counts':list(net.counts)}
    if isinstance(net,AlgorithmRouter):
        return {**base,'kind':'router','routes':net.routes,'candidates':{k:describe(v,arrays,prefix+'_'+k) for k,v in net.candidates.items()}}
    if isinstance(net,Ensemble):return {**base,'kind':'ensemble','members':[describe(v,arrays,prefix+'_'+str(i)) for i,v in enumerate(net.members)]}
    names=[]
    for i,p in enumerate(net.params):
        name=prefix+'_p'+str(i);arrays[name]=p;names.append(name)
    return {**base,'kind':getattr(net,'kind','neural'),'configuration':asdict(net.cfg),
            'ordinal_heads':list(getattr(net,'ordinal_heads',())),'parameters':names}


def restore(desc,arrays,dim,depth=0):
    if depth>3 or not isinstance(desc,dict):raise ValueError('invalid model graph')
    counts=desc['counts'];kind=desc['kind']
    if not isinstance(counts,list) or not 1<=len(counts)<=100 or any(type(k) is not int or not 2<=k<=256 for k in counts):raise ValueError('invalid head counts')
    if kind=='router':
        candidates=desc['candidates']
        if not isinstance(candidates,dict) or not 1<=len(candidates)<=8 or any(k not in ('neural','ensemble','corn','selective') for k in candidates):raise ValueError('invalid candidates')
        net=AlgorithmRouter({k:restore(v,arrays,dim,depth+1) for k,v in candidates.items()},desc['routes'])
    elif kind=='ensemble':
        if not 2<=len(desc['members'])<=5:raise ValueError('invalid ensemble size')
        net=Ensemble([restore(v,arrays,dim,depth+1) for v in desc['members']])
    elif kind in ('neural','corn','selective'):
        cfg=Config(**desc['configuration'])
        if type(cfg.hidden) is not int or not 1<=cfg.hidden<=1024:raise ValueError('invalid hidden size')
        ordinal=desc.get('ordinal_heads',[])
        if any(type(i) is not int or not 0<=i<len(counts) for i in ordinal) or len(set(ordinal))!=len(ordinal):raise ValueError('invalid ordinal heads')
        net=MultiDecisionNet(dim,cfg,0,counts) if kind=='neural' else AdvancedNet(dim,cfg,0,counts,kind,ordinal)
        params=[arrays[name] for name in desc['parameters']]
        if len(params)!=len(net.params) or any(a.shape!=b.shape or a.dtype.kind!='f' or not np.isfinite(a).all() for a,b in zip(params,net.params)):raise ValueError('invalid model parameters')
        net.params=params
    else:raise ValueError('unknown model architecture')
    t=np.asarray(desc['temperature'])
    if tuple(net.counts)!=tuple(counts) or t.shape!=(len(counts),) or not np.isfinite(t).all() or (t<=0).any():raise ValueError('invalid model temperatures')
    net.temperature=t.tolist()
    return net
