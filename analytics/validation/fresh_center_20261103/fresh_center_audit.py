"""Predeclared centre freshness ablations; no probability bands or deployment."""
import json,hashlib
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from asset_feature_research import ROOT,EXPANDED,SHOCKS,model
from reselect_shock_direction import fit
SRC=ROOT/'reports/reselection_20261103';OUT=ROOT/'reports/fresh_center_20261103'

def main():
    OUT.mkdir(exist_ok=True)
    assets=json.loads((SRC/'selected_assets.json').read_text());d=pd.read_parquet(SRC/'learning_table.parquet');base=pd.read_parquet(SRC/'predictions.parquet');base=base[base.selected&base.method.eq('all4_lgb')]
    gold=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet'
    raw=pd.read_parquet(SRC/'research_daily_input.parquet');oil=raw.groupby('trading_date').wti.first().sort_index();bad=set(pd.to_datetime(oil.index[oil.le(0).rolling(6).max().shift(-5).eq(1)]))
    protocol=dict(assets=assets,selection='Frozen prior study; no reselection using current evaluation',evaluation='Same918rows 2023-2026; reused development walk-forward, not blind',primary='Direction excluding true zero returns; asset return MAE; fixed5pp coverage diagnostic',train_boundary='label_end < fit_time -20calendar days',oil='training rows whose 6-date WTI observation span contains nonpositive price removed for corrected paths only; evaluation rows never removed',methods=['old_stale','fresh_annual','fresh_quarter','clean_quarter','clean_recent8','clean_recent8_raw','clean_recent8_state','clean_recent8_direction'],features='Same27 features; direction classifier standardized logistic C.1. No future market return or intraday feature substitution.',no_parameter_search=True,no_interval_widening=True,gold_sha256=hashlib.sha256(gold.read_bytes()).hexdigest(),production=False)
    (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2))
    rows=[];audits=[]
    for asset in assets:
        f=d[d.asset.eq(asset)].sort_values('date');b=base[base.asset.eq(asset)].sort_values('date')
        for name in protocol['methods']:
            if name=='old_stale':
                z=b.copy();z['method']=name;rows.extend(z.to_dict('records'));continue
            annual=name=='fresh_annual';periods=b.date.dt.to_period('Y' if annual else 'Q')
            for period,zz in b.groupby(periods):
                cut=period.start_time;tr=f[f.end_date<cut-pd.Timedelta(days=20)].copy();before=len(tr)
                if name.startswith('clean'):tr=tr[~tr.date.isin(bad)]
                if 'recent8' in name:tr=tr[tr.date>=cut-pd.DateOffset(years=8)]
                te=f.set_index('date').loc[zz.date].reset_index();assert tr.end_date.max()<te.date.min()
                cols=[c for c in EXPANDED if c not in SHOCKS] if name.endswith('_state') else EXPANDED
                if name.endswith('_direction'):
                    nz=tr[tr.target.ne(0)];m=fit(nz[cols],nz.target.gt(0));p=m.predict_proba(te[cols])[:,1];pred=np.where(p>=.5,nz.loc[nz.target>0,'target'].median(),nz.loc[nz.target<0,'target'].median())
                else:
                    m=model('lgb');normalized=not name.endswith('_raw');m.fit(tr[cols],tr.target/tr.scale if normalized else tr.target);pred=m.predict(te[cols])*(te.scale.to_numpy() if normalized else 1)
                z=zz.copy();z['method']=name;z['center']=pred;rows.extend(z.to_dict('records'))
                audits.append(dict(asset=asset,method=name,fit_time=str(cut),test_start=str(te.date.min()),train_label_end=str(tr.end_date.max()),train_n=len(tr),before_filters=before,latest_label_age_days=(te.date.min()-tr.end_date.max()).days))
            print(asset,name,flush=True)
    r=pd.DataFrame(rows);r['mae']=(r.center-r.actual).abs();r['direction_correct']=np.sign(r.center)==np.sign(r.actual);r['fixed5_coverage']=r.mae<=2.5
    r.to_parquet(OUT/'predictions.parquet',index=False);pd.DataFrame(audits).to_csv(OUT/'time_audit.csv',index=False)
    metrics=[]
    for group,x in [('ALL',r),*list(r.groupby('asset'))]:
        for name,z in x.groupby('method'):
            for scope,q in [('all',z),('shock_events',z[z.event]),('crash',z[z.actual<=-5]),('rally',z[z.actual>=5])]:
                nz=q[q.actual.ne(0)]
                metrics.append(dict(asset=group,method=name,scope=scope,n=len(q),direction_n=len(nz),direction_accuracy=nz.direction_correct.mean(),always_down=nz.actual.lt(0).mean(),mae=q.mae.mean(),fixed5_coverage=q.fixed5_coverage.mean(),crash_called=int(q.center.le(-5).sum()),rally_called=int(q.center.ge(5).sum())))
    pd.DataFrame(metrics).to_csv(OUT/'metrics.csv',index=False)
    assert len(r)==918*8 and not r.duplicated(['asset','date','method']).any()
    assert r.groupby(['asset','date']).actual.nunique().eq(1).all()
    assert hashlib.sha256(gold.read_bytes()).hexdigest()==protocol['gold_sha256']
    (OUT/'verification.json').write_text(json.dumps(dict(same918=True,all_labels_end_before_fit=True,gold_unchanged=True,operating_model_unchanged=True,approved=False),indent=2))
if __name__=='__main__':main()
