"""Package the promising development Huber arm without replacing defaults."""
import copy,hashlib,json
from pathlib import Path
import joblib,numpy as np,pandas as pd
from threadpoolctl import threadpool_limits
from .conditional_loss_research import ConditionalFactor
from .rebuild_fixed_model import training
from .finalize_model import stats
from .tiered_service import prepare_cache

ROOT=Path('reports/service_scope_20261105');OUT=Path('reports/robust_candidate_20261105')

def main():
    OUT.mkdir(exist_ok=True)
    original=ROOT/'final_service_bundle.joblib';before=hashlib.sha256(original.read_bytes()).hexdigest()
    b=copy.deepcopy(joblib.load(original));f=pd.read_parquet(ROOT/'corrected_features.parquet')
    p=pd.read_parquet('reports/conditional_loss_20261105/predictions.parquet')
    config=dict(name='huber',loss='huber',gates=False);checks=[]
    for group in ['primary','expanded']:
        e=b[group]['engine'];data=f[f.asset.isin(e.global_model.assets)];day=b[group]['snapshot'].date.iloc[0];tr=training(data,day)
        from conditional_service.conditional_loss_research import ConditionalFactor as SavedFactor
        e.global_model=SavedFactor(config).fit(tr);e.state_model=e.global_model;e.checks=[]
        assert e.global_model.converged
        for months in [18,12,6]:
            d=tr[tr.end_date<tr.end_date.max()-pd.DateOffset(months=months)]
            good=set(d.groupby('asset').size().loc[lambda z:z>=250].index)
            m=SavedFactor(config).fit(d[d.asset.isin(good)]);assert m.converged;e.checks.append((m,m))
        assert e.train_label_end==tr.end_date.max()
        b[group]['version']='robust-huber-development-20261105'
        checks.append(dict(group=group,training_rows=len(tr),iterations=e.global_model.iterations,converged=True,all_coefficients_finite=bool(np.isfinite(e.global_model.model.coef_).all())))
    b['return_validation']={a:stats(z.actual,z.huber) for a,z in p.groupby('asset')};b['evidence']={}
    b=prepare_cache(b)
    for cache in b['calculation_cache'].values():
        for sensitivity in cache['sensitivities'].values():sensitivity['validation_model_scope']='Fixed Huber development arm, repeated historical evaluation, not independent blind; stability from training truncations.'
    metric=stats(p.actual,p.huber);zero=stats(p.actual,np.zeros(len(p)));sector=stats(p.actual,p.sector)
    gate=bool(metric['mae_pp']<=min(zero['mae_pp'],sector['mae_pp'])*1.03)
    b['release_decision']=dict(service_candidate_confirmed=False,production_approved=False,selected='robust_huber_research_candidate',performance_gate_passed=gate,data_integrity_passed=True,additional_model_experiments_stopped=False,reason='Promising fixed development arm; selection policy improvement smaller, independent prospective evaluation outstanding. Original defaults preserved.')
    joblib.dump(b,OUT/'final_service_bundle.joblib');digest=hashlib.sha256((OUT/'final_service_bundle.joblib').read_bytes()).hexdigest()
    manifest=json.loads((ROOT/'final_service_manifest.json').read_text());manifest.update(sha256=digest,version='robust-huber-development-20261105',same_settings_rebuild=False,local_candidate_only=True)
    (OUT/'final_service_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    decision=dict(performance_gate_passed=gate,production_approved=False,default_replaced=False,model_sha256=digest,checks=checks,metrics=metric,zero=zero,sector=sector,old_model_unchanged=hashlib.sha256(original.read_bytes()).hexdigest()==before)
    assert decision['old_model_unchanged']
    (OUT/'rebuild_decision.json').write_text(json.dumps(decision,indent=2),encoding='utf8')
    print(json.dumps(decision))

if __name__=='__main__':
    with threadpool_limits(limits=2):main()
