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

const run = () => ({ stressResult: gatewayResult(), portfolioLots: [
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

test('market view identifies an equal-money supported-asset basket, not a KOSPI index', () => {
  const html = chart.render({ run: run(), mode: 'market' });
  assert.match(html, /지원 종목 동일금액 바스켓/);
  assert.match(html, /지원 종목당 100만 원 가상 투입/);
  assert.match(html, /5거래일 수익률 · %/);
  assert.match(html, /무충격 기준선/);
  assert.match(html, /입력 충격/);
  assert.doesNotMatch(html, /KOSPI 시장 지수|코스피 지수 경로/);
});

test('portfolio total view shows amounts in KRW and asset view keeps per-asset percentages', () => {
  const input = run();
  const total = chart.render({ run: input, mode: 'portfolio' });
  assert.match(total, /개인 포트폴리오/);
  assert.match(total, /조회 시세 × 보유 주수 투입금액/);
  assert.match(total, /평가금액 · 원/);
  for (const amount of ['3,000,000원', '3,020,000원', '2,950,000원']) assert.ok(total.includes(amount), amount);
  const assets = chart.render({ run: input, mode: 'portfolio', state: { view: 'assets' } });
  assert.match(assets, /삼성전자 \(005930\)/);
  assert.match(assets, /SK하이닉스 \(000660\)/);
  assert.match(assets, /종목별 수익률/);
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
  assert.doesNotMatch(total, /fig-stress-interval|90%/);
  assert.equal((assets.match(/class="fig-stress-interval"/g) || []).length, 2);
  assert.match(assets, /종목별 90%/);
  assert.doesNotMatch(assets, /포트폴리오 90%/);
});

test('single-endpoint SVG uses marks, with no invented future line or path', () => {
  const html = chart.render({ run: run(), mode: 'market', state: { view: 'total' } });
  const svg = html.match(/<svg\b[\s\S]*?<\/svg>/)?.[0];
  assert.ok(svg);
  assert.match(svg, /fig-stress-point/);
  assert.equal((svg.match(/class="fig-stress-point"/g) || []).length, 2);
  assert.doesNotMatch(svg, /<(?:path|polyline)\b/);
  assert.doesNotMatch(svg, /시계열|미래 경로/);
  assert.match(svg, /단일 시점/);
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
