const test = require('node:test');
const assert = require('node:assert/strict');
const chart = require('../site/whatif-v6/assets/scenario-stress-chart.js');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// These are the fields produced by services/api/src/gateway.py /api/stress/analyze.
// The engine returns one five-trading-day endpoint per asset, not a future series.
function gatewayResult() {
  return {
    api_version: '1.1',
    model: 'ridge',
    horizon_trading_days: 5,
    model_context: { as_of_trading_date: '2026-11-20' },
    assets: [
      {
        asset_id: '005930', holding_krw: 2_000_000,
        baseline_model_return_pct: 1.5, scenario_return_pct: -3.5,
        change_from_baseline_pp: -5,
        baseline_pnl_krw: 30_000, hypothetical_pnl_krw: -70_000,
        shock_incremental_pnl_krw: -100_000,
        model_interval_90_return_pct: { lower: -5, upper: -1 },
      },
      {
        asset_id: '000660', holding_krw: 1_000_000,
        baseline_model_return_pct: -1, scenario_return_pct: 2,
        change_from_baseline_pp: 3,
        baseline_pnl_krw: -10_000, hypothetical_pnl_krw: 20_000,
        shock_incremental_pnl_krw: 30_000,
        model_interval_90_return_pct: { lower: 0, upper: 4 },
      },
    ],
    portfolio_hypothetical_pnl_krw: -50_000,
    portfolio_shock_incremental_pnl_krw: -70_000,
    interval_note: '종목별 모델 구간입니다. 포트폴리오 손실 한도를 보장하지 않습니다.',
  };
}

const run = () => ({ stressResult: gatewayResult(), priceSnapshot: {'005930':{price:80000,at:'2026-11-24T01:00:00Z'},'000660':{price:100000,at:'2026-11-24T01:00:00Z'}}, portfolioLots: [
  { code: '005930', name: '삼성전자', quantity: 25, price: 80_000 },
  { code: '000660', name: 'SK하이닉스', quantity: 10, price: 100_000 },
] });

test('uses raw gateway KRW amounts and derives portfolio return percentages from holdings', () => {
  const result = gatewayResult();
  const data = chart.derive(result);
  assert.equal(data.error, undefined);
  assert.equal(data.totalHoldingKrw, 3_000_000);
  assert.equal(data.baselinePnlKrw, 20_000);
  assert.equal(data.scenarioPnlKrw, result.portfolio_hypothetical_pnl_krw);
  assert.equal(data.incrementalPnlKrw, result.portfolio_shock_incremental_pnl_krw);
  assert.equal(data.baselineValueKrw, 3_020_000);
  assert.equal(data.scenarioValueKrw, 2_950_000);
  assert.ok(Math.abs(data.baselineReturnPct - (20_000 / 3_000_000 * 100)) < 1e-12);
  assert.ok(Math.abs(data.scenarioReturnPct - (-50_000 / 3_000_000 * 100)) < 1e-12);
  assert.equal(data.basisDate, '2026-11-20');
  assert.equal(data.horizon, 5);
  assert.deepEqual(result.assets.map(row => row.hypothetical_pnl_krw), [-70_000, 20_000]);
});

test('market view identifies independent stocks, not a KOSPI index', () => {
  const html = chart.render({ run: run(), mode: 'market' });
  assert.match(html, /종목별 독립 계산/);
  assert.match(html, /포트폴리오 합계와 분리/);
  assert.match(html, /5거래일/);
  assert.match(html, /기준선 · 무충격/);
  assert.match(html, /입력 충격/);
  assert.doesNotMatch(html, /KOSPI 시장 지수|코스피 지수 경로/);
});

test('portfolio total view shows amounts in KRW and asset view keeps per-asset percentages', () => {
  const input = run();
  const total = chart.render({ run: input, mode: 'portfolio' });
  assert.match(total, /개인 포트폴리오/);
  assert.match(total, /선택한 보유 종목 범위의 평가금액/);
  assert.match(total, /평가금액 · 원/);
  for (const amount of ['3,000,000원', '3,020,000원', '2,950,000원']) assert.ok(total.includes(amount), amount);
  const assets = chart.render({ run: input, mode: 'portfolio', state: { view: 'assets' } });
  assert.match(assets, /삼성전자 \(005930\)/);
  assert.match(assets, /SK하이닉스 \(000660\)/);
  assert.match(assets, /종목별 5거래일 수익률/);
  assert.match(assets, /-3\.50%/);
  assert.match(assets, /\+2\.00%/);
});

