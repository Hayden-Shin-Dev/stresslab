"""Select stock/shock pairs using pre-2022 rolling validation only."""
import json
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from asset_feature_research import ROOT, EXPANDED, SHOCKS
SRC=ROOT/'reports/exposure_universe_20261103';OUT=ROOT/'reports/reselection_20261103'
def fit(x,y):return make_pipeline(StandardScaler(),LogisticRegression(C=.1,solver='liblinear',max_iter=300,random_state=20261103)).fit(x,y)
def main():
    OUT.mkdir(exist_ok=True)
    protocol=dict(selection='2019-2021 rolling internal validation, fit preceding years only with20day label embargo; no 2022+ selection data',candidate_source='Existing206 KRX official candidates; prior price-quality eligibility retained',target='sign of actual5day total stock return; actual realized shock supplied retrospectively',features='pre-state plus ONE shock, vs pre-state alone; no future market return control',event='abs(shock)>=training75th percentile; excludes zero returns',gate='>=45event observations, direction>=60%, gain>=3pp, positive gain in>=2years, coefficient sign same3years',ranking='Top6 pairs, distinct stocks, gate first then (accuracy-.5)+gain. If fewer pass, remaining are explicitly exploratory, not validated selections',holdout='2023-2026 excluded from selection, but previously reused overall research; not independent blind',production=False)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8')
    d=pd.read_parquet(SRC/'screen_learning_table.parquet');eligible=pd.read_csv(SRC/'eligibility.csv',dtype={'asset':str});names=eligible.set_index('asset').name.to_dict();d=d[d.asset.isin(eligible[eligible.eligible].asset)]
    state=[c for c in EXPANDED if c not in SHOCKS];rows=[];folds=[]
    for asset,f in d.groupby('asset'):
        f=f.sort_values('date')
        for year in [2019,2020,2021]:
            cut=pd.Timestamp(year,1,1);tr=f[(f.end_date<cut-pd.Timedelta(days=20))&f.target.ne(0)]
            te=f[(f.date>=cut)&(f.end_date<pd.Timestamp(year+1,1,1)-pd.Timedelta(days=20))].iloc[::6];te=te[te.target.ne(0)]
            if len(tr)<250 or len(te)<20:continue
            y=tr.target.gt(0);truth=te.target.gt(0).to_numpy();base=fit(tr[state],y);bp=base.predict(te[state]);ba=bp==truth
            for shock in SHOCKS:
                cols=state+[shock];m=fit(tr[cols],y);pred=m.predict(te[cols]);ok=pred==truth;threshold=tr[shock].abs().quantile(.75);event=te[shock].abs().to_numpy()>=threshold
                coef=float(m[-1].coef_[0,-1]);folds.append(dict(asset=asset,shock=shock,year=year,train_end=str(tr.end_date.max()),coefficient=coef,event_n=int(event.sum()),gain=float((ok[event].astype(float)-ba[event]).mean()) if event.any() else None))
                rows.extend(dict(asset=asset,shock=shock,date=str(t),year=year,actual_up=bool(a),shock_up=bool(p),state_up=bool(b),event=bool(e),correct=bool(o),state_correct=bool(c)) for t,a,p,b,e,o,c in zip(te.date,truth,pred,bp,event,ok,ba))
        print(asset,flush=True)
    r=pd.DataFrame(rows);r.to_parquet(OUT/'selection_predictions.parquet',index=False);fs=pd.DataFrame(folds);fs.to_csv(OUT/'selection_folds.csv',index=False)
    scores=[]
    for (asset,shock),z in r[r.event].groupby(['asset','shock']):
        f=fs[(fs.asset==asset)&(fs.shock==shock)];gain=z.correct.mean()-z.state_correct.mean();acc=z.correct.mean();stable=len(f)==3 and (np.sign(f.coefficient)==np.sign(f.coefficient.iloc[0])).all();positive=int(f.gain.gt(0).sum());passed=len(z)>=45 and acc>=.6 and gain>=.03 and positive>=2 and stable
        scores.append(dict(asset=asset,name=names[asset],shock=shock,n=len(z),accuracy=acc,state_accuracy=z.state_correct.mean(),gain=gain,positive_years=positive,stable_sign=stable,direction='positive' if f.coefficient.mean()>0 else 'negative',passed=passed,score=acc-.5+gain))
    s=pd.DataFrame(scores).sort_values(['passed','score','asset','shock'],ascending=[False,False,True,True]);s.to_csv(OUT/'all_pairs.csv',index=False)
    chosen=s.drop_duplicates('asset').head(6);chosen.to_csv(OUT/'selected_pairs.csv',index=False);(OUT/'selected_assets.json').write_text(json.dumps(chosen.asset.tolist(),indent=2))
    print(chosen.to_string(index=False))
if __name__=='__main__':main()
