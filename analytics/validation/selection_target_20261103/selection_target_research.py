"""Frozen train-only selection and market-excess target experiment. Local only."""
import json,hashlib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from asset_feature_research import ROOT,FEATURES,EXPANDED,SHOCKS,A_STATE,model,record
from adaptive_residual_benchmark import weighted_q

OUT=ROOT/'reports/selection_target_20261103'
MARKET_FEATURES=A_STATE+SHOCKS

def sensitivity(tr,asset,year):
    # Disjoint outcomes for selection diagnostics; realized market return is a
    # retrospective control here, NEVER an inference input for stress models.
    h=tr.sort_values('date').iloc[::6].copy()
    cols=SHOCKS+['market_target']+A_STATE
    sx=StandardScaler().fit(h[cols]);x=sx.transform(h[cols]);y=h.target.to_numpy()
    design=np.column_stack([np.ones(len(x)),x]);beta=np.linalg.lstsq(design,y,rcond=None)[0][1:]
    chunks=[]
    for ids in np.array_split(np.arange(len(h)),3):
        if len(ids)<50:continue
        chunks.append(np.linalg.lstsq(design[ids],y[ids],rcond=None)[0][1:])
    rows=[]
    for j,shock in enumerate(SHOCKS):
        others=np.delete(x,j,axis=1);control=np.column_stack([np.ones(len(x)),others])
        ry=y-control@np.linalg.lstsq(control,y,rcond=None)[0]
        rx=x[:,j]-control@np.linalg.lstsq(control,x[:,j],rcond=None)[0]
        event=np.abs(rx)>=np.quantile(np.abs(rx),.8)
        agree=float(np.mean(np.sign(ry[event]*rx[event])==np.sign(beta[j])))
        stable=float(np.mean([np.sign(b[j])==np.sign(beta[j]) for b in chunks])) if chunks else 0.
        effect=abs(beta[j])/max(float(np.std(y)),1e-8)
        rows.append(dict(asset=asset,year=year,shock=shock,n=len(h),event_n=int(event.sum()),
            train_label_end=str(tr.end_date.max()),correlation=h[shock].corr(h.target),
            coefficient_per_unit=beta[j]/sx.scale_[j],standardized_coefficient=beta[j],
            coefficient_early=chunks[0][j]/sx.scale_[j] if chunks else np.nan,
            coefficient_middle=chunks[1][j]/sx.scale_[j] if chunks else np.nan,
            coefficient_late=chunks[2][j]/sx.scale_[j] if chunks else np.nan,
            period_sign_agreement=stable,controlled_event_direction_agreement=agree,
            score=effect*stable*max(2*agree-1,0)))
    return rows

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    path=ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet'
    gold=pd.read_parquet(path);d=pd.read_parquet(ROOT/'reports/model_redesign_20261103/learning_table.parquet')
    price=gold.groupby('trading_date').kospi_close.first().sort_index()
    mt=(price.shift(-5)/price-1)*100;mt.index=pd.to_datetime(mt.index)
    d['market_target']=d.date.map(mt);assert d.market_target.notna().all()
    # Same date must have identical market inputs; asset state never enters market model.
    spread=d.groupby('date')[MARKET_FEATURES+['market_target']].max()-d.groupby('date')[MARKET_FEATURES+['market_target']].min()
    assert spread.max().max()<1e-9  # rolling floating point roundoff across listings
    market=d.sort_values(['date','asset']).drop_duplicates('date').copy()
    market['market_scale']=np.sqrt((market.market_vol20**2+market.market_vol60**2)/2*5).clip(lower=.1)
    protocol={'gold_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
      'target':'total_return or total_return-minus-realized_KOSPI_return over identical5day interval',
      'restore':'predicted_excess_return + predicted_KOSPI_return; no future market return input',
      'selection':'top8 by max of4 train-only conditional sensitivity scores; fixed rule, no evaluation outcomes; score=abs standardized coefficient/targetSD *3period signagreement *max(2*controlled_event_direction_agreement-1,0)',
      'selection_control':'OLS realized market return plus4shocks plus pre-shock market state, disjoint6row sample; descriptive associations, not causal',
      'interval':'per-asset5year vintage OOS errors of full restored prediction, normalized by asset scale',
      'split':'identical previous annual2018-2026 fitting, evaluated2023-2026;20calendar day label embargo, perasset6row spaced eval',
      'models':'original perasset Ridge FEATURES and LightGBM EXPANDED; fixed existing hyperparameters; separate market models on unique dates',
      'selection_effect':'independent fits unchanged by selected universe; experiment3/4 subset1/2, not algorithm improvement',
      'blind':False,'point_in_time_publications_certified':False,'cloud_changed':False,'gold_contract_changed':False}
    (OUT/'protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf8')
    banks={};rows=[];sens=[];selections=[];folds=[];marketrows=[];diagnostics=[]
    for year in range(2018,2027):
        cut=pd.Timestamp(year,1,1);cc=pd.Timestamp(year-1,1,1);traincut=cc-pd.Timedelta(days=20)
        mtr=market[market.end_date<traincut];marketmodels={}
        for kind in ['ridge','lgb']:
            mm=model(kind).fit(mtr[MARKET_FEATURES],mtr.market_target/mtr.market_scale)
            marketmodels[kind]=mm
        annual={};annualsens=[]
        for asset,f in d.groupby('asset'):
            f=f.sort_values('date');tr=f[f.end_date<traincut]
            ca=f[(f.date>=cc)&(f.end_date<cut-pd.Timedelta(days=20))].iloc[::6]
            te=f[(f.date>=cut)&(f.date<pd.Timestamp(year+1,1,1))].iloc[::6];te=te[te.end_date<pd.Timestamp(year+1,1,1)]
            if len(tr)<250 or len(ca)<30:continue
            annual[asset]=(tr,ca,te)
            if year>=2023:annualsens.extend(sensitivity(tr,asset,year))
        selected=set()
        if annualsens:
            ss=pd.DataFrame(annualsens);rank=ss.groupby('asset').score.max().sort_values(ascending=False,kind='stable');selected=set(rank.head(8).index)
            for i,(asset,score) in enumerate(rank.items()):selections.append(dict(year=year,asset=asset,score=score,rank=i+1,selected=asset in selected,selection_before=str(traincut)))
            sens.extend(annualsens)
        for asset,(tr,ca,te) in annual.items():
            assert tr.end_date.max()<ca.date.min()
            high=tr.market_vol20.quantile(2/3)
            for kind in ['ridge','lgb']:
                features=FEATURES if kind=='ridge' else EXPANDED
                for target in ['total','excess']:
                    label=kind+'_'+target;key=(asset,label)
                    y=tr.target if target=='total' else tr.target-tr.market_target
                    fitted=model(kind).fit(tr[features],y/tr.scale)
                    def predict(z):
                        base=fitted.predict(z[features])*z.scale.to_numpy()
                        mscale=np.sqrt((z.market_vol20**2+z.market_vol60**2)/2*5).clip(lower=.1)
                        mp=marketmodels[kind].predict(z[MARKET_FEATURES])*mscale.to_numpy()
                        return (base if target=='total' else base+mp),base,mp
                    cp,_,_=predict(ca);bank=ca[['date','end_date']].copy();bank['residual']=(ca.target.to_numpy()-cp)/ca.scale.to_numpy();bank['ready']=bank.end_date+pd.Timedelta(days=20);banks.setdefault(key,[]).append(bank)
                    if year<2023 or not len(te):continue
                    pool=pd.concat(banks[key],ignore_index=True).sort_values('date');pool=pool[(pool.date>=cut-pd.DateOffset(years=5))&(pool.ready<cut)]
                    assert pool.ready.max()<te.date.min()
                    for z in [pool,te]:assert (z.end_date.to_numpy()[:-1]<z.date.to_numpy()[1:]).all()
                    pred,component,mp=predict(te);rw=np.ones(len(pool))/len(pool);adj=weighted_q(pool.residual,rw)
                    for i,(_,t) in enumerate(te.iterrows()):
                        row=record(t,pred[i],pred[i]+adj*t.scale,label,high,t.market_target,pool,rw)
                        row.update(year=year,selected=asset in selected,predicted_market=mp[i],actual_market=t.market_target,predicted_component=component[i],target_type=target,model=kind)
                        rows.append(row)
                        if target=='excess':
                            diagnostics.append(dict(asset=asset,date=t.date,model=kind,excess_error=component[i]-(t.target-t.market_target),market_error=mp[i]-t.market_target,restored_error=pred[i]-t.target))
                    folds.append(dict(asset=asset,year=year,method=label,train_n=len(tr),train_end=str(tr.end_date.max()),cal_n=len(pool),test_n=len(te),market_train_n=len(mtr),market_train_end=str(mtr.end_date.max())))
            print(year,asset,flush=True)
        if rows:pd.DataFrame(rows).to_parquet(OUT/'predictions.parquet',index=False)
    r=pd.DataFrame(rows);pd.DataFrame(sens).to_csv(OUT/'sensitivity.csv',index=False);pd.DataFrame(selections).to_csv(OUT/'selections.csv',index=False);pd.DataFrame(folds).to_csv(OUT/'folds.csv',index=False);pd.DataFrame(diagnostics).to_csv(OUT/'error_decomposition.csv',index=False)
    old=pd.read_parquet(ROOT/'reports/asset_feature_research_20261103/predictions.parquet')
    for a,b in [('ridge_total','ridge_old_residual'),('lgb_total','lgb_expanded_residual')]:
        chk=r[r.method==a].merge(old[old.method==b],on=['asset','date'],suffixes=('_new','_old'),validate='one_to_one')
        assert len(chk)==len(r[r.method==a])==len(old[old.method==b])
        assert np.max(np.abs(chk.center_new-chk.center_old))<1e-8
        assert np.max(np.abs(chk.q10_new-chk.q10_old))<1e-8
    assert np.max(np.abs(pd.DataFrame(diagnostics).restored_error-(pd.DataFrame(diagnostics).excess_error+pd.DataFrame(diagnostics).market_error)))<1e-8
    (OUT/'verification.json').write_text(json.dumps({'existing_models_exactly_reproduced':True,'same_evaluation_pairs':True,'selection_train_only':True,'future_market_not_input':True,'restoration_identity':True,'production_approved':False},indent=2))

if __name__=='__main__':main()
