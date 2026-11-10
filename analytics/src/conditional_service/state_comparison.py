"""Local controlled A-to-B experiment. No production model promotion."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.linear_model import Ridge
from threadpoolctl import threadpool_limits
from .core import Factor, STATE, SHOCKS, features, anchors, metrics, validate, market_search


class StateWeightedFactor:
    """A's shock-free state distance controls soft training and inference weights."""
    def fit(self, d):
        h=d.drop_duplicates('date')
        self.mid=h[STATE].median()
        self.iqr=(h[STATE].quantile(.75)-h[STATE].quantile(.25)).replace(0,1)
        z=(h[STATE]-self.mid)/self.iqr
        self.centers=KMeans(n_clusters=3, random_state=41,n_init=10).fit(z).cluster_centers_
        # Fixed smooth gating, not tuned on the outer evaluation outcomes.
        self.temperature=max(float(np.median(((z.to_numpy()[:,None,:]-self.centers)**2).mean(2).min(1))),.5)
        self.global_model=Factor().fit(d)
        self.local=[]
        base=1/d.groupby('date').date.transform('size').to_numpy()
        gate=self.gates(d)
        for j in range(3):
            m=Factor(); x=m.design(d,True)
            w=base*(.25+.75*gate[:,j]);w=w/w.mean()
            m.model=Ridge(alpha=300).fit(x,d.target/d.scale,sample_weight=w)
            self.local.append(m)
        return self

    def gates(self,d):
        z=((d[STATE]-self.mid)/self.iqr).to_numpy()
        dist=((z[:,None,:]-self.centers)**2).mean(2)
        logits=-dist/self.temperature;logits-=logits.max(1,keepdims=True)
        w=np.exp(logits);return w/w.sum(1,keepdims=True)

    def predict(self,d):
        local=np.column_stack([m.predict(d) for m in self.local])
        return .5*self.global_model.predict(d)+.5*(local*self.gates(d)).sum(1)


def run(gold,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    g=pd.read_parquet(gold);audit=validate(g,True)
    d=features(g).dropna(subset=SHOCKS+['target','end_date'])
    rows=[];splits=[];checks=[]
    for year in [2023,2024,2025,2026]:
        start=pd.Timestamp(year-1,1,1);cut=pd.Timestamp(year,1,1)
        tr=d[d.end_date<start-pd.Timedelta(days=20)]
        ca=anchors(d[(d.date>=start)&(d.end_date<cut-pd.Timedelta(days=20))])
        te=anchors(d[(d.date>=cut)&(d.date<pd.Timestamp(year+1,1,1))])
        eligible=set(tr.groupby('asset').size().loc[lambda x:x>=250].index)&set(ca.asset)&set(te.asset)
        tr,ca,te=[x[x.asset.isin(eligible)].copy() for x in [tr,ca,te]]
        assert tr.end_date.max()<ca.date.min() and ca.end_date.max()<te.date.min()
        linked=StateWeightedFactor().fit(tr)
        change=te.copy();change[SHOCKS]=0
        assert np.allclose(linked.gates(te),linked.gates(change))
        checks.append(dict(year=year,shock_does_not_change_A=True,gate_change_across_dates=float(np.std(linked.gates(te),axis=0).mean())))
        for name,m in [('global_factor',linked.global_model),('A_weighted_factor',linked)]:
            cp=m.predict(ca);p=m.predict(te)
            q=np.quantile((ca.target-cp)/ca.scale,[.1,.9])
            r=te[['asset','date','target']].rename(columns={'target':'actual'}).copy()
            r['center']=p;r['lo']=p+q[0]*te.scale;r['hi']=p+q[1]*te.scale;r['model']=name
            rows.append(r)
        splits.append(dict(year=year,train_label_end=str(tr.end_date.max()),cal_start=str(ca.date.min()),cal_label_end=str(ca.end_date.max()),test_start=str(te.date.min()),test_rows=len(te)))
        print('completed',year,flush=True)
    p=pd.concat(rows);p.to_parquet(out/'predictions.parquet',index=False)
    summary=pd.DataFrame([dict(model=k,**metrics(z)) for k,z in p.groupby('model')]);summary.to_csv(out/'metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,model=k,**metrics(z)) for (a,k),z in p.groupby(['asset','model'])]).to_csv(out/'per_asset.csv',index=False)
    p['error']=abs(p.actual-p.center)
    daily=p.groupby(['date','model']).error.mean().unstack()
    blocks=[v for _,v in daily.groupby(daily.index.to_period('M'))];rng=np.random.default_rng(41);gains=[]
    for _ in range(1000):
        z=pd.concat([blocks[i] for i in rng.integers(0,len(blocks),len(blocks))])
        gains.append(100*(1-z.A_weighted_factor.mean()/z.global_factor.mean()))
    audit.update(splits=splits,checks=checks,mae_gain_pct=100*(1-daily.A_weighted_factor.mean()/daily.global_factor.mean()),gain_95pct=np.quantile(gains,[.025,.975]).tolist(),production_promoted=False,evaluation='Reused development period; realized future shocks supplied retrospectively; publication timestamps unresolved')
    (out/'audit.json').write_text(json.dumps(audit,indent=2),encoding='utf8')
    # Fixed final fold model, last complete common state. These are scenarios, not scored forecasts.
    snap=te[te.date==te.date.max()].copy()
    zero=snap.copy();zero[SHOCKS]=0
    base=linked.predict(zero);scenarios=[]
    for shock,amount in zip(SHOCKS,[5,100,10,10]):
        x=zero.copy();x[shock]=amount
        pred=linked.predict(x)
        for i,asset in enumerate(x.asset):
            scenarios.append(dict(asset=asset,state_date=str(x.date.iloc[i]),shock=shock,amount=amount,
                                  zero_shock_center_pp=float(base[i]),center_pp=float(pred[i]),
                                  change_pp=float(pred[i]-base[i]),
                                  pnl_per_million_krw=float(pred[i]*10000),
                                  interpretation='Model scenario, not observed outcome or causal effect'))
    pd.DataFrame(scenarios).to_csv(out/'scenario_responses.csv',index=False)
    market_search(tr,zero.iloc[0]).to_csv(out/'state_analogues.csv',index=False)
    print(summary.to_string(index=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--gold',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    with threadpool_limits(limits=2):run(a.gold,a.out)
