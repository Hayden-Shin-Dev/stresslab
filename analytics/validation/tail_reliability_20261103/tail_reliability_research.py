"""Separate centre and tail failures; fixed local interval comparisons on six stocks."""
import json,hashlib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from asset_feature_research import ROOT,EXPANDED,model,record
from adaptive_residual_benchmark import weighted_q

SRC=ROOT/'reports/exposure_universe_20261103'
OUT=ROOT/'reports/tail_reliability_20261103'
CONTEXT=['market_trend20','market_vol20','asset_vol20','shock_fx','shock_rate','shock_oil','shock_vix']

def decompose(base):
    rows=[];cases=[];per_asset=[]
    for kind in ['ridge','lgb']:
        a=base[(base.model==kind)&(base.spec=='state_only')];b=base[(base.model==kind)&(base.spec=='all4')]
        z=a.merge(b,on=['asset','date'],suffixes=('_state','_shock'),validate='one_to_one')
        z['lo00']=z.q10_state;z['lo11']=z.q10_shock
        z['lo10']=z.center_shock+z.q10_state-z.center_state
        z['lo01']=z.center_state+z.q10_shock-z.center_shock
        for regime in ['all','asset_crash','high_vol']:
            x=z if regime=='all' else z[z[regime+'_state']]
            b={s:(x.actual_state<x['lo'+s]).mean() for s in ['00','10','01','11']}
            rows.append(dict(model=kind,regime=regime,n=len(x),state_center_mae=x.center_mae_state.mean(),shock_center_mae=x.center_mae_shock.mean(),center_shift_pp=(x.center_shock-x.center_state).mean(),lower_offset_shift_pp=((x.q10_shock-x.center_shock)-(x.q10_state-x.center_state)).mean(),lower_bound_shift_pp=(x.q10_shock-x.q10_state).mean(),**{'breach_'+k:v for k,v in b.items()},center_shapley=.5*(b['10']-b['00']+b['11']-b['01']),residual_shapley=.5*(b['01']-b['00']+b['11']-b['10']),new_misses=int(((x.actual_state>=x.lo00)&(x.actual_state<x.lo11)).sum()),fixed_misses=int(((x.actual_state<x.lo00)&(x.actual_state>=x.lo11)).sum())))
        z['model']=kind;cases.append(z)
        for asset,x in z[z.asset_crash_state].groupby('asset'):
            b={s:(x.actual_state<x['lo'+s]).mean() for s in ['00','10','01','11']}
            per_asset.append(dict(asset=asset,model=kind,n=len(x),centre_mae_state=x.center_mae_state.mean(),centre_mae_shock=x.center_mae_shock.mean(),centre_shift_pp=(x.center_shock-x.center_state).mean(),lower_offset_shift_pp=((x.q10_shock-x.center_shock)-(x.q10_state-x.center_state)).mean(),state_breach=b['00'],shock_breach=b['11'],centre_shapley=.5*(b['10']-b['00']+b['11']-b['01']),residual_shapley=.5*(b['01']-b['00']+b['11']-b['10'])))
    pd.DataFrame(rows).to_csv(OUT/'center_interval_decomposition.csv',index=False)
    pd.DataFrame(per_asset).to_csv(OUT/'center_interval_by_asset.csv',index=False)
    pd.concat(cases).to_parquet(OUT/'decomposition_cases.parquet',index=False)

