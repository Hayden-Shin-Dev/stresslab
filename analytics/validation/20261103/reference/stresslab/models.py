"""Joint response distributions. Whole residual rows preserve cross-asset dependence."""
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.neighbors import NearestNeighbors
from .config import SEED

def pct(log_returns):
    return np.expm1(np.asarray(log_returns)/100)*100

class DistributionModel:
    def __init__(self, name):
        self.name=name

    def fit(self,X,Y):
        self.X=np.asarray(X); self.Y=np.asarray(Y)
        self.scaler=StandardScaler().fit(self.X)
        if self.name=='ridge':
            self.model=make_pipeline(StandardScaler(),Ridge(alpha=30)).fit(X,Y)
        elif self.name=='quantile_gb':
            self.models=[]
            for j in range(Y.shape[1]):
                row=[]
                for q in [.05,.5,.95]:
                    m=GradientBoostingRegressor(loss='quantile',alpha=q,n_estimators=90,max_depth=2,
                                                min_samples_leaf=35,learning_rate=.04,random_state=SEED)
                    m.fit(X,Y[:,j]); row.append(m)
                self.models.append(row)
        elif self.name=='conditional_history':
            self.nn=NearestNeighbors(n_neighbors=min(120,len(X))).fit(self.scaler.transform(X))
        self.residuals=None
        return self

    def location_scale(self,X):
        X=np.asarray(X)
        if self.name=='quantile_gb':
            qs=np.stack([np.column_stack([m.predict(X) for m in row]) for row in self.models],axis=1)
            qs.sort(axis=2)  # quantile crossing repair, explicitly recorded in model card
            center=qs[:,:,1]
            low=np.maximum(center-qs[:,:,0],.05)
            high=np.maximum(qs[:,:,2]-center,.05)
            return center,low,high
        if self.name=='ridge': center=np.asarray(self.model.predict(X)).reshape(len(X),-1)
        elif self.name=='conditional_history':
            ids=self.nn.kneighbors(self.scaler.transform(X),return_distance=False)
            center=np.median(self.Y[ids],axis=1)
        else: center=np.tile(np.median(self.Y,axis=0),(len(X),1))
        scale=np.ones_like(center)
        return center,scale,scale

    def calibrate(self,X,Y):
        center,lo,hi=self.location_scale(X)
        error=np.asarray(Y)-center
        self.residuals=error/np.where(error<0,lo,hi)
        return self

    def draws(self,X,max_draws=400):
        X=np.asarray(X)
        if self.residuals is None:
            if self.name=='conditional_history':
                ids=self.nn.kneighbors(self.scaler.transform(X),return_distance=False)
                return self.Y[ids]
            if self.name=='unconditional_history': return np.tile(self.Y[None,::max(1,len(self.Y)//max_draws),:],(len(X),1,1))
            if self.name=='quantile_gb':
                c,l,h=self.location_scale(X)
                # Deterministic asymmetric-normal baseline, then independent calibration replaces it.
                from scipy.stats import norm
                z=norm.ppf((np.arange(200)+.5)/200)/norm.ppf(.95)
                return c[:,None,:]+np.where(z[None,:,None]<0,l[:,None,:],h[:,None,:])*z[None,:,None]
            center,_,_=self.location_scale(self.X)
            residuals=self.Y-center
        else: residuals=self.residuals
        # Evenly spaced calendar rows, same row index for every asset; no independent sampling.
        ids=np.linspace(0,len(residuals)-1,min(max_draws,len(residuals))).astype(int)
        z=residuals[ids]
        c,l,h=self.location_scale(X)
        return c[:,None,:]+np.where(z[None,:,:]<0,l[:,None,:],h[:,None,:])*z[None,:,:]

def metrics(actual,draws):
    y=pct(actual); d=pct(draws)
    qs=np.quantile(d,[.05,.5,.95],axis=1).transpose(1,2,0)
    lo,med,hi=qs[:,:,0],qs[:,:,1],qs[:,:,2]
    score=hi-lo+20*np.maximum(lo-y,0)+20*np.maximum(y-hi,0)
    pin=np.mean([np.maximum(q*(y-qs[:,:,i]),(q-1)*(y-qs[:,:,i])) for i,q in enumerate([.05,.5,.95])],axis=0)
    exceed=y<lo
    es=np.empty_like(y)
    for i in range(len(y)):
        for j in range(y.shape[1]):
            tail=d[i,:,j][d[i,:,j]<=lo[i,j]]
            es[i,j]=tail.mean()
    out=[]
    for j in range(y.shape[1]):
        hits=exceed[:,j]
        out.append({'n':len(y),'coverage90':float(np.mean((y[:,j]>=lo[:,j])&(y[:,j]<=hi[:,j]))),
                    'interval_score':float(score[:,j].mean()),'pinball_loss':float(pin[:,j].mean()),
                    'mae':float(np.abs(y[:,j]-med[:,j]).mean()),'var95_exceedance':float(hits.mean()),
                    'tail_count':int(hits.sum()),'observed_tail_mean_pct':float(y[hits,j].mean()) if hits.any() else None,
                    'estimated_tail_mean_pct':float(es[hits,j].mean()) if hits.any() else None})
    return out
