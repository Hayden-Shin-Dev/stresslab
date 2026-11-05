"""Service capacity prioritization using only frozen pre2022 selection evidence."""
import json
from pathlib import Path
import pandas as pd

def freeze(out,primary):
 out=Path(out);s=pd.read_csv(out/'training_selection.csv',dtype={'asset':str});p=json.loads(Path(primary).read_text());whole=s.groupby('asset').agg(stable_count=('stable','sum'),mean_cv=('coefficient_cv','mean'),economic_count=('economic_hypothesis','sum'))
 eligible=set(whole[(whole.stable_count>=3)&(whole.mean_cv<=.75)&(whole.economic_count>=2)].index)
 pool=s[s.asset.isin(eligible)&~s.prior_primary].copy()
 picked=[];shock_n={k:sum(k in v for v in p.values()) for k in s.shock.unique()};sector_n={}
 for a in p:
  sec=s[s.asset.eq(a)].sector.iloc[0];sector_n[sec]=sector_n.get(sec,0)+1
 while len(picked)<33 and len(pool):
  scores=[]
  for a,z in pool.groupby('asset'):
   sector=z.sector.iloc[0]
   # Prefer currently sparse shock/sector coverage, then stable training coefficients.
   coverage=sum(1/(1+shock_n[k]) for k in z.loc[z.economic_hypothesis,'shock'])/(1+sector_n.get(sector,0))
   scores.append((coverage,-z.coefficient_cv.mean(),a,sector,z.loc[z.economic_hypothesis,'shock'].tolist()))
  _,_,a,sec,sh=max(scores,key=lambda x:(x[0],x[1],x[2]));picked.append(a);sector_n[sec]=sector_n.get(sec,0)+1
  for k in sh:shock_n[k]+=1
  pool=pool[~pool.asset.eq(a)]
 result=dict(prior17=list(p),priority_additions=picked,maximum_service_candidates=50,rule='whole-stock pre2022 rule: >=3 of 4 stable slopes, mean four-slope CV<=.75, >=2 economic exposure hypotheses, existing quality criteria; prioritize sparse sector/shock coverage then lower CV; no evaluation metrics read',evaluation_based_selection=False)
 (out/'frozen_four_shock_priority.json').write_text(json.dumps(result,indent=2),encoding='utf8');print('Frozen primary/addition count',len(p),len(picked))
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('out');p.add_argument('primary');a=p.parse_args();freeze(a.out,a.primary)
