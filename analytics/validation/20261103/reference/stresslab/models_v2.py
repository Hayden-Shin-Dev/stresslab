"""Volatility-normalized joint residual models, with unchanged calibration in selection/evaluation."""
import numpy as np
from .models import DistributionModel
class ScaledDistribution:
    def __init__(self,name): self.name=name
    def scale(self,X): return np.maximum(np.asarray(X)[:,-7:],.05)
    def inputs(self,X):
        x=np.asarray(X)[:,:-7].copy()
        if self.name=='volatility_history': return np.zeros((len(x),1))
        # Normalize cumulative shocks by known current market volatility.
        x[:,:4]/=np.maximum(np.asarray(X)[:,-7:-6],.05)
        return x
    def fit(self,X,Y):
        base={'volatility_history':'unconditional_history','scaled_ridge':'ridge','scaled_quantile_gb':'quantile_gb'}[self.name]
        self.inner=DistributionModel(base).fit(self.inputs(X),np.asarray(Y)/self.scale(X))
        return self
    def calibrate(self,X,Y):
        self.inner.calibrate(self.inputs(X),np.asarray(Y)/self.scale(X));return self
    def draws(self,X,max_draws=400):
        return self.inner.draws(self.inputs(X),max_draws)*self.scale(X)[:,None,:]

def add_scales(panel,h):
    import pandas as pd
    from .config import ASSETS
    out=pd.DataFrame({'date':panel.date})
    for a in ASSETS:
        r=np.log(panel[a]/panel[a].shift(1))*100
        out['scale_'+a]=np.sqrt((r.rolling(20).var()+r.rolling(60).var())/2)*np.sqrt(h)
    return out


def scenario_draws(model,queries):
    """Same deterministic empirical distribution for API and historical scenario evaluation."""
    queries=queries.drop_duplicates()
    if model.name=='volatility_history':queries=queries.iloc[:1]
    return model.draws(queries.to_numpy(),max_draws=400).reshape(-1,7)