def main():
    OUT.mkdir(exist_ok=True)
    selected=json.loads((SRC/'selected_assets.json').read_text())
    protocol={'selected':selected,'baseline_predictions_sha256':hashlib.sha256((SRC/'predictions.parquet').read_bytes()).hexdigest(),'gold_unchanged':True,'azure_unchanged':True,
        'primary':'six assets, same 153 evaluation dates per asset, 2023-2026 reused development period; not blind',
        'centre':'same frozen annual LightGBM median model as previous study, no new centre tuning',
        'calibration':'previous five years of sparse OOS vintage residuals; online updates use only current-year completed evaluations with label_end+20days strictly before query; reset current-year online additions at annual refit to prevent duplicate vintages',
        'methods':['existing_all4','online_uniform','online_recent','online_conditional','direct_quantile_raw','direct_quantile_recent'],
        'recent_half_life_days':365,'conditional_context':CONTEXT,'conditional_local_fraction':.5,'conditional_neighbors':60,'conditional_min_samples':100,
        'direct_quantiles':[.1,.9],'direct_parameters':'same 250trees depth4 leaves15 learning_rate.04 min_child40 seed20261103; normalized by existing historical scale',
        'direct_calibration':'signed tail-specific OOS errors with recency weights, 10th percentile lower correction and 90th percentile upper correction; quantify crossing repair',
        'no_forced_width':True,'no_test_parameter_search':True,'two_by_two':'counterfactual interval swaps for attribution only, not approved prediction intervals',
        'approval':'No automatic promotion. Require no material loss of coverage or downside capture; width and interval score assessed jointly.',
        'limitations':'selection reused research outcomes, unknown historical release vintages, old negative WTI percentage definition unchanged for baseline reproduction'}
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    d=pd.read_parquet(SRC/'learning_table.parquet');d=d[d.asset.isin(selected)]
    base=pd.read_parquet(SRC/'predictions.parquet');base=base[base.asset.isin(selected)]
    decompose(base);rows=[];audit=[]
    g=pd.read_parquet(SRC/'research_daily_input.parquet');p=g.groupby('trading_date').kospi_close.first().sort_index();cr=(p.shift(-5)/p-1)*100
    for asset,f in d.groupby('asset'):
        cp=OUT/f'{asset}_checkpoint.parquet'
        if cp.exists():rows.extend(pd.read_parquet(cp).to_dict('records'));continue
        f=f.sort_values('date');banks=[];ar=[];aa=[]
        for year in range(2018,2027):
            cut=pd.Timestamp(year,1,1);cc=pd.Timestamp(year-1,1,1)
            tr=f[f.end_date<cc-pd.Timedelta(days=20)]
            ca=f[(f.date>=cc)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
            te=f[(f.date>=cut)&(f.date<pd.Timestamp(year+1,1,1))].iloc[::6];te=te[te.end_date<pd.Timestamp(year+1,1,1)]
            if len(tr)<250 or len(ca)<30:continue
            m=model('lgb').fit(tr[EXPANDED],tr.target/tr.scale)
            tails=[]
            for alpha in [.1,.9]:
                q=LGBMRegressor(objective='quantile',alpha=alpha,n_estimators=250,learning_rate=.04,max_depth=4,num_leaves=15,min_child_samples=40,random_state=20261103,n_jobs=2,verbosity=-1)
                tails.append(q.fit(tr[EXPANDED],tr.target/tr.scale))
            centre_ca=m.predict(ca[EXPANDED]);tail_ca=np.sort(np.column_stack([q.predict(ca[EXPANDED]) for q in tails]),axis=1)
            history=ca[['date','end_date',*CONTEXT]].copy()
            yn=ca.target.to_numpy()/ca.scale.to_numpy()
            history['residual']=yn-centre_ca;history['lower_error']=yn-tail_ca[:,0];history['upper_error']=yn-tail_ca[:,1];history['ready']=history.end_date+pd.Timedelta(days=20);banks.append(history)
            if year<2023 or not len(te):continue
            pool=pd.concat(banks,ignore_index=True).sort_values('date');pool=pool[(pool.date>=cut-pd.DateOffset(years=5))&(pool.ready<cut)]
            assert tr.end_date.max()<ca.date.min() and pool.ready.max()<te.date.min()
            assert not pool.date.duplicated().any()
            for z in [pool,te]:assert (z.end_date.to_numpy()[:-1]<z.date.to_numpy()[1:]).all()
            centres=m.predict(te[EXPANDED])*te.scale.to_numpy();tails_te=np.sort(np.column_stack([q.predict(te[EXPANDED]) for q in tails]),axis=1)
            uniform=np.ones(len(pool))/len(pool);fixed=weighted_q(pool.residual,uniform)
            mean=tr[CONTEXT].mean().to_numpy();sd=tr[CONTEXT].std().clip(lower=1e-8).to_numpy();high=tr.market_vol20.quantile(2/3)
            pending=[]
            for i,(_,t) in enumerate(te.iterrows()):
                additions=pd.DataFrame([x for x in pending if x['ready']<t.date])
                live=pd.concat([pool,additions],ignore_index=True) if len(additions) else pool.copy()
                live=live[(live.ready<t.date)&(live.date>=t.date-pd.DateOffset(years=5))]
                assert not live.date.duplicated().any() and live.ready.max()<t.date
                u=np.ones(len(live))/len(live);recent=np.exp(-np.log(2)*(t.date-live.date).dt.days.to_numpy()/365);recent/=recent.sum()
                distance=np.mean(((live[CONTEXT].to_numpy()-t[CONTEXT].to_numpy(dtype=float))/sd)**2,axis=1)
                bandwidth=max(np.partition(distance,min(59,len(distance)-1))[min(59,len(distance)-1)],1e-8)
                local=np.exp(-np.minimum(distance/bandwidth,700));local/=local.sum();conditional=.5*u+.5*local if len(live)>=100 else u
                centre=centres[i];scale=t.scale
                variants={'existing_all4':(centre+fixed*scale,pool,uniform)}
                for name,w in [('online_uniform',u),('online_recent',recent),('online_conditional',conditional)]:variants[name]=(centre+weighted_q(live.residual,w)*scale,live,w)
                raw=tails_te[i]*scale
                corrected=raw+np.array([weighted_q(live.lower_error,recent)[0],weighted_q(live.upper_error,recent)[2]])*scale
                for name,bound in [('direct_quantile_raw',raw),('direct_quantile_recent',corrected)]:
                    repaired=np.sort([bound[0],centre,bound[1]])
                    variants[name]=(repaired,live,recent)
                for name,(q,h,w) in variants.items():
                    r=record(t,centre,q,name,high,cr.get(t.date,np.nan),h,w)
                    r.update(year=year,online_completed=len(additions),latest_residual_ready=str(h.ready.max()),tail_crossing=bool(raw[0]>centre or raw[1]<centre) if name=='direct_quantile_raw' else bool(corrected[0]>centre or corrected[1]<centre) if name=='direct_quantile_recent' else False)
                    ar.append(r)
                aa.append(dict(asset=asset,date=str(t.date),train_end=str(tr.end_date.max()),base_cal_n=len(pool),online_cal_n=len(live),online_completed=len(additions),recent_ess=1/(recent@recent),conditional_ess=1/(conditional@conditional),lower_q_fixed=fixed[0],lower_q_online=weighted_q(live.residual,u)[0],lower_q_recent=weighted_q(live.residual,recent)[0]))
                pending.append(dict(date=t.date,end_date=t.end_date,ready=t.end_date+pd.Timedelta(days=20),residual=t.target/scale-centre/scale,lower_error=t.target/scale-tails_te[i,0],upper_error=t.target/scale-tails_te[i,1],**{c:t[c] for c in CONTEXT}))
            print(asset,year,flush=True)
        pd.DataFrame(ar).to_parquet(cp,index=False);pd.DataFrame(aa).to_csv(OUT/f'{asset}_audit.csv',index=False);rows.extend(ar)
    r=pd.DataFrame(rows)
    raw=r.method.eq('direct_quantile_raw');r.loc[raw,['cal_n','ess']]=0;r.loc[raw,'latest_residual_ready']=''
    r.to_parquet(OUT/'predictions.parquet',index=False)
    old=base[(base.model=='lgb')&(base.spec=='all4')]
    z=r[r.method=='existing_all4'].merge(old,on=['asset','date'],suffixes=('_new','_old'),validate='one_to_one')
    assert len(z)==len(old)==918
    for col in ['center','q10','q90']:assert abs(z[col+'_new']-z[col+'_old']).max()<1e-8
    assert r[['q10','q90','center']].notna().all().all() and (r.q10<=r.q90).all()
    (OUT/'verification.json').write_text(json.dumps({'baseline_exact':True,'same_centre_all_interval_methods':bool(r.groupby(['asset','date']).center.nunique().eq(1).all()),'future_residuals_excluded':True,'selected_assets_unchanged':True,'production_approved':False},indent=2))

if __name__=='__main__':main()
