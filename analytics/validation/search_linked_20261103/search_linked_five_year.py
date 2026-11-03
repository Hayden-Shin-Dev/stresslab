"""Five-year historical OOS banks for search-linked models, fixed before evaluation."""
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from gold_quantile_benchmark import ROOT,build,FEATURES,STATE
from adaptive_residual_benchmark import weighted_q,rec,summarize
import adaptive_residual_benchmark as base
from search_linked_benchmark import OUT,weights

def main():
    g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet');data=build(g)
    existing=pd.read_parquet(OUT/'predictions.parquet');existing=existing[~existing.method.str.contains('_5year')]
    rows=[];bank_dump=[]
    for asset,f in data.groupby('asset'):
        f=f.sort_values('date');banks={False:[],True:[]}
        for year in range(2018,2027):
            cut=pd.Timestamp(year,1,1);cc=pd.Timestamp(year-1,1,1)
            tr=f[f.end_date<cc-pd.Timedelta(days=20)];ca=f[(f.date>=cc)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
            if len(tr)<250 or len(ca)<30:continue
            ss=StandardScaler().fit(tr[STATE]);hs=ss.transform(tr[STATE]);fs=StandardScaler().fit(tr[FEATURES])
            X=np.column_stack([np.ones(len(tr)),fs.transform(tr[FEATURES])]);y=(tr.target/tr.scale).to_numpy();penalty=np.diag([0]+[30]*len(FEATURES));beta=np.linalg.solve(X.T@X+penalty,X.T@y)
            cx=np.column_stack([np.ones(len(ca)),fs.transform(ca[FEATURES])]);cs=ss.transform(ca[STATE]);global_cp=(cx@beta)*ca.scale.to_numpy();local_cp=[]
            for i in range(len(ca)):
                w,_=weights(hs,cs[i]);b=np.linalg.solve(X.T@(X*(w*len(tr))[:,None])+penalty,X.T@(y*w*len(tr)));local_cp.append(cx[i]@b*ca.scale.iloc[i])
            for local,cp in [(False,global_cp),(True,np.array(local_cp))]:
                p=ca[['date','end_date','scale']+STATE].copy();p['ready']=p.end_date+pd.Timedelta(days=20);p['scaled']=(ca.target.to_numpy()-cp)/ca.scale.to_numpy();p['vintage']=year;banks[local].append(p)
            if year<2023:continue
            te=f[(f.date>=cut)&(f.date<pd.Timestamp(year+1,1,1))].iloc[::6];te=te[te.end_date<pd.Timestamp(year+1,1,1)]
            for local in [False,True]:
                pool=pd.concat(banks[local],ignore_index=True).sort_values('date');pool=pool[(pool.date>=cut-pd.DateOffset(years=5))&(pool.ready<cut)]
                assert (pool.end_date.to_numpy()[:-1]<pool.date.to_numpy()[1:]).all()
                bank_dump.append(pool.assign(asset=asset,local=local,evaluation_year=year))
                ps=ss.transform(pool[STATE]);prefix='linked_center' if local else 'global_center'
                original=existing[(existing.asset==asset)&(existing.method==prefix+'_global_residual')].set_index('date')
                for _,t in te.iterrows():
                    if t.date not in original.index:continue
                    old=original.loc[t.date];center=old.center;cw,_=weights(ps,ss.transform(t[STATE].to_frame().T)[0])
                    for linked in [False,True]:
                        w=cw if linked else np.ones(len(pool))/len(pool);q=center+weighted_q(pool.scaled,w)*t.scale
                        method=prefix+('_linked_residual_5year' if linked else '_global_residual_5year')
                        row=rec(t,q,'ridge',method,pool,w,False,tr.market_vol20.quantile(2/3),-6 if old.market_crash else 0,center);rows.append(row)
            print(asset,year,flush=True)
    extra=pd.DataFrame(rows)
    check=extra[extra.method.eq('global_center_global_residual_5year')].merge(existing[existing.method.eq('frozen5_scaled')],on=['date','asset'],suffixes=('_a','_b'),validate='one_to_one')
    assert len(check)==len(existing[existing.method.eq('frozen5_scaled')]) and abs(check.q10_a-check.q10_b).max()<1e-7 and abs(check.q90_a-check.q90_b).max()<1e-7
    r=pd.concat([existing,extra],ignore_index=True);r.to_parquet(OUT/'predictions.parquet',index=False);pd.concat(bank_dump,ignore_index=True).to_parquet(OUT/'historical_error_banks.parquet',index=False)
    r[r.asset.eq('portfolio')].to_csv(OUT/'portfolio_predictions.csv',index=False);base.OUT=OUT;summarize(r)
    import json
    protocol=json.loads((OUT/'protocol.json').read_text(encoding='utf8'));protocol['extended_calibration']='5year historical OOS vintage errors, same20day embargo; both globally weighted and state-weighted; no hyperparameter tuning'
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    v=json.loads((OUT/'verification.json').read_text());v.update(five_year_global_baseline_reproduced=True,five_year_rows=len(extra));(OUT/'verification.json').write_text(json.dumps(v,indent=2))
if __name__=='__main__':main()
