"""Point-in-time join rules for official flows/accounts and historical peer states."""
import json,hashlib,subprocess
from pathlib import Path
import numpy as np
import pandas as pd
from gold_quantile_benchmark import ROOT
OUT=ROOT/'reports/gold20_locked_20261104';FLOW=ROOT/'data/research/official_flow_20261103';DART=ROOT/'data/research/rich_dart_20261103'
FLOW_FEATURES=[f'{p}_{h}' for p in ['foreign_flow','institution_flow'] for h in ['1','5','20','accel']]
FLOW_RATIOS=[f'{p}_cash_fraction{h}' for p in ['foreign','institution'] for h in [5,20]]
MARKET_FLOW=[f'market_{p}_{h}' for p in ['foreign_flow','institution_flow'] for h in [5,20]]
PRICE_FEATURES=['intraday_range5','intraday_range20','close_position5','gap_vol20','cash_turnover20','log_market_cap']
PEER_FEATURES=['peer_return5','peer_return20','peer_down_fraction','peer_vol20','observed_breadth','observed_return_dispersion']
COMPANY_FEATURES=['debt_assets','operating_assets','equity_assets','report_age','financial_missing']

def number(v):
    return pd.to_numeric(v.astype(str).str.replace(',',''),errors='coerce')

def accounts(asset):
    issuer='005930' if asset=='005935' else asset;records=[];audit=[]
    paths=sorted((DART/issuer).glob('20*.json')) or sorted((ROOT/'data/research/dart_ml_history'/issuer).glob('20*.json'))
    for path in paths:
        rows=json.loads(path.read_text(encoding='utf8')).get('list',[]);basis='CFS' if any(z.get('fs_div')=='CFS' for z in rows) else 'OFS'
        ac={z['account_nm']:z for z in rows if z.get('fs_div')==basis and z.get('currency')=='KRW'}
        op=ac.get('영업이익',ac.get('영업이익(손실)'));items=[ac.get('자산총계'),ac.get('부채총계'),op,ac.get('자본총계')]
        if any(z is None for z in items):audit.append(dict(asset=asset,year=path.stem,status='missing_accounts'));continue
        receipts={z['rcept_no'] for z in items};values=[pd.to_numeric(str(z['thstrm_amount']).replace(',',''),errors='coerce') for z in items]
        if len(receipts)!=1 or not np.isfinite(values).all() or values[0]<=0:audit.append(dict(asset=asset,year=path.stem,status='invalid_accounts'));continue
        receipt=items[0]['rcept_no'];known=pd.to_datetime(receipt[:8],format='%Y%m%d')+pd.Timedelta(days=1)
        records.append(dict(asset=asset,issuer=issuer,fiscal_year=int(path.stem),known_from=known,receipt_no=receipt,debt_assets=values[1]/values[0],operating_assets=values[2]/values[0],equity_assets=values[3]/values[0],source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return records,audit

def main():
    from gold_quantile_benchmark import build
    OUT.mkdir(parents=True,exist_ok=True)
    g=pd.read_parquet(ROOT/'exports/seongjin_gold_v1_1/gold_stress_daily.parquet')
    g['trading_date']=pd.to_datetime(g.trading_date)
    assets=sorted(g.asset_id.unique());assert len(assets)==20
    d=build(g);d=d[d.asset.ne('portfolio')].copy()
    dates=pd.DatetimeIndex(sorted(g.trading_date.unique()));frames=[];quality=[];receipts=[];account_audit=[]
    for asset in assets:
        rows=[]
        for p in sorted((FLOW/'stocks'/asset).glob('*.json')):rows+=json.loads(p.read_text(encoding='utf8'))
        z=pd.DataFrame(rows)
        if z.empty:raise ValueError('no_flow:'+asset)
        z['date']=pd.to_datetime(z.TRD_DD);assert not z.date.duplicated().any();z=z.sort_values('date').set_index('date')
        amounts=z[['TRDVAL1','TRDVAL2','TRDVAL3','TRDVAL4','TRDVAL_TOT']].apply(number)
        valid=amounts.notna().all(axis=1)&amounts.iloc[:,:4].sum(axis=1).eq(amounts.TRDVAL_TOT)&amounts.TRDVAL_TOT.eq(0)
        quality.append(dict(asset=asset,rows=len(z),first=str(z.index.min()),last=str(z.index.max()),invalid_rows=int((~valid).sum())))
        amounts=amounts.where(valid).reindex(dates);x=pd.DataFrame(index=dates);x['asset']=asset;x['date']=dates
        price_rows=[]
        for folder in ['official20_20261102','sector6_20261103','exposure_universe_20261103']:
            paths=sorted((ROOT/'data/research'/folder/'stocks'/asset).glob('*.json'))
            if paths:
                for p in paths:price_rows+=json.loads(p.read_text(encoding='utf8'))
                break
        raw=pd.DataFrame(price_rows);raw['date']=pd.to_datetime(raw.TRD_DD);assert not raw.date.duplicated().any();raw=raw.set_index('date').reindex(dates)
        cash=number(raw.ACC_TRDVAL);cap=number(raw.MKTCAP);cl=number(raw.TDD_CLSPRC);hi=number(raw.TDD_HGPRC);lo=number(raw.TDD_LWPRC);op=number(raw.TDD_OPNPRC)
        reference=g[g.asset_id.eq(asset)].set_index('trading_date').close.reindex(dates)
        matched=(cl-reference).abs()<=np.maximum(1,reference.abs()*.0001)
        coherent=matched & lo.gt(0)&hi.ge(lo)&cl.between(lo-1,hi+1)&op.between(lo-1,hi+1)
        spread=((hi-lo)/cl*100).where(coherent);position=((cl-lo)/(hi-lo).replace(0,np.nan)).where(coherent)
        x['intraday_range5']=spread.rolling(5).mean();x['intraday_range20']=spread.rolling(20).mean();x['close_position5']=position.rolling(5,min_periods=3).mean()
        x['gap_vol20']=((op/cl.shift(1)-1)*100).where(coherent&coherent.shift(1,fill_value=False)).rolling(20).std()
        x['cash_turnover20']=(cash/cap.where(cap>0)).rolling(20).mean();x['log_market_cap']=np.log(cap.where(cap>0))
        quality[-1]['price_mismatch_rows']=int((cl.notna()&reference.notna()&~matched).sum());quality[-1]['ohlc_incoherent_rows']=int((cl.notna()&~coherent).sum())
        for prefix,col in [('foreign','TRDVAL4'),('institution','TRDVAL1')]:
            for h in [5,20]:x[f'{prefix}_cash_fraction{h}']=amounts[col].shift(1).rolling(h).sum()/cash.shift(1).rolling(h).sum().replace(0,np.nan)
        # Prior completed session only. Ratios avoid mixing adjusted prices with nominal cash amounts.
        for name,col in [('foreign_flow','TRDVAL4'),('institution_flow','TRDVAL1')]:
            v=amounts[col].shift(1);den=v.abs().rolling(60,min_periods=40).mean().replace(0,np.nan)
            for h in [1,5,20]:x[f'{name}_{h}']=v.rolling(h).mean()/den
            x[name+'_accel']=x[name+'_5']-x[name+'_20']
        x['flow_available']=x[FLOW_FEATURES].notna().all(axis=1)
        rr,aa=accounts(asset);receipts+=rr;account_audit+=aa
        x=x.reset_index(drop=True)
        if rr:
            rs=pd.DataFrame(rr).sort_values(['known_from','fiscal_year']).drop_duplicates('known_from',keep='last');rs=rs[rs.fiscal_year.eq(rs.fiscal_year.cummax())]
            x=pd.merge_asof(x.sort_values('date'),rs.drop(columns='asset'),left_on='date',right_on='known_from',direction='backward')
            assert (x.loc[x.known_from.notna(),'known_from']<=x.loc[x.known_from.notna(),'date']).all()
            age=(x.date-x.known_from).dt.days;end=pd.to_datetime(x.fiscal_year.astype('Int64').astype(str)+'-12-31',format='%Y-%m-%d',errors='coerce')
            stale=(age>550)|((x.date-end).dt.days>550)
            x['report_age']=age;x.loc[stale,['debt_assets','operating_assets','equity_assets','report_age']]=np.nan
        else:
            for c in COMPANY_FEATURES[:-1]:x[c]=np.nan
        x['financial_missing']=x.debt_assets.isna().astype(int)
        frames.append(x[['asset','date']+FLOW_FEATURES+FLOW_RATIOS+PRICE_FEATURES+['flow_available']+COMPANY_FEATURES])
    d=d.merge(pd.concat(frames),on=['asset','date'],validate='one_to_one')
    market_rows=[]
    for p in sorted((FLOW/'market').glob('2*.json')):market_rows+=json.loads(p.read_text(encoding='utf8'))
    market=pd.DataFrame(market_rows);market['date']=pd.to_datetime(market.TRD_DD);assert not market.date.duplicated().any();market=market.set_index('date').reindex(dates)
    mv=market[['TRDVAL1','TRDVAL2','TRDVAL3','TRDVAL4','TRDVAL_TOT']].apply(number);valid=mv.notna().all(axis=1)&mv.iloc[:,:4].sum(axis=1).eq(mv.TRDVAL_TOT)&mv.TRDVAL_TOT.eq(0)
    mf=pd.DataFrame(index=dates);mf['date']=dates
    for name,col in [('foreign_flow','TRDVAL4'),('institution_flow','TRDVAL1')]:
        v=mv[col].where(valid).shift(1);den=v.abs().rolling(60,min_periods=40).mean().replace(0,np.nan)
        for h in [5,20]:mf[f'market_{name}_{h}']=v.rolling(h).mean()/den
    d=d.merge(mf.reset_index(drop=True),on='date',validate='many_to_one')
    prices=g.assign(valid_close=g.close.where(g.quality_status.eq('valid'))).pivot(index='trading_date',columns='asset_id',values='valid_close').sort_index();r=prices.pct_change(fill_method=None)*100
    p5=prices.pct_change(5,fill_method=None)*100;p20=prices.pct_change(20,fill_method=None)*100;vol=r.rolling(20).std();peers=[];peer_audit=[]
    for quarter in dates.to_period('Q').unique():
        cut=quarter.start_time;hist=r[r.index<cut].tail(252);corr=hist.corr(min_periods=120);ix=dates[dates.to_period('Q')==quarter]
        for asset in assets:
            similar=corr[asset].drop(labels=asset).dropna().sort_values(ascending=False).head(5) if asset in corr else pd.Series(dtype=float)
            members=similar[similar>0].index.tolist();x=pd.DataFrame(dict(asset=asset,date=ix))
            for name,table in [('peer_return5',p5),('peer_return20',p20),('peer_vol20',vol)]:x[name]=table.loc[ix,members].mean(axis=1).where(table.loc[ix,members].notna().sum(axis=1)>=3).to_numpy() if len(members)>=3 else np.nan
            sub=r.loc[ix,members];x['peer_down_fraction']=sub.lt(0).sum(axis=1).div(sub.notna().sum(axis=1)).where(sub.notna().sum(axis=1)>=3).to_numpy() if len(members)>=3 else np.nan
            x['observed_breadth']=r.loc[ix].lt(0).sum(axis=1).div(r.loc[ix].notna().sum(axis=1)).to_numpy();x['observed_return_dispersion']=r.loc[ix].std(axis=1).to_numpy();peers.append(x)
            peer_audit.append(dict(asset=asset,quarter=str(quarter),history_end=str(hist.index.max()) if len(hist) else None,members=';'.join(members)))
    d=d.merge(pd.concat(peers),on=['asset','date'],validate='one_to_one').replace([np.inf,-np.inf],np.nan)
    # Same flow-supported rows for every ablation. Never replace missing flow with zero.
    excluded=d[~d.flow_available][['asset','date']];excluded.to_csv(OUT/'missing_flow_rows.csv',index=False)
    d.to_parquet(OUT/'learning_table.parquet',index=False)
    columns=['foreign_flow_20','market_foreign_flow_20','intraday_range20','peer_return20','debt_assets']
    d.assign(period=pd.cut(d.date.dt.year,[1999,2008,2015,2022,2026],labels=['2000-2008','2009-2015','2016-2022','2023-2026'])).groupby('period',observed=True)[columns].agg(lambda x:x.notna().mean()).to_csv(OUT/'feature_availability_by_period.csv')
    assert d.asset.nunique()==20 and not d.duplicated(['asset','date']).any()
    pd.DataFrame(quality).to_csv(OUT/'flow_quality.csv',index=False);pd.DataFrame(receipts).to_csv(OUT/'financial_receipts.csv',index=False);pd.DataFrame(account_audit).to_csv(OUT/'financial_missing_accounts.csv',index=False);pd.DataFrame(peer_audit).to_csv(OUT/'peer_selection.csv',index=False)
    coverage=d.groupby('asset').agg(rows=('date','size'),first=('date','min'),last=('date','max'),financial_rows=('financial_missing',lambda x:int(x.eq(0).sum())),peer_rows=('peer_return20',lambda x:int(x.notna().sum())))
    coverage.to_csv(OUT/'feature_coverage.csv')
    (OUT/'feature_contract_research.json').write_text(json.dumps(dict(flow=FLOW_FEATURES+FLOW_RATIOS+MARKET_FLOW,price_liquidity=PRICE_FEATURES,peers=PEER_FEATURES,company=COMPANY_FEATURES,preferred_alias={'005935':'005930'},flow_known='Prior completed KRX trading row, historical release timestamps unavailable',company_known='receipt date+1 calendar day; no fiscal-year backfill; max550day age',peer_scope='Fixed research universe historical correlation neighbours, NOT official sectors or wholeKOSPI',industry_current='Company metadata only, not backfilled into historical ML',production=False),indent=2),encoding='utf8')

if __name__=='__main__':main()
