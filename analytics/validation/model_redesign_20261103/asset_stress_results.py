"""Apply asset model point estimates to holdings. No portfolio model or interval."""
import math


def apply_asset_returns(holdings, asset_results):
    if not holdings or any(not math.isfinite(v) or v < 0 for v in holdings.values()):
        raise ValueError('보유 평가금액은 유한한 0 이상의 값이어야 합니다.')
    if sum(holdings.values()) <= 0:
        raise ValueError('전체 보유 평가금액은 0보다 커야 합니다.')
    missing=set(holdings)-set(asset_results)
    if missing:
        raise ValueError('종목별 분석 결과가 누락됐습니다: '+','.join(sorted(missing)))
    contexts=[];items=[]
    for asset,value in holdings.items():
        result=asset_results[asset]
        context=tuple(result[k] for k in ['market_state_id','scenario_id','horizon_days'])
        contexts.append(context)
        ret=float(result['point_return_pct'])
        if not math.isfinite(ret):
            raise ValueError('종목별 계산 수익률을 확인하세요.')
        items.append({'asset_id':asset,'holding_value_krw':value,
                      'point_return_pct':ret,'scenario_pnl_krw':value*ret/100})
    if len(set(contexts))!=1:
        raise ValueError('시장 상태, 충격 조건, 분석 기간이 같은 결과만 합산할 수 있습니다.')
    pnl=sum(x['scenario_pnl_krw'] for x in items);total=sum(holdings.values())
    return {'assets':items,'holding_value_krw':total,'scenario_pnl_krw':pnl,
            'scenario_return_pct':pnl/total*100,
            'market_state_id':contexts[0][0],'scenario_id':contexts[0][1],
            'horizon_days':contexts[0][2],
            'interpretation':'종목별 중심 수익률을 적용한 가상 손익 합계. 포트폴리오 확률 구간이나 중앙값을 뜻하지 않습니다.'}
