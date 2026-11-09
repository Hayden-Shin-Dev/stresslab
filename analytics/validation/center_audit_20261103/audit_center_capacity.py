"""Diagnostic fit-versus-next-year gap, not model selection or blind testing."""
import json
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
from asset_feature_research import model,EXPANDED
from audit_center_training import SRC,OUT
from report_long_universe import metric

def main():
    (OUT/'capacity_protocol.json').write_text(json.dumps(dict(purpose='Distinguish limited training fit from temporal generalization; do not promote either model',train='labels end before2021-12-12',validation='2022 disjoint5day rows, labels finish within2022',models={'existing_raw':'250trees depth4 leaves15 minchild40','larger_raw':'500trees depth6 leaves31 minchild20'},selection='Same101 fixed; no ranking or parameter search',blind=False),indent=2),encoding='utf8')
    assets=json.loads((SRC/'selected_assets.json').read_text());g=pd.read_parquet(SRC/'research_daily_input.parquet').sort_values(['asset_id','trading_date']);d=pd.read_parquet(SRC/'learning_table.parquet');flags=[]
    for a,z in g.groupby('asset_id'):
        ok=z.quality_status.eq('valid')&z.close.gt(0)&z.is_mock.eq(False)
        flags.append(pd.DataFrame(dict(asset=a,date=z.trading_date,clean=ok.rolling(61).sum().eq(61))))
    d=d.merge(pd.concat(flags),on=['asset','date'],validate='one_to_one');oil=g.groupby('trading_date').wti.first().sort_index();bad=set(oil.index[oil.le(0).rolling(6).max().shift(-5).eq(1)])
    def run(a):
        f=d[d.asset.eq(a)&d.clean&~d.date.isin(bad)].sort_values('date');tr=f[f.end_date<pd.Timestamp('2021-12-12')];va=f[(f.date>=pd.Timestamp('2022-01-01'))&(f.end_date<pd.Timestamp('2023-01-01'))].iloc[::6];rows=[]
        assert tr.end_date.max()<va.date.min()
        for kind in ['existing_raw','larger_raw']:
            m=model('lgb')
            if kind=='larger_raw':m.set_params(n_estimators=500,max_depth=6,num_leaves=31,min_child_samples=20)
            m.fit(tr[EXPANDED],tr.target)
            for scope,z in [('in_sample',tr),('next_year',va)]:
                pred=m.predict(z[EXPANDED]);rows.append(dict(asset=a,model=kind,scope=scope,**metric(pd.DataFrame(dict(actual=z.target.to_numpy(),center=pred)))))
        return rows
    rows=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for i,f in enumerate(as_completed([pool.submit(run,a) for a in assets]),1):
            rows.extend(f.result());print(i,len(assets),flush=True)
    pd.DataFrame(rows).to_csv(OUT/'capacity_audit.csv',index=False)
    # Stock-average metrics; do not confuse these with pooled main evaluation.
    pd.DataFrame(rows).groupby(['model','scope'])[['direction_accuracy','mae','fixed5_coverage']].mean().to_csv(OUT/'capacity_summary.csv')

if __name__=='__main__':main()
