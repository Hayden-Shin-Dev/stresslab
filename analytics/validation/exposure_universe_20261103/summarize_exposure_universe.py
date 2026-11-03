"""Frozen selection evaluation; diagnostic test results never change membership."""
import json
import numpy as np
import pandas as pd
from select_exposure_universe import ROOT, SRC, OUT, screen_coefficients

def metrics(s):
    return dict(n=len(s),dates=s.date.nunique(),assets=s.asset.nunique(),mae=s.center_mae.mean(),rmse=np.sqrt(s.center_sq_error.mean()),coverage=s.coverage.mean(),width=s.width.mean(),interval_score=s.interval_score.mean(),lower_breach=s.lower_breach.mean(),missed_loss_pp=s.missed_loss_pp.mean())

def bootstrap(delta):
    z=np.asarray(delta);n=len(z)
    rng=np.random.default_rng(20261103)
    starts=rng.integers(n,size=(2000,int(np.ceil(n/10))))
    ix=((starts[:,:,None]+np.arange(10))%n).reshape(2000,-1)[:,:n]
    b=z[ix].mean(1);p=(1+np.sum(abs(b-z.mean())>=abs(z.mean())))/2001
    return dict(delta=float(z.mean()),ci_low=float(np.quantile(b,.025)),ci_high=float(np.quantile(b,.975)),bootstrap_p=float(p))

