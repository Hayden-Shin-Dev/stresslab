"""Importable globally pooled engine used by versioned model artifacts."""
import numpy as np
from .sensitivity_model import SensitivityEngine

class GlobalOnlyEngine(SensitivityEngine):
    def coefficients(self,q):
        _,_,detail=super().coefficients(q);v=detail['global_fold_beta'];beta=detail['global_beta']
        stable=np.isfinite(v).all(0)&((v>0).all(0)|(v<0).all(0))&(detail['global_spread']<=.75)&(abs(beta)*self.iqr.to_numpy()>=.1)
        detail['use_state']=np.zeros_like(stable,dtype=bool)
        return beta,stable,detail