test('asset visibility and search affect display only, never aggregate engine totals', () => {
  const input = run();
  const initial = chart.derive(input.stressResult);
  const filtered = chart.render({ run: input, mode: 'portfolio', state: {
    view: 'assets', hiddenAssets: ['005930'], search: '000660', pickerOpen: true,
  } });
  assert.match(filtered, /SK하이닉스 \(000660\)/);
  assert.doesNotMatch(filtered, /class="fig-stress-row"[^>]*>\s*<strong[^>]*>삼성전자/);
  assert.match(filtered, /종목 표시 1\/2/);
  const after = chart.derive(input.stressResult);
  assert.equal(after.totalHoldingKrw, initial.totalHoldingKrw);
  assert.equal(after.scenarioPnlKrw, initial.scenarioPnlKrw);
  const total = chart.render({ run: input, mode: 'portfolio', state: { view: 'total', hiddenAssets: ['005930'] } });
  assert.match(total, /2,950,000원/);
});

test('90% intervals are labeled and drawn only for individual assets', () => {
  const input = run();
  const total = chart.render({ run: input, mode: 'portfolio', state: { view: 'total' } });
  const assets = chart.render({ run: input, mode: 'portfolio', state: { view: 'assets' } });
  assert.doesNotMatch(total, /fig-stress-interval|모델 예측 구간/);
  assert.equal((assets.match(/class="fig-stress-interval"/g) || []).length, 2);
  assert.match(assets, /90% 모델 예측 구간/);
  assert.match(assets, /fig-stress-cap-low/);
  assert.match(assets, /입력 충격 중심값/);
  assert.doesNotMatch(assets, /포트폴리오 90%/);
});

