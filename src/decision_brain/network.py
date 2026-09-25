"""Shared neural encoder with a variable number of classification heads."""
import numpy as np
from dataclasses import dataclass, asdict

def softmax(x):
    z=x-x.max(axis=1,keepdims=True); p=np.exp(z)
    return p/p.sum(axis=1,keepdims=True)


@dataclass(frozen=True)
class Config:
    hidden:int=64
    lr:float=.008
    decay:float=.0002
    epochs:int=55


class MultiDecisionNet:
    def __init__(self,dim,cfg,seed,counts):
        rng=np.random.default_rng(seed)
        self.cfg=cfg
        self.counts=tuple(counts)
        self.params=[rng.normal(0,np.sqrt(2/dim),(dim,cfg.hidden)).astype(np.float32),
                     np.zeros(cfg.hidden,dtype=np.float32)]
        for count in self.counts:
            self.params.extend([rng.normal(0,np.sqrt(2/cfg.hidden),(cfg.hidden,count)).astype(np.float32),
                                np.zeros(count,dtype=np.float32)])
        self.temperature=[1.] * len(self.counts)

    def forward(self,x):
        p=self.params; h=np.tanh(x@p[0]+p[1]);
        return h,[softmax(h@p[2+2*i]+p[3+2*i]) for i in range(len(self.counts))]

    def predict(self,x):
        p=self.params;h=np.tanh(x@p[0]+p[1]);
        return [softmax((h@p[2+2*i]+p[3+2*i])/self.temperature[i]) for i in range(len(self.counts))]

    def train(self,x,y,seed,xv,yv,log_every=10):
        rng=np.random.default_rng(seed); p=self.params
        m=[np.zeros_like(a) for a in p]; v=[np.zeros_like(a) for a in p]
        best=float('inf'); saved=None; wait=0; step=0; history=[]
        for epoch in range(self.cfg.epochs):
            for ix in np.array_split(rng.permutation(len(x)),max(1,int(np.ceil(len(x)/64)))):
                xb=x[ix]; h,probs=self.forward(xb); dh=np.zeros_like(h)
                g=[np.zeros_like(a) for a in p]
                for i,prob in enumerate(probs):
                    dz=prob.copy();dz[np.arange(len(ix)),y[i][ix]]-=1
                    dz/=(len(ix)*len(self.counts))
                    g[2+2*i]=h.T@dz+self.cfg.decay*p[2+2*i]
                    g[3+2*i]=dz.sum(axis=0)
                    dh+=dz@p[2+2*i].T
                da=dh*(1-h*h)
                g[0]=xb.T@da+self.cfg.decay*p[0];g[1]=da.sum(axis=0)
                step+=1
                for j in range(len(p)):
                    m[j]=.9*m[j]+.1*g[j];v[j]=.999*v[j]+.001*g[j]*g[j]
                    p[j]-=self.cfg.lr*(m[j]/(1-.9**step))/(np.sqrt(v[j]/(1-.999**step))+1e-8)
            train_score=loss(self.predict(x),y)
            score=loss(self.predict(xv),yv)
            if not np.isfinite(train_score) or not np.isfinite(score):raise ValueError('Nonfinite training loss; check data scale and learning rate')
            history.append({'epoch':epoch+1,'train_loss':train_score,'validation_loss':score})
            if epoch==0 or (epoch+1)%log_every==0:
                print(f'  epoch={epoch+1} train_loss={train_score:.5f} '
                      f'validation_loss={score:.5f}',flush=True)
            if score<best-1e-4:
                best=score;saved=[a.copy() for a in p];wait=0
            else:wait+=1
            if wait>=9:break
        self.params=saved
        if history[-1]['epoch']%log_every!=0:
            last=history[-1]
            print(f"  epoch={last['epoch']} train_loss={last['train_loss']:.5f} "
                  f"validation_loss={last['validation_loss']:.5f}",flush=True)
        return best,history

    def _raw_prob(self,x,i,t):
        p=self.params;h=np.tanh(x@p[0]+p[1]);return softmax((h@p[2+2*i]+p[3+2*i])/t)


def single_loss(p,y):return float(-np.log(np.clip(p[np.arange(len(y)),y],1e-9,1)).mean())
def loss(probs,y):return float(np.mean([single_loss(p,a) for p,a in zip(probs,y)]))

