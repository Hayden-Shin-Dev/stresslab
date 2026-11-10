"""Bounded tuning and chronological selection. No operating deployment."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np,pandas as pd,joblib
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits
from .core import STATE,ASSET,SHOCKS,features,anchors
from .sensitivity_model import SensitivityFactor

CONFIGS=[dict(name='pool300_dev10_all',alpha=300,dev=10,years=None),dict(name='pool1000_dev10_all',alpha=1000,dev=10,years=None),dict(name='pool300_dev30_all',alpha=300,dev=30,years=None),dict(name='pool300_dev3_all',alpha=300,dev=3,years=None),dict(name='pool300_dev10_10y',alpha=300,dev=10,years=10),dict(name='sector_shock300',alpha=300,dev=10,years=None,sector=True)]

class BoundedFactor(SensitivityFactor):
 def __init__(self,config,sectors):super().__init__();self.config=config;self.sectors=sectors
 def design(self,d,fit=False):
  cols=SHOCKS if self.config.get('sector') else STATE+ASSET+SHOCKS
  if fit:
   self.assets=sorted(d.asset.unique());self.columns=cols;self.scaler=StandardScaler().fit(d[cols])
  z=self.scaler.transform(d[cols]);ids=[self.assets.index(a) for a in d.asset];one=np.eye(len(self.assets))[ids]/np.sqrt(self.config['dev']);sh=z[:,[self.columns.index(s) for s in SHOCKS]]
  return np.column_stack([z,one,(one[:,:,None]*sh[:,None,:]).reshape(len(d),-1)])
 def fit(self,d):
  if self.config.get('years'):d=d[d.date>=d.end_date.max()-pd.DateOffset(years=self.config['years'])]
  self.fit_start=d.date.min();self.fit_end=d.end_date.max()
  if self.config.get('sector'):
   self.assets=sorted(d.asset.unique());self.columns=SHOCKS;self.scaler=StandardScaler().fit(d[SHOCKS]);self.sector_models={}
   for s,z in d.groupby(d.asset.map(self.sectors)):
    sc=StandardScaler().fit(z[SHOCKS]);self.sector_models[s]=(sc,Ridge(alpha=self.config['alpha']).fit(sc.transform(z[SHOCKS]),z.target))
   return self
  w=1/d.groupby('date').date.transform('size');self.model=Ridge(alpha=self.config['alpha']).fit(self.design(d,True),d.target,sample_weight=w/w.mean());return self
 def predict(self,d):
  if not self.config.get('sector'):return super().predict(d)
  pred=np.empty(len(d))
  for s in d.asset.map(self.sectors).unique():
   ix=d.asset.map(self.sectors).eq(s).to_numpy();sc,m=self.sector_models[s];pred[ix]=m.predict(sc.transform(d.loc[ix,SHOCKS]))
  return pred
 def slope_parts(self,row,shock):
  if self.config.get('sector'):
   sc,m=self.sector_models[self.sectors[row.asset]];j=SHOCKS.index(shock);return dict(shared_coefficient=float(m.coef_[j]/sc.scale_[j]),asset_deviation=0.,state_interaction=0.)
  j=self.columns.index(shock);a=self.assets.index(row.asset);k=SHOCKS.index(shock);idx=len(self.columns)+len(self.assets)+a*4+k
  return dict(shared_coefficient=float(self.model.coef_[j]/self.scaler.scale_[j]),asset_deviation=float(self.model.coef_[idx]/np.sqrt(self.config['dev'])/self.scaler.scale_[j]),state_interaction=0.)

def stats(y,p):
 y=np.asarray(y);p=np.asarray(p);crash=y<=-5
 return dict(n=len(y),mae_pp=float(abs(y-p).mean()),rmse_pp=float(np.sqrt(np.mean((y-p)**2))),direction=float(np.mean(np.sign(y)==np.sign(p))),crash_n=int(crash.sum()),crash_underestimate_pp=float(np.maximum(p[crash]-y[crash],0).mean()) if crash.any() else None)

def run(root,out):
 root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=True);old=root/'reports/support_expansion_20261104';bundle=joblib.load(old/'tiered_bundle.joblib')
 protocol=dict(configs=CONFIGS,selection='Previous calibration year MAE; candidate crash underestimation <= sector baseline*1.05; tie lowest MAE. No test scores used.',production_approved=False,independent_blind=False,stop_after_this_grid=True)
 (out/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
 g=pd.read_parquet(old/'research_input.parquet');f=features(g);assets={a for a,t in bundle['tiers'].items() if t=='quantitative_candidate'};data=f[f.asset.isin(assets)].dropna(subset=SHOCKS+['target','end_date']).copy();sectors=bundle['sectors'];rows=[];scores=[];splits=[];choices=[]
 for year in [2023,2024,2025,2026]:
  tr=data[data.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)];cal=anchors(data[(data.date>=pd.Timestamp(year-1,1,1))&(data.end_date<pd.Timestamp(year,1,1)-pd.Timedelta(days=20))]);test=anchors(data[(data.date>=pd.Timestamp(year,1,1))&(data.date<pd.Timestamp(year+1,1,1))])
  assert tr.end_date.max()<cal.date.min() and cal.end_date.max()<test.date.min();models={};cal_scores=[];year_rows={}
  for config in CONFIGS:
   model=BoundedFactor(config,sectors).fit(tr);models[config['name']]=model
   tp=model.predict(test);cp=model.predict(cal);train_eval=anchors(tr[tr.date>=model.fit_start]);trainp=model.predict(train_eval)
   score=dict(year=year,model=config['name'],**stats(cal.target,cp));cal_scores.append(score)
   scores.extend([dict(year=year,model=config['name'],stage='training',**stats(train_eval.target,trainp)),dict(stage='calibration',**score)])
   z=test[['date','asset','target']].rename(columns={'target':'actual'}).copy();z['center']=tp;z['year']=year;z['model']=config['name'];rows.append(z);year_rows[config['name']]=z
  baseline=next(s for s in cal_scores if s['model']=='sector_shock300');allowed=[s for s in cal_scores if s['crash_underestimate_pp']<=baseline['crash_underestimate_pp']*1.05];choice=min(allowed,key=lambda x:x['mae_pp'])['model']
  selected=year_rows[choice].copy();selected['model']='chronological_selection';rows.append(selected);choices.append(dict(year=year,selected=choice,selection_uses='previous calibration year only'))
  splits.append(dict(year=year,train_start=str(tr.date.min()),train_end=str(tr.end_date.max()),cal_start=str(cal.date.min()),cal_end=str(cal.end_date.max()),test_start=str(test.date.min()),test_end=str(test.end_date.max()),n=len(test)))
  print('bounded fold',year,choice,flush=True)
 p=pd.concat(rows);p.to_parquet(out/'predictions.parquet',index=False);pd.DataFrame(scores).to_csv(out/'training_calibration.csv',index=False);pd.DataFrame([dict(model=k,**stats(z.actual,z.center)) for k,z in p.groupby('model')]).to_csv(out/'metrics.csv',index=False)
 (out/'splits.json').write_text(json.dumps(splits,indent=2),encoding='utf8');(out/'choices.json').write_text(json.dumps(choices,indent=2),encoding='utf8')
 # Latest internal selection is fixed before looking at outer evaluation scores.
 final_config=next(c for c in CONFIGS if c['name']==choices[-1]['selected']);tr=data[data.end_date<f.date.max()-pd.Timedelta(days=20)]
 from conditional_service.finalize_model import BoundedFactor as SavedFactor
 final=SavedFactor(final_config,sectors).fit(tr);checks=[]
 for months in [18,12,6]:checks.append(SavedFactor(final_config,sectors).fit(tr[tr.end_date<tr.end_date.max()-pd.DateOffset(months=months)]))
 joblib.dump(dict(model=final,checks=checks,snapshot=f[f.date.eq(f.date.max())&f.asset.isin(assets)],history=anchors(tr),config=final_config,assets=sorted(assets),source_bundle=str(old/'tiered_bundle.joblib')),out/'bounded_model.joblib')
 print('final config',final_config,flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args()
 with threadpool_limits(limits=2):run(a.root,a.out)
