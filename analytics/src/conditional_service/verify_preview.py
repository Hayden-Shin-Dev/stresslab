"""Verify the running preview against the frozen service, without training."""
import argparse
import json
import math
from pathlib import Path
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8157')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    url = args.url.rstrip('/')
    session = httpx.Client()
    checks = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)

    def near(a, b):
        return math.isclose(a, b, abs_tol=1e-6, rel_tol=1e-9)

    def analyze(positions, shocks, status=200):
        r = session.post(url+'/api/analyze', json={'positions': positions, 'shocks': shocks}, timeout=120)
        check('HTTP '+str(status), r.status_code == status)
        return r.json()

    info = session.get(url+'/api/model-info', timeout=120).json()
    support = session.get(url+'/api/support', timeout=120).json()['assets']
    validation = session.get(url+'/preview-info', timeout=120).json()['validation']
    check('50 supported assets', len(support) == 50)
    check('validation belongs to loaded artifact', validation['artifact_sha256'] == info['artifact']['sha256'])
    positions = [{'asset_id': '003490', 'value_krw': 1000000}, {'asset_id': '010950', 'value_krw': 1000000}]
    oil = analyze(positions, {'wti_pct': 10})
    zero = analyze(positions, {})
    mixed = analyze(positions, {'fx_pct': 5, 'us_rate_bp': 100, 'wti_pct': 10, 'vix_points': 5})
    doubled = analyze([{**p, 'value_krw': p['value_krw']*2} for p in positions], {'wti_pct': 10})
    all_assets = analyze([{'asset_id': a['asset_id'], 'value_krw': 1000000} for a in support], {'fx_pct': 5, 'us_rate_bp': 100, 'wti_pct': 10, 'vix_points': 5})
    extreme = analyze(positions, {'fx_pct': 100, 'us_rate_bp': 1000, 'wti_pct': 200, 'vix_points': 100})
    combinations=[]
    factors=['fx_pct','us_rate_bp','wti_pct','vix_points']
    values=[2,25,5,2]
    for mask in range(1,16):
        result=analyze(positions,{s:values[i] if mask & (1<<i) else 0 for i,s in enumerate(factors)})
        check('all 15 nonempty shock combinations use selected model',result['model_name']==info['model_name'])
        combinations.append(result)
    for result in [oil, zero, mixed, doubled, all_assets, extreme, *combinations]:
        p = result['portfolio_summary']
        check('portfolio sums to asset PnL', near(p['scenario_pnl_krw'], sum(a['hypothetical_pnl_krw'] for a in result['assets'])))
        check('baseline plus delta equals final', near(p['baseline_pnl_krw']+p['incremental_pnl_krw'], p['scenario_pnl_krw']))
        check('shock contributions reconcile', near(sum(p['shock_contributions_krw'].values()), p['incremental_pnl_krw']))
        check('historical state is not advertised as live', result['data_status']['latest_market_state'] is False)
        for a in result['assets']:
            check('asset contributions reconcile', near(sum(a['contributions_pp'].values()), a['change_from_baseline_pp']))
            check('asset holding conversion', near(a['holding_krw']*a['scenario_return_pct']/100, a['hypothetical_pnl_krw']))
            for shock, value in a['contributions_pp'].items():
                check('contribution uses trained coefficient', near(value, a['sensitivities'][shock]['coefficient_pp_per_unit']*result['shocks'][shock]))
    check('zero shock has zero incremental PnL', near(zero['portfolio_summary']['incremental_pnl_krw'], 0))
    check('doubling holdings doubles PnL', near(doubled['portfolio_summary']['scenario_pnl_krw'], 2*oil['portfolio_summary']['scenario_pnl_krw']))
    check('shock change changes model output', not near(oil['portfolio_summary']['scenario_pnl_krw'], mixed['portfolio_summary']['scenario_pnl_krw']))
    check('A candidates are independent of user shocks', oil['market_candidates'] == mixed['market_candidates'])
    check('extreme shock is flagged', all(a['evidence_summary']['extrapolated_shocks'] for a in extreme['assets']))
    analyze([{'asset_id': 'INVALID', 'value_krw': 1}], {}, 422)
    analyze([{'asset_id': '003490', 'value_krw': -1}], {}, 422)
    analyze([], {}, 422)
    analyze(positions, {'wti_pct': -100}, 422)
    analyze([positions[0],positions[0]], {}, 422)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    (out/'verification.json').write_text(json.dumps({'passed': len(checks), 'checks': sorted(set(checks)), 'model_info': info, 'validation': validation}, ensure_ascii=False, indent=2), encoding='utf8')
    for name, value in [('oil', oil), ('zero', zero), ('mixed', mixed), ('extreme', extreme)]:
        (out/(name+'_response.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'passed': len(checks), 'oil_scenario_pnl_krw': oil['portfolio_summary']['scenario_pnl_krw'], 'output': str(out)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