def main():
    selected=set(json.loads((OUT/'selected_assets.json').read_text()))
    original=set(x['asset_id'] for x in json.loads((ROOT/'data/research/official20_20261102/universe.json').read_text(encoding='utf8'))['assets'])
    six=set(x['asset_id'] for x in json.loads((ROOT/'data/research/sector6_20261103/universe.json').read_text(encoding='utf8'))['assets'])
    names={x['asset_id']:x['name'] for x in json.loads((SRC/'universe.json').read_text(encoding='utf8'))['assets']}
    r=pd.read_parquet(OUT/'predictions.parquet');per=[];scopes=[];comparison=[];annual=[]
    for (asset,kind,spec),s in r.groupby(['asset','model','spec']):
        for regime in ['all','high_vol','asset_crash']:
            z=s if regime=='all' else s[s[regime]]
            per.append(dict(asset=asset,name=names.get(asset,asset),model=kind,spec=spec,selected=asset in selected,regime=regime,**metrics(z)))
    groups={'original20':original,'prior6':six,'selected':selected,'selected_new':selected-original-six,'selected_common_original20':selected&original}
    for label,assets in groups.items():
        for (kind,spec),s in r[r.asset.isin(assets)].groupby(['model','spec']):
            scopes.append(dict(scope=label,model=kind,spec=spec,**metrics(s)))
    for (asset,kind),s in r.groupby(['asset','model']):
        a=s[s.spec=='all4'];b=s[s.spec=='state_only'];z=a.merge(b,on=['asset','date'],suffixes=('_a','_b'),validate='one_to_one')
        assert len(z)==len(a)==len(b)
        comparison.append(dict(asset=asset,name=names.get(asset,asset),model=kind,selected=asset in selected,mae_with=z.center_mae_a.mean(),mae_without=z.center_mae_b.mean(),gain_pct=100*(1-z.center_mae_a.mean()/z.center_mae_b.mean()),**bootstrap(z.center_mae_a-z.center_mae_b)))
        for year,v in z.groupby(z.date.dt.year):annual.append(dict(asset=asset,model=kind,year=year,n=len(v),mae_with=v.center_mae_a.mean(),mae_without=v.center_mae_b.mean(),coverage_with=v.coverage_a.mean(),width_with=v.width_a.mean()))
    c=pd.DataFrame(comparison);p=c.bootstrap_p.to_numpy();ix=np.argsort(p);q=np.empty(len(p));q[ix]=np.minimum.accumulate((p[ix]*len(p)/np.arange(1,len(p)+1))[::-1])[::-1];c['bh_q_all_assets_models']=np.minimum(q,1)
    c.to_csv(OUT/'shock_added_comparison.csv',index=False)
    pd.DataFrame(per).to_csv(OUT/'per_asset_metrics.csv',index=False)
    pd.DataFrame(scopes).to_csv(OUT/'scope_metrics.csv',index=False)
    pd.DataFrame(annual).to_csv(OUT/'annual_metrics.csv',index=False)
    regimes=[];group_effect=[]
    selected_rows=r[r.asset.isin(selected)]
    for (kind,spec),z in selected_rows.groupby(['model','spec']):
        for regime in ['all','high_vol','asset_crash']:
            q=z if regime=='all' else z[z[regime]]
            regimes.append(dict(model=kind,spec=spec,regime=regime,**metrics(q)))
    for kind,z in selected_rows.groupby('model'):
        a=z[z.spec=='all4'].groupby('date').center_mae.mean();b=z[z.spec=='state_only'].groupby('date').center_mae.mean()
        group_effect.append(dict(model=kind,**bootstrap((a-b).sort_index())))
    pd.DataFrame(regimes).to_csv(OUT/'selected_regime_metrics.csv',index=False)
    pd.DataFrame(group_effect).to_csv(OUT/'selected_group_effect.csv',index=False)
    # Compare different baskets on the same dates; this is composition, not model improvement.
    matched=[]
    for kind in ['ridge','lgb']:
        s=r[(r.model==kind)&(r.spec=='all4')]
        dates=set.intersection(*(set(s[s.asset==a].date) for a in selected|original))
        if not dates:
            matched.append(dict(scope='no_complete_common_date_panel',model=kind,n=0))
            continue
        a=s[s.asset.isin(selected)&s.date.isin(dates)];b=s[s.asset.isin(original)&s.date.isin(dates)]
        for label,z in [('selected',a),('original20',b)]:matched.append(dict(scope=label,model=kind,**metrics(z)))
        delta=a.groupby('date').center_mae.mean()-b.groupby('date').center_mae.mean()
        matched.append(dict(scope='selected_minus_original20_composition',model=kind,**bootstrap(delta.sort_index())))
    pd.DataFrame(matched).to_csv(OUT/'matched_date_composition.csv',index=False)
    # Retrospective OOS relationship audit, not a forecasting feature or a new selection.
    d=pd.read_parquet(OUT/'learning_table.parquet');g=pd.read_parquet(OUT/'research_daily_input.parquet')
    price=g.groupby('trading_date').kospi_close.first().sort_index();d['market_target']=d.date.map((price.shift(-5)/price-1)*100)
    pair=pd.read_csv(OUT/'selected_asset_shock_pairs.csv',dtype={'asset':str});diag=[]
    eligibility=pd.read_csv(OUT/'eligibility.csv',dtype={'asset':str}).fillna('')
    screen=pd.read_csv(OUT/'training_screen_all.csv',dtype={'asset':str}).fillna('')
    decisions=[]
    for _,e in eligibility.iterrows():
        p=pair[pair.asset==e.asset];z=screen[screen.asset==e.asset]
        decisions.append(dict(asset=e.asset,name=e['name'],selected=e.asset in selected,training_samples=e.sparse_rows,valid_coverage=e.valid_coverage,selected_shocks=';'.join(p.shock+'='+p['sign']),excluded_data_reason=e.exclusion_reason,failed_shocks=';'.join(z.loc[~z.selected,'shock']+':'+z.loc[~z.selected,'failure_reasons'])))
    pd.DataFrame(decisions).to_csv(OUT/'all_candidate_decisions.csv',index=False)
    for asset in sorted(selected):
        f=d[(d.asset==asset)&(d.date>=pd.Timestamp('2023-01-01'))].sort_values('date');parts=[]
        for year,z in f.groupby(f.date.dt.year):
            z=z.iloc[::6];parts.append(z[z.end_date<pd.Timestamp(year+1,1,1)])
        h=pd.concat(parts).dropna(subset=['market_target'])
        if len(h)<60:continue
        for row in screen_coefficients(h):
            train=pair[(pair.asset==asset)&(pair.shock==row['shock'])]
            if train.empty:continue
            diag.append(dict(asset=asset,name=names.get(asset,asset),train_sign=train.iloc[0]['sign'],oos_same_sign=train.iloc[0]['sign']==row['sign'],evaluation_start=str(h.date.min()),evaluation_end=str(h.end_date.max()),**row))
    pd.DataFrame(diag).to_csv(OUT/'selected_direction_oos.csv',index=False)
    responses=[]
    for p in sorted((OUT/'checkpoints').glob('*_responses.csv')):
        if p.stat().st_size>1:responses.append(pd.read_csv(p,dtype={'asset':str}))
    if responses:pd.concat(responses).to_csv(OUT/'model_shock_responses.csv',index=False)
    summary={'candidates':206,'selected':len(selected),'pairs':len(pair),'target_met_selected_all4':pd.DataFrame(per).query("selected and spec=='all4' and regime=='all' and coverage>=0.8 and width<=5")[['asset','model']].to_dict('records'),'evaluation_is_blind':False,'production_approved':False,'existing26_preserved':True}
    (OUT/'result_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
    print(pd.DataFrame(scopes).round(4).to_string(index=False))

if __name__=='__main__':main()
