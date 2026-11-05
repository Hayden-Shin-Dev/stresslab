"""Training-only support selection, selected-universe refit and complete/partial API."""
import argparse,json,hashlib
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from .core import features,anchors,STATE,SHOCKS,validate,metrics
from .sensitivity_model import SensitivityEngine,explain
from .risk_ranking import SECTOR

EXPOSURE={
 'fx_pct':{'auto','semi','electronics','battery','airline','refinery','chemical'},
 'us_rate_bp':{'bank','insurance','battery','biopharma'},
 'wti_pct':{'airline','refinery','chemical'},
 'vix_points':{'bank','insurance','auto','semi','electronics','chemical','refinery','airline'},
}
REASONS={'fx_pct':'수출 매출과 수입 원가의 환율 노출을 검토하는 업종 가설',
 'us_rate_bp':'금융 자산과 부채 또는 장기 자금조달의 금리 노출 가설. 미국 금리와 국내 금리는 다름',
 'wti_pct':'항공유 원가 또는 원유 투입과 제품 판매가격의 노출 가설. WTI는 실제 원가의 대용 변수',
 'vix_points':'글로벌 위험회피와 자본시장 노출 가설. VIX가 기업의 직접 원가라는 의미는 아님'}

from .release_core import GlobalOnlyEngine


def analyze_release(bundle,positions,shocks):
    if any(not bundle['support'].get(p['asset_id']) for p in positions):raise ValueError('Asset has no active supported shock combination')
    z=explain(bundle,positions,shocks);policy=bundle['support'];sh=z['shocks']
    total_contributions={s:0. for s in SHOCKS};unknown_contributions=set()
    for r in z['assets']:
        allowed=policy.get(r['asset_id'],[])
        unsupported=[s for s in SHOCKS if sh[s]!=0 and s not in allowed]
        unknown=set(unsupported)|set(r['unstable_or_outside_shocks'])
        r['supported_shocks']=allowed;r['unsupported_active_shocks']=unsupported
        r['analysis_complete']=not bool(unknown)
        r['diagnostic_contributions_pp']=dict(r['contributions_pp'])
        r['exploratory_change_from_baseline_pp']=r['change_from_baseline_pp']
        for s in unknown:r['contributions_pp'][s]=None;unknown_contributions.add(s)
        for s in SHOCKS:
            if r['contributions_pp'][s] is not None:total_contributions[s]+=r['contributions_pp'][s]*r['holding_krw']/100
        r['supported_shock_change_pp']=sum(v for v in r['contributions_pp'].values() if v is not None)
        if unknown:
            r['model_return_pct']=None;r['hypothetical_pnl_krw']=None;r['change_from_baseline_pp']=None;r['status']='partial_analysis'
        r['support_reason']=bundle['selection_reasons'].get(r['asset_id'])
    complete=all(r['analysis_complete'] for r in z['assets'])
    z['portfolio_analysis_complete']=complete
    z['portfolio_hypothetical_pnl_krw']=sum(r['hypothetical_pnl_krw'] for r in z['assets']) if complete else None
    z['complete_assets_subtotal_krw']=sum(r['hypothetical_pnl_krw'] for r in z['assets'] if r['analysis_complete'])
    z['shock_contributions_krw']={s:None if s in unknown_contributions else total_contributions[s] for s in SHOCKS}
    z['coefficient_policy']='global_partial_pool_only';z['support_version']=bundle['support_version']
    z['dataset_version']=bundle['audit']['dataset_version'];z['training_label_end']=str(bundle['engine'].train_label_end)
    return z

