"""Check real saved study outputs and local scenario identities."""
import json,hashlib
import pandas as pd
from asset_feature_research import ROOT
from tail_reliability_research import SRC,OUT

def main():
    r=pd.read_parquet(OUT/'all_comparisons.parquet')
    assert r.groupby('method').size().eq(918).all()
    assert r.groupby(['asset','date']).center.nunique().eq(1).all()
    assert not r.duplicated(['asset','date','method']).any()
    guard=r[r.method=='residual_tail_guard'].merge(r[r.method=='same_width_symmetric_control'],on=['asset','date'],suffixes=('_a','_b'),validate='one_to_one')
    assert abs(guard.width_a-guard.width_b).max()<1e-10
    for p in OUT.glob('*_audit.csv'):
        z=pd.read_csv(p,parse_dates=['date','train_end'])
        assert (z.train_end<z.date).all()
    dates=r[r.latest_residual_ready.notna() & r.latest_residual_ready.ne('')]
    assert (pd.to_datetime(dates.latest_residual_ready)<dates.date).all()
    examples=json.loads((OUT/'scenario_examples.json').read_text(encoding='utf8'))
    for x in examples:
        assert abs(sum(x['model_contributions_pp'].values())-x['scenario_difference_pp'])<1e-8
        assert abs(x['center_pnl_krw']-x['holding_krw_example']*x['conditional_center_return_pct']/100)<1e-8
        assert not x['nominal_probability_approved'] and not x['contributions_are_causal']
    expected=json.loads((SRC/'environment.json').read_text())['gold_sha256']
    assert hashlib.sha256((ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet').read_bytes()).hexdigest()==expected
    protocol=json.loads((OUT/'protocol.json').read_text())
    assert hashlib.sha256((SRC/'predictions.parquet').read_bytes()).hexdigest()==protocol['baseline_predictions_sha256']
    v=json.loads((OUT/'verification.json').read_text());v.update({'same_918_samples_each_method':True,'same_width_control_exact':True,'scenario_examples':len(examples),'contributions_and_currency_identities':True,'gold_sha256_unchanged':True,'probability_labels_not_promoted':True})
    (OUT/'verification.json').write_text(json.dumps(v,indent=2),encoding='utf8')
    print('Saved predictions, chronological boundaries, references and scenario identities passed.')

if __name__=='__main__':main()
