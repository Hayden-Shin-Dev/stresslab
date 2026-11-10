"""Screen all 1,770 variable pairs after removing fitted additive relationships.
Uses only two pre-2022 chronological development periods, not final evaluation.
"""
import json
from concurrent.futures import ThreadPoolExecutor,as_completed
from itertools import combinations
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from crash_mechanism_20261104 import OUT,FEATURES,Additive,inputs

def main():
    pairs,data,_=inputs();comb=list(combinations(range(len(FEATURES)),2));ii=np.array([x[0] for x in comb]);jj=np.array([x[1] for x in comb]);rows=[]
    def run(asset):
        f=data[data.asset.eq(asset)].sort_values('date');result=[]
        for year in [2018,2020]:
            cut=pd.Timestamp(year,1,1);tr=f[f.end_date<cut-pd.Timedelta(days=20)].iloc[::6]
            te=f[(f.date>=cut)&(f.end_date<pd.Timestamp(year+2,1,1)-pd.Timedelta(days=20))].iloc[::6]
            if len(tr)<100 or len(te)<40:continue
            m=Additive().fit(tr,tr.target);x=m.design(tr);v=m.design(te);a=m.raw(tr);b=m.raw(te)
            products=a[:,ii]*a[:,jj];testproducts=b[:,ii]*b[:,jj];mu=products.mean(0);scale=np.maximum(products.std(0),1e-6)
            products=(products-mu)/scale;testproducts=(testproducts-mu)/scale
            # The same main-effect projection controls all 60 variables jointly.
            nuisance=m.inverse@(x.T@products);res=testproducts-v@nuisance
            yr=te.target.to_numpy()-m.predict(te);centered=res-res.mean(0);y=yr-yr.mean()
            den=np.sqrt((centered**2).sum(0)*(y@y));corr=np.divide(centered.T@y,den,out=np.zeros(len(comb)),where=den>1e-10)
            cr=te.target.to_numpy()<=-5;ra=te.target.to_numpy()>=5
            for k,(i,j) in enumerate(comb):
                result.append(dict(asset=asset,fold=year,left=FEATURES[i],right=FEATURES[j],n=len(te),
                  residual_correlation=float(corr[k]),residual_sd=float(res[:,k].std()),crash_residual_product=float(res[cr,k].mean()) if cr.any() else None,
                  rally_residual_product=float(res[ra,k].mean()) if ra.any() else None,screen_only=True))
        return result
    with threadpool_limits(limits=1,user_api='blas'),ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(run,a):a for a in sorted(pairs.asset.unique())}
        for i,f in enumerate(as_completed(jobs),1):rows+=f.result();print('interactions',i,len(jobs),flush=True)
    r=pd.DataFrame(rows);r.to_parquet(OUT/'all_pair_interaction_screen.parquet',index=False,compression='zstd')
    g=r.groupby(['asset','left','right']).agg(folds=('fold','nunique'),positive=('residual_correlation',lambda x:(x>0).sum()),negative=('residual_correlation',lambda x:(x<0).sum()),strength=('residual_correlation',lambda x:x.abs().mean()),minimum_strength=('residual_correlation',lambda x:x.abs().min()),minimum_sd=('residual_sd','min')).reset_index()
    # Exploratory pre-test screening, not statistically significant independent effects.
    g['eligible']=(g.folds==2)&((g.positive==2)|(g.negative==2))&g.minimum_strength.ge(.1)&g.strength.ge(.15)&g.minimum_sd.gt(.01)
    g.to_csv(OUT/'interaction_stability.csv',index=False)
    chosen={a:[] for a in sorted(pairs.asset.unique())};selected=[]
    for asset,z in g[g.eligible].groupby('asset'):
        z=z.sort_values('strength',ascending=False).head(8);chosen[asset]=list(zip(z.left,z.right));selected.append(z)
    if selected:pd.concat(selected).to_csv(OUT/'selected_interactions.csv',index=False)
    else:pd.DataFrame(columns=g.columns).to_csv(OUT/'selected_interactions.csv',index=False)
    (OUT/'interactions.json').write_text(json.dumps(chosen,indent=2))
    (OUT/'interaction_complete.json').write_text(json.dumps(dict(complete=True,pairs_per_stock=len(comb),rows=len(r),
       selected=sum(len(x) for x in chosen.values()),controls='Joint 60-variable additive projection trained before each development period',
       limitation='Residual correlations are exploratory; screening 1770 pairs entails multiplicity and correlated products. Performance must be evaluated later; no causal or significance claim.')))
if __name__=='__main__':main()