def run(gold,prior,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);prior=Path(prior)
    g=pd.read_parquet(gold);audit=validate(g,True);f=features(g);d=f.dropna(subset=SHOCKS+['target','end_date'])
    # All selection observations end before the first evaluation period; no evaluation errors used.
    selection_end=pd.Timestamp('2021-12-12');tr=d[d.end_date<selection_end].copy()
    initial=GlobalOnlyEngine().fit(tr);probe=tr.sort_values('date').groupby('asset').tail(1).copy()
    beta,stable,detail=initial.coefficients(probe);selection=[];support={}
    for i,r in enumerate(probe.itertuples()):
        raw=g[g.asset_id.eq(r.asset)&pd.to_datetime(g.trading_date).lt(selection_end)].sort_values('trading_date')
        observed=raw[raw.close.gt(0)&raw.volume.gt(0)];years=(pd.to_datetime(observed.trading_date).max()-pd.to_datetime(observed.trading_date).min()).days/365.25
        quality=float(raw.tail(252).quality_status.eq('valid').mean());count=len(initial.history[initial.history.asset.eq(r.asset)])
        data_ok=years>=5 and quality>=.95 and count>=100 and r.asset!='005935'
        for j,s in enumerate(SHOCKS):
            economic=SECTOR.get(r.asset) in EXPOSURE[s];ok=bool(data_ok and economic and stable[i,j])
            selection.append(dict(asset=r.asset,sector=SECTOR.get(r.asset),shock=s,selected=ok,economic_prior=economic,reason=REASONS[s],years=years,recent_valid_fraction=quality,nonoverlap_training_windows=count,coefficient=float(beta[i,j]),stable=bool(stable[i,j]),selection_label_end=str(tr.end_date.max()),corporate_actions_fully_certified=False,publication_times_verified=False))
            if ok:support.setdefault(r.asset,[]).append(s)
    if not support:raise ValueError('No supported research combinations under frozen rules')
    pd.DataFrame(selection).to_csv(out/'selection.csv',index=False)
    (out/'frozen_support.json').write_text(json.dumps(dict(selection_end=str(selection_end),support=support,protocol='Sector priors fixed without outcome signs; >=5 years, last252 valid>=95%, >=100 nonoverlap windows; stable global coefficient across training windows; preferred share duplicate excluded.',independent_blind=False,scope='Research support candidates; source timing and corporate actions not fully certified'),ensure_ascii=False,indent=2),encoding='utf8')
    selected=d[d.asset.isin(support)].copy();previous=pd.read_parquet(prior/'predictions.parquet');raw_control=pd.read_parquet(prior/'raw_control_predictions.parquet');rows=[];splits=[]
    for year in [2023,2024,2025,2026]:
        training=selected[selected.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)]
        cal=anchors(selected[(selected.date>=pd.Timestamp(year-1,1,1))&(selected.end_date<pd.Timestamp(year,1,1)-pd.Timedelta(days=20))])
        locked=previous[previous.model.eq('partial_global')&previous.fold.eq(year)&previous.asset.isin(support)]
        test=locked[['asset','date']].merge(selected,on=['asset','date'],validate='one_to_one')
        assert training.end_date.max()<cal.date.min() and cal.end_date.max()<test.date.min()
        e=GlobalOnlyEngine().fit(training)
        for name,model in [('selected_global',e.global_model),('selected_state',SensitivityEngine.predict)]:
            if name=='selected_state':
                # Evaluate prior state-choice rule separately; it cannot change default routing.
                trial=SensitivityEngine();trial.__dict__.update(e.__dict__);cp=trial.predict(cal);tp=trial.predict(test)
            else:cp=model.predict(cal);tp=model.predict(test)
            q=np.quantile((cal.target-cp)/cal.scale,[.1,.9]);z=test[['date','asset','target']].rename(columns={'target':'actual'}).copy();z['center']=tp;z['lo']=tp+q[0]*test.scale;z['hi']=tp+q[1]*test.scale;z['fold']=year;z['model']=name;rows.append(z)
        for source,kind,label in [(previous,'partial_global','all26_global_common'),(raw_control,'individual_ridge_raw','individual_ridge_raw')]:
            z=source[source.model.eq(kind)&source.fold.eq(year)&source.asset.isin(support)].copy();z['model']=label
            check=z.merge(test[['asset','date','target']],on=['asset','date'],validate='one_to_one');assert len(check)==len(test);np.testing.assert_allclose(check.actual,check.target);rows.append(z)
        splits.append(dict(year=year,train_label_end=str(training.end_date.max()),cal_start=str(cal.date.min()),cal_end=str(cal.end_date.max()),test_start=str(test.date.min()),test_rows=len(test)))
        print('selected fold complete',year,flush=True)
    p=pd.concat(rows);p.to_parquet(out/'predictions.parquet',index=False)
    summary=pd.DataFrame([dict(model=k,**metrics(z)) for k,z in p.groupby('model')]);summary.to_csv(out/'metrics.csv',index=False)
    per=pd.DataFrame([dict(asset=a,model=k,**metrics(z)) for (a,k),z in p.groupby(['asset','model'])]);per.to_csv(out/'per_asset.csv',index=False)
    latest=f.date.max();training=selected[selected.end_date<latest-pd.Timedelta(days=20)]
    final=GlobalOnlyEngine().fit(training);snap=f[f.date.eq(latest)&f.asset.isin(support)].copy();b,ok,detail=final.coefficients(snap)
    effective={};changes=[]
    for i,r in enumerate(snap.itertuples()):
        effective[r.asset]=[s for j,s in enumerate(SHOCKS) if s in support[r.asset] and ok[i,j]]
        changes.append(dict(asset=r.asset,initial_support=support[r.asset],current_support=effective[r.asset],removed=sorted(set(support[r.asset])-set(effective[r.asset]))))
    # Never add a test-period winner to initial scope. Refit may remove unstable combinations.
    reasons={a:[r for r in selection if r['asset']==a and r['selected']] for a in support}
    validation={r.asset:{k:v for k,v in r._asdict().items() if k not in ['asset','model']} for r in per[per.model.eq('selected_global')].itertuples(index=False)}
    audit.update(source_sha256=hashlib.sha256(Path(gold).read_bytes()).hexdigest(),splits=splits,selection_labels_end=str(tr.end_date.max()),final_fit_label_end=str(training.end_date.max()),production_approved=False)
    effective={a:s for a,s in effective.items() if s}
    bundle=dict(version='selected-global-factor-v1',support_version='training2021-global-stability-v1',engine=final,snapshot=snap,support=effective,selection_reasons=reasons,validation=validation,audit=audit)
    joblib.dump(bundle,out/'candidate_bundle.joblib');(out/'audit.json').write_text(json.dumps(audit,indent=2),encoding='utf8');(out/'support_changes.json').write_text(json.dumps(changes,indent=2),encoding='utf8')
    positions=[dict(asset_id=a,value_krw=1000000) for a in ['003490','010950'] if a in effective]
    if not positions:positions=[dict(asset_id=a,value_krw=1000000) for a in list(effective)[:2]]
    examples={name:analyze_release(bundle,positions,sh) for name,sh in [('zero',{}),('oil10',{'wti_pct':10}),('fx5_rate100',{'fx_pct':5,'us_rate_bp':100})]}
    (out/'examples.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2),encoding='utf8')
    coefs=[]
    for i,r in enumerate(snap.itertuples()):
        for j,s in enumerate(SHOCKS):coefs.append(dict(asset=r.asset,shock=s,coefficient_pp_per_unit=float(b[i,j]),supported=s in effective.get(r.asset,[]),source='global_partial_pool'))
    pd.DataFrame(coefs).to_csv(out/'coefficients.csv',index=False)
    print('support',effective,flush=True);print(summary.to_string(index=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--gold',required=True);p.add_argument('--prior',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    with threadpool_limits(limits=2):run(a.gold,a.prior,a.out)
