"""Paired date-block assessment and auditable hypothetical example."""
import json,hashlib
import numpy as np
import pandas as pd
import joblib
from pooled_stress_core_20261104 import *
from run_pooled_hybrid_20261104 import MODELS, tree_x

def rowscore(z):
    return point_score(z)

def block_ci(z,base):
    q=z.merge(base[['asset','date','center']],on=['asset','date'],suffixes=('','_base'),validate='one_to_one')
    q['gain']=abs(q.actual-q.center_base)-abs(q.actual-q.center)
    q['zero_gain']=abs(q.actual)-abs(q.actual-q.center)
    q['crash_gain']=q.gain.where(q.actual<=-5)
    q['month']=q.date.dt.to_period('M').astype(str);rng=np.random.default_rng(SEED);out={}
    for name in ['gain','zero_gain','crash_gain']:
        x=q.groupby('month')[name].agg(['sum','count']);idx=rng.integers(0,len(x),size=(2000,len(x)))
        a=x['sum'].to_numpy()[idx].sum(1);b=x['count'].to_numpy()[idx].sum(1);v=a[b>0]/b[b>0]
        out[name+'_lo'],out[name+'_hi']=np.quantile(v,[.025,.975]);out[name]=q[name].mean()
    out['date_blocks']=q.month.nunique();return out

def scenario_example(d):
    pack=joblib.load(OUT/'folds/2026_models.joblib');lin=pack['linear'];support=pack['support'];rows=[];search=[];attribution=[]
    calibration=pd.read_parquet(OUT/'folds/2026_calibration.parquet')
    # Same saved evaluation state, not a claim about today's live market.
    state_date=pd.Timestamp('2026-10-19')
    selected=d[(d.date==state_date)&d.asset.isin(['005930','005380'])].copy();assert len(selected)==2
    for label,shocks in [('unchanged',[0,0,0,0]),('user_fx5_rate100',[5,100,0,0]),('user_fx10_rate200',[10,200,0,0])]:
        x=selected.copy();x[SHOCKS]=shocks
        for s in SHOCKS:
            for c in ['market_trend20','market_vol20']:x[s+'__'+c]=x[s]*x[c]
        gate,ratio,outside=support.inspect(x);linear=lin.predict(x)*x.scale.to_numpy()
        for name in ['partial_ridge','hybrid_catboost','hybrid_lightgbm']:
            extra=0 if name=='partial_ridge' else pack['trees'][name].predict(tree_x(x))*x.scale.to_numpy()*gate
            values=linear+extra
            cal=calibration[calibration.model==name];q10=float(((cal.actual-cal.center)/cal.scale).quantile(.1))
            for i,(_,v) in enumerate(x.iterrows()):
                rows.append(dict(scenario=label,asset=v.asset,state_date=str(state_date.date()),model=name,current_value_krw=50000000,center_pct=float(values[i]),hypothetical_pnl_krw=float(values[i]*500000),lower_reference_pct=float(values[i]+q10*v.scale),lower_reference_definition='pooled historical normalized residual q10; not validated scenario probability',support_ratio=float(ratio[i]),residual_gate=float(gate[i]),outside_marginal=bool(outside[i]),user_inputs_preserved=True,validated_extreme=False))
        if label=='user_fx5_rate100':
            zero=x.copy();zero[SHOCKS]=0
            for c in INTER:zero[c]=0
            z=lin.predict(zero)*zero.scale.to_numpy()
            slope=pd.DataFrame(lin.slopes(x))
            for i,(_,v) in enumerate(x.iterrows()):
                contribution={s:float(slope[(slope.asset==v.asset)&(slope.shock==s)].slope_pp_per_unit.iloc[0]*shocks[j]) for j,s in enumerate(SHOCKS)}
                assert abs(z[i]+sum(contribution.values())-linear[i])<1e-8
                attribution.append(dict(asset=v.asset,zero_shock_center=float(z[i]),**contribution,factor_center=float(linear[i]),interpretation='model decomposition, not causal effects'))
    # A search: STATE only, no shock condition and no future response in distances.
    for _,v in selected.iterrows():
        h=chronological_anchors(d[(d.asset==v.asset)&(d.end_date<state_date-pd.Timedelta(days=20))&d.oil_valid]).copy()
        scale=(h[STATE].quantile(.75)-h[STATE].quantile(.25)).replace(0,1)
        h['distance']=((h[STATE]-v[STATE].astype(float))/scale).pow(2).mean(axis=1)
        for _,n in h.nsmallest(5,'distance').iterrows():search.append(dict(asset=v.asset,state_date=str(state_date.date()),historical_date=str(n.date.date()),historical_end=str(n.end_date.date()),state_distance=float(n.distance),actual_return_pct=n.target,**{s:n[s] for s in SHOCKS},shock_used_for_search=False))
    s=pd.DataFrame(rows);s.to_csv(OUT/'service_example.csv',index=False)
    s.groupby(['model','scenario']).hypothetical_pnl_krw.sum().reset_index().to_csv(OUT/'portfolio_example.csv',index=False)
    pd.DataFrame(search).to_csv(OUT/'state_only_search_example.csv',index=False);pd.DataFrame(attribution).to_csv(OUT/'factor_attribution_example.csv',index=False)

