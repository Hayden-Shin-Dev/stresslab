"""Original 4.119 pp cohort vs honest training-only baselines on exact rows."""
import argparse,json
from pathlib import Path
import pandas as pd,numpy as np
from threadpoolctl import threadpool_limits
from .core import features,anchors,SHOCKS
from .expansion import Nuisance

def run(root,out):
 root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=True)
 p=pd.read_parquet(root/'reports/selected_service_20261104/predictions.parquet');p=p[p.model.eq('selected_global')].copy()
 f=features(pd.read_parquet(root/'reports/state_link_26_20261104/research_input.parquet')).dropna(subset=SHOCKS+['target','end_date'])
 rule=json.loads(Path(__file__).with_name('expansion_protocol.json').read_text());sectors={a:s for s,aa in rule['groups'].items() for a in aa};f['sector']=f.asset.map(sectors)
 rows=[]
 for year,z in p.groupby('fold'):
  tr=f[f.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)];tr=tr[tr.asset.isin(p.asset.unique())]
  q=z.merge(f,on=['date','asset'],validate='one_to_one');np.testing.assert_allclose(q.actual,q.target)
  means=anchors(tr).groupby(['date','sector']).target.mean().groupby('sector').mean()
  q['sector_history_mean']=q.sector.map(means);q['zero']=0.
  for s in q.sector.unique():
   t=tr[tr.sector.eq(s)];mask=q.sector.eq(s)
   # Sector-conditioned mean relation, no asset identifier and no future sector returns.
   from sklearn.linear_model import Ridge
   from sklearn.preprocessing import StandardScaler
   scale=StandardScaler().fit(t[SHOCKS]);m=Ridge(alpha=300).fit(scale.transform(t[SHOCKS]),t.target)
   q.loc[mask,'sector_shock_ridge']=m.predict(scale.transform(q.loc[mask,SHOCKS]))
  rows.append(q[['asset','date','sector','actual','center','zero','sector_history_mean','sector_shock_ridge']])
 x=pd.concat(rows);x.to_parquet(out/'primary_baseline_observations.parquet',index=False)
 result=[];rng=np.random.default_rng(44)
 for model in ['zero','sector_history_mean','sector_shock_ridge']:
  a=abs(x.center-x.actual);base=abs(x[model]-x.actual);z=pd.DataFrame(dict(date=x.date,new=a,base=base)).groupby('date').agg(new=('new','sum'),base=('base','sum'))
  vals=[];n=len(z)
  for _ in range(2000):
   ix=np.concatenate([(s+np.arange(5))%n for s in rng.integers(0,n,size=int(np.ceil(n/5)))])[:n];r=z.iloc[ix];vals.append((1-r.new.sum()/r.base.sum())*100)
  result.append(dict(baseline=model,n=len(x),dates=n,assets=x.asset.nunique(),model_mae_pp=a.mean(),baseline_mae_pp=base.mean(),improvement_pct=(1-a.mean()/base.mean())*100,improvement_ci95_pct=np.quantile(vals,[.025,.975]).tolist()))
 (out/'primary_relative_performance.json').write_text(json.dumps(result,indent=2),encoding='utf8')
 print(json.dumps(result),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args()
 with threadpool_limits(limits=2):run(a.root,a.out)
