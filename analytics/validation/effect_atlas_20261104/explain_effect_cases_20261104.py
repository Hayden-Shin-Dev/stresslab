"""Prespecified illustrative stocks; fixed-weight uncertainty, no winner selection."""
import json
import pandas as pd
import numpy as np
from threadpoolctl import threadpool_limits
from balance_effect_atlas_20261104 import ROOT,OUT,weights,controls_for
from analyze_effect_atlas_20261104 import SHOCKS

def main():
    data=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet');data=data[data.end_date<pd.Timestamp('2022-01-01')-pd.Timedelta(days=20)];rows=[]
    with threadpool_limits(limits=1):
        for asset in ['005930','000660','003490','010950','005380']:
            z=data[data.asset==asset].sort_values('date').iloc[::6];quarters=pd.period_range(z.date.min(),z.date.max(),freq='Q');rng=np.random.default_rng(20261104);draw=rng.integers(0,len(quarters),(1000,len(quarters)))
            for feature in SHOCKS:
                low,high=z[feature].quantile([.25,.75]);ia=np.where(z[feature]>=high)[0];ib=np.where(z[feature]<=low)[0]
                controls=[c for c in controls_for(feature) if z[c].notna().mean()>=.5 and z[c].std()>1e-8];raw=z[controls];x=raw.fillna(raw.median()).to_numpy();x=(x-x.mean(0))/np.maximum(x.std(0),1e-8);missing=raw.isna().to_numpy().astype(float);vary=missing.std(0)>.01
                if vary.any():x=np.column_stack([x,missing[:,vary]])
                target=np.vstack([x[ia],x[ib]]).mean(0);wa,oka=weights(x[ia],target);wb,okb=weights(x[ib],target)
                a=z.iloc[ia];b=z.iloc[ib];A=pd.DataFrame(dict(block=a.date.dt.to_period('Q').to_numpy(),sum=wa*a.target.to_numpy(),weight=wa)).groupby('block')[['sum','weight']].sum().reindex(quarters,fill_value=0)
                B=pd.DataFrame(dict(block=b.date.dt.to_period('Q').to_numpy(),sum=wb*b.target.to_numpy(),weight=wb)).groupby('block')[['sum','weight']].sum().reindex(quarters,fill_value=0)
                sa=A['sum'].to_numpy()[draw].sum(1);sb=B['sum'].to_numpy()[draw].sum(1);da=A.weight.to_numpy()[draw].sum(1);db=B.weight.to_numpy()[draw].sum(1);boot=sa/da-sb/db;lo,hi=np.quantile(boot,[.025,.975]);full=float(wa@a.target.to_numpy()-wb@b.target.to_numpy());leave=[]
                for year in sorted(z.date.dt.year.unique()):
                    ka=a.date.dt.year.ne(year).to_numpy();kb=b.date.dt.year.ne(year).to_numpy()
                    if wa[ka].sum()>0 and wb[kb].sum()>0:leave.append(float(wa[ka]@a.target.to_numpy()[ka]/wa[ka].sum()-wb[kb]@b.target.to_numpy()[kb]/wb[kb].sum()))
                rows.append(dict(asset=asset,shock=feature,contrast_pp=full,fixed_weight_quarter_ci_low=lo,fixed_weight_quarter_ci_high=hi,leave_one_year_out_min=min(leave),leave_one_year_out_max=max(leave),
                    leave_one_year_sign_agreement=float(np.mean(np.sign(leave)==np.sign(full))),weights_refitted_in_bootstrap=False,causal_effect=False,uncertainty='Exploratory fixed-weight quarterly bootstrap; excludes weight estimation and hidden confounding uncertainty'))
    pd.DataFrame(rows).to_csv(OUT/'사전지정5종목_충격반응안정성.csv',index=False,encoding='utf-8-sig')
if __name__=='__main__':main()