def main():
    points=pd.concat([pd.read_parquet(p) for p in (OUT/'folds').glob('*_points.parquet')],ignore_index=True)
    intervals=pd.concat([pd.read_parquet(p) for p in (OUT/'folds').glob('*_intervals.parquet')],ignore_index=True)
    points['market_removed_actual']=points.actual-points.groupby(['model','date']).actual.transform('mean')
    points['market_removed_center']=points.center-points.groupby(['model','date']).center.transform('mean')
    vol=[]
    for path in (OUT/'folds').glob('*_calibration.parquet'):
        c=pd.read_parquet(path);c=c[c.model=='catboost'];year=int(c.fold.iloc[0])
        for a,f in c.groupby('asset'):
            z=points[(points.fold==year)&(points.asset==a)&(points.model=='catboost')].copy()
            q=np.quantile(f.actual/f.scale,[.1,.5,.9]);z['model']='volatility_history';z['interval']='normalized_history';z['lo']=q[0]*z.scale;z['center']=q[1]*z.scale;z['hi']=q[2]*z.scale;vol.append(z)
    intervals=pd.concat([intervals,*vol],ignore_index=True)
    regimes=points[points.model=='catboost'][['asset','date','regime']].rename(columns={'regime':'reference_regime'})
    intervals=intervals.merge(regimes,on=['asset','date'],validate='many_to_one')
    intervals['regime']=intervals.regime.fillna(intervals.reference_regime)
    d,g=prepare();r=points[points.fold>=2023];dev=points[points.fold<2023];ri=intervals[intervals.fold>=2023];di=intervals[intervals.fold<2023]
    common=d.groupby('date')[STATE+SHOCKS]
    common_spread=float((common.max()-common.min()).max().max())
    assert common_spread<1e-10  # rolling floating-point arithmetic differs by at most ~2.5e-14
    assert np.isfinite(points[['actual','center']].to_numpy()).all()
    assert np.isfinite(intervals[['actual','center','lo','hi']].to_numpy()).all() and (intervals.lo<=intervals.hi).all()
    locked=pd.read_parquet(ROOT/'reports/gold20_locked_20261104/locked_baseline.parquet').sort_values(['asset','date'])
    for name,z in r.groupby('model'):
        z=z.sort_values(['asset','date']);assert len(z)==2928 and z.asset.nunique()==20
        assert z[['asset','date']].reset_index(drop=True).equals(locked[['asset','date']].reset_index(drop=True))
        np.testing.assert_array_equal(z.actual,locked.actual)
    audit=pd.concat([pd.read_csv(p) for p in (OUT/'folds').glob('*_audit.csv')]);assert (pd.to_datetime(audit.train_label_end)<pd.to_datetime(audit.cal_start)).all();assert (pd.to_datetime(audit.cal_label_end)<pd.to_datetime(audit.test_start)).all()
    tuning=pd.concat([pd.read_csv(p) for p in (OUT/'factor_cache').glob('*_tuning.csv')]);assert (pd.to_datetime(tuning.inner_end)<pd.to_datetime(tuning.validation_start)).all()
    for p in (OUT/'factor_cache').glob('*.parquet'):
        q=pd.read_parquet(p,columns=['date','oof_train_label_end']);assert (q.oof_train_label_end<q.date).all()
    for p in (OUT/'folds').glob('*_calibration.parquet'):
        c=pd.read_parquet(p);a=c[c.model=='catboost']
        for _,z in a.groupby('asset'):
            z=z.sort_values('date');assert (z.end_date.iloc[:-1].to_numpy()<z.date.iloc[1:].to_numpy()).all()
    center=pd.DataFrame([dict(model=n,**point_score(z)) for n,z in r.groupby('model')]);dc=pd.DataFrame([dict(model=n,**point_score(z)) for n,z in dev.groupby('model')]);center.to_csv(OUT/'center_metrics.csv',index=False);dc.to_csv(OUT/'development_center_metrics.csv',index=False)
    risk=pd.DataFrame([dict(model=n,interval=i,**interval_score(z)) for (n,i),z in ri.groupby(['model','interval'])]);dr=pd.DataFrame([dict(model=n,interval=i,**interval_score(z)) for (n,i),z in di.groupby(['model','interval'])])
    u=risk[risk.model=='unconditional'].iloc[0];risk['pinball_gain_unconditional']=1-risk.pinball_mean/u.pinball_mean;risk['interval_score_gain_unconditional']=1-risk.interval_score80/u.interval_score80
    uv=risk[risk.model=='volatility_history'].iloc[0];risk['interval_score_gain_volatility']=1-risk.interval_score80/uv.interval_score80
    risk.to_csv(OUT/'interval_metrics.csv',index=False);dr.to_csv(OUT/'development_interval_metrics.csv',index=False)
    for group in ['asset','sector','fold','regime']:
        pd.DataFrame([dict(model=n,group=k,**rowscore(z)) for (n,k),z in r.groupby(['model',group])]).to_csv(OUT/f'center_by_{group}.csv',index=False)
        pd.DataFrame([dict(model=n,interval=i,group=k,**interval_score(z)) for (n,i,k),z in ri.groupby(['model','interval',group])]).to_csv(OUT/f'interval_by_{group}.csv',index=False)
    base=r[r.model=='catboost'];pd.DataFrame([dict(model=n,**block_ci(z,base)) for n,z in r.groupby('model')]).to_csv(OUT/'center_date_block_ci.csv',index=False)
    # Risk comparisons on paired calendar-month blocks; preserve all stocks within blocks.
    ur=ri[ri.model=='unconditional'][['asset','date','lo','hi']];risks=[]
    rng=np.random.default_rng(SEED)
    for (n,i),z in ri.groupby(['model','interval']):
        q=z.merge(ur,on=['asset','date'],suffixes=('','_u'),validate='one_to_one');y=q.actual
        loss=q.hi-q.lo+10*(q.lo-y).clip(lower=0)+10*(y-q.hi).clip(lower=0)
        ul=q.hi_u-q.lo_u+10*(q.lo_u-y).clip(lower=0)+10*(y-q.hi_u).clip(lower=0)
        q['loss']=loss;q['uloss']=ul;q['month']=q.date.dt.to_period('M').astype(str);a=q.groupby('month')[['loss','uloss']].sum();idx=rng.integers(0,len(a),(2000,len(a)));v=1-a.loss.to_numpy()[idx].sum(1)/a.uloss.to_numpy()[idx].sum(1)
        risks.append(dict(model=n,interval=i,gain_low95=np.quantile(v,.025),gain_high95=np.quantile(v,.975),blocks=len(a)))
    pd.DataFrame(risks).to_csv(OUT/'risk_date_block_ci.csv',index=False)
    scenarios=pd.concat([pd.read_csv(p,dtype={'asset':str}) for p in (OUT/'folds').glob('*_scenarios.csv')]);slopes=pd.concat([pd.read_csv(p,dtype={'asset':str}) for p in (OUT/'folds').glob('*_slopes.csv')])
    scenarios.to_csv(OUT/'scenarios.csv',index=False);slopes.to_csv(OUT/'factor_slopes_by_year.csv',index=False)
    stability=slopes[slopes.fold>=2023].groupby(['asset','shock']).slope_pp_per_unit.agg(['min','max','mean','std']).reset_index();stability['sign_stable']=(stability['min']*stability['max']>0);stability.to_csv(OUT/'slope_stability.csv',index=False)
    coefficients=[]
    for year in [2023,2024,2025,2026]:
        lm=joblib.load(OUT/'folds'/f'{year}_models.joblib')['linear'];coef=lm.model.coef_
        for ai,a in enumerate(ASSETS):
            for si,s in enumerate(SHOCKS):
                j=FACTORS.index(s);common=coef[j]/lm.scaler.scale_[j]
                delta=coef[len(FACTORS)+len(ASSETS)+ai*4+si]/np.sqrt(lm.ratio)/lm.scaler.scale_[j]
                vj=FACTORS.index(s+'__market_vol20');tj=FACTORS.index(s+'__market_trend20')
                vb=coef[vj]/lm.scaler.scale_[vj];tb=coef[tj]/lm.scaler.scale_[tj]
                coefficients.append(dict(asset=a,fold=year,shock=s,common=common,asset_deviation=delta,trend_interaction=tb,vol_interaction=vb,fixed_state_slope_normalized=common+delta+vb,reference='markettrend20=0%,marketvol20=1%p,return_scale=1',alpha=lm.alpha,deviation_penalty_ratio=lm.ratio))
    cf=pd.DataFrame(coefficients);cf.to_csv(OUT/'factor_coefficients.csv',index=False)
    cs=cf.groupby(['asset','shock']).fixed_state_slope_normalized.agg(['min','max','mean','std']).reset_index();cs['sign_stable']=(cs['min']*cs['max']>0);cs.to_csv(OUT/'coefficient_stability_fixed_state.csv',index=False)
    sat=scenarios[scenarios.fold==2026].pivot(index=['asset','model'],columns='scenario',values='center');sat['same_2_5_to_10']=(sat.moderate-sat.extreme).abs()<1e-10;sat.reset_index().to_csv(OUT/'saturation_comparison.csv',index=False)
    # Development-only choice, not the best outer-test result.
    b=dc[dc.model=='catboost'].iloc[0];eligible=dc[(dc.model.str.startswith(('partial','hybrid')))&(dc.mae<=b.mae*.99)&(dc.crash_mae<=b.crash_mae)&(dc.demeaned_corr>=b.demeaned_corr)]
    chosen=eligible.sort_values('mae').model.iloc[0] if len(eligible) else 'catboost'
    ub=dr[dr.model=='unconditional'].iloc[0];valid=dr[(dr.model==chosen)&(dr.coverage80>=.78)&(dr.interval_score80<ub.interval_score80)&(dr.crash_lower_breach<=ub.crash_lower_breach)]
    interval=valid.sort_values('interval_score80').interval.iloc[0] if len(valid) else None
    selection=dict(development_years=[2020,2021],center_choice=chosen,interval_choice=interval,rule='newcenter:>=1% MAE improvement vs CatBoost + crashMAE and demeaned correlation no worse; interval:coverage>=78%, score better and crash breach no worse than unconditional',production_promoted=False)
    (OUT/'development_selection.json').write_text(json.dumps(selection,indent=2))
    audit.to_csv(OUT/'split_audit.csv',index=False);tuning.to_csv(OUT/'inner_tuning.csv',index=False)
    r.to_parquet(OUT/'predictions.parquet',index=False);ri.to_parquet(OUT/'interval_predictions.parquet',index=False)
    scenario_example(d)
    old=json.loads((OUT/'legacy_reproduction.json').read_text());oldr=pd.read_parquet(ROOT/'reports/four_models_gold_20261104/predictions.parquet');oldr=oldr[oldr.model=='catboost'];old['uncentered_r2_vs_zero']=float(1-((oldr.actual-oldr.center)**2).sum()/(oldr.actual**2).sum());old['prediction_actual_corr_squared']=float(oldr.actual.corr(oldr.center)**2)
    (OUT/'legacy_reproduction.json').write_text(json.dumps(old,indent=2))
    checks=dict(passed=True,models=6,stocks=20,per_model_rows=2928,dates=169,paired_targets_exact=True,common_market_state_max_numerical_difference=common_spread,temporal_inner_split=True,oof_targets_verified=True,train_cal_test_label_separation=True,cal_windows_nonoverlapping=True,publication_times_verified=False,revision_vintages_verified=False,all_available_at_null={c:bool(g[c].isna().all()) for c in g if c.endswith('_available_at')},research_not_blind=True,operational_changes=False)
    (OUT/'verification.json').write_text(json.dumps(checks,indent=2));print(center.to_string(index=False));print(risk.to_string(index=False));print(selection)
    (OUT/'progress.json').write_text(json.dumps(dict(stage='evaluated',checks_passed=True,production_promoted=False)))

if __name__=='__main__':main()
