"""Diagnostic selected-factor ablation; does not alter frozen selection or primary results."""
import numpy as np
import pandas as pd
from asset_feature_research import FEATURES,EXPANDED,SHOCKS,model,record
from select_exposure_universe import OUT
from adaptive_residual_benchmark import weighted_q
from summarize_exposure_universe import bootstrap,metrics

def main():
    pairs=pd.read_csv(OUT/'selected_asset_shock_pairs.csv',dtype={'asset':str})
    d=pd.read_parquet(OUT/'learning_table.parquet');base=pd.read_parquet(OUT/'predictions.parquet');rows=[]
    for _,pair in pairs.iterrows():
        f=d[d.asset==pair.asset].sort_values('date');banks={}
        for year in range(2018,2027):
            cut=pd.Timestamp(year,1,1);cc=pd.Timestamp(year-1,1,1)
            tr=f[f.end_date<cc-pd.Timedelta(days=20)]
            ca=f[(f.date>=cc)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
            te=f[(f.date>=cut)&(f.date<pd.Timestamp(year+1,1,1))].iloc[::6];te=te[te.end_date<pd.Timestamp(year+1,1,1)]
            if len(tr)<250 or len(ca)<30:continue
            for kind in ['ridge','lgb']:
                full=FEATURES if kind=='ridge' else EXPANDED
                specs={'only_selected':[c for c in full if c not in SHOCKS]+[pair.shock],'without_selected':[c for c in full if c!=pair.shock]}
                for spec,features in specs.items():
                    m=model(kind).fit(tr[features],tr.target/tr.scale)
                    p=ca[['date','end_date']].copy();p['residual']=ca.target/ca.scale-m.predict(ca[features]);p['ready']=p.end_date+pd.Timedelta(days=20)
                    key=(kind,spec);banks.setdefault(key,[]).append(p)
                    if year<2023 or not len(te):continue
                    pool=pd.concat(banks[key],ignore_index=True).sort_values('date');pool=pool[(pool.date>=cut-pd.DateOffset(years=5))&(pool.ready<cut)]
                    assert tr.end_date.max()<ca.date.min() and pool.ready.max()<te.date.min()
                    w=np.ones(len(pool))/len(pool);adj=weighted_q(pool.residual,w);pred=m.predict(te[features])*te.scale.to_numpy()
                    for i,(_,t) in enumerate(te.iterrows()):
                        r=record(t,pred[i],pred[i]+adj*t.scale,kind+'_'+spec,tr.market_vol20.quantile(2/3),np.nan,pool,w)
                        r.update(model=kind,spec=spec,selected_shock=pair.shock);rows.append(r)
        print(pair.asset,flush=True)
    r=pd.DataFrame(rows);r.to_parquet(OUT/'selected_factor_predictions.parquet',index=False);comp=[]
    for _,pair in pairs.iterrows():
        for kind in ['ridge','lgb']:
            for mode in ['add_to_state','drop_from_all4']:
                if mode=='add_to_state':
                    a=r[(r.asset==pair.asset)&(r.model==kind)&(r.spec=='only_selected')];b=base[(base.asset==pair.asset)&(base.model==kind)&(base.spec=='state_only')]
                else:
                    a=base[(base.asset==pair.asset)&(base.model==kind)&(base.spec=='all4')];b=r[(r.asset==pair.asset)&(r.model==kind)&(r.spec=='without_selected')]
                z=a.merge(b,on=['asset','date'],suffixes=('_a','_b'),validate='one_to_one');assert len(z)==len(a)==len(b)
                comp.append(dict(asset=pair.asset,name=pair['name'],shock=pair.shock,model=kind,mode=mode,n=len(z),mae_with=z.center_mae_a.mean(),mae_without=z.center_mae_b.mean(),gain_pct=100*(1-z.center_mae_a.mean()/z.center_mae_b.mean()),**bootstrap(z.center_mae_a-z.center_mae_b)))
    c=pd.DataFrame(comp);pv=c.bootstrap_p.to_numpy();order=np.argsort(pv);q=np.empty(len(pv));q[order]=np.minimum.accumulate((pv[order]*len(pv)/np.arange(1,len(pv)+1))[::-1])[::-1];c['bh_q_diagnostic_family']=np.minimum(q,1)
    c.to_csv(OUT/'selected_factor_ablation.csv',index=False)

if __name__=='__main__':main()
