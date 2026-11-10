"""Interpretable partial pooling of raw 5-day return sensitivities."""
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from .core import STATE,ASSET,SHOCKS,anchors,market_search

class SensitivityFactor:
    def __init__(self,interactions=False):self.interactions=interactions

    def design(self,d,fit=False):
        x=d[STATE+ASSET+SHOCKS].copy()
        if self.interactions:
            for s in SHOCKS:
                for c in ['market_trend20','market_vol20']:x[s+'__'+c]=d[s]*d[c]
        if fit:
            self.assets=sorted(d.asset.unique());self.columns=list(x);self.scaler=StandardScaler().fit(x)
        z=self.scaler.transform(x);one=np.eye(len(self.assets))[[self.assets.index(a) for a in d.asset]]/np.sqrt(10)
        sh=z[:,[self.columns.index(s) for s in SHOCKS]]
        return np.column_stack([z,one,(one[:,:,None]*sh[:,None,:]).reshape(len(d),-1)])

    def fit(self,d):
        w=1/d.groupby('date').date.transform('size');self.model=Ridge(alpha=300).fit(self.design(d,True),d.target,sample_weight=w/w.mean());return self

    def predict(self,d):return self.model.predict(self.design(d))

    def slopes(self,d):
        zero=d.copy();zero[SHOCKS]=0;base=self.predict(zero);values=[]
        for s in SHOCKS:
            x=zero.copy();x[s]=1;values.append(self.predict(x)-base)
        return np.column_stack(values)

    def slope_parts(self,row,shock):
        j=self.columns.index(shock);s=SHOCKS.index(shock);a=self.assets.index(row.asset)
        common=float(self.model.coef_[j]/self.scaler.scale_[j])
        offset=len(self.columns)+len(self.assets)+a*len(SHOCKS)+s
        deviation=float(self.model.coef_[offset]/np.sqrt(10)/self.scaler.scale_[j])
        state=0.
        if self.interactions:
            for c in ['market_trend20','market_vol20']:
                k=self.columns.index(shock+'__'+c);state+=float(self.model.coef_[k]*row[c]/self.scaler.scale_[k])
        return dict(shared_coefficient=common,asset_deviation=deviation,state_interaction=state)


class SensitivityEngine:
    def fit(self,tr):
        self.global_model=SensitivityFactor().fit(tr);self.state_model=SensitivityFactor(True).fit(tr)
        self.history=anchors(tr).copy();self.iqr=(tr[SHOCKS].quantile(.75)-tr[SHOCKS].quantile(.25)).replace(0,1)
        self.state_iqr=(tr[STATE].quantile(.75)-tr[STATE].quantile(.25)).replace(0,1)
        self.checks=[];end=tr.end_date.max()
        for months in [18,12,6]:
            x=tr[tr.end_date<end-pd.DateOffset(months=months)]
            good=set(x.groupby('asset').size().loc[lambda z:z>=250].index)
            self.checks.append((SensitivityFactor().fit(x[x.asset.isin(good)]),SensitivityFactor(True).fit(x[x.asset.isin(good)])))
        self.train_label_end=end
        return self

    def coefficients(self,q):
        gs=self.global_model.slopes(q);ss=self.state_model.slopes(q);gchecks=[];schecks=[]
        for gm,sm in self.checks:
            eligible=q.asset.isin(gm.assets);g=np.full_like(gs,np.nan);s=np.full_like(ss,np.nan)
            if eligible.any():g[eligible]=gm.slopes(q[eligible]);s[eligible]=sm.slopes(q[eligible])
            gchecks.append(g);schecks.append(s)
        def stability(full,checks):
            v=np.stack(checks+[full]);valid=np.isfinite(v).all(axis=0)
            signs=((v>0).all(axis=0)|(v<0).all(axis=0))&valid
            spread=np.nanstd(v,axis=0)/np.maximum(abs(np.nanmedian(v,axis=0)),1e-8)
            meaningful=abs(full)*self.iqr.to_numpy()>=.1
            return signs&(spread<=.75)&meaningful,spread,v
        gok,gspread,gv=stability(gs,gchecks);sok,sspread,sv=stability(ss,schecks)
        count=[]
        for _,r in q.iterrows():
            h=self.history[self.history.asset.eq(r.asset)]
            count.append(int((((h[STATE]-r[STATE].astype(float))/self.state_iqr).pow(2).mean(axis=1)<=1).sum()))
        use_state=sok&(np.asarray(count)[:,None]>=30)
        beta=np.where(use_state,ss,gs);supported=np.where(use_state,sok,gok)
        return beta,supported,dict(use_state=use_state,state_analogues=np.array(count),global_beta=gs,state_beta=ss,global_spread=gspread,state_spread=sspread,global_fold_beta=gv,state_fold_beta=sv)

    def predict(self,q):
        zero=q.copy();zero[SHOCKS]=0
        beta,_,_=self.coefficients(q)
        return self.global_model.predict(zero)+(beta*q[SHOCKS].to_numpy()).sum(axis=1)


