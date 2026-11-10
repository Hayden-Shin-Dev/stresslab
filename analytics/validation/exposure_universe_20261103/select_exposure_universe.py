"""Frozen training-only signed shock screening. Does not read evaluation performance."""
import json
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.preprocessing import StandardScaler
from asset_feature_research import ROOT,make_data,SHOCKS,A_STATE
SRC=ROOT/'data/research/exposure_universe_20261103';OUT=ROOT/'reports/exposure_universe_20261103'

def number(s):return pd.to_numeric(s.astype(str).str.replace(',',''),errors='coerce')

def assemble(assets,screen=False):
    original=pd.read_parquet(ROOT/'reports/sector6_factors_20261103/research_daily_input.parquet');original['trading_date']=pd.to_datetime(original.trading_date)
    template=original[original.asset_id=='005930'].copy();old=set(original.asset_id);parts=[original[original.asset_id.isin(set(assets)|{'005930','005380'})].copy()];quality=[]
    if screen:template=template[template.trading_date.between('2016-01-01','2021-12-31')];parts=[p[p.trading_date.between('2016-01-01','2021-12-31')] for p in parts]
    for asset in assets:
        if asset in old:continue
        rows=[]
        for p in sorted((SRC/'stocks'/asset).glob('*.json')):rows.extend(json.loads(p.read_text(encoding='utf8')))
        if not rows:quality.append(dict(asset=asset,raw_rows=0,reason='no_rows'));continue
        z=pd.DataFrame(rows);z['trading_date']=pd.to_datetime(z.TRD_DD);assert not z.trading_date.duplicated().any();z=z.sort_values('trading_date');z['close']=number(z.TDD_CLSPRC);z['volume']=number(z.ACC_TRDVOL);reported=number(z.FLUC_RT);diff=(z.close.pct_change(fill_method=None)*100-reported).abs();z['bad']=diff>(.011+200/z.close.shift(1))
        x=template.drop(columns=['close','volume']).merge(z[['trading_date','close','volume','bad']],on='trading_date',how='left',validate='one_to_one');x['asset_id']=asset;x['sector_id']=None;x['source_ref']='KRX_exposure_research';x['adjustment_version']='KRX_reference20261030';x['dataset_version']='exposure_research';x['quality_status']=np.where(x.close.isna(),'missing',np.where(x.bad.eq(True)|x.volume.le(0)|x.close.le(0),'quarantined','valid'));x=x.drop(columns='bad');parts.append(x[original.columns]);quality.append(dict(asset=asset,raw_rows=len(z),first=str(z.trading_date.min()),last=str(z.trading_date.max()),return_disagreements=int(z.bad.sum()),zero_volume=int(z.volume.eq(0).sum())))
    g=pd.concat(parts,ignore_index=True);assert not g.duplicated(['asset_id','trading_date']).any();return g,pd.DataFrame(quality)

def screen_coefficients(h):
    cols=SHOCKS+['market_target']+A_STATE;sx=StandardScaler().fit(h[cols]);x=sx.transform(h[cols]);v=np.column_stack([np.ones(len(x)),x]);y=h.target.to_numpy();inv=np.linalg.pinv(v.T@v);beta=inv@v.T@y;err=y-v@beta;hat=np.einsum('ij,jk,ik->i',v,inv,v);scaled=err/np.maximum(1-hat,1e-6);cov=inv@(v.T@(v*scaled[:,None]**2))@inv
    periods=[np.linalg.lstsq(v[ix],y[ix],rcond=None)[0] for ix in np.array_split(np.arange(len(h)),3)];rows=[]
    years=h.date.dt.year.to_numpy()
    year_deleted=[np.linalg.lstsq(v[years!=yr],y[years!=yr],rcond=None)[0] for yr in np.unique(years)]
    # Total-return association is separate from the market-controlled association.
    total_cols=SHOCKS+A_STATE
    total_x=StandardScaler().fit_transform(h[total_cols])
    total_beta=np.linalg.lstsq(np.column_stack([np.ones(len(h)),total_x]),y,rcond=None)[0]
    # Exact leave-one-observation OLS influence, for the fixed disjoint sample.
    deleted=beta[None,:]-(v@inv)*scaled[:,None]
    for j,shock in enumerate(SHOCKS):
        k=j+1;control=np.delete(v,k,axis=1);ry=y-control@np.linalg.lstsq(control,y,rcond=None)[0];rx=x[:,j]-control@np.linalg.lstsq(control,x[:,j],rcond=None)[0];event=abs(rx)>=np.quantile(abs(rx),.8);se=np.sqrt(max(cov[k,k],1e-30));sign=np.sign(beta[k]);agree=float((np.sign(ry[event]*rx[event])==sign).mean())
        rows.append(dict(shock=shock,coefficient=beta[k]/sx.scale_[j],coefficient_early=periods[0][k]/sx.scale_[j],coefficient_middle=periods[1][k]/sx.scale_[j],coefficient_late=periods[2][k]/sx.scale_[j],period_sign_agreement=float(np.mean([np.sign(b[k])==sign for b in periods])),event_n=int(event.sum()),direction_agreement=agree,effect=abs(beta[k])/max(y.std(),1e-9),leave_one_sign_agreement=float((np.sign(deleted[:,k])==sign).mean()),hc3_p=float(2*norm.sf(abs(beta[k])/se)),sign='positive' if sign>0 else 'negative',n=len(h)))
        rows[-1].update(leave_one_year_sign_agreement=float(np.mean([np.sign(b[k])==sign for b in year_deleted])),total_return_association_sign='positive' if total_beta[k]>0 else 'negative',minimum_period_rows=min(len(ix) for ix in np.array_split(np.arange(len(h)),3)))
    return rows

