"""Same additive partial-pooling Ridge with explicit block penalties."""
import numpy as np
from .core import SHOCKS,STATE,ASSET
from .finalize_model import BoundedFactor

class RegularizedFactor(BoundedFactor):
    def design(self,d,fit=False):
        z=super().design(d,fit)
        state=np.sqrt(self.config.get('state_penalty',1.))
        shock=np.sqrt(self.config.get('shock_penalty',1.))
        z[:,:len(STATE+ASSET)]/=state
        z[:,len(STATE+ASSET):len(self.columns)]/=shock
        z[:,len(self.columns)+len(self.assets):]/=shock
        return z

    def slope_parts(self,row,shock):
        p=super().slope_parts(row,shock)
        scale=np.sqrt(self.config.get('shock_penalty',1.))
        return {k:v/scale for k,v in p.items()}
