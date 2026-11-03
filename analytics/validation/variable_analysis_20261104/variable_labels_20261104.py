"""Plain Korean labels for the exact research inputs, not a new Gold contract."""
from train_rich_context import ALL
from analyze_variables_20261104 import LINKS

def labels():
    names={'shock_fx':'향후 5거래일 환율 변화율','shock_rate':'향후 5거래일 미국 금리 변화(bp)','shock_oil':'향후 5거래일 WTI 변화율','shock_vix':'향후 5거래일 VIX 변화(포인트)',
        'fx_trend20':'최근 20일 환율 등락률','rate_level':'미국 10년 금리 수준','oil_level':'WTI 가격 수준','vix_level':'VIX 수준','kr3y_level':'한국 3년 금리 수준','kr3y_change20':'한국 3년 금리의 20일 변화',
        'volume_ratio20':'거래량을 최근 20일 평균으로 나눈 값','drawdown60':'최근 60일 최고가 대비 하락률','beta60':'시장 대비 종목의 60일 민감도','corr60':'종목과 시장의 60일 상관관계',
        'downside_vol20':'최근 20일 하락 수익률의 크기','oil_trend20':'최근 20일 WTI 등락률','vix_change20':'최근 20일 VIX 변화','rate_change20':'최근 20일 미국 금리 변화(bp)',
        'asset_vol_ratio':'종목의 5일 변동성 / 60일 변동성','market_vol_ratio':'시장의 5일 변동성 / 60일 변동성','asset_acceleration':'종목 5일 등락률 - 20일 등락률의 1/4','market_acceleration':'시장 5일 등락률 - 20일 등락률의 1/4',
        'close_position5':'일중 고저가 사이 종가 위치의 5일 평균','gap_vol20':'시가와 전일 종가 사이 등락률의 20일 변동성','cash_turnover20':'거래대금 / 시가총액의 20일 평균','log_market_cap':'시가총액의 로그값',
        'peer_down_fraction':'과거 상관이 비슷한 종목 중 하락 비율','peer_vol20':'과거 상관이 비슷한 종목의 20일 변동성 평균','observed_breadth':'관측 연구 종목 중 하락 비율','observed_return_dispersion':'관측 연구 종목 간 당일 등락률 차이',
        'debt_assets':'공시된 부채 / 자산','operating_assets':'공시된 영업이익 / 자산','equity_assets':'공시된 자본 / 자산','report_age':'사용한 재무보고서 공개 이후 경과 일수','financial_missing':'사용 가능한 재무정보의 부재 여부'}
    for h in [5,20,60]:
        names['asset_trend'+str(h)]=f'최근 {h}일 종목 등락률';names['market_trend'+str(h)]=f'최근 {h}일 시장 등락률'
        names['asset_vol'+str(h)]=f'최근 {h}일 종목 일별 변동성';names['market_vol'+str(h)]=f'최근 {h}일 시장 일별 변동성';names['relative_market'+str(h)]=f'최근 {h}일 종목 등락률 - 시장 등락률'
    for h in [5,20]:
        names['intraday_range'+str(h)]=f'최근 {h}일 고저가 폭의 평균';names['peer_return'+str(h)]=f'과거 상관이 비슷한 종목의 {h}일 등락률 평균'
    for prefix,who in [('foreign','외국인'),('institution','기관')]:
        for h in [1,5,20]:names[f'{prefix}_flow_{h}']=f'전일까지 {h}일 평균 {who} 순매수 / 최근 절대 순매수 평균'
        names[f'{prefix}_flow_accel']=f'{who}의 최근 5일 수급과 20일 수급 차이'
        for h in [5,20]:
            names[f'{prefix}_cash_fraction{h}']=f'전일까지 {h}일 {who} 순매수 / 거래대금'
            names[f'market_{prefix}_flow_{h}']=f'코스피 전체의 전일까지 {h}일 평균 {who} 수급(규모 정규화)'
    for c,parents in LINKS.items():names[c]=' × '.join(names.get(p,p) for p in parents)
    assert all(c in names for c in ALL),[c for c in ALL if c not in names]
    return {c:names[c] for c in ALL}
