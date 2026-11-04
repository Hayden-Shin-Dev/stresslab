"""Frozen ranking diagnostic; no new model, selection, cloud or contract changes."""
import argparse,json
from pathlib import Path
import numpy as np
import pandas as pd
from .core import features,anchors,SHOCKS

SECTOR={'000270':'auto','005380':'auto','012330':'auto','000660':'semi','005930':'semi','005935':'semi','009150':'electronics','006400':'battery','373220':'battery','055550':'bank','086790':'bank','105560':'bank','032830':'insurance','012450':'industrial','034020':'industrial','028260':'holding','034730':'holding','402340':'holding','068270':'biopharma','207940':'biopharma','003490':'airline','020560':'airline','010950':'refinery','096770':'refinery','051910':'chemical','011170':'chemical'}

def paired_accuracy(actual,pred):
    i,j=np.triu_indices(len(actual),1);y=np.sign(actual[i]-actual[j]);p=np.sign(pred[i]-pred[j]);valid=y!=0
    if not valid.any():return np.nan
    return float(np.where(p[valid]==0,.5,p[valid]==y[valid]).mean())

def run(gold,evidence,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    data=features(pd.read_parquet(gold)).dropna(subset=SHOCKS+['target','end_date']);data['sector']=data.asset.map(SECTOR)
    dg=pd.read_parquet(Path(evidence)/'diagnostics.parquet');dg=dg[dg.stage.eq('evaluation')]
    base=pd.read_parquet(Path(evidence)/'predictions.parquet');base=base[base.model.eq('global_factor')]
    rows=[];cutoffs=[];full_rows=[]
    for year in [2023,2024,2025,2026]:
        tr=anchors(data[data.end_date<pd.Timestamp(year-1,1,1)-pd.Timedelta(days=20)])
        test=base[base.date.dt.year.eq(year)].merge(data,on=['date','asset'],validate='one_to_one')
        for shock in SHOCKS:
            unique=tr.drop_duplicates('date');low,high=unique[shock].quantile([.2,.8]);cutoffs.append(dict(year=year,shock=shock,low=low,high=high,train_label_end=str(tr.end_date.max())))
            for direction,threshold in [('up',high),('down',low)]:
                hist=tr[tr[shock]>=threshold] if direction=='up' else tr[tr[shock]<=threshold]
                ev=test[test[shock]>=threshold] if direction=='up' else test[test[shock]<=threshold]
                # Absolute sign is required as well as training-tail membership.
                ev=ev[ev[shock]>0] if direction=='up' else ev[ev[shock]<0]
                hist=hist[hist[shock]>0] if direction=='up' else hist[hist[shock]<0]
                sector_mean=hist.groupby(['date','sector']).target.mean().groupby('sector').mean()
                asset_mean=hist.groupby('asset').target.mean()
                z=ev.merge(dg[dg.shock.eq(shock)][['asset','date','raw_pair_slope','used','matched_pairs']],on=['asset','date'],validate='one_to_one')
                z['sector_baseline']=z.sector.map(sector_mean);z['asset_baseline']=z.asset.map(asset_mean)
                z['A_response']=z.raw_pair_slope*z[shock]
                full=z.copy();full['shock']=shock;full['direction']=direction
                full_rows.append(full[['date','asset','actual','sector_baseline','shock','direction','used']])
                # Separate subset: no unsupported A estimates, no fabricated fallback comparisons.
                z=z[z.used&z.sector_baseline.notna()&z.asset_baseline.notna()&z.A_response.notna()].copy()
                z['shock']=shock;z['direction']=direction
                rows.append(z[['date','asset','sector','actual','center','sector_baseline','asset_baseline','A_response','shock','direction','matched_pairs']])
    observations=pd.concat(rows);observations.to_parquet(out/'ranking_observations.parquet',index=False)
    full_pair=[]
    for (shock,direction,date),z in pd.concat(full_rows).groupby(['shock','direction','date']):
        z=z.set_index('asset')
        if {'003490','010950'}<=set(z.index):
            air=float(z.loc['003490','actual']);oil=float(z.loc['010950','actual'])
            sector_difference=float(z.loc['003490','sector_baseline']-z.loc['010950','sector_baseline'])
            full_pair.append(dict(shock=shock,direction=direction,date=date,air_return=air,refinery_return=oil,air_minus_refinery=air-oil,both_negative=air<0 and oil<0,sector_predicted_difference=sector_difference,sector_rank_correct=float(np.sign(sector_difference)==np.sign(air-oil)) if sector_difference!=0 else .5,matched_supported=bool(z.loc['003490','used'] and z.loc['010950','used'])))
    full_frame=pd.DataFrame(full_pair)
    full_frame.to_csv(out/'air_refinery_all_eligible.csv',index=False)
    oil_up=full_frame[full_frame.shock.eq('wti_pct')&full_frame.direction.eq('up')].copy()
    oil_up['year']=pd.to_datetime(oil_up.date).dt.year
    oil_up.groupby('year').agg(n=('date','size'),air_underperformed=('air_minus_refinery',lambda x:int((x<0).sum()))).to_csv(out/'oil_up_by_year.csv')
    oil_up[oil_up.air_minus_refinery>=0].to_csv(out/'oil_up_exceptions.csv',index=False)
    # Descriptive evidence, never a probability forecast or guaranteed hedge.
    insight=dict(type='historical_relative_exposure',assets=['003490','010950'],shock='wti_pct',direction='up',
                 evaluation_dates=len(oil_up),air_underperformed_count=int((oil_up.air_minus_refinery<0).sum()),
                 median_air_minus_refinery_pp=float(oil_up.air_minus_refinery.median()),
                 both_negative_count=int(oil_up.both_negative.sum()),independent_blind=False,
                 future_probability=False,hedge_guaranteed=False,A_superiority_established=False,
                 scope='Two named stocks, not all airline/refinery companies. Observed joint shocks; not isolated oil causality.',
                 wording='과거 유가 상승 평가 구간에서는 대한항공이 S-Oil보다 상대적으로 불리했던 경우가 더 많았습니다. 두 종목이 함께 하락한 사례도 있어 손실 상쇄를 보장하지 않습니다.')
    (out/'service_insight.json').write_text(json.dumps(insight,ensure_ascii=False,indent=2),encoding='utf8')
    dates=[];air=[]
    methods=['A_response','sector_baseline','asset_baseline','center']
    for (shock,direction,date),z in observations.groupby(['shock','direction','date']):
        if len(z)<4:continue
        for method in methods:
            actual=z.actual.to_numpy();pred=z[method].to_numpy();k=max(1,int(np.ceil(len(z)/4)))
            # Fractional tie handling in top risk set avoids asset-order-dependent baseline scores.
            def membership(v):
                boundary=np.sort(v)[k-1];below=v<boundary;equal=v==boundary
                return below.astype(float)+equal*(k-below.sum())/max(equal.sum(),1)
            recall=float(np.dot(membership(actual),membership(pred))/k)
            dates.append(dict(shock=shock,direction=direction,date=date,model=method,assets=len(z),pairs=len(z)*(len(z)-1)//2,pair_accuracy=paired_accuracy(actual,pred),spearman=z.actual.corr(z[method],method='spearman') if z[method].nunique()>1 else np.nan,worst_quartile_recall=recall))
        pair=z.set_index('asset')
        if {'003490','010950'}<=set(pair.index):
            for method in methods:
                y=float(pair.loc['003490','actual']-pair.loc['010950','actual']);p=float(pair.loc['003490',method]-pair.loc['010950',method])
                air.append(dict(shock=shock,direction=direction,date=date,model=method,actual_air_minus_refinery=y,predicted_difference=p,correct=float(np.sign(y)==np.sign(p)) if p!=0 else .5,air_actual=float(pair.loc['003490','actual']),refinery_actual=float(pair.loc['010950','actual'])))
    scores=pd.DataFrame(dates);scores.to_csv(out/'date_scores.csv',index=False);pd.DataFrame(air).to_csv(out/'air_refinery.csv',index=False)
    summary=scores.groupby(['shock','direction','model']).agg(dates=('date','size'),pair_accuracy=('pair_accuracy','mean'),spearman=('spearman','mean'),worst_quartile_recall=('worst_quartile_recall','mean'));summary.to_csv(out/'summary.csv')
    uncertainty=[];rng=np.random.default_rng(41)
    for (shock,direction),z in scores.groupby(['shock','direction']):
        p=z.pivot(index='date',columns='model',values='pair_accuracy');groups=p.groupby(p.index.to_period('M'));s=groups.sum();n=groups.size().to_numpy();draw=rng.integers(0,len(s),size=(2000,len(s)))
        gains=(s.A_response.to_numpy()[draw].sum(1)-s.sector_baseline.to_numpy()[draw].sum(1))/n[draw].sum(1)
        uncertainty.append(dict(shock=shock,direction=direction,dates=len(p),gain_pp=100*(p.A_response-p.sector_baseline).mean(),lower_pp=100*np.quantile(gains,.025),upper_pp=100*np.quantile(gains,.975)))
    pd.DataFrame(uncertainty).to_csv(out/'ranking_uncertainty.csv',index=False)
    pd.DataFrame(cutoffs).to_csv(out/'training_cutoffs.csv',index=False)
    (out/'protocol.json').write_text(json.dumps(dict(independent_blind=False,period='2023-2026 reused development windows',A_supported_subset_only=True,raw_shock_effect_not_causal=True,thresholds='training 20th/80th percentile plus actual positive/negative sign',frozen_matching=True,sector_baseline='training shock-tail sector average; sector taxonomy fixed, not selected by test results',ties='half credit for pair ties; fractional top-quartile membership',offset_claim_approved=False,production_changed=False),indent=2),encoding='utf8')
    print(summary.to_string());print(pd.DataFrame(uncertainty).to_string(index=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--gold',required=True);p.add_argument('--evidence',required=True);p.add_argument('--out',required=True);a=p.parse_args();run(a.gold,a.evidence,a.out)
