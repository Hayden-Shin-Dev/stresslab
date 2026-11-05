"""Rebuild locked existing models on corrected input. No search or tuning."""
import copy,hashlib,json
from pathlib import Path
import joblib,numpy as np,pandas as pd
from threadpoolctl import threadpool_limits
from .core import STATE,ASSET,SHOCKS,anchors
from .finalize_model import stats,BoundedFactor
from .tiered_service import prepare_cache
OUT=Path('reports/pit_rebuild_20261105')
OLD=Path('reports/final_model_20261104/final_service_bundle.joblib')

def training(frame,cutoff):
    cutoff=pd.Timestamp(cutoff)
    d=frame.dropna(subset=SHOCKS+['target','end_date','label_known_by'])
    return d[(d.end_date<cutoff-pd.Timedelta(days=20))&(pd.to_datetime(d.label_known_by,utc=True)<cutoff.tz_localize('UTC'))].copy()

def main():
    cfg=json.loads((OUT/'locked_protocol.json').read_text());original=joblib.load(OLD);b=copy.deepcopy(original)
    price=json.loads((OUT/'corporate_adjustment_audit.json').read_text())
    correction=json.loads((OUT/'data_correction_audit.json').read_text())
    index_audit=json.loads((OUT/'market_index_audit.json').read_text())
    assert index_audit['passed']
    assert price['price_adjustment_validation_passed'] and price['assets']==len(cfg['supported_assets'])
    assert hashlib.sha256(Path('reports/support_expansion_20261104/research_input.parquet').read_bytes()).hexdigest()==correction['gold_sha256']
    assert hashlib.sha256(OLD.read_bytes()).hexdigest()==cfg['original_model_sha256']
    data=pd.read_parquet(OUT/'corrected_features.parquet');supported=json.loads(Path(__file__).with_name('final_service_manifest.json').read_text())['supported_assets']
    rows=[];splits=[];calibration=[];checks=[];baseline=[]
    for group in ['primary','expanded']:
        expected=cfg['cohorts'][group];cohort=data[data.asset.isin(expected['assets'])]
        wanted=set(supported)&(set(b['primary']['support']) if group=='primary' else set(supported)-set(b['primary']['support']))
        for year in cfg['folds']:
            tr=training(cohort,pd.Timestamp(year-1,1,1))
            cal=anchors(training(cohort[cohort.date>=pd.Timestamp(year-1,1,1)],pd.Timestamp(year,1,1)))
            te=anchors(cohort[(cohort.date>=pd.Timestamp(year,1,1))&(cohort.date<pd.Timestamp(year+1,1,1))].dropna(subset=SHOCKS+['target','end_date','label_known_by']))
            te=te[te.asset.isin(wanted)]
            assert len(te) and len(cal) and tr.end_date.max()<cal.date.min() and cal.end_date.max()<te.date.min()
            assert set(tr.asset)==set(expected['assets']),'Fixed cohort lacks certified training observations'
            engine=type(original[group]['engine'])().fit(tr)
            assert engine.global_model.model.get_params()==expected['ridge']
            pred=engine.global_model.predict(te)
            z=te[['date','end_date','asset','target',*SHOCKS]].rename(columns={'target':'actual'}).copy();z['center']=pred;z['group']=group;z['year']=year;rows.append(z.copy())
            for stage,d in [('train',anchors(tr)),('calibration',cal)]:calibration.append(dict(group=group,year=year,stage=stage,**stats(d.target,engine.global_model.predict(d))))
            ref=BoundedFactor(dict(alpha=300,dev=10,years=None,sector=True),b['sectors']).fit(tr)
            z['sector_center']=ref.predict(te);baseline.append(z[['date','asset','sector_center']])
            splits.append(dict(group=group,year=year,training_rows=len(tr),train_date_start=str(tr.date.min()),train_label_end=str(tr.end_date.max()),last_training_label_publication=str(tr.label_known_by.max()),calibration_rows=len(cal),test_rows=len(te),test_dates=te.date.nunique(),calibration_start=str(cal.date.min()),calibration_label_end=str(cal.end_date.max()),test_start=str(te.date.min())))
            print('verified fold',group,year,len(te),flush=True)
        # Fixed snapshot choice: latest available confirmed date shared by all 50 stocks.
        complete=data[data.asset.isin(supported)].groupby('date').asset.nunique();day=complete[complete.eq(len(supported))].index.max()
        assert pd.notna(day)
        tr=training(cohort,day)
        engine=type(original[group]['engine'])().fit(tr)
        assert engine.global_model.model.get_params()==expected['ridge']
        assert engine.global_model.assets==expected['assets']
        for m,_ in engine.checks:assert m.model.get_params()==expected['ridge']
        snap=cohort[cohort.date.eq(day)].copy();snap[SHOCKS]=0
        assert wanted<=set(snap.asset),'Supported stock missing certified snapshot'
        b[group]['engine']=engine;b[group]['snapshot']=snap;b[group]['version']='pit-rebuild-existing-config-20261105'
        b[group]['audit']={'dataset_version':'pit-corrected-local-20261105','publication_verified':True,
            'availability_precision':'official date bounds, not exact timestamps','training_rows':len(tr),
            'training_assets':len(expected['assets']),'gold_unchanged':True}
        checks.append(dict(group=group,training_rows=len(tr),date_start=str(tr.date.min()),label_end=str(tr.end_date.max()),all_coefficients_finite=bool(np.isfinite(engine.global_model.model.coef_).all()),identical_hyperparameters=True))
    p=pd.concat(rows).merge(pd.concat(baseline),on=['date','asset'],validate='one_to_one')
    p.to_parquet(OUT/'rebuilt_predictions.parquet',index=False)
    metrics=dict(rebuilt=stats(p.actual,p.center),zero=stats(p.actual,np.zeros(len(p))),sector=stats(p.actual,p.sector_center))
    old=pd.read_parquet('reports/support_expansion_20261104/fallback_predictions.parquet');old=old[old.model.eq('validated_common_fallback')]
    common=p.merge(old[['date','asset','actual','center']],on=['date','asset'],suffixes=('','_old'),validate='one_to_one')
    if len(common):
        np.testing.assert_allclose(common.actual,common.actual_old)
        metrics['same_rows_previous']=stats(common.actual,common.center_old);metrics['same_rows_rebuilt']=stats(common.actual,common.center)
    metrics['distinct_evaluation_dates']=p.date.nunique();metrics['evaluation_is_development_not_blind']=True
    metrics['by_year']={str(y):dict(rebuilt=stats(z.actual,z.center),zero=stats(z.actual,np.zeros(len(z))),sector=stats(z.actual,z.sector_center),dates=z.date.nunique()) for y,z in p.groupby('year')}
    pd.DataFrame([dict(asset=a,**stats(z.actual,z.center),zero_mae_pp=float(abs(z.actual).mean()),sector_mae_pp=float(abs(z.actual-z.sector_center).mean())) for a,z in p.groupby('asset')]).to_csv(OUT/'stock_metrics.csv',index=False)
    pd.DataFrame(calibration).to_csv(OUT/'training_calibration.csv',index=False)
    (OUT/'metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf8');(OUT/'splits.json').write_text(json.dumps(splits,indent=2),encoding='utf8')
    # Existing fallback choices and support stay fixed; prior-data association evidence is not reused.
    b['evidence']={};b['return_validation']={a:stats(z.actual,z.center) for a,z in p.groupby('asset')}
    for group in ['primary','expanded']:b[group]['validation']={a:v for a,v in b['return_validation'].items() if a in b[group]['engine'].global_model.assets}
    b['common_fallback_policy']=copy.deepcopy(original['common_fallback_policy'])
    assert not any(b['common_fallback_policy'].values()),'Unexpected old routing; explicit replay needed'
    b=prepare_cache(b)
    for cached in b['calculation_cache'].values():
        for sensitivity in cached['sensitivities'].values():
            sensitivity['validation_model_scope']='Corrected-data chronological return reconstruction; coefficient stability from fixed training truncations. Prior residual-association evidence not reused.'
    sensitivities=[dict(asset=a,shock=s,**c) for a in supported for s,c in b['calculation_cache'][a]['sensitivities'].items()]
    (OUT/'sensitivity_stability.json').write_text(json.dumps(sensitivities,indent=2),encoding='utf8')
    prov=pd.read_parquet(OUT/'observation_provenance.parquet');latest=prov[prov.date.eq(day)]
    assert latest.verified.all() and len(latest)==5
    b['source_observation_dates']={r.source:str(r.observation_date.date()) for r in latest.itertuples()}
    used=prov[prov.verified]
    assert (pd.to_datetime(used.known_by,utc=True)<=pd.to_datetime(used.date,utc=True)+pd.Timedelta(hours=6,minutes=30)).all()
    b['pit_provenance']=dict(model_basis_date=str(day.date()),observations={r.source:dict(observation_date=str(r.observation_date.date()),known_by=r.known_by.isoformat(),available_at=None,source_ref=r.source_ref) for r in latest.itertuples()},state_cutoff='15:30 Asia/Seoul',lookback_verified=True)
    calendar=sorted(prov.date.unique());end_index=calendar.index(day.to_datetime64())
    b['pit_provenance']['lookback_basis_dates']={str(n):str(pd.Timestamp(calendar[end_index-n]).date()) for n in [5,20,60]}
    earlier=prov[prov.date.eq(pd.Timestamp(calendar[end_index-20]))]
    b['pit_provenance']['macro_20_session_start']={r.source:dict(observation_date=str(r.observation_date.date()),known_by=r.known_by.isoformat()) for r in earlier[earlier.verified].itertuples()}
    b['data_certification']=dict(all_checks_passed=True,price_adjustment_validation_passed=True,
        market_index_verified=True,training_publication_boundaries_passed=True,
        price_audit_assets=price['assets'],verified_ecos_documents=correction['verified_ecos_documents'],
        exact_release_clocks_known=False,corporate_event_names_fully_verified=False,
        scope='Official date bounds before cutoff and adjusted price-return continuity; excludes dividends and unverified observations',
        evidence_hashes={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in ['corporate_adjustment_audit.json','market_index_audit.json','data_correction_audit.json','splits.json','observation_provenance.parquet']})
    passed=bool(metrics['rebuilt']['mae_pp']<=metrics['sector']['mae_pp']*1.03 and metrics['rebuilt']['mae_pp']<=metrics['zero']['mae_pp']*1.03 and metrics['distinct_evaluation_dates']>=50 and all(x['all_coefficients_finite'] for x in checks))
    b['release_decision']=dict(service_candidate_confirmed=passed,production_approved=False,selected='same_existing_partial_pool_rebuilt_on_certified_observations',additional_model_experiments_stopped=True,approval_scope='Conditional sensitivity simulation only; not calibrated future loss prediction',data_integrity_passed=True,performance_gate_passed=passed)
    joblib.dump(b,OUT/'final_service_bundle.joblib')
    decision=dict(performance_gate_passed=passed,model_retrained_same_settings=True,new_model_experiments=False,checks=checks,model_basis_date=str(day.date()),model_sha256=hashlib.sha256((OUT/'final_service_bundle.joblib').read_bytes()).hexdigest(),original_model_preserved=hashlib.sha256(OLD.read_bytes()).hexdigest()==cfg['original_model_sha256'],support_unchanged=50)
    (OUT/'rebuild_decision.json').write_text(json.dumps(decision,indent=2),encoding='utf8');print(json.dumps(decision),flush=True)
    manifest=json.loads(Path(__file__).with_name('final_service_manifest.json').read_text())
    manifest.update(sha256=decision['model_sha256'],model_basis_date=str(day.date()),
        version='pit-rebuild-existing-config-20261105',production_approved=False,
        local_candidate_only=True,same_settings_rebuild=True)
    (OUT/'final_service_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
if __name__=='__main__':
    with threadpool_limits(limits=2):main()
