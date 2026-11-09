"""Port B134 distribution recipe, not its KOSPI weights, to stock stress inputs."""
import json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from .core import STATE,ASSET,SHOCKS
from .rebuild_fixed_model import training

OUT=Path('reports/preopen_method_trial_20261105')
SOURCE=Path('C:/Users/shinm/OneDrive/문서/ChatGPT/논문 기반3차 프로젝트 디벨롭')
F=STATE+ASSET+SHOCKS
LEVELS=(np.arange(1001)+.5)/1001

def fit(z):
    assert (z.target>-100).all() and (z.scale>0).all()
    y=100*np.log1p(z.target.to_numpy()/100)/z.scale.to_numpy()
    scaler=StandardScaler().fit(z[F]);m=Ridge(alpha=100).fit(scaler.transform(z[F]),y)
    return dict(columns=F,center=scaler.mean_.tolist(),scale=scaler.scale_.tolist(),coef=m.coef_.tolist(),intercept=float(m.intercept_),levels=LEVELS.tolist(),base_quantiles=(np.quantile(y,LEVELS)-y.mean()).tolist(),training_n=len(z),training_start=str(z.date.min()),training_label_end=str(z.end_date.max()))

def predict(m,d):
    x=(d[F].to_numpy()-np.array(m['center']))/np.array(m['scale'])
    loc=x@np.array(m['coef'])+m['intercept']
    quant=100*np.expm1((loc[:,None]+np.array(m['base_quantiles'])[None,:])*d.scale.to_numpy()[:,None]/100)
    return np.quantile(quant,[.05,.1,.5,.9,.95],axis=1).T,100*np.expm1(loc*d.scale.to_numpy()/100)

def metrics(z):
    crash=z.actual<=-5;nz=z.actual!=0
    return dict(n=len(z),dates=z.date.nunique(),assets=z.asset.nunique(),mae_pp=float(abs(z.actual-z.center).mean()),direction=float((np.sign(z.actual[nz])==np.sign(z.center[nz])).mean()),coverage=float(((z.actual>=z.lo)&(z.actual<=z.hi)).mean()),width_pp=float((z.hi-z.lo).mean()),interval_score=float((z.hi-z.lo+2/(1-float(z.level.iloc[0]))*((z.lo-z.actual).clip(lower=0)+(z.actual-z.hi).clip(lower=0))).mean()),crash_n=int(crash.sum()),crash_mae_pp=float(abs(z.actual[crash]-z.center[crash]).mean()),crash_lower_breach=float((z.actual[crash]<z.lo[crash]).mean()))