def explain(bundle,positions,shocks):
    if set(shocks)-set(SHOCKS):raise ValueError('Unknown shock')
    sh={s:float(shocks.get(s,0)) for s in SHOCKS}
    if not np.isfinite(list(sh.values())).all() or sh['fx_pct']<=-100 or sh['wti_pct']<=-100:raise ValueError('Invalid shock')
    if not positions or len({p['asset_id'] for p in positions})!=len(positions):raise ValueError('Unique positions required')
    engine=bundle['engine'];snap=bundle['snapshot'];results=[]
    candidates=market_search(engine.history,snap.iloc[0]);portfolio_contributions={s:0. for s in SHOCKS}
    for p in positions:
        asset=p['asset_id'];value=float(p['value_krw'])
        if not np.isfinite(value) or value<=0:raise ValueError('Positive finite holding required')
        q=snap[snap.asset.eq(asset)].copy()
        if len(q)!=1:raise ValueError('Asset unavailable at snapshot')
        if q.vix_level.iloc[0]+sh['vix_points']<0:raise ValueError('Negative VIX level')
        q[SHOCKS]=0;base=float(engine.global_model.predict(q)[0]);beta,stable,detail=engine.coefficients(q)
        contributions={s:float(beta[0,j]*sh[s]) for j,s in enumerate(SHOCKS)}
        center=base+sum(contributions.values());q[SHOCKS]=[sh[s] for s in SHOCKS]
        np.testing.assert_allclose(center,engine.predict(q)[0],atol=1e-8)
        hist=engine.history[engine.history.asset.eq(asset)]
        joint=((hist[SHOCKS]-pd.Series(sh))/engine.iqr).abs().max(axis=1)<=1
        state=((hist[STATE]-q.iloc[0][STATE].astype(float))/engine.state_iqr).pow(2).mean(axis=1)<=1
        joint_n=int((joint&state).sum());flags=[];sens={}
        for j,s in enumerate(SHOCKS):
            outside=not hist[s].min()<=sh[s]<=hist[s].max()
            if sh[s]!=0 and (not stable[0,j] or outside):flags.append(s)
            sens[s]=dict(coefficient_pp_per_unit=float(beta[0,j]),stable_by_training_rule=bool(stable[0,j]),coefficient_source='state_interaction' if detail['use_state'][0,j] else 'global_partial_pool',outside_observed_range=bool(outside),training_range=[float(hist[s].min()),float(hist[s].max())],rolling_coefficients=[float(v) if np.isfinite(v) else None for v in (detail['state_fold_beta'] if detail['use_state'][0,j] else detail['global_fold_beta'])[:,0,j]])
            chosen=engine.state_model if detail['use_state'][0,j] else engine.global_model
            parts=chosen.slope_parts(q.iloc[0],s)
            np.testing.assert_allclose(sum(parts.values()),beta[0,j],atol=1e-8)
            sens[s]['coefficient_components']=parts
            portfolio_contributions[s]+=contributions[s]*value/100
        limited=bool(flags)
        status='limited_evidence' if limited else ('assumption_dependent' if any(sh.values()) and joint_n<15 else 'research_sensitivity_supported')
        evidence=hist[hist.date.isin(candidates.date)].copy();evidence['distance']=((evidence[SHOCKS]-pd.Series(sh))/engine.iqr).pow(2).mean(axis=1)
        examples=[dict(date=str(r.date.date()),observed_shocks={s:float(getattr(r,s)) for s in SHOCKS},actual_return_pct=float(r.target),replay_pnl_krw=float(r.target*value/100)) for r in evidence.sort_values('distance').head(5).itertuples()]
        results.append(dict(asset_id=asset,holding_krw=value,baseline_model_return_pct=base,model_return_pct=None if limited else center,exploratory_model_return_pct=center,change_from_baseline_pp=center-base,contributions_pp=contributions,sensitivities=sens,hypothetical_pnl_krw=None if limited else center*value/100,exploratory_pnl_krw=center*value/100,status=status,unstable_or_outside_shocks=flags,joint_state_shock_history_n=joint_n,validation=bundle['validation'].get(asset),historical_examples=examples))
    return dict(version=bundle['version'],state_date=str(snap.date.iloc[0].date()),horizon_trading_days=5,shocks=sh,market_candidates=[str(x.date()) for x in candidates.date],assets=results,portfolio_hypothetical_pnl_krw=None if any(r['status']=='limited_evidence' for r in results) else sum(r['hypothetical_pnl_krw'] for r in results),exploratory_portfolio_pnl_krw=sum(r['exploratory_pnl_krw'] for r in results),shock_contributions_krw=portfolio_contributions,production_approved=False,publication_verified=False,interpretation='Conditional statistical scenario, not causal effect or guaranteed future return. Zero shocks mean unchanged levels. Unstable numeric outputs are exploratory only.')
