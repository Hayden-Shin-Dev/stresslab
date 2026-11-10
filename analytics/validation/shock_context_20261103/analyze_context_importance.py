"""Held-out2022 grouped feature reliance; no test-driven feature selection."""
import json
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from research_shock_context import OUT,COLS,EXPANDED,STATE_EXTRA,SHOCKS,interactions,fit_predict

def main():
    d=pd.read_parquet(OUT/'learning_table.parquet')
    raw=EXPANDED+STATE_EXTRA
    market=[c for c in raw if c.startswith('market_')]
    asset=[c for c in raw if c.startswith(('asset_','relative_','volume_','drawdown')) or c in ['beta60','corr60','downside_vol20']]
    macro=[c for c in raw if c not in SHOCKS+market+asset]
    groups={**{s:[s] for s in SHOCKS},'market_history':market,'asset_history':asset,'macro_history':macro}
    assert set(sum(groups.values(),[]))==set(raw)
    (OUT/'importance_groups.json').write_text(json.dumps(groups,indent=2),encoding='utf8')
    def run(a,f):
        tr=f[f.end_date<pd.Timestamp('2021-12-12')];va=f[(f.date>=pd.Timestamp('2022-01-01'))&(f.end_date<pd.Timestamp('2023-01-01'))].sort_values('date').iloc[::6]
        if len(tr)<500 or len(va)<20:return []
        m,p,cols=fit_predict('context',tr,va,pd.Timestamp('2022-01-01'));base=np.abs(va.target-p).mean();rows=[];rng=np.random.default_rng(20261103)
        for group,features in groups.items():
            changes=[]
            for rep in range(10):
                ix=rng.permutation(len(va));alt=va.copy();alt[features]=va[features].to_numpy()[ix];alt=interactions(alt);changes.append(float(np.abs(va.target-m.predict(alt[cols])).mean()-base))
            rows.append(dict(asset=a,group=group,n=len(va),base_mae=base,permuted_mae_increase=np.mean(changes),permutation_std=np.std(changes)))
        return rows
    rows=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in as_completed([pool.submit(run,a,z) for a,z in d.groupby('asset')]):rows.extend(f.result())
    pd.DataFrame(rows).to_csv(OUT/'context_importance.csv',index=False)
    pd.DataFrame(rows).groupby('group').agg(stocks=('asset','nunique'),mean_mae_increase=('permuted_mae_increase','mean'),positive_fraction=('permuted_mae_increase',lambda x:(x>0).mean())).to_csv(OUT/'context_importance_summary.csv')

if __name__=='__main__':main()
