"""Long-history stock/shock selection; only pre-2022 data decide admission."""
import json
import numpy as np
import pandas as pd
from asset_feature_research import ROOT,make_data,EXPANDED,SHOCKS
from select_exposure_universe import assemble
from reselect_shock_direction import fit
OUT=ROOT/'reports/long_universe_20261103'
def main():
    status=json.loads((OUT/'collection_progress.json').read_text());assert status['status']=='complete' and not status['failed']
    assets=json.loads((OUT/'collection_assets.json').read_text());rule=json.loads((OUT/'protocol.json').read_text())
    g,quality=assemble(assets);quality.to_csv(OUT/'source_quality.csv',index=False)
    # Selection code cannot inspect post2021 price or response data.
    g=g[g.trading_date<pd.Timestamp('2022-01-01')].copy();d,_=make_data(g);d=d[d.asset.isin(assets)&(d.end_date<pd.Timestamp('2021-12-12'))]
    oil=g.groupby('trading_date').wti.first().sort_index();bad=set(oil.index[oil.le(0).rolling(6).max().shift(-5).eq(1)]);d=d[~d.date.isin(bad)]
    d.to_parquet(OUT/'selection_learning_table.parquet',index=False)
    names={a['asset_id']:a['name'] for a in json.loads((ROOT/'data/research/exposure_universe_20261103/universe.json').read_text(encoding='utf8'))['assets']}
    state=[c for c in EXPANDED if c not in SHOCKS];rows=[];folds=[];quality_rows=[]
    for asset,f in d.groupby('asset'):
        f=f.sort_values('date');prices=g[g.asset_id.eq(asset)];present=prices[prices.close.notna()];life=prices[prices.trading_date.between(present.trading_date.min(),present.trading_date.max())];coverage=life.quality_status.eq('valid').mean()
        quality_rows.append(dict(asset=asset,valid_coverage=coverage,eligible=coverage>=rule['minimum_valid_price_coverage'],nonpositive=int(prices.close.le(0).sum()),quarantined=int(prices.quality_status.eq('quarantined').sum())))
        if coverage<rule['minimum_valid_price_coverage']:continue
        for year in range(2007,2022):
            cut=pd.Timestamp(year,1,1);tr=f[(f.end_date<cut-pd.Timedelta(days=20))&f.target.ne(0)]
            te=f[(f.date>=cut)&(f.end_date<pd.Timestamp(year+1,1,1)-pd.Timedelta(days=20))].iloc[::6];te=te[te.target.ne(0)]
            if len(tr)<500 or len(te)<20:continue
            y=tr.target.gt(0);truth=te.target.gt(0).to_numpy();baseline=fit(tr[state],y).predict(te[state]);bc=baseline==truth
            for shock in SHOCKS:
                cols=state+[shock];m=fit(tr[cols],y);prediction=m.predict(te[cols]);correct=prediction==truth;event=te[shock].abs().to_numpy()>=tr[shock].abs().quantile(.75)
                folds.append(dict(asset=asset,shock=shock,year=year,coefficient=float(m[-1].coef_[0,-1]),train_end=str(tr.end_date.max()),event_n=int(event.sum()),gain=float((correct[event].astype(float)-bc[event]).mean()) if event.any() else None))
                rows.extend(dict(asset=asset,shock=shock,date=str(t),event=bool(e),correct=bool(c),state_correct=bool(b)) for t,e,c,b in zip(te.date,event,correct,bc))
        (OUT/'selection_progress.json').write_text(json.dumps(dict(last_asset=asset,completed=len(quality_rows),total=len(assets),status='running')))
        print(asset,flush=True)
    r=pd.DataFrame(rows);fs=pd.DataFrame(folds);r.to_parquet(OUT/'selection_predictions.parquet',index=False);fs.to_csv(OUT/'selection_folds.csv',index=False);pd.DataFrame(quality_rows).to_csv(OUT/'selection_quality.csv',index=False)
    scores=[]
    for (asset,shock),z in r[r.event].groupby(['asset','shock']):
        f=fs[(fs.asset==asset)&(fs.shock==shock)];sign=np.sign(f.coefficient);stable=max(sign.eq(1).mean(),sign.eq(-1).mean());gain=z.correct.mean()-z.state_correct.mean();positive=f.gain.gt(0).mean()
        checks={'too_few_years':len(f)<rule['minimum_folds'],'too_few_events':len(z)<rule['minimum_event_observations'],'weak_accuracy':z.correct.mean()<rule['minimum_direction_accuracy'],'weak_added_value':gain<rule['minimum_gain_vs_state'],'unstable_gain':positive<rule['minimum_positive_gain_year_fraction'],'unstable_sign':stable<rule['minimum_coefficient_sign_consistency']}
        scores.append(dict(asset=asset,name=names[asset],shock=shock,n=len(z),years=len(f),accuracy=z.correct.mean(),state_accuracy=z.state_correct.mean(),gain=gain,positive_year_fraction=positive,sign_consistency=stable,direction='positive' if sign.eq(1).mean()>.5 else 'negative',selected=not any(checks.values()),failures=';'.join(k for k,v in checks.items() if v)))
    s=pd.DataFrame(scores);s.to_csv(OUT/'all_candidate_pairs.csv',index=False);passed=s[s.selected];passed.to_csv(OUT/'eligible_pairs.csv',index=False);chosen=sorted(passed.asset.unique());(OUT/'selected_assets.json').write_text(json.dumps(chosen,indent=2))
    (OUT/'selection_progress.json').write_text(json.dumps(dict(status='complete',selected_assets=len(chosen),selected_pairs=len(passed),no_post2021_selection=True),indent=2))
    if not chosen:raise RuntimeError('No pair passed frozen long-history criteria; do not force selection')
if __name__=='__main__':main()
