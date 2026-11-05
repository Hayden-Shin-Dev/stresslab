"""Frozen service API. No training, cloud writes or Gold changes."""
import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
import joblib
import numpy as np
from fastapi import HTTPException
from .core import STATE, ASSET, SHOCKS
from .service_data import state_metadata
from .scenario_scope import SCOPE, attach_scope

MANIFEST = Path(os.environ.get('STRESSLAB_MODEL_MANIFEST', str(Path(__file__).with_name('final_service_manifest.json'))))

@lru_cache(maxsize=1)
def bundle():
    m = json.loads(MANIFEST.read_text(encoding='utf8'))
    path = Path(os.environ.get('STRESSLAB_TIERED_BUNDLE', 'reports/service_scope_20261105/final_service_bundle.joblib'))
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != m['sha256']:
        raise HTTPException(503, 'Frozen model absent or checksum mismatch')
    b = joblib.load(path)
    if sorted(a for a,t in b['tiers'].items() if t == 'quantitative_candidate') != m['supported_assets']:
        raise HTTPException(503, 'Frozen support list mismatch')
    for name in ('primary', 'expanded'):
        q = b[name]['snapshot']
        if q.empty or not np.isfinite(q[STATE+ASSET].to_numpy(dtype=float)).all():
            raise HTTPException(503, 'Frozen snapshot missing or invalid')
        if not q.date.eq(b['expanded']['snapshot'].date.iloc[0]).all():
            raise HTTPException(503, 'A and B state date mismatch')
        if not np.allclose(q[STATE].to_numpy(dtype=float), b['expanded']['snapshot'][STATE].iloc[0].to_numpy(dtype=float)):
            raise HTTPException(503, 'A and B market features mismatch')
    return b

def support():
    b = bundle(); assets = json.loads(MANIFEST.read_text(encoding='utf8'))['supported_assets']
    return dict(api_version='1.0', accepted_shocks_for_all=SHOCKS,
        assets=[dict(asset_id=a,name=b['names'][a]) for a in assets],
        quantitative_production_approved=False, mode='sensitivity_scenario', service_scope=dict(SCOPE), count=len(assets))

def model_info():
    b = bundle()
    return dict(api_version='1.0', artifact=json.loads(MANIFEST.read_text(encoding='utf8')),
        release_decision=b['release_decision'], data_status=state_metadata(b),
        production_approved=False, service_scope=dict(SCOPE),
        local_scenario_data_ready=state_metadata(b)['verified_asof_state_available'],
        deployment_status='local_only_not_deployed',
        model_experiments_stopped=True)

def post(request):
    from .tiered_service import analyze
    b = bundle(); allowed={a for a,t in b['tiers'].items() if t=='quantitative_candidate'}
    status=state_metadata(b)
    if not status['verified_asof_state_available']:
        raise HTTPException(503,dict(code='data_certification_required',blockers=status['deployment_blockers']))
    if any(p.asset_id not in allowed for p in request.positions):
        raise HTTPException(422, 'Asset outside final 50-stock support')
    try:
        result=analyze(b,[p.model_dump() for p in request.positions],request.shocks.model_dump())
        result['api_version']='1.0'; result['data_status']=state_metadata(b)
        result['model_artifact_sha256']=json.loads(MANIFEST.read_text(encoding='utf8'))['sha256']
        result['portfolio_analysis_class']='exploratory'
        for row in result['assets']:
            selected=b['primary'] if row['asset_id'] in b['primary']['support'] else b['expanded']
            hist=selected['engine'].history
            for example in row['historical_examples']:
                matching=hist[(hist.asset==row['asset_id']) & (hist.date==example['date'])]
                example['response_end_date']=str(matching.end_date.iloc[0].date())
                example['evidence_kind']='historical_observation_not_user_scenario'
            row['analysis_class']='exploratory'
            row['warnings'].append('Frozen historical state, not current market. See data_status for observation dates and certification scope.')
            if not result['data_status']['verified_asof_state_available']:
                row['warnings'].append('Historical input availability is not certified for this artifact.')
            row['baseline_pnl_krw']=row['holding_krw']*row['baseline_model_return_pct']/100
            row['shock_incremental_pnl_krw']=row['holding_krw']*row['change_from_baseline_pp']/100
            row['shock_contribution_pnl_krw']={s:row['holding_krw']*v/100 for s,v in row['contributions_pp'].items()}
        result['portfolio_baseline_pnl_krw']=sum(r['baseline_pnl_krw'] for r in result['assets'])
        result['portfolio_shock_incremental_pnl_krw']=sum(r['shock_incremental_pnl_krw'] for r in result['assets'])
        result['analysis_flow']={'A':'Confirmed daily historical snapshot, state-only search',
            'B':'Frozen shared plus stock coefficient; A does not reweight B',
            'common_state_date':result['state_date'], 'state_publication_certified':result['data_status']['verified_asof_state_available']}
        result['publication_verified']=result['data_status']['verified_asof_state_available']
        return attach_scope(result)
    except (ValueError, OverflowError) as exc:
        raise HTTPException(422,str(exc)) from exc
    except (KeyError, AssertionError) as exc:
        raise HTTPException(503,'Frozen data or calculation consistency check failed') from exc