def main():
    status=json.loads((SRC/'screen_progress.json').read_text(encoding='utf8'))
    assert status['status']=='complete', 'All candidate downloads must complete before screening'
    OUT.mkdir(exist_ok=True);rule=json.loads((OUT/'selection_protocol.json').read_text(encoding='utf8'));u=json.loads((SRC/'universe.json').read_text(encoding='utf8'))['assets'];assets=[a['asset_id'] for a in u];names={a['asset_id']:a['name'] for a in u};g,quality=assemble(assets,screen=True);quality.to_csv(OUT/'screen_source_quality.csv',index=False);d,_=make_data(g);price=g.groupby('trading_date').kospi_close.first().sort_index();mt=(price.shift(-5)/price-1)*100;d['market_target']=d.date.map(mt)
    oil=g.groupby('trading_date').wti.first().sort_index();invalid=oil.le(0).rolling(6).max().shift(-5).eq(1);bad=set(oil.index[invalid]);d=d[(d.end_date<pd.Timestamp('2021-12-12'))&~d.date.isin(bad)];d.to_parquet(OUT/'screen_learning_table.parquet',index=False)
    scores=[];eligibility=[]
    for asset in assets:
        f=d[d.asset==asset].sort_values('date');h=f.iloc[::6];z=g[g.asset_id==asset];observed=z[z.close.notna()];inlife=z[z.trading_date.between(observed.trading_date.min(),observed.trading_date.max())];coverage=inlife.quality_status.eq('valid').mean() if len(inlife) else 0
        ok=len(h)>=rule['min_sparse_rows'] and coverage>=rule['min_valid_coverage_within_observed_life'];reasons=[]
        if len(h)<rule['min_sparse_rows']:reasons.append('insufficient_nonoverlap_training_samples')
        if coverage<rule['min_valid_coverage_within_observed_life']:reasons.append('insufficient_valid_price_coverage')
        eligibility.append(dict(asset=asset,name=names[asset],sparse_rows=len(h),valid_coverage=coverage,eligible=ok,exclusion_reason=';'.join(reasons)))
        if not ok:continue
        for row in screen_coefficients(h):scores.append(dict(asset=asset,name=names[asset],train_start=str(h.date.min()),train_label_end=str(h.end_date.max()),**row))
    if not scores:
        pd.DataFrame(eligibility).to_csv(OUT/'eligibility.csv',index=False)
        (OUT/'selected_assets.json').write_text('[]')
        raise RuntimeError('No eligible training samples; selection is not complete')
    s=pd.DataFrame(scores);pv=s.hc3_p.to_numpy();assert np.isfinite(pv).all();order=np.argsort(pv);q=np.empty(len(pv));q[order]=np.minimum.accumulate((pv[order]*len(pv)/np.arange(1,len(pv)+1))[::-1])[::-1];s['bh_q']=np.minimum(q,1)
    s['selected']=(s.period_sign_agreement>=rule['period_same_sign_fraction'])&(s.event_n>=rule['min_controlled_event_rows'])&(s.direction_agreement>=rule['min_controlled_event_direction_fraction'])&(s.effect>=rule['min_standardized_effect_divided_by_target_sd'])&(s.leave_one_sign_agreement>=rule['min_delete_one_sign_fraction'])&(s.bh_q<=rule['max_bh_q'])
    s['selected'] &= s.minimum_period_rows>=rule['min_each_period_rows']
    s['failure_reasons']=s.apply(lambda z:';'.join(k for k,failed in {
        'period_sign_changes':z.period_sign_agreement<rule['period_same_sign_fraction'],
        'too_few_events':z.event_n<rule['min_controlled_event_rows'],
        'event_direction_inconsistent':z.direction_agreement<rule['min_controlled_event_direction_fraction'],
        'small_effect':z.effect<rule['min_standardized_effect_divided_by_target_sd'],
        'single_window_dependence':z.leave_one_sign_agreement<rule['min_delete_one_sign_fraction'],
        'multiplicity_evidence_weak':z.bh_q>rule['max_bh_q'],
        'short_subperiod':z.minimum_period_rows<rule['min_each_period_rows']}.items() if failed),axis=1)
    s.to_csv(OUT/'training_screen_all.csv',index=False);s[s.selected].to_csv(OUT/'selected_asset_shock_pairs.csv',index=False);pd.DataFrame(eligibility).to_csv(OUT/'eligibility.csv',index=False);chosen=sorted(s[s.selected].asset.unique());(OUT/'selected_assets.json').write_text(json.dumps(chosen,indent=2))
    print(json.dumps({'candidate_count':len(assets),'eligible':int(sum(x['eligible'] for x in eligibility)),'selected_stocks':len(chosen),'selected_pairs':int(s.selected.sum()),'training_only':True}))
if __name__=='__main__':main()
