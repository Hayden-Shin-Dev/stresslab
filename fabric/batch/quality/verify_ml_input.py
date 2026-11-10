"""Fabric Gold 묶음을 기존 로컬 모델에 연결합니다. 재학습과 클라우드 쓰기는 없습니다."""
# 2026-11-09 13:05 KST 민철 추가 — Gold 읽기, 과거 피처 유지, API 손익 계산을 확인합니다.
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'analytics/src'))
from conditional_service.gold_ready import read_gold
from conditional_service.gold_ready_api import create_app
from conditional_service.core import STATE, ASSET, SHOCKS


def verify(bundle, snapshot):
    bundle, snapshot = Path(bundle), Path(snapshot)
    model_path = bundle/'model.joblib'
    digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
    g,f,p = read_gold(snapshot/'gold.parquet',snapshot/'provenance.parquet',snapshot/'certificate.json')
    old,oldf,_ = read_gold(bundle/'gold.parquet',bundle/'provenance.parquet',bundle/'certificate.json')
    z = f.merge(oldf,on=['asset','date'],suffixes=('','_old'),validate='one_to_one')
    if z.empty:
        raise ValueError('기존 검증 데이터와 공통 날짜가 없습니다')
    for col in STATE+ASSET:
        np.testing.assert_allclose(z[col],z[col+'_old'],rtol=0,atol=1e-10,equal_nan=True)
    matured = z[z.end_date_old<=pd.to_datetime(old.trading_date).max()]
    for col in SHOCKS+['target']:
        np.testing.assert_allclose(matured[col],matured[col+'_old'],rtol=0,atol=1e-10,equal_nan=True)
    app = create_app(bundle,snapshot/'gold.parquet',snapshot/'provenance.parquet',snapshot/'certificate.json')
    with TestClient(app) as client:
        response = client.get('/model-info');response.raise_for_status();info=response.json()
        for source,row in info['macro_observations'].items():
            evidence = p[p.date.eq(pd.Timestamp(info['market_basis_date'])) & p.source.eq(source)].iloc[0]
            assert row['availability_precision']==evidence.availability_basis
            assert row['available_at'] is None
        positions = [dict(asset_id=a,value_krw=1000000) for a in sorted(g.asset_id.unique())]
        results = []
        for shocks in [{},dict(fx_pct=5,us_rate_bp=100,wti_pct=10,vix_points=5)]:
            response = client.post('/analyze',json=dict(positions=positions,shocks=shocks))
            response.raise_for_status();data=response.json()
            assert len(data['assets'])==len(positions)
            for asset in data['assets']:
                np.testing.assert_allclose(asset['baseline_model_return_pct']+sum(asset['shock_contributions_pp'].values()),asset['conditional_return_pct'],atol=1e-8)
                np.testing.assert_allclose(asset['hypothetical_pnl_krw'],asset['value_krw']*asset['conditional_return_pct']/100)
            np.testing.assert_allclose(data['portfolio_hypothetical_pnl_krw'],sum(a['hypothetical_pnl_krw'] for a in data['assets']))
            results.append(data)
        assert results[0]['market_candidates']==results[1]['market_candidates']
    assert hashlib.sha256(model_path.read_bytes()).hexdigest()==digest
    return dict(status='passed',model_sha256_unchanged=digest,model_kind=info['model_kind'],
                market_basis_date=info['market_basis_date'],assets=len(positions),
                common_feature_rows=len(z),common_matured_label_rows=len(matured),
                scenarios=['zero changes','four shocks together'],contribution_and_pnl_sums_match=True,
                A_candidates_unchanged_by_user_shocks=True,training_performed=False,cloud_write=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--bundle',required=True,help='신뢰할 수 있는 기존 모델과 검증 Gold 폴더')
    parser.add_argument('--snapshot',required=True,help='Fabric에서 받은 Gold/근거/인증 파일 폴더')
    parser.add_argument('--output',required=True,help='검증 결과 JSON 경로')
    args=parser.parse_args()
    result=verify(args.bundle,args.snapshot)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=True))
