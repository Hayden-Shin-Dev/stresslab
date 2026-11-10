"""Export the retained local research model only; never replace a service model."""
import json
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
from catboost import CatBoostRegressor
from compare_gold20_locked_20261104 import OUT,FEATURES,GROUPS,PARAMS

def predict_center(model,frame,features):
    """All four shocks are changes, so explicit zero means unchanged level."""
    assert all(k in frame for k in ['shock_fx','shock_rate','shock_oil','shock_vix','scale'])
    return np.sort(model.predict(frame[features].to_numpy()),axis=1)[:,1]*frame.scale.to_numpy()

def main():
    decision=json.loads((OUT/'decision.json').read_text());method=decision['retained_research_method']
    columns=FEATURES+GROUPS.get(method,[]);data=pd.read_parquet(OUT/'learning_table.parquet');pred=pd.read_parquet(OUT/'predictions.parquet')
    folder=OUT/'models';folder.mkdir(exist_ok=True)
    def fit(item):
        asset,frame=item;frame=frame.sort_values('date');tr=frame[frame.end_date<pd.Timestamp('2025-01-01')-pd.Timedelta(days=20)]
        ref=pred[(pred.asset==asset)&(pred.method==method)&(pred.fold==2026)].sort_values('date');te=frame[frame.date.isin(ref.date)]
        model=CatBoostRegressor(**PARAMS).fit(tr[columns].to_numpy(),tr.target/tr.scale)
        difference=float(np.max(abs(predict_center(model,te,columns)-ref.center.to_numpy())));assert difference<1e-7
        path=folder/f'{asset}.cbm';model.save_model(str(path));loaded=CatBoostRegressor();loaded.load_model(str(path))
        assert np.allclose(predict_center(loaded,te,columns),ref.center,rtol=0,atol=1e-7)
        return dict(asset=asset,train_rows=len(tr),train_label_end=str(tr.end_date.max()),test_rows=len(te),reproduction_max_error=difference)
    with ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(fit,data.groupby('asset')))
    pd.DataFrame(rows).to_csv(OUT/'model_export_verification.csv',index=False)
    (folder/'manifest.json').write_text(json.dumps(dict(method=method,features=columns,scale='sqrt((asset_vol20^2+asset_vol60^2)/2*5), floor0.1; returns in percentage points',models=20,fold=2026,production=False,source='Frozen 2026 evaluation fit, not a newly fitted live service',shock_zero='unchanged level, not a zero price or interest-rate level'),indent=2),encoding='utf8')
    print(json.dumps(dict(exported=20,method=method,reload_prediction_verified=True,production=False)))

if __name__=='__main__':main()
