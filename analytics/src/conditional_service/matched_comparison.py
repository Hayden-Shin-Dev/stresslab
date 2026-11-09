"""Matched shock contrasts and local partial regression. Development research only."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from threadpoolctl import threadpool_limits
from .core import STATE,ASSET,SHOCKS,features,anchors,validate,metrics
from .state_comparison import StateWeightedFactor

COLS=STATE+ASSET+SHOCKS

class MatchedResponse:
    def fit(self,tr,global_model):
        self.model=global_model
        self.mid=tr[COLS].median();self.iqr=(tr[COLS].quantile(.75)-tr[COLS].quantile(.25)).replace(0,1)
        h=anchors(tr).copy();h['global']=global_model.predict(h)
        self.history={a:z.reset_index(drop=True) for a,z in h.groupby('asset')}
        self.arrays={a:((z[COLS]-self.mid)/self.iqr).to_numpy() for a,z in self.history.items()}
        return self

    def predict(self,q,stage,fold):
        base=self.model.predict(q);outputs={k:base.copy() for k in ['matched','local','supported_blend']}
        diagnostics=[];pairs=[]
        query=((q[COLS]-self.mid)/self.iqr).to_numpy()
        for row,(_,r) in enumerate(q.iterrows()):
            h=self.history[r.asset];z=self.arrays[r.asset];v=query[row]
            # A's candidates depend only on pre-shock market state, never on user shocks.
            dist=((z[:,:len(STATE)]-v[:len(STATE)])**2).mean(1)
            ids=np.argsort(dist,kind='stable')[:120]
            a=z[ids];hh=h.iloc[ids];delta=(hh.target-hh['global']).to_numpy()
            state_weights=np.exp(-dist[ids]/max(float(np.median(dist[ids])),.1))
            local=Ridge(alpha=20).fit(a,delta,sample_weight=state_weights/state_weights.mean())
            total_match=0.;total_local=0.;total_blend=0.
            for shock in SHOCKS:
                s=COLS.index(shock);controls=[i for i in range(len(COLS)) if i!=s]
                # Compare shocks conditional on the three others and pre-event state/asset history.
                dc=((a[:,None,controls]-a[None,:,controls])**2).mean(2)**.5
                ds=a[:,s,None]-a[None,:,s]
                others=[COLS.index(x) for x in SHOCKS if x!=shock]
                othermax=abs(a[:,None,others]-a[None,:,others]).max(2)
                mask=np.triu((dc<=.5)&(othermax<=.5)&(abs(ds)>=.5),1)
                ii,jj=np.where(mask)
                proximity=((a[:,controls]-v[controls])**2).mean(1)
                order=np.argsort(dc[ii,jj]+.25*(proximity[ii]+proximity[jj]),kind='stable')
                used=set();selected=[]
                for k in order:
                    i,j=int(ii[k]),int(jj[k])
                    if i not in used and j not in used:
                        selected.append((i,j));used.update([i,j])
                # A partial R2 measures how much target-shock variation remains after controls.
                nuisance=Ridge(alpha=10).fit(a[:,controls],a[:,s],sample_weight=state_weights)
                sr=a[:,s]-nuisance.predict(a[:,controls])
                remaining=float(np.average(sr**2,weights=state_weights)/max(np.average((a[:,s]-np.average(a[:,s],weights=state_weights))**2,weights=state_weights),1e-8))
                ess=float(state_weights.sum()**2/(state_weights**2).sum())
                supported=len(selected)>=15 and remaining>=.2 and ess>=40
                pair_delta=[];pair_y=[];pair_res=[];pw=[]
                for i,j in selected:
                    dt=(a[i,s]-a[j,s])*self.iqr[shock]
                    pair_delta.append(dt);pair_y.append(float(hh.target.iloc[i]-hh.target.iloc[j]));pair_res.append(delta[i]-delta[j])
                    pw.append(float(np.sqrt(state_weights[i]*state_weights[j])/(1+proximity[i]+proximity[j])))
                    if stage=='evaluation':
                        pairs.append(dict(fold=fold,query_date=r.date,asset=r.asset,shock=shock,date_i=hh.date.iloc[i],date_j=hh.date.iloc[j],shock_i=hh[shock].iloc[i],shock_j=hh[shock].iloc[j],return_i=hh.target.iloc[i],return_j=hh.target.iloc[j],control_distance=dc[i,j],other_shock_max_iqr=othermax[i,j],weight=pw[-1]))
                dx=np.array(pair_delta);w=np.array(pw);den=float(np.sum(w*dx**2))
                raw=float(np.sum(w*dx*np.array(pair_y))/den) if den>0 else None
                adjustment=float(np.sum(w*dx*np.array(pair_res))/den) if den>0 else 0.
                ls=float(local.coef_[s]/self.iqr[shock])
                in_range=bool(hh[shock].min()<=r[shock]<=hh[shock].max() and hh[shock].min()<=0<=hh[shock].max())
                use=supported and in_range
                # Transport a conditional slope difference relative to the same global zero-shock reference.
                # This additive transport is an explicit model assumption, not an identified causal effect.
                if use:
                    total_match+=adjustment*r[shock];total_local+=ls*r[shock]
                    total_blend+=min(.5,len(selected)/(len(selected)+30))*adjustment*r[shock]
                diagnostics.append(dict(fold=fold,stage=stage,date=r.date,asset=r.asset,shock=shock,A_candidates=len(ids),matched_pairs=len(selected),effective_state_n=ess,remaining_shock_variance_ratio=remaining,raw_pair_slope=raw,residual_pair_slope=adjustment,local_residual_slope=ls,used=use,range_supported=in_range,shock_min=hh[shock].min(),shock_max=hh[shock].max(),candidate_id_hash=hashlib.sha256(','.join(hh.date.astype(str)).encode()).hexdigest()[:16]))
            outputs['matched'][row]+=total_match;outputs['local'][row]+=total_local;outputs['supported_blend'][row]+=total_blend
        return outputs,diagnostics,pairs


def run(gold,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    g=pd.read_parquet(gold);audit=validate(g,True)
    audit['source_sha256']=hashlib.sha256(Path(gold).read_bytes()).hexdigest()
    d=features(g).dropna(subset=SHOCKS+['target','end_date'])
    rows=[];diagnostics=[];evidence=[];splits=[]
    for year in [2023,2024,2025,2026]:
        start=pd.Timestamp(year-1,1,1);cut=pd.Timestamp(year,1,1)
        tr=d[d.end_date<start-pd.Timedelta(days=20)]
        ca=anchors(d[(d.date>=start)&(d.end_date<cut-pd.Timedelta(days=20))])
        te=anchors(d[(d.date>=cut)&(d.date<pd.Timestamp(year+1,1,1))])
        good=set(tr.groupby('asset').size().loc[lambda x:x>=250].index)&set(ca.asset)&set(te.asset)
        tr,ca,te=[x[x.asset.isin(good)].copy() for x in [tr,ca,te]]
        assert tr.end_date.max()<ca.date.min() and ca.end_date.max()<te.date.min()
        km=StateWeightedFactor().fit(tr);m=MatchedResponse().fit(tr,km.global_model)
        cp,cd,_=m.predict(ca,'calibration',year);pred,td,ev=m.predict(te,'evaluation',year)
        cp.update(global_factor=km.global_model.predict(ca),kmeans=km.predict(ca))
        pred.update(global_factor=km.global_model.predict(te),kmeans=km.predict(te))
        for name in pred:
            quant=np.quantile((ca.target-cp[name])/ca.scale,[.1,.9])
            r=te[['asset','date','target']].rename(columns={'target':'actual'}).copy()
            r['center']=pred[name];r['lo']=pred[name]+quant[0]*te.scale;r['hi']=pred[name]+quant[1]*te.scale;r['model']=name
            rows.append(r)
        diagnostics+=cd+td;evidence+=ev
        splits.append(dict(year=year,train_label_end=str(tr.end_date.max()),cal_start=str(ca.date.min()),cal_label_end=str(ca.end_date.max()),test_start=str(te.date.min())))
        print('completed',year,flush=True)
    p=pd.concat(rows);p.to_parquet(out/'predictions.parquet',index=False)
    diag=pd.DataFrame(diagnostics);diag.to_parquet(out/'diagnostics.parquet',index=False)
    pd.DataFrame(evidence).to_parquet(out/'matched_pairs.parquet',index=False)
    summary=pd.DataFrame([dict(model=k,**metrics(z)) for k,z in p.groupby('model')]);summary.to_csv(out/'metrics.csv',index=False)
    pd.DataFrame([dict(asset=a,model=k,**metrics(z)) for (a,k),z in p.groupby(['asset','model'])]).to_csv(out/'per_asset.csv',index=False)
    diag[diag.stage=='evaluation'].groupby(['asset','shock']).agg(queries=('used','size'),use_fraction=('used','mean'),median_pairs=('matched_pairs','median'),remaining_variance=('remaining_shock_variance_ratio','median'),median_pair_slope=('raw_pair_slope','median'),slope_q10=('raw_pair_slope',lambda x:x.quantile(.1)),slope_q90=('raw_pair_slope',lambda x:x.quantile(.9))).to_csv(out/'support.csv')
    diag[diag.stage=='evaluation'].groupby(['fold','asset','shock']).raw_pair_slope.median().to_csv(out/'fold_slopes.csv')
    extra=[]
    for name,z in p.groupby('model'):
        y=z.actual-z.groupby('date').actual.transform('mean');c=z.center-z.groupby('date').center.transform('mean')
        extra.append(dict(model=name,demeaned_direction=float((np.sign(y)==np.sign(c)).mean()),demeaned_correlation=float(y.corr(c))))
    pd.DataFrame(extra).to_csv(out/'stock_specific.csv',index=False)
    audit.update(splits=splits,production_promoted=False,unobserved_confounders_identified=False,protocol='Fixed 120 A candidates; control RMS <=0.5 IQR, other shocks each <=0.5 IQR, target shock gap >=0.5 IQR; disjoint pairs; >=15 pairs, ESS>=40, residual shock variance >=0.2. All cutoffs prespecified development heuristics. Global fallback otherwise.',evaluation='Reused development evaluation, not independent blind test. Realized future shocks supplied retrospectively.')
    (out/'audit.json').write_text(json.dumps(audit,indent=2),encoding='utf8')
    print(summary.to_string(index=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--gold',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    with threadpool_limits(limits=2):run(a.gold,a.out)
