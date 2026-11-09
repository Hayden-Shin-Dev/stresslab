"""Historical-state support guard; never clip predicted returns or consult evaluation outcomes."""
import json
import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors
from train_orthogonal_response_20261104 import ROOT,OUT,BASIS

def main():
    assert json.loads((OUT/'response_progress.json').read_text())['status']=='complete'
    d=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet');r=pd.read_parquet(OUT/'response_predictions.parquet')
    output=[];audit=[]
    for asset,f in d.groupby('asset'):
        f=f.sort_values('date');bank=[]
        for year in range(2016,2027):
            cut=pd.Timestamp(year,1,1);train=f[f.end_date<cut-pd.Timedelta(days=20)]
            ca=f[(f.date>=cut)&(f.end_date<pd.Timestamp(year+1,1,1)-pd.Timedelta(days=20))].iloc[::6]
            if len(train)<500 or len(ca)<15:continue
            z=r[(r.asset==asset)&(r.date.dt.year==year)&r.method.eq('orthogonal_state_response')].sort_values('date')
            if len(z):
                pool=pd.concat(bank);pool=pool[pool.end_date<cut-pd.Timedelta(days=20)]
                te=f.set_index('date').loc[z.date].reset_index();med=pool[BASIS].median().fillna(0)
                b=pool[BASIS].fillna(med).to_numpy();mean=b.mean(axis=0);scale=np.maximum(b.std(axis=0),1e-6);bn=(b-mean)/scale;tn=(te[BASIS].fillna(med).to_numpy()-mean)/scale
                nn=NearestNeighbors(n_neighbors=2,n_jobs=1).fit(bn);past_dist=nn.kneighbors(bn)[0][:,1];threshold=max(float(np.quantile(past_dist,.95)),1e-8)
                distance=nn.kneighbors(tn,n_neighbors=1)[0][:,0];outside=(tn<bn.min(axis=0)-1e-8)|(tn>bn.max(axis=0)+1e-8)
                fallback=outside.any(axis=1)|(distance>threshold)
                constant=r[(r.asset==asset)&(r.date.dt.year==year)&r.method.eq('orthogonal_constant')].set_index('date').loc[z.date]
                out=z.copy();out['method']='orthogonal_support_guard';out['center']=np.where(fallback,constant.center.to_numpy(),z.center.to_numpy());output.append(out)
                for i,date in enumerate(z.date):audit.append(dict(asset=asset,date=str(date),year=year,fallback=bool(fallback[i]),outside_marginal_range=bool(outside[i].any()),
                    nearest_state_distance=float(distance[i]),historical95_distance=threshold,max_absolute_standardized_state=float(np.abs(tn[i]).max()),
                    pool_label_end=str(pool.end_date.max()),decision_uses_actual_return=False,reason='Use fixed-coefficient response for novel states; state mean remains conditional',
                    extrapolated_center=float(z.center.iloc[i]),guarded_center=float(out.center.iloc[i])))
            bank.append(ca[['date','end_date']+BASIS])
    guarded=pd.concat(output,ignore_index=True);guarded.to_parquet(OUT/'guard_predictions.parquet',index=False);pd.DataFrame(audit).to_csv(OUT/'state_support_audit.csv',index=False)
    (OUT/'guard_protocol.json').write_text(json.dumps(dict(rule='Fallback to pre-fitted constant shock response if any basis leaves prior residual-bank range or nearest standardized state distance exceeds historical leave-one-out95thpercentile.',
        target_values_used_for_guard=False,prediction_clipping=False,basis=BASIS,
        development_history='Added after finding state-interaction extrapolation failure in reused research evaluation. NOT independent confirmation.',
        remaining_limit='Support guard does not certify arbitrary shock combinations or causal effects; constant response also requires validation',production=False),indent=2))

if __name__=='__main__':main()
