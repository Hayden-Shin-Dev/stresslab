"""Read-only historical width audit and matched data-value correction ablation."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from .core import features, STATE, ASSET, SHOCKS
from .rebuild_fixed_model import training

OUT=Path('reports/width_audit_20261105')
F=STATE+ASSET+SHOCKS

def metric(y,lo,hi):
    return dict(n=len(y),coverage=float(np.mean((y>=lo)&(y<=hi))),width_pp=float(np.mean(hi-lo)))

def main():
    OUT.mkdir(exist_ok=True)
    history=[]
    for path in [Path('reports/validation.json'),Path('reports/v2/evaluation.json')]:
        d=json.loads(path.read_text(encoding='utf8'))
        for horizon,v in d['horizons'].items():
            for model,results in v['models'].items():
                for asset,m in results['test'].items():
                    if isinstance(m,dict) and 'width90' in m:
                        history.append(dict(file=str(path),horizon=int(horizon),model=model,asset=asset,level=.9,n=m['n'],coverage=m['coverage90'],width_pp=m['width90']))
    for version in ['v2','v3','v4']:
        for path in Path('reports',version).glob('draws*.npz'):
            a=np.load(path);draw=a['draws'];actual=a['actual']
            horizon=1 if 'draws_1_' in path.name else 5
            for level in [.8,.9]:
                lo,hi=np.quantile(draw,[(1-level)/2,1-(1-level)/2],axis=1)
                for i,asset in enumerate(['kospi','kosdaq','samsung','hyundai','shinhan','semis','banks']):
                    if i<actual.shape[1]:history.append(dict(file=str(path),horizon=horizon,model=path.stem,asset=asset,level=level,**metric(actual[:,i],lo[:,i],hi[:,i])))
    pd.DataFrame(history).to_csv(OUT/'historical_widths.csv',index=False)
    oldp=pd.read_parquet('reports/pooled_hybrid_20261104/predictions.parquet');oldassets=set(oldp.asset)
    cur=pd.read_parquet('reports/three_model_intervals_20261105/intervals.parquet');cur=cur[cur.model.eq('catboost')]
    rows=[]
    for scope,z in [('all50',cur),('old20_overlap',cur[cur.asset.isin(oldassets)]),('additional',cur[~cur.asset.isin(oldassets)])]:
        for (method,level),q in z.groupby(['interval','level']):rows.append(dict(scope=scope,method=method,level=level,assets=q.asset.nunique(),**metric(q.actual,q.lo,q.hi)))
    pd.DataFrame(rows).to_csv(OUT/'current_scope_and_calibration.csv',index=False)
    # Repeat identical CatBoost fits on identical eligible rows; only data values differ.
    corrected=pd.read_parquet('reports/service_scope_20261105/corrected_features.parquet')
    legacy=features(pd.read_parquet('reports/support_expansion_20261104/research_input.parquet'))
    common=corrected[corrected.asset.isin(oldassets)].dropna(subset=F+['target','end_date','label_known_by'])[['date','asset']].merge(legacy.dropna(subset=F+['target','end_date'])[['date','asset']],on=['date','asset'])
    corrected=common.merge(corrected,on=['date','asset'],validate='one_to_one')
    legacy=common.merge(legacy,on=['date','asset'],validate='one_to_one')
    legacy=legacy.merge(corrected[['date','asset','label_known_by']],on=['date','asset'])
    p=pd.read_parquet('reports/three_model_intervals_20261105/points.parquet');c=pd.read_parquet('reports/three_model_intervals_20261105/calibration.parquet')
    predictions=[];splits=[]
    for year in [2023,2024,2025,2026]:
        keys=training(corrected,pd.Timestamp(year-1,1,1))[['date','asset']]
        testkeys=p[p.model.eq('catboost')&p.year.eq(year)][['date','asset']].merge(common,on=['date','asset'])
        calkeys=c[c.model.eq('catboost')&c.year.eq(year)][['date','asset']].merge(common,on=['date','asset'])
        for version,data in [('legacy_values',legacy),('corrected_values',corrected)]:
            tr=keys.merge(data,on=['date','asset']);cal=calkeys.merge(data,on=['date','asset']);te=testkeys.merge(data,on=['date','asset'])
            assert tr.end_date.max()<cal.date.min() and cal.end_date.max()<te.date.min()
            for asset in sorted(te.asset.unique()):
                z=tr[tr.asset.eq(asset)]
                m=CatBoostRegressor(iterations=150,depth=3,learning_rate=.04,loss_function='Quantile:alpha=0.5',random_seed=20261104,thread_count=2,verbose=False,allow_writing_files=False).fit(z[F].to_numpy(),z.target/z.scale)
                for split,d in [('cal',cal[cal.asset.eq(asset)]),('test',te[te.asset.eq(asset)])]:
                    v=d[['date','asset','target','scale']].copy();v['center']=m.predict(d[F].to_numpy())*d.scale;v['version']=version;v['year']=year;v['split']=split;predictions.append(v)
            splits.append(dict(year=year,version=version,train_rows=len(tr),cal_rows=len(cal),test_rows=len(te),train_end=str(tr.end_date.max()),cal_end=str(cal.end_date.max())))
            print(year,version,len(te),flush=True)
    allp=pd.concat(predictions);allp.to_parquet(OUT/'matched_correction_predictions.parquet',index=False)
    results=[];iv=[]
    for (version,year),v in allp.groupby(['version','year']):
        ca=v[v.split.eq('cal')];te=v[v.split.eq('test')]
        for method in ['asset','pooled']:
            for level in [.8,.9]:
                for asset,z in te.groupby('asset'):
                    q=ca if method=='pooled' else ca[ca.asset.eq(asset)]
                    low,high=np.quantile((q.target-q.center)/q.scale,[(1-level)/2,1-(1-level)/2])
                    z=z.copy();z['lo']=z.center+low*z.scale;z['hi']=z.center+high*z.scale;z['method']=method;z['level']=level;iv.append(z)
    iv=pd.concat(iv);iv.to_parquet(OUT/'matched_correction_intervals.parquet',index=False)
    for (version,method,level),z in iv.groupby(['version','method','level']):results.append(dict(version=version,method=method,level=level,**metric(z.target,z.lo,z.hi)))
    pd.DataFrame(results).to_csv(OUT/'correction_effect.csv',index=False)
    (OUT/'splits.json').write_text(json.dumps(splits,indent=2))
    print(pd.DataFrame(rows).to_string(index=False));print(pd.DataFrame(results).to_string(index=False))

if __name__=='__main__':main()
