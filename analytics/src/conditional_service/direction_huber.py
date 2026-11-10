"""Development test of a direction-aware penalty in the same additive factor."""
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from threadpoolctl import threadpool_limits
from .huber_followup import HuberFollowup

class DirectionHuber(HuberFollowup):
    def fit(self,d):
        super().fit(d)
        strength=self.config.get('direction_weight',0.)
        if not strength:return self
        x=self.design(d);y=d.target.to_numpy();sign=np.sign(y)
        w=(1/d.groupby('date').date.transform('size')).to_numpy();w/=w.mean()
        delta=self.config['delta']*self.huber_scale;n=len(d);alpha=self.config.get('alpha',300)
        def objective(theta):
            beta=theta[:-1];prediction=x@beta+theta[-1];r=prediction-y;absolute=abs(r)
            huber=np.where(absolute<=delta,.5*r*r,delta*(absolute-.5*delta))
            direction=np.logaddexp(0.,-sign*prediction)
            loss=float((w*(huber+strength*direction)).sum()/n+alpha/(2*n)*(beta@beta))
            derivative=w*(np.clip(r,-delta,delta)-strength*sign*expit(-sign*prediction))/n
            grad=np.r_[x.T@derivative+alpha/n*beta,derivative.sum()]
            return loss,grad
        result=minimize(objective,np.r_[self.model.coef_,self.model.intercept_],jac=True,method='L-BFGS-B',options=dict(maxiter=200,ftol=1e-10,gtol=1e-5))
        self.model.coef_=result.x[:-1];self.model.intercept_=float(result.x[-1]);self.iterations+=result.nit;self.converged=bool(result.success)
        self.optimization_message=str(result.message)
        return self

def main():
    from . import huber_followup as run
    run.OUT=Path('reports/huber_direction_20261105')
    run.CONFIGS=[dict(name='huber',delta=1.35,normalize=False,stock_states=False)]+[
        dict(name=f'direction{strength}',delta=1.35,normalize=False,stock_states=False,direction_weight=strength) for strength in [1,4]]
    run.HuberFollowup=DirectionHuber
    run.main()

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
