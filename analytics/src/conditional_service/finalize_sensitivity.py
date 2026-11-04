"""Refit fixed candidate on mature labels; never report refit in-sample metrics."""
import argparse,json
from pathlib import Path
import joblib
import pandas as pd
from threadpoolctl import threadpool_limits
from .core import features,SHOCKS
from .sensitivity_model import SensitivityEngine,explain

def run(gold,out):
    out=Path(out);f=features(pd.read_parquet(gold));latest=f.date.max();d=f.dropna(subset=SHOCKS+['target','end_date'])
    tr=d[d.end_date<latest-pd.Timedelta(days=20)].copy()
    eligible=set(tr.groupby('asset').size().loc[lambda x:x>=250].index)
    tr=tr[tr.asset.isin(eligible)];e=SensitivityEngine().fit(tr);snap=f[(f.date==latest)&f.asset.isin(eligible)].copy()
    assert tr.end_date.max()<latest
    per=pd.read_csv(out/'per_asset.csv',dtype={'asset':str});v={r.asset:{k:x for k,x in r._asdict().items() if k not in ['asset','model']} for r in per[per.model.eq('partial_state_gated')].itertuples(index=False)}
    audit=json.loads((out/'audit.json').read_text());audit.update(final_refit_label_end=str(tr.end_date.max()),final_refit_rows=len(tr),final_refit_evaluation='Historical annual backtests assess the procedure; this final refit has no fresh independent test.')
    b=dict(version='sensitivity-factor-v1-refit-research',engine=e,snapshot=snap,validation=v,audit=audit);joblib.dump(b,out/'candidate_bundle.joblib')
    positions=[dict(asset_id=a,value_krw=1000000) for a in ['003490','010950'] if a in set(snap.asset)]
    examples={name:explain(b,positions,shock) for name,shock in [('zero',{}),('oil10',{'wti_pct':10}),('fx5_rate100',{'fx_pct':5,'us_rate_bp':100}),('fx10_rate200',{'fx_pct':10,'us_rate_bp':200})]}
    (out/'candidate_examples.json').write_text(json.dumps(examples,ensure_ascii=False,indent=2),encoding='utf8');(out/'candidate_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf8')
    probe=snap.copy();probe[SHOCKS]=0;beta,ok,detail=e.coefficients(probe);rows=[]
    for i,r in enumerate(probe.itertuples()):
        for j,s in enumerate(SHOCKS):rows.append(dict(asset=r.asset,shock=s,coefficient=beta[i,j],training_rule_supported=bool(ok[i,j]),source='state' if detail['use_state'][i,j] else 'global',state_analogues=int(detail['state_analogues'][i])))
    pd.DataFrame(rows).to_csv(out/'candidate_support.csv',index=False)
    print('Final candidate refit complete',tr.end_date.max(),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--gold',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    with threadpool_limits(limits=2):run(a.gold,a.out)
