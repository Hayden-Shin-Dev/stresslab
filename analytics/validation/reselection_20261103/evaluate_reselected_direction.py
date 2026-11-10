"""Frozen post-selection evaluation, observed shocks not causal effects."""
import json
import numpy as np
import pandas as pd
from asset_feature_research import ROOT,EXPANDED,SHOCKS,make_data,model
from select_exposure_universe import assemble
from reselect_shock_direction import OUT,fit

def main():
    status=json.loads((OUT/'collection_progress.json').read_text());assert status['status']=='complete' and not status['failed']
    sel=pd.read_csv(OUT/'selected_pairs.csv',dtype={'asset':str});old=pd.read_csv(ROOT/'reports/exposure_universe_20261103/selected_asset_shock_pairs.csv',dtype={'asset':str})
    pairs=pd.concat([sel[['asset','name','shock']],old[['asset','name','shock']]]).drop_duplicates('asset');new=set(sel.asset)
    g,quality=assemble(pairs.asset.tolist());quality.to_csv(OUT/'source_quality.csv',index=False);g.to_parquet(OUT/'research_daily_input.parquet',index=False)
    d,_=make_data(g);d=d[d.asset.isin(pairs.asset)];d.to_parquet(OUT/'learning_table.parquet',index=False)
    state=[c for c in EXPANDED if c not in SHOCKS];rows=[];audits=[];scenarios=[]
    for _,pair in pairs.iterrows():
        f=d[d.asset.eq(pair.asset)].sort_values('date')
        for year in range(2023,2027):
            tr=f[f.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)]
            te=f[(f.date>=pd.Timestamp(year,1,1))&(f.date<pd.Timestamp(year+1,1,1))].iloc[::6];te=te[te.end_date<pd.Timestamp(year+1,1,1)]
            assert tr.end_date.max()<te.date.min()
            nz=tr[tr.target.ne(0)];y=nz.target.gt(0);neg=nz.loc[~y,'target'].median();pos=nz.loc[y,'target'].median()
            threshold=tr[pair.shock].abs().quantile(.75);event=te[pair.shock].abs().to_numpy()>=threshold
            predictions={};scores={}
            for label,cols in [('state',state),('all4',EXPANDED),('focused',state+[pair.shock])]:
                m=fit(nz[cols],y);p=m.predict_proba(te[cols])[:,1]
                predictions[label+'_direction_route']=np.where(p>=.5,pos,neg);scores[label+'_direction_route']=p
                if label=='focused':
                    # Model attribution diagnostics, same pre-state. No financial causal claim.
                    for value in [-2,-1,0,1,2]:
                        alt=te[cols].copy();alt[pair.shock]=value*tr[pair.shock].std();pp=m.predict_proba(alt)[:,1]
                        scenarios.extend(dict(asset=pair.asset,date=str(t),shock=pair.shock,shock_value=float(value*tr[pair.shock].std()),up_score=float(prob),conditional_score_weighted_return=float(prob*pos+(1-prob)*neg)) for t,prob in zip(te.date,pp))
                    predictions['focused_score_mix']=p*pos+(1-p)*neg
            for label,cols in [('state_lgb',state),('all4_lgb',EXPANDED)]:
                m=model('lgb').fit(tr[cols],tr.target/tr.scale);predictions[label]=m.predict(te[cols])*te.scale.to_numpy()
            for label,p in predictions.items():
                for i,(_,t) in enumerate(te.iterrows()):rows.append(dict(asset=pair.asset,name=pair['name'],selected=pair.asset in new,shock=pair.shock,date=t.date,end_date=t.end_date,method=label,actual=t.target,center=p[i],event=bool(event[i]),up_score=float(scores[label][i]) if label in scores else None))
            audits.append(dict(asset=pair.asset,year=year,train_label_end=str(tr.end_date.max()),test_start=str(te.date.min()),train_n=len(tr),test_n=len(te),event_threshold=threshold,negative_median=neg,positive_median=pos))
            print(pair.asset,year,flush=True)
    r=pd.DataFrame(rows);r.to_parquet(OUT/'predictions.parquet',index=False);pd.DataFrame(audits).to_csv(OUT/'time_audit.csv',index=False);pd.DataFrame(scenarios).to_csv(OUT/'shock_sweep.csv',index=False)
    metrics=[]
    groups=[('selected6',r[r.selected]),('original6',r[r.asset.isin(old.asset)]),*list(r.groupby('asset'))]
    for group,x in groups:
        for name,z in x.groupby('method'):
            for scope,q in [('all',z),('selected_shock_events',z[z.event])]:
                nonzero=q.actual.ne(0);up=q.actual>0;dn=q.actual<0;cr=q.actual<=-5;ra=q.actual>=5;cp=q.center<=-5;rp=q.center>=5
                metrics.append(dict(group=group,method=name,scope=scope,n=len(q),direction_n=int(nonzero.sum()),direction_accuracy=(np.sign(q.loc[nonzero,'actual'])==np.sign(q.loc[nonzero,'center'])).mean(),balanced_accuracy=.5*((q.loc[up,'center']>0).mean()+(q.loc[dn,'center']<0).mean()),mae=(q.actual-q.center).abs().mean(),fixed5_coverage=((q.actual-q.center).abs()<=2.5).mean(),crash_mae=(q.loc[cr,'actual']-q.loc[cr,'center']).abs().mean(),rally_mae=(q.loc[ra,'actual']-q.loc[ra,'center']).abs().mean(),crash_n=int(cr.sum()),crash_tp=int((cr&cp).sum()),crash_false=int((cp&~cr).sum()),rally_n=int(ra.sum()),rally_tp=int((ra&rp).sum()),rally_false=int((rp&~ra).sum())))
    pd.DataFrame(metrics).to_csv(OUT/'metrics.csv',index=False)
    # Original six baseline models and inputs must reproduce prior results.
    previous=pd.read_parquet(ROOT/'reports/exposure_universe_20261103/predictions.parquet');previous=previous[previous.model.eq('lgb')&previous.spec.eq('all4')]
    q=r[r.method.eq('all4_lgb')&r.asset.isin(old.asset)].merge(previous,on=['asset','date'],suffixes=('_new','_old'),validate='one_to_one');assert len(q)==918 and (q.center_new-q.center_old).abs().max()<1e-8
    assert r.groupby(['asset','date']).size().eq(6).all()
    (OUT/'verification.json').write_text(json.dumps(dict(previous6_exact=True,selection_before2022=True,evaluation_labels_not_in_training=True,main_unchanged=True,azure_unchanged=True,gold_unchanged=True,approved=False),indent=2))
if __name__=='__main__':main()
