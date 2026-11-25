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
    assert.match(html, /시뮬레이션 · 일별 환산/);
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
    tab: 'portfolio', portfolioBasisDate: '2026-11-20',
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
  assert.match(html, /2026-11-20/);
  assert.equal((html.match(/data-gx="p63-remove-lot"/g) || []).length, 2);
});

test('portfolio tab distinguishes purchase cost, valuation and stress result', () => {
  const source = fs.readFileSync(path.join(__dirname, '../site/whatif-v6/assets/scenario-window.js'), 'utf8');
  const context = { window: {}, Date, Intl };
  vm.runInNewContext(source, context);
  const html = context.window.whatIfScenarioMarketStatePanel({
    tab: 'portfolio', portfolioLots: [{ code: '005930', name: '삼성전자', quantity: 2,
      price: 80000, avgPurchasePrice: 70000 }],
    portfolioResults: [{ asset_id: '005930', holding_krw: 160000,
      scenario_return_pct: -2, hypothetical_pnl_krw: -3200 }],
  });
  assert.match(html, /총 매입금액/);
  assert.match(html, /140,000원/);
  assert.match(html, /160,000원/);
  assert.match(html, /20,000원/);
  assert.match(html, /-3,200원/);
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

test('Scenario archived and live actuals stay left of the fixed forecast divider', () => {
  const input = {...run(), at: '2026-11-25T06:40:00Z'};
  const archived = [
    {at:'2026-11-02T06:19:59Z',price:229000,interval:'1d'},
    {at:'2026-11-25T06:19:59Z',price:171100,interval:'1d'},
  ];
  const live = {at:'2026-11-26T00:17:21Z',price:172500,interval:'1d'};
  const render = rows => chart.render({run:input,state:{compareAssets:['005930']}, priceSeries:{'005930':rows}});
  const before = render(archived), after = render([...archived,live]);
  const marker = html => Number(html.match(/<line x1="([^"]+)"[^>]+class="fig-stress-now-line"/)[1]);
  const actual = html => html.match(/<polyline points="([^"]+)" class="fig-stress-actual-line"/)[1].split(' ');
  assert.equal(marker(after),marker(before));
  const points = actual(after).map(point=>Number(point.split(',')[0]));
  assert.equal(points.length,3);
  assert.ok(points[0] < points[1] && points[1] < points[2] && points[2] < marker(after));
  assert.equal(after.match(/class="fig-projection-line"/g).length,3);
  assert.match(after,/11\. 2\./);
  assert.match(after,/11\. 26\./);
  assert.match(after,/172,500원/);
});

test('Scenario minute and tick views preserve their own grain', () => {
  const at = '2026-11-02T02:49:23Z';
  const series = {'005930': [
    {at,price:224500,interval:'tick',event_id:'one'},
    {at,price:224750,interval:'tick',event_id:'two'},
    {at,price:224500,interval:'tick',event_id:'one'},
    {at:'2026-11-02T02:49:59Z',price:228000,interval:'1m',open:224500,high:228000,low:224500},
  ]};
  const render = period => chart.render({state:{period,compareAssets:['005930']},priceSeries:series,maxTickDate:'2026-11-26'});
  assert.match(render('tick'),/실제 관측 2건/);
  assert.match(render('tick'),/11:49:23/);
  assert.match(render('tick'),/min="2026-11-02"/);
  assert.doesNotMatch(render('tick'),/228,000원/);
  assert.match(render('minute'),/종가 228,000원/);
});

test('Scenario draws the existing latest quote after stored history on the actual side', () => {
  const code = '005930';
  const input = {...run(),at:'2026-11-25T06:25:00Z'};
  const state = {compareAssets:[code],period:'day'};
  const priceSeries = {[code]:[
    {at:'2026-11-02T06:19:59Z',price:229000,interval:'1d'},
    {at:'2026-11-25T06:19:59Z',price:171100,interval:'1d'},
  ]};
  const quote = {code,price:172550,tradeAt:'2026-11-26T00:17:21Z',dateConfirmed:true};
  const options = {run:input,state,priceSeries};
  const html = chart.render({...options,quotes:[quote]});
  assert.match(html,/실제 관측 3건/);
  assert.match(html,/172,550원/);
  const divider = Number(html.match(/<line x1="([^"]+)"[^>]+class="fig-stress-now-line"/)[1]);
  const positions = html.match(/<polyline points="([^"]+)" class="fig-stress-actual-line"/)[1]
    .split(' ').map(point=>Number(point.split(',')[0]));
  assert.ok(positions.every(x=>x<divider));
  assert.equal(html.match(/class="fig-projection-line"/g).length,3);
  assert.doesNotMatch(chart.render({...options,quotes:[{...quote,dateConfirmed:false}]}),/172,550원/);
  const sameDay = chart.render({...options,quotes:[{...quote,tradeAt:'2026-11-25T06:45:00Z'}]});
  assert.match(sameDay,/실제 관측 2건/);
  assert.match(sameDay,/종가 172,550원/);
});
