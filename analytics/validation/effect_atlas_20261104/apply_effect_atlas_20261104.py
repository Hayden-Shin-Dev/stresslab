"""Freeze pre2022 response-curve selection, then apply to later same-key evaluation."""
import json,joblib,hashlib
from concurrent.futures import ThreadPoolExecutor,as_completed
import pandas as pd
import numpy as np
from threadpoolctl import threadpool_limits
from analyze_effect_atlas_20261104 import OUT,ROOT,RAW,SHOCKS
from analyze_variables_20261104 import model
from balance_effect_atlas_20261104 import ALIASES

def selected_features(pack,balanced):
    e=pd.DataFrame(pack['effects']);h=pd.DataFrame(pack['heterogeneity']);chosen=[];evidence=[]
    for outcome,limit in [('return',15),('crash_score',10)]:
        z=e[e.outcome==outcome];r=z.groupby('feature').agg(folds=('fold','nunique'),positive=('net_effect',lambda x:(x>0).sum()),negative=('net_effect',lambda x:(x<0).sum()),amplitude=('range_effect','mean'))
        stable=r[(r.folds==2)&((r.positive==2)|(r.negative==2))].sort_values('amplitude',ascending=False).head(limit)
        for c,row in stable.iterrows():
            if c not in balanced:continue
            chosen.append(c);evidence.append(dict(feature=c,source=outcome,mean_ale_amplitude=float(row.amplitude),folds=2))
    chosen=list(dict.fromkeys(SHOCKS+['market_trend20','market_vol20','asset_trend20','asset_vol20','vix_level']+[ALIASES.get(c,c) for c in chosen]))
    interactions=[]
    if len(h):
        r=h[h.outcome=='return'].groupby(['shock','state']).agg(folds=('fold','nunique'),positive=('response_difference',lambda x:(x>0).sum()),negative=('response_difference',lambda x:(x<0).sum()),strength=('response_difference',lambda x:x.abs().mean()))
        r=r[(r.folds==2)&((r.positive==2)|(r.negative==2))]
        r=r[~r.index.get_level_values('state').isin(ALIASES)].sort_values('strength',ascending=False).head(8)
        for (shock,state),v in r.iterrows():
            if state not in chosen:continue
            if state not in chosen:chosen.append(state)
            interactions.append((shock,state))
    return chosen,interactions,evidence

def main():
    assert json.loads((OUT/'progress.json').read_text())['status']=='complete'
    assert json.loads((OUT/'coordinates/progress.json').read_text())['status']=='complete'
    assert json.loads((OUT/'balance_progress.json').read_text())['status']=='complete'
    balanced=pd.read_csv(OUT/'entropy_balanced_contrasts.csv',dtype={'asset':str})
    d=pd.read_parquet(ROOT/'reports/rich_context_20261103/learning_table.parquet');ref=pd.read_parquet(ROOT/'reports/variable_analysis_20261104/predictions.parquet');ref=ref[ref.method.eq('baseline')]
    packs=[];failed=[];feature_rows=[];audit=[]
    def run(a):
        pack=json.loads((OUT/'coordinates/checkpoints'/f'{a}.json').read_text());eligible=set(balanced.loc[balanced.asset.eq(a)&balanced.status.eq('balanced_descriptive'),'feature']);cols,inter,evidence=selected_features(pack,eligible);f=d[d.asset==a].copy();features=cols.copy()
        for s,c in inter:
            name='atlas_'+s+'__'+c;f[name]=f[s]*f[c];features.append(name)
        records=[];times=[]
        for year in range(2023,2027):
            cut=pd.Timestamp(year,1,1);tr=f[f.end_date<cut-pd.Timedelta(days=20)];old=ref[(ref.asset==a)&(ref.date.dt.year==year)].sort_values('date');te=f.set_index('date').loc[old.date]
            if not len(old):continue
            assert tr.end_date.max()<old.date.min()
            m=model('lgb').fit(tr[features],tr.target);pred=m.predict(te[features]);r=old.copy();r['method']='response_atlas_guided';r['center']=pred;records.append(r)
            times.append(dict(asset=a,year=year,train_end=str(tr.end_date.max()),test_start=str(old.date.min()),feature_selection_label_end=pack['time_audit'][-1]['test_end']))
            if year==2026:
                folder=OUT/'models';folder.mkdir(exist_ok=True);joblib.dump(dict(model=m,features=features,interactions=inter,approved=False),folder/(a+'.joblib'))
        return pd.concat(records),[dict(asset=a,feature=c,interaction=c.startswith('atlas_'),selection_uses_future_test=False) for c in features],times
    with threadpool_limits(limits=1,user_api='blas'),ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(run,a):a for a in sorted(ref.asset.unique())}
        for i,fu in enumerate(as_completed(futures),1):
            try:r,features,t=fu.result();packs.append(r);feature_rows+=features;audit+=t
            except Exception as e:failed.append(dict(asset=futures[fu],error=repr(e)))
            (OUT/'application_progress.json').write_text(json.dumps(dict(status='running',completed=i,total=len(futures),failed=failed)));print(i,len(futures),flush=True)
    assert not failed,failed
    p=pd.concat(packs);assert len(p)==len(ref)
    pd.concat([ref,p]).to_parquet(OUT/'application_predictions.parquet',index=False);pd.DataFrame(feature_rows).to_csv(OUT/'applied_features.csv',index=False);pd.DataFrame(audit).to_csv(OUT/'application_time_audit.csv',index=False)
    (OUT/'application_progress.json').write_text(json.dumps(dict(status='complete',completed=len(futures),failed=[])))
if __name__=='__main__':main()
