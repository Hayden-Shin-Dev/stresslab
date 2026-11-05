"""Frozen economic candidate expansion. Local official KRX cache only."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np,pandas as pd,joblib
from threadpoolctl import threadpool_limits
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from .core import features,anchors,STATE,ASSET,SHOCKS,validate,metrics
from .sensitivity_model import SensitivityFactor
from .release_core import GlobalOnlyEngine

class ExpansionEngine(GlobalOnlyEngine):
    def fit(self,tr):
        self.global_model=SensitivityFactor().fit(tr);self.state_model=self.global_model
        self.history=anchors(tr).copy();self.iqr=(tr[SHOCKS].quantile(.75)-tr[SHOCKS].quantile(.25)).replace(0,1)
        self.state_iqr=(tr[STATE].quantile(.75)-tr[STATE].quantile(.25)).replace(0,1)
        self.checks=[];end=tr.end_date.max()
        for months in [18,12,6]:
            x=tr[tr.end_date<end-pd.DateOffset(months=months)]
            good=set(x.groupby('asset').size().loc[lambda z:z>=250].index)
            m=SensitivityFactor().fit(x[x.asset.isin(good)]);self.checks.append((m,m))
        self.train_label_end=end;return self

class Nuisance:
    def fit(self,d,cols,y):
        self.cols=cols;self.assets=sorted(d.asset.unique());self.sc=StandardScaler().fit(d[cols])
        self.m=Ridge(alpha=300).fit(self.x(d),y);return self
    def x(self,d):
        ids=pd.Categorical(d.asset,categories=self.assets).codes
        if (ids<0).any():raise ValueError('Unseen asset')
        return np.column_stack([self.sc.transform(d[self.cols]),np.eye(len(self.assets))[ids]/np.sqrt(10)])
    def predict(self,d):return self.m.predict(self.x(d))

def prepare(root,out,rule):
    original=pd.read_parquet(root/'reports/state_link_26_20261104/research_input.parquet')
    original['trading_date']=pd.to_datetime(original.trading_date);template=original[original.asset_id.eq('005930')].copy()
    sectors={a:k for k,v in rule['groups'].items() for a in v};parts=[original[original.asset_id.isin(sectors)].copy()];quality=[];hashes=[]
    source=root/'data/research/exposure_universe_20261103/stocks'
    for a in sectors:
        if a in set(original.asset_id):continue
        records=[];files=sorted((source/a).glob('*.json'))
        for f in files:records.extend(json.loads(f.read_text(encoding='utf8')));hashes.append(dict(file=str(f.relative_to(root)),sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
        if not records:quality.append(dict(asset=a,raw_rows=0,missing=True));continue
        z=pd.DataFrame(records);z['trading_date']=pd.to_datetime(z.TRD_DD)
        assert not z.trading_date.duplicated().any();z=z.sort_values('trading_date')
        def number(s):return pd.to_numeric(s.astype(str).str.replace(',',''),errors='coerce')
        z['close']=number(z.TDD_CLSPRC);z['volume']=number(z.ACC_TRDVOL)
        z['bad']=(z.close.pct_change(fill_method=None)*100-number(z.FLUC_RT)).abs()>(.011+200/z.close.shift(1))
        x=template.drop(columns=['close','volume']).merge(z[['trading_date','close','volume','bad']],on='trading_date',how='left',validate='one_to_one')
        x['asset_id']=a;x['source_ref']='KRX_official_cache_expansion';x['adjustment_version']='KRX_reference20261030'
        x['quality_status']=np.where(x.close.isna(),'missing',np.where(x.bad.eq(True)|x.volume.le(0)|x.close.le(0),'quarantined','valid'))
        parts.append(x[original.columns]);quality.append(dict(asset=a,raw_rows=len(z),first=str(z.trading_date.min()),last=str(z.trading_date.max()),quarantined=int(z.bad.sum()),zero_volume=int(z.volume.eq(0).sum()),missing=False))
    g=pd.concat(parts,ignore_index=True);g['sector_id']=g.asset_id.map(sectors);g['dataset_version']='official-expansion73-local-20261104'
    audit=validate(g,True);g.to_parquet(out/'research_input.parquet',index=False)
    pd.DataFrame(quality).to_csv(out/'source_quality.csv',index=False)
    (out/'source_manifest.json').write_text(json.dumps(dict(reused_26=str(root/'reports/state_link_26_20261104/research_input.parquet'),raw_files=hashes,official_hosts=['data.krx.co.kr'],new_download_required=False,reason='Existing official cache covers requested candidate histories; prelisting absence is not missing history'),indent=2),encoding='utf8')
    (out/'input_audit.json').write_text(json.dumps(audit,indent=2),encoding='utf8');return g,sectors

def run(root,out):
    root=Path(root);out=Path(out);out.mkdir(parents=True,exist_ok=True)
    rule=json.loads(Path(__file__).with_name('expansion_protocol.json').read_text(encoding='utf8'))
    (out/'frozen_protocol.json').write_text(json.dumps(rule,indent=2),encoding='utf8')
    old=joblib.load(root/'reports/selected_service_20261104/candidate_bundle.joblib');primary=old['support']
    g,sectors=prepare(root,out,rule);f=features(g);d=f.dropna(subset=SHOCKS+['target','end_date']).copy();d['sector']=d.asset.map(sectors)
    tr=d[d.end_date<pd.Timestamp(rule['selection_label_before'])].copy();quality=[];eligible=[]
    for a,z in g[g.trading_date.lt(rule['selection_label_before'])].groupby('asset_id'):
        observed=z[z.close.gt(0)&z.volume.gt(0)];years=(observed.trading_date.max()-observed.trading_date.min()).days/365.25
        fraction=z.sort_values('trading_date').tail(252).quality_status.eq('valid').mean();n=len(anchors(tr)[lambda x:x.asset.eq(a)])
        ok=years>=5 and fraction>=.95 and n>=100
        quality.append(dict(asset=a,years=years,recent_valid_fraction=fraction,disjoint_windows=n,eligible=ok,sector=sectors[a]))
        if ok:eligible.append(a)
    pd.DataFrame(quality).to_csv(out/'training_quality.csv',index=False)
    tr=tr[tr.asset.isin(eligible)];print('eligible training assets',len(eligible),'rows',len(tr),flush=True)
    engine=ExpansionEngine().fit(tr);probe=tr.sort_values('date').groupby('asset').tail(1);b,ok,det=engine.coefficients(probe);rows=[];support={}
    for i,r in enumerate(probe.itertuples()):
        for j,s in enumerate(SHOCKS):
            permitted=s in rule['economic_hypotheses'][sectors[r.asset]];passed=bool(ok[i,j] and permitted)
            rows.append(dict(asset=r.asset,sector=sectors[r.asset],shock=s,economic_hypothesis=permitted,stable=bool(ok[i,j]),coefficient=b[i,j],coefficient_cv=det['global_spread'][i,j],selected=passed,prior_primary=r.asset in primary))
            if passed:support.setdefault(r.asset,[]).append(s)
    pd.DataFrame(rows).to_csv(out/'training_selection.csv',index=False)
    # Keep every existing primary pair on its unchanged model; additions are training-selected.
    additions={a:s for a,s in support.items() if a not in primary}
    (out/'frozen_additions.json').write_text(json.dumps(additions,indent=2),encoding='utf8')
    from .freeze_expansion_scope import freeze
    freeze(out,root/'reports/selected_service_20261104/active_support.json')
    print('new training-selected assets',len(additions),'preserved',len(primary),flush=True)
    cohort=set(primary)|set(additions);data=d[d.asset.isin(cohort)].copy();outputs=[];diagnostics=[];coefs=[];splits=[]
    for year in [2023,2024,2025,2026]:
        training=data[data.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)]
        cal=anchors(data[(data.date>=pd.Timestamp(year-1,1,1))&(data.end_date<pd.Timestamp(year,1,1)-pd.Timedelta(days=20))])
        test=anchors(data[(data.date>=pd.Timestamp(year,1,1))&(data.date<pd.Timestamp(year+1,1,1))])
        assert training.end_date.max()<cal.date.min() and cal.end_date.max()<test.date.min()
        m=SensitivityFactor().fit(training);state=Nuisance().fit(training,STATE+ASSET,training.target)
        means=anchors(training).groupby(['date','sector']).target.mean().groupby('sector').mean()
        cp=m.predict(cal);tp=m.predict(test);q=np.quantile((cal.target-cp)/cal.scale,[.1,.9])
        for name,pred in [('expanded_factor',tp),('state_only',state.predict(test)),('zero',np.zeros(len(test))),('sector_history_mean',test.sector.map(means).to_numpy())]:
            z=test[['asset','date','sector','target']].rename(columns={'target':'actual'}).copy();z['center']=pred;z['model']=name;z['year']=year
            if name=='expanded_factor':z['lo']=tp+q[0]*test.scale;z['hi']=tp+q[1]*test.scale
            outputs.append(z)
        # Pure shock-conditioned sector baseline: fit on historical rows, never future sector return.
        sectorpred=np.empty(len(test))
        for sec in test.sector.unique():
            a=training[training.sector.eq(sec)];mask=test.sector.eq(sec)
            sm=Ridge(alpha=300);sc=StandardScaler().fit(a[SHOCKS]);sm.fit(sc.transform(a[SHOCKS]),a.target)
            sectorpred[mask]=sm.predict(sc.transform(test.loc[mask,SHOCKS]))
        z=test[['asset','date','sector','target']].rename(columns={'target':'actual'}).copy();z['center']=sectorpred;z['model']='sector_shock_ridge';z['year']=year;outputs.append(z)
        coeff=m.slopes(test);unique=test.groupby('asset').head(1)
        for r,c in zip(unique.itertuples(),m.slopes(unique)):
            for j,s in enumerate(SHOCKS):coefs.append(dict(asset=r.asset,shock=s,year=year,coefficient=c[j]))
        for j,s in enumerate(SHOCKS):
            controls=STATE+ASSET+[k for k in SHOCKS if k!=s]
            nx=Nuisance().fit(training,controls,training[s]);ny=Nuisance().fit(training,controls,training.target)
            rx=test[s].to_numpy()-nx.predict(test);ry=test.target.to_numpy()-ny.predict(test)
            threshold=np.quantile(abs(training[s]-nx.predict(training)),.75)
            zz=test[['asset','date']].copy();zz['shock']=s;zz['year']=year;zz['residual_shock']=rx;zz['residual_return']=ry;zz['model_response']=coeff[:,j]*rx;zz['coefficient']=coeff[:,j];zz['large_residual_shock']=abs(rx)>=threshold
            diagnostics.append(zz)
        splits.append(dict(year=year,train_end=str(training.end_date.max()),cal_end=str(cal.end_date.max()),test_start=str(test.date.min()),test_n=len(test)))
        print('expansion fold complete',year,flush=True)
    p=pd.concat(outputs,ignore_index=True);p.to_parquet(out/'predictions.parquet',index=False)
    pd.concat(diagnostics,ignore_index=True).to_parquet(out/'shock_diagnostics.parquet',index=False);pd.DataFrame(coefs).to_csv(out/'annual_coefficients.csv',index=False)
    (out/'splits.json').write_text(json.dumps(splits,indent=2),encoding='utf8')
    final=ExpansionEngine().fit(data[data.end_date<f.date.max()-pd.Timedelta(days=20)]);snap=f[f.date.eq(f.date.max())&f.asset.isin(cohort)].copy();b,ok,det=final.coefficients(snap);active={};changes=[]
    for i,r in enumerate(snap.itertuples()):
        if r.asset in primary:continue
        pairs=[s for j,s in enumerate(SHOCKS) if s in additions.get(r.asset,[]) and ok[i,j]]
        if pairs:active[r.asset]=pairs
        changes.append(dict(asset=r.asset,frozen=additions.get(r.asset,[]),current=pairs))
    # Importable class is assigned before serialization even when this module ran as __main__.
    from conditional_service.expansion import ExpansionEngine as SavedEngine
    final.__class__=SavedEngine
    audit=validate(g,True);audit.update(production_approved=False,selection_label_before=rule['selection_label_before'])
    newbundle=dict(version='expansion-factor-v1',support_version=rule['protocol_version'],engine=final,snapshot=snap,support=active,selection_reasons={},validation={},audit=audit)
    joblib.dump(dict(primary=old,expanded=newbundle,exploratory=sorted(set(sectors)-set(primary)-set(active)),sectors=sectors),out/'tiered_bundle.joblib')
    (out/'current_additions.json').write_text(json.dumps(active,indent=2),encoding='utf8');(out/'support_changes.json').write_text(json.dumps(changes,indent=2),encoding='utf8')
    print('finished prior/new/currenttotal',len(primary),len(active),len(primary)+len(active),flush=True)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--root',required=True);a.add_argument('--out',required=True);args=a.parse_args()
    with threadpool_limits(limits=2):run(args.root,args.out)
