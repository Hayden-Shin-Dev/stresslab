"""Ex-post error diagnostics only. Realized market return is NEVER a model input."""
import json
import numpy as np
import pandas as pd
from research_shock_context import OUT,SRC

def main():
    r=pd.read_parquet(OUT/'predictions.parquet');r=r[r.method.eq('baseline')]
    d=pd.read_parquet(OUT/'learning_table.parquet')
    g=pd.read_parquet(SRC/'research_daily_input.parquet',columns=['trading_date','kospi_close'])
    market=g.groupby('trading_date').kospi_close.first().sort_index();realized=(market.shift(-5)/market-1)*100
    r=r.merge(d[['asset','date','beta60']],on=['asset','date'],validate='one_to_one');r['realized_market_return']=r.date.map(realized)
    r['error']=r.actual-r.center;r['historical_beta_market_component']=r.beta60*r.realized_market_return
    r['remaining_component']=r.actual-r.historical_beta_market_component
    rows=[]
    for a,z in r.groupby('asset'):
        x=z.realized_market_return.to_numpy();y=z.error.to_numpy();xc=x-x.mean();yc=y-y.mean()
        slope=float(xc@yc/(xc@xc)) if xc@xc else np.nan
        corr=z.error.corr(z.realized_market_return)
        rows.append(dict(asset=a,n=len(z),error_market_correlation=corr,ex_post_linear_association_r2=corr*corr,error_market_slope=slope,actual_variance=z.actual.var(),past_beta_market_component_variance=z.historical_beta_market_component.var(),remaining_component_variance=z.remaining_component.var(),twice_component_covariance=2*z.historical_beta_market_component.cov(z.remaining_component),market_return_used_as_model_input=False))
    result=pd.DataFrame(rows);assert np.allclose(result.actual_variance,result.past_beta_market_component_variance+result.remaining_component_variance+result.twice_component_covariance)
    result.to_csv(OUT/'remaining_error_market_diagnostic.csv',index=False)
    summary=dict(stocks=len(result),median_error_market_correlation=float(result.error_market_correlation.median()),median_ex_post_r2=float(result.ex_post_linear_association_r2.median()),stocks_positive_correlation=int(result.error_market_correlation.gt(0).sum()),warning='Descriptive association computed after outcomes. Not deployable performance, causal attribution, or fraction of error that future inputs could remove. Does not train an excess-return model.')
    (OUT/'remaining_error_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')

if __name__=='__main__':main()