test('comparison selection shows at most four selected assets and preserves computed totals', () => {
  const input = run();
  const before = chart.derive(input.stressResult);
  const compared = chart.render({ run: input, mode: 'market', state: { view: 'assets', compareAssets: ['005930', '000660'] } });
  assert.match(compared, /종목 비교 <span>2\/4/);
  assert.match(compared, /삼성전자 \(005930\)/);
  assert.match(compared, /SK하이닉스 \(000660\)/);
  assert.doesNotMatch(compared, /현대차 \(005380\)/);
  // Selected stocks are overlaid on one chart: one series and one table row each.
  assert.equal((compared.match(/class="fig-stress-series/g) || []).length, 2);
  assert.equal((compared.match(/<tr data-code=/g) || []).length, 2);
  const limited = chart.render({ run: input, mode: 'market', state: { view: 'assets', compareAssets: ['005930','000660','005380','035420','012330'] } });
  assert.match(limited, /종목 비교 <span>2\/4/);
  assert.equal((limited.match(/class="fig-stress-series/g) || []).length, 2);
  assert.equal(chart.derive(input.stressResult).scenarioPnlKrw, before.scenarioPnlKrw);
});

test('five-day simulation has five closes, candles or OHLC glyphs per scenario', () => {
  const input = run();
  const before = JSON.stringify(input);
  for (const representation of ['line', 'candle', 'ohlc']) {
    const html = chart.render({
      run: input, mode: 'market',
      state: { compareAssets: ['005930'], representation }
    });
    const forecast = [...html.matchAll(/<g class="fig-stress-forecast-point is-(\w+)" data-day="(\d+)"[^>]*>(.*?)<circle[^>]+fill="transparent"\/>/g)];
    assert.doesNotMatch(html, /시뮬레이션 · 일별 환산/);
    assert.equal(forecast.length, 15);
    for (const scenario of ['positive', 'baseline', 'negative']) {
      assert.deepEqual(forecast.filter(m => m[1] === scenario).map(m => Number(m[2])), [1, 2, 3, 4, 5]);
    }
    for (const [, , , glyph] of forecast) {
      if (representation === 'line') assert.match(glyph, /<circle/);
      if (representation === 'candle') assert.match(glyph, /<path[^>]+V[^>]+\/>s*<rect/);
      if (representation === 'ohlc') {
        assert.match(glyph, /<path[^>]+V[^>]+\/><path[^>]+H[^>]+M[^>]+H/);
        assert.doesNotMatch(glyph, /<rect/);
      }
    }
    assert.equal((html.match(/class="fig-projection-line"/g) || []).length, representation === 'line' ? 3 : 0);
    assert.match(html, /종가 77,200원/);
    assert.doesNotMatch(html, /종료값 연결|일별 예측 없음/);
  }
  assert.equal(JSON.stringify(input), before);
});

test('chart preserves model OHLC and uses the approved terminal return', () => {
  const input = run();
  input.stressResult.assets[0].daily_scenarios = {
    baseline: [
      { day: 1, open_return_pct: 0, high_return_pct: 3, low_return_pct: -4, return_pct: 1 },
      { day: 5, return_pct: 9 }
    ]
  };
  const html = chart.render({ run: input, state: { compareAssets: ['005930'], representation: 'ohlc' } });
  assert.match(html, /시가 80,000원 · 고가 82,400원 · 저가 76,800원 · 종가 80,800원/);
  assert.match(html, /종가 77,200원/);
  assert.doesNotMatch(html, /종가 87,200원/);
});

test('rejects missing, malformed, duplicate, and inconsistent gateway numbers', () => {
  const cases = [
    result => { delete result.horizon_trading_days; },
    result => { delete result.portfolio_hypothetical_pnl_krw; },
    result => { delete result.assets[0].holding_krw; },
    result => { result.assets[0].scenario_return_pct = NaN; },
    result => { result.assets[0].model_interval_90_return_pct.lower = 3; },
    result => { result.assets[1].asset_id = result.assets[0].asset_id; },
    result => { result.portfolio_hypothetical_pnl_krw += 1_000; },
  ];
  for (const damage of cases) {
    const result = gatewayResult();
    damage(result);
    assert.match(chart.derive(result).error || '', /올바르지 않아/);
    const html = chart.render({ run: { stressResult: result }, mode: 'market' });
    assert.match(html, /role="alert"/);
    assert.doesNotMatch(html, /NaN|Infinity/);
  }
});

test('escapes user names and API text in text and attribute contexts', () => {
  const input = run();
  input.portfolioLots[0].name = '<img src=x onerror="alert(1)">';
  input.stressResult.model = '<script>alert(2)</script>';
  input.stressResult.model_context.as_of_trading_date = '"><svg onload=alert(3)>';
  const html = chart.render({ run: input, mode: 'portfolio', state: { view: 'assets', pickerOpen: true } });
  assert.doesNotMatch(html, /<img src=x|<script>|<svg onload/);
  assert.match(html, /&lt;img src=x onerror=&quot;alert\(1\)&quot;&gt;/);
  assert.match(html, /&lt;script&gt;alert\(2\)&lt;\/script&gt;/);
  assert.match(html, /&quot;&gt;&lt;svg onload=alert\(3\)&gt;/);
  assert.doesNotMatch(html, /onerror="alert\(1\)"|onload=alert\(3\)>/);
});

test('portfolio tab groups duplicate lots and displays the gateway amounts', () => {
  const source = fs.readFileSync(path.join(__dirname, '../site/whatif-v6/assets/scenario-window.js'), 'utf8');
  const context = { window: {}, Date, Intl };
  vm.runInNewContext(source, context);
  const html = context.window.whatIfScenarioMarketStatePanel({
    group: 'portfolio', analysisMode: 'portfolio',
    portfolioLots: [
      { code: '005930', name: '삼성전자', quantity: 2, price: 80_000 },
      { code: '005930', name: '삼성전자', quantity: 3, price: 81_000 },
    ],
    portfolioPrices: [82_000, 82_000],
    portfolioResults: [{ asset_id: '005930', holding_krw: 410_000,
      scenario_return_pct: -2, hypothetical_pnl_krw: -8_200,
      model_interval_90_return_pct: { lower: -4, upper: 1 } }],
  });
  assert.equal((html.match(/<tr><th scope="row">삼성전자/g) || []).length, 1);
  assert.match(html, /5주/);
  assert.match(html, /82,000원/);
  assert.match(html, /410,000원/);
  assert.match(html, /-8,200원/);
  assert.doesNotMatch(html, /서버에 저장된 보유 종목입니다/);
  assert.equal((html.match(/data-gx="p63-remove-lot"/g) || []).length, 2);
});

test('portfolio tab distinguishes purchase cost, valuation and stress result', () => {
  const source = fs.readFileSync(path.join(__dirname, '../site/whatif-v6/assets/scenario-window.js'), 'utf8');
  const context = { window: {}, Date, Intl };
  vm.runInNewContext(source, context);
  const html = context.window.whatIfScenarioMarketStatePanel({
    group: 'portfolio', analysisMode: 'portfolio', portfolioLots: [{ code: '005930', name: '삼성전자', quantity: 2,
      price: 80000, avgPurchasePrice: 70000 }],
    portfolioResults: [{ asset_id: '005930', holding_krw: 160000,
      scenario_return_pct: -2, hypothetical_pnl_krw: -3200 }],
  });
  assert.match(html, /총 매입금액/);
  assert.match(html, /140,000원/);
  assert.match(html, /160,000원/);
  assert.match(html, /20,000원/);
  assert.match(html, /-3,200원/);
  assert.doesNotMatch(html, /role="tab"|>포트폴리오 결과<|>실행 결과</);
  const stock = context.window.whatIfScenarioLiveMarketStatePanel({
    analysisMode: 'market', runSummary: '<p>종목 실행값</p>',
  });
  assert.doesNotMatch(stock, /role="tab"|>실행 결과<|>시나리오 분석 결과</);
  assert.match(stock, /종목 실행값/);
  assert.doesNotMatch(stock, /포트폴리오 결과/);
});

test('forecast conversion uses immutable analysis price, not the latest reference quote', () => {
  const input=run(), original=JSON.stringify(input);
  const args={run:input,mode:'market',selectedCode:'005930',historyStatus:{'005930':'ready'},priceSeries:{'005930':[{at:'2026-11-20',price:79000},{at:'2026-11-23',price:80000}]}};
  const first=chart.render({...args,quotes:[{code:'005930',dateConfirmed:true,price:81000,tradeAt:'2026-11-24T01:01:00Z'}]});
  const later=chart.render({...args,quotes:[{code:'005930',dateConfirmed:true,price:100000,tradeAt:'2026-11-24T01:02:00Z'}]});
  for(const html of [first,later]){
    assert.match(html,/79,200원 · -1%/); // 80000 * (1 - .01), not latest quote
    assert.match(html,/76,000원 · -5%/);
    assert.match(html,/81,200원 · \+1.5%/); // baseline remains outside conditional interval
    assert.match(html,/class="fig-stress-actual-line"/);
  }
  assert.equal(JSON.stringify(input),original);
  const missing=run();delete missing.priceSnapshot;
  const deferred=chart.render({...args,run:missing});
  assert.match(deferred,/기준가 미확인 · 가격 환산 보류 · -5%/);
  assert.doesNotMatch(deferred,/fig-stress-forecast-point/);
});

test('legend focus dims other overlaid series without hiding data',()=>{
  const input=run(),original=JSON.stringify(input);
  const html=chart.render({run:input,mode:'market',state:{compareAssets:['005930','000660'],focusedAsset:'000660'}});
  assert.equal((html.match(/class="fig-stress-series/g)||[]).length,2);
  assert.equal((html.match(/class="fig-stress-series is-dimmed"/g)||[]).length,1);
  assert.equal((html.match(/<tr data-code=/g)||[]).length,2);
  assert.doesNotMatch(html,/data-gx="p63-chart-columns"/);
  assert.match(html,/전체 차트로 복귀/);
  assert.equal(JSON.stringify(input),original);
});

test('chart annotates the executed shocks and uses only approved news for endpoint comparisons', () => {
  const input = run();
  input.id = 'analysis-1';
  input.horizon = 5;
  input.inputSnapshot = { includeNews: true, conditions: { rate: .25, fx: 1.5, oil: 3, vix: 4 } };
  input.newsScenarios = {
    status: 'approved', version: 'V1.6-r8', analysis_id: input.id,
    horizon_trading_days: 5, model: input.stressResult.model, basis_date: '2026-11-20',
    window: { start_at: '2026-11-19T00:00:00Z', end_at: '2026-11-20T00:00:00Z' },
    sources: [{ url: 'https://example.com/news' }],
    assets: input.stressResult.assets.map(row => ({
      asset_id: row.asset_id, basis_price: input.priceSnapshot[row.asset_id].price,
      scenarios: { positive: { return_pct: 6 }, baseline: { return_pct: -2 }, negative: { return_pct: -7 } },
    })),
  };
  const render = () => chart.render({ run: input, conditions: { rate: 2 },
    state: { compareAssets: ['005930'] }, plotWidth: 1000 });
  const html = render();
  assert.match(html, /fig-projection-start.*금리 \+25bp · 원\/달러 \+1.5%.*WTI \+3% · VIX \+4pt/);
  assert.match(html, /fig-projection-end-card is-baseline[^]*?뉴스 반영 전 <tspan[^>]*>-3.50%<[^]*?뉴스 반영 후 <tspan[^>]*>-2.00%/);
  input.newsScenarios.basis_date = '2026-01-01';
  const withoutNews = render();
  assert.match(withoutNews, /fig-projection-end-card is-baseline[^]*?-3.50%/);
  assert.doesNotMatch(withoutNews, /뉴스 반영 후/);
});

test('daily price history retains source OHLC, prefers complete same-day rows, and never invents a bar', () => {
  const code = '005930';
  const rows = [
    { Date: '2026-11-20', Open: '78,000', High: 81000, Low: 77000, Close: 80000 },
    { at: '2026-11-20T06:30:00Z', price: 80000 },
    { date: '20261123', ohlc: { open_price: 80000, high_price: 82000, low_price: 79000, close_price: 81500 } },
    { date: '2026-11-24', open: 81000, high: 80000, low: 79000, price: 82000 },
  ];
  const daily = chart.normalizeDailyHistory({asset_id:code,rows},code);
  assert.deepEqual(daily,[
    {at:'2026-11-20',interval:'1d',price:80000,open:78000,high:81000,low:77000},
    {at:'2026-11-23',interval:'1d',price:81500,open:80000,high:82000,low:79000},
    {at:'2026-11-24',interval:'1d',price:82000},
  ]);
  for(const representation of ['ohlc','candle']){
    const html = chart.render({
      assetUniverse:[{code,name:'삼성전자'}],priceSeries:{[code]:daily},
      state:{compareAssets:[code],period:'day',representation},
    });
    assert.match(html,/일봉 · 가격 \(원\)/);
    assert.match(html,/fig-stress-y-label">[\d,]+원/);
    const glyphs = [...html.matchAll(/data-history-representation="([^"]+)"[^>]*><title>[\s\S]*?<\/title>(.*?)<\/g>/g)];
    assert.equal(glyphs.length,2);
    assert.ok(glyphs.every(([,mode])=>mode===representation));
    assert.ok(glyphs.every(([, ,body])=>body.includes('<rect')===(representation==='candle')));
    assert.match(html,/종가 82,000원/);
  }
});


test('calendar charts use local trading periods and the first open, extremes and last close', () => {
  const code='005930';
  const rows=[
    {date:'2025-12-26',open:70000,high:74000,low:69000,close:73000},
    {date:'2025-12-29',open:73000,high:76000,low:72000,close:75000},
    {date:'2026-01-02',open:75000,high:80000,low:74000,close:78000},
    {date:'2026-01-05',open:78000,high:82500,low:76000,close:80000},
    {date:'2026-01-06',high:84000,low:77500,close:83000},
    {date:'2026-02-02',open:83000,high:88000,low:82500,close:87000},
    {date:'2026-02-03',open:87000,high:90000,low:85000,close:88000}
  ];
  const daily=chart.normalizeDailyHistory({asset_id:code,rows},code);
  const expected={
    day:{periods:7,bars:6,tip:/시가 87,000원 · 고가 90,000원 · 저가 85,000원 · 종가 88,000원/},
    week:{periods:4,bars:4,tip:/시가 73,000원 · 고가 80,000원 · 저가 72,000원 · 종가 78,000원/},
    month:{periods:3,bars:3,tip:/시가 75,000원 · 고가 84,000원 · 저가 74,000원 · 종가 83,000원/},
    year:{periods:2,bars:2,tip:/시가 75,000원 · 고가 90,000원 · 저가 74,000원 · 종가 88,000원/}
  };
  for(const [period,{periods,bars,tip}] of Object.entries(expected)){
    for(const representation of ['line','candle','ohlc']){
      const html=chart.render({assetUniverse:[{code,name:'삼성전자'}],priceSeries:{[code]:daily},
        state:{compareAssets:[code],period,representation}});
      assert.match(html,new RegExp('data-period-count="'+periods+'"'));
      if(representation==='line'){
        assert.match(html,/class="fig-stress-actual-line"/);
        assert.doesNotMatch(html,/data-history-representation=/);
      }else{
        assert.equal([...html.matchAll(/data-history-representation=/g)].length,bars);
        assert.match(html,tip);
      }
      assert.doesNotMatch(html,/NaN|Infinity/);
    }
  }
});

test('weekly and yearly history choices keep every PLAY endpoint and its five daily marks', () => {
  const input=run(),code='005930';
  const daily=chart.normalizeDailyHistory({asset_id:code,rows:[
    {date:'2025-12-30',open:65000,high:70000,low:64000,close:69000},
    {date:'2026-11-23',open:78000,high:81500,low:77000,close:80000}
  ]},code);
  for(const period of ['day','week','month','year']){
    for(const representation of ['line','candle','ohlc']){
      const html=chart.render({run:input,priceSeries:{[code]:daily},state:{compareAssets:[code],period,representation}});
      assert.equal([...html.matchAll(/class="fig-stress-forecast-point /g)].length,15);
      assert.match(html,/종가 77,200원/);
      assert.doesNotMatch(html,/일별 환산|검증된 뉴스 반영 결과/);
    }
  }
});

test('Eventhouse 1-tick charts keep distinct trades at the same second', () => {
  const code='005930';
  const at='2026-11-02T02:49:21Z';
  const priceSeries=chart.normalizeEventHistory({
    period:'tick',source:'quote_events',series:{[code]:[
      {at,price:157000,event_id:'trade-1'},
      {at,price:157100,event_id:'trade-2'},
      {at:'2026-11-02T02:49:22Z',price:157200,event_id:'trade-3'},
    ]},
  },[code],'tick');
  const html=chart.render({priceSeries,state:{compareAssets:[code],period:'tick'}});
  assert.match(html,/data-period-count="3"/);
  assert.match(html,/실제 관측 3건/);
  assert.match(html,/11:49:21/);
  assert.match(html,/체결가 157,100원/);
});

test('Eventhouse minute bars roll up without losing the intraminute high or low', () => {
  const code='005930';
  const priceSeries=chart.normalizeEventHistory({
    period:'minute',source:'quote_events',series:{[code]:[
      {at:'2026-11-02T02:49:45Z',open:157000,high:158000,low:156000,price:157500},
      {at:'2026-11-02T02:50:04Z',open:157500,high:157500,low:155000,price:155500},
    ]},
  },[code],'minute');
  for(const period of chart.periods.keys()){
    if(!period.startsWith('minute'))continue;
    const html=chart.render({priceSeries,state:{compareAssets:[code],period,representation:'candle'}});
    assert.match(html,/고가 158,000원/);
    assert.match(html,/저가 155,000원/);
  }
  const html=chart.render({priceSeries,state:{compareAssets:[code],period:'minute-5',representation:'candle'}});
  assert.match(html,/data-period-count="2"/);
});

test('Eventhouse volume is shown per bar and aggregates only complete periods', () => {
  const code = '005930';
  const rows = [
    {at:'2026-11-26T00:32:12Z',price:156000,volume:355},
    {at:'2026-11-26T00:33:24Z',price:157000,volume:2270},
    {at:'2026-11-26T00:35:50Z',price:157500,volume:null},
  ];
  function render(period, source) {
    const priceSeries = chart.normalizeEventHistory(
      {period:source,source:'quote_events',series:{[code]:rows}},[code],source);
    return chart.render({priceSeries,state:{compareAssets:[code],period}});
  }
  assert.match(render('minute','minute'), /거래량 355주/);
  assert.match(render('minute','minute'), /거래량 2,270주/);
  assert.match(render('minute-5','minute'), /거래량 2,625주/);
  assert.match(render('minute-5','minute'), /거래량 —/);
  rows.splice(1);
  assert.match(render('day','day'), /거래량 355주/);
});

test('wide intraday charts keep both bars on either side of a trading-day boundary', () => {
  const code = '005930';
  const previousOpen = Date.parse('2026-11-25T23:30:00Z');
  const nextOpen = Date.parse('2026-11-27T00:00:00Z');
  const bars = (start, count) => Array.from({length:count}, (_,i) => {
    const at = new Date(start+i*60000).toISOString();
    return {at,observedAt:at,price:170000,volume:i+1,interval:'minute',source:'quote_events'};
  });
  const html = chart.render({
    priceSeries:{[code]:[...bars(previousOpen,619),...bars(nextOpen,81)]},
    quoteHistory:{range:{days:['2026-11-26','2026-11-27'],first:0,last:1}},
    state:{compareAssets:[code],period:'minute'},
  });
  assert.ok(html.includes(`data-quote-key="${code}:minute:${previousOpen+618*60000}"`));
  assert.ok(html.includes(`data-quote-key="${code}:minute:${nextOpen}"`));
});
