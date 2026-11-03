"""Dense support audit and a service-facing research payload without invented confidence."""
import json
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler
from hypothetical_scenario_audit import OUT,ROOT,SCENARIOS,A_STATE

def independent_count(z):
    n=0;end=pd.Timestamp.min
    for t in z.sort_values('end_date').itertuples():
        if t.date>end:n+=1;end=t.end_date
    return n

def run():
    protocol=json.loads((OUT/'protocol.json').read_text(encoding='utf8'));asof=pd.Timestamp(protocol['as_of'])
    hist=pd.read_parquet(ROOT/'reports/asset_feature_research_20261103/learning_table.parquet');qs=pd.read_csv(OUT/'query_states.csv',dtype={'asset':str})
    rows=[]
    for asset,f in hist.groupby('asset'):
        tr=f[f.end_date<asof-pd.Timedelta(days=20)];q=qs[qs.asset==asset]
        ss=StandardScaler().fit(tr[A_STATE]);d=((ss.transform(tr[A_STATE])-ss.transform(q[A_STATE])[0])**2).mean(axis=1)
        tr=tr.assign(state_distance=np.sqrt(d));near=tr.nsmallest(max(120,int(np.ceil(len(tr)*.2))),'state_distance')
        for label,(fx,rate) in SCENARIOS.items():
            for scope,bank in [('all_daily_windows',tr),('state_selected_daily_windows',near)]:
                match=bank[(abs(bank.shock_fx-fx)<=1.25)&(abs(bank.shock_rate-rate)<=25)];all4=match[(abs(match.shock_oil)<=2.5)&(abs(match.shock_vix)<=2)]
                rows.append(dict(asset=asset,scenario=label,scope=scope,raw_windows=len(bank),matching_windows=len(match),nonoverlap_matches=independent_count(match),four_factor_windows=len(all4),four_factor_nonoverlap=independent_count(all4),fx_min=bank.shock_fx.min(),fx_max=bank.shock_fx.max(),rate_min=bank.shock_rate.min(),rate_max=bank.shock_rate.max()))
    s=pd.DataFrame(rows);s.to_csv(OUT/'dense_support.csv',index=False)
    r=pd.read_csv(OUT/'scenario_returns.csv',dtype={'asset':str});a=pd.read_csv(OUT/'factor_attribution.csv',dtype={'asset':str});payload={'state_date':protocol['as_of'],'horizon_trading_days':5,'input':{'usdkrw_pct':5,'us10y_bp':100,'wti_pct':0,'vix_points':0},'mode':'exploratory','approved_as_expected_loss':False,'historical_coverage_is_not_this_scenario_probability':True,'assets':[]}
    for asset,z in r[(r.scenario=='requested')&(r.model.isin(['ridge','lightgbm']))].groupby('asset'):
        support=s[(s.asset==asset)&(s.scenario=='requested')&(s.scope=='all_daily_windows')].iloc[0]
        forecasts=z[z.version=='current_mature']
        payload['assets'].append({'asset_id':asset,'holding_example_krw':1000000,'all_history_matching_windows':int(support.matching_windows),'nonoverlap_matching_windows':int(support.nonoverlap_matches),'historical_5day_rate_max_bp':float(support.rate_max),'models':forecasts[['model','return_pct','pnl_per_1m']].to_dict('records'),'factor_decomposition':a[(a.asset==asset)&(a.version=='current_mature')&a.model.isin(['ridge','lightgbm'])].to_dict('records'),'interpretation':'가정별 모델 계산값. 과거 관측 사실, 검증된 예상 손실 또는 확률 구간이 아닙니다.'})
    (OUT/'service_payload.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf8')
    report=[]
    for (asset,method),z in r[r.scenario=='requested'].groupby(['asset','model']):
        report.append(dict(asset=asset,model=method,version_count=len(z),same_direction=bool((z.return_pct>0).all() or (z.return_pct<0).all()),min_model_value=z.return_pct.min(),max_model_value=z.return_pct.max(),note='model sensitivity, not probability bounds'))
    pd.DataFrame(report).to_csv(OUT/'model_stability.csv',index=False)
    print(s[(s.asset.isin(['005930','005380']))&(s.scenario=='requested')].to_string(index=False))
if __name__=='__main__':run()