def main():
    OUT.mkdir(exist_ok=True)
    data=pd.read_parquet('reports/service_scope_20261105/corrected_features.parquet')
    daily=pd.read_parquet('reports/service_scope_20261105/corrected_daily_input.parquet')
    scales=[]
    for a,z in daily.groupby('asset_id'):
        z=z.sort_values('trading_date');r=np.log(z.close.where(z.close>0)).diff()*100
        scales.append(pd.DataFrame(dict(date=pd.to_datetime(z.trading_date),asset=a,ewma_scale=np.sqrt(r.pow(2).ewm(alpha=.06,adjust=False).mean()).clip(lower=.05)*np.sqrt(5))))
    data=data.merge(pd.concat(scales),on=['date','asset'],validate='one_to_one')
    ref=pd.read_parquet('reports/three_model_intervals_20261105/points.parquet');ref=ref[ref.model.eq('catboost')]
    original=pd.read_parquet('reports/three_model_intervals_20261105/intervals.parquet');original=original[original.model.eq('catboost')&original.interval.eq('pooled')].copy()
    assets=sorted(ref.asset.unique());models=[];pieces=[];audit=[]
    for year in sorted(ref.year.unique()):
        cutoff=pd.Timestamp(int(year)-1,1,1);tr=training(data,cutoff)
        te=ref[ref.year.eq(year)][['date','asset']].merge(data,on=['date','asset'],validate='one_to_one')
        for variant,limit in [('b134_recipe_2520',2520),('b134_recipe_all_history',None),('b134_recipe_ewma',2520)]:
            for a,t in te.groupby('asset'):
                z=tr[tr.asset.eq(a)].sort_values('date');z=z.tail(limit) if limit else z
                t=t.copy();z=z.copy()
                if variant=='b134_recipe_ewma':
                    z['scale']=z.ewma_scale;t['scale']=t.ewma_scale
                assert len(z)>=250 and z.end_date.max()<t.date.min()
                m=fit(z);m.update(model=variant,asset=a,year=int(year),horizon=5);models.append(m)
                quant,location=predict(m,t)
                # Source distribution_summary reports q50: median includes base q50 offset.
                for level,lo,hi in [(.8,1,3),(.9,0,4)]:
                    v=t[['date','asset','target','scale']].rename(columns={'target':'actual'}).copy()
                    v['year']=year;v['model']=variant;v['level']=level;v['center']=quant[:,2];v['location_return']=location;v['lo']=quant[:,lo];v['hi']=quant[:,hi];pieces.append(v)
                audit.append(dict(year=int(year),variant=variant,asset=a,n=len(z),train_end=str(z.end_date.max()),test_start=str(t.date.min())))
            print('completed',year,variant,flush=True)
    result=pd.concat(pieces,ignore_index=True)
    assert np.isfinite(result[['actual','center','lo','hi']]).all().all()
    for (_,level),v in result.groupby(['model','level']):assert set(zip(v.date,v.asset))==set(zip(ref.date,ref.asset)) and len(v)==len(ref)
    for m in models:
        z=result[(result.model==m['model'])&(result.year==m['year'])&(result.asset==m['asset'])]
        assert (z.lo<=z.center).all() and (z.center<=z.hi).all()
    result.to_parquet(OUT/'predictions.parquet',index=False)
    (OUT/'models.json').write_text(json.dumps(models,allow_nan=False),encoding='utf8')
    (OUT/'splits.json').write_text(json.dumps(audit,indent=2),encoding='utf8')
    allv=pd.concat([result,original],ignore_index=True);rows=[]
    for period,z in [('all',allv),('2025_2026',allv[allv.year>=2025])]:
        for (m,l),v in z.groupby(['model','level']):rows.append(dict(period=period,model=m,level=l,**metrics(v)))
    pd.DataFrame(rows).to_csv(OUT/'metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,model=m,level=l,**metrics(v)) for (a,m,l),v in allv.groupby(['asset','model','level'])]).to_csv(OUT/'per_asset.csv',index=False)
    pd.DataFrame([dict(year=y,model=m,level=l,**metrics(v)) for (y,m,l),v in allv.groupby(['year','model','level'])]).to_csv(OUT/'per_year.csv',index=False)
    (OUT/'protocol.json').write_text(json.dumps(dict(source_script=str(SOURCE/'scripts/project_b_ewy_forward.py'),source_sha256=hashlib.sha256((SOURCE/'scripts/project_b_ewy_forward.py').read_bytes()).hexdigest(),formula='log return / known-at-origin scale; StandardScaler; Ridge alpha100; 1001 quantiles(normalized training returns)-training mean; exponential inverse then empirical quantiles',scale_variants='existing 20/60 scale control; source EWMA squared log returns alpha=.06 floor=.05 times sqrt(5)',inputs=F,ewy_included=False,original_kospi_weights_used=False,training_cutoff='Same prior-year cutoff as CatBoost; 20-day label/publication embargo; 2520 rows if available, no padding',center='q50 consistent with source distribution summary; location also saved',target='Individual stock 5-session return; actual future shocks supplied ex post',test='Same 50 stocks 4150 rows 85 dates; reused development sample, not blind',original_calibration='No additional calibration: source empirical training distribution, not OOS residuals',azure_gold_changed=False,production_promoted=False),indent=2),encoding='utf8')
    print(pd.DataFrame(rows).to_string(index=False))

if __name__=='__main__':main()
