/* The deployed stress API returns one five-trading-day endpoint per asset.
   Keep its numbers separate from display coordinates; never synthesize a path. */
(function (root) {
  "use strict";

  const cream = "#fcf8ed";
  const red = "#c3191c";
  const blue = "#2264e6";
  const escape = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[ch]);
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const money = value => `${Math.round(value).toLocaleString("ko-KR")}원`;
  const pct = value => `${value > 0 ? "+" : ""}${value.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
  const precisePct = value => `${value > 0 ? "+" : ""}${value.toLocaleString("ko-KR", { maximumFractionDigits: 6 })}%`;
  const modelName = model => model === "catboost" ? "CatBoost" : model === "ridge" ? "Ridge" : String(model || "모델 미확인");
  const bad = () => ({ error: "모델 반환값의 항목 또는 단위가 올바르지 않아 그래프를 표시할 수 없습니다." });

  function derive(result) {
    if (!result || !Array.isArray(result.assets) || !result.assets.length ||
        !Number.isSafeInteger(result.horizon_trading_days) || result.horizon_trading_days <= 0) return bad();
    if (!finite(result.portfolio_hypothetical_pnl_krw) || !finite(result.portfolio_shock_incremental_pnl_krw)) return bad();
    const ids = new Set();
    const assets = [];
    for (const row of result.assets) {
      if (!row || typeof row.asset_id !== "string" || !row.asset_id || ids.has(row.asset_id) ||
          !finite(row.holding_krw) || row.holding_krw <= 0 ||
          !finite(row.baseline_model_return_pct) || !finite(row.scenario_return_pct) ||
          !finite(row.baseline_pnl_krw) || !finite(row.hypothetical_pnl_krw) ||
          !finite(row.shock_incremental_pnl_krw)) return bad();
      const baselineExpected = row.holding_krw * row.baseline_model_return_pct / 100;
      const scenarioExpected = row.holding_krw * row.scenario_return_pct / 100;
      const rowTolerance = Math.max(0.01, Math.abs(row.holding_krw) * 1e-9);
      if (Math.abs(row.baseline_pnl_krw - baselineExpected) > rowTolerance ||
          Math.abs(row.hypothetical_pnl_krw - scenarioExpected) > rowTolerance ||
          Math.abs(row.shock_incremental_pnl_krw - (row.hypothetical_pnl_krw - row.baseline_pnl_krw)) > rowTolerance) return bad();
      ids.add(row.asset_id);
      const interval = row.model_interval_90_return_pct;
      if (interval != null && (!finite(interval.lower) || !finite(interval.upper) || interval.lower > interval.upper)) return bad();
      assets.push({ ...row, asset_id: row.asset_id });
    }
    const total = assets.reduce((sum, row) => sum + row.holding_krw, 0);
    const baselinePnl = assets.reduce((sum, row) => sum + row.baseline_pnl_krw, 0);
    const assetScenarioPnl = assets.reduce((sum, row) => sum + row.hypothetical_pnl_krw, 0);
    const assetIncrementalPnl = assets.reduce((sum, row) => sum + row.shock_incremental_pnl_krw, 0);
    const scenarioPnl = result.portfolio_hypothetical_pnl_krw;
    const incrementalPnl = result.portfolio_shock_incremental_pnl_krw;
    const tolerance = Math.max(0.01, Math.abs(scenarioPnl) * 1e-9);
    if (!finite(total) || total <= 0 ||
        Math.abs(assetScenarioPnl - scenarioPnl) > tolerance ||
        Math.abs(assetIncrementalPnl - incrementalPnl) > tolerance ||
        Math.abs(scenarioPnl - baselinePnl - incrementalPnl) > tolerance) return bad();
    const basisDate = typeof result.model_context?.as_of_trading_date === "string"
      ? result.model_context.as_of_trading_date : null;
    const horizon = result.horizon_trading_days;
    const baselineValue = total + baselinePnl;
    const scenarioValue = total + scenarioPnl;
    const baselineReturn = baselinePnl / total * 100;
    const scenarioReturn = scenarioPnl / total * 100;
    return {
      assets, total, baselinePnl, scenarioPnl, incrementalPnl,
      baselineValue, scenarioValue, baselineReturn, scenarioReturn,
      totalHoldingKrw: total, baselinePnlKrw: baselinePnl,
      scenarioPnlKrw: scenarioPnl, incrementalPnlKrw: incrementalPnl,
      baselineValueKrw: baselineValue, scenarioValueKrw: scenarioValue,
      baselineReturnPct: baselineReturn, scenarioReturnPct: scenarioReturn,
      basisDate, horizon, model: result.model || null
    };
  }

  function stateOf(raw) {
    const state = raw || {};
    return {
      view: state.view === "assets" ? "assets" : "total",
      series: { baseline: state.series?.baseline !== false, scenario: state.series?.scenario !== false },
      hiddenAssets: Array.isArray(state.hiddenAssets) ? state.hiddenAssets.map(String) : [],
      search: typeof state.search === "string" ? state.search : "",
      focus: ["baseline", "scenario"].includes(state.focus) ? state.focus : "both",
      pickerOpen: state.pickerOpen === true
    };
  }

  function axis(values, unit, caption) {
    const minValue = Math.min(...values), maxValue = Math.max(...values);
    const span = Math.max(maxValue - minValue, unit === "krw" ? Math.max(Math.abs(minValue) * 0.002, 1) : 0.2);
    const low = minValue - span * 0.12, high = maxValue + span * 0.12;
    const x = value => 195 + (value - low) / (high - low) * 610;
    const format = unit === "krw" ? money : pct;
    const ticks = [low, (low + high) / 2, high].map(value =>
      `<text x="${x(value).toFixed(1)}" y="286" text-anchor="middle">${escape(format(value))}</text>`).join("");
    return { x, low, high, html: `<g class="fig-stress-axis"><line x1="195" y1="257" x2="805" y2="257" stroke="${cream}" opacity=".58"/>${ticks}<text x="990" y="286" text-anchor="end">${escape(caption)}</text></g>` };
  }

  function endpointSvg(data, mode, state) {
    const portfolio = mode === "portfolio";
    const values = portfolio
      ? [data.total, data.baselineValue, data.scenarioValue]
      : [0, data.baselineReturn, data.scenarioReturn];
    const range = axis(values, portfolio ? "krw" : "pct", portfolio ? "평가금액 · 원" : "5거래일 수익률 · %");
    const rows = portfolio
      ? [
          { label: "분석 투입금액", value: data.total, y: 61, color: cream, kind: "input", visible: true },
          { label: "무충격 기준선", value: data.baselineValue, y: 139, color: cream, kind: "baseline", visible: state.series.baseline },
          { label: "입력 충격", value: data.scenarioValue, y: 217, color: data.scenarioReturn >= 0 ? red : blue, kind: "scenario", visible: state.series.scenario }
        ]
      : [
          { label: "무충격 기준선", value: data.baselineReturn, y: 101, color: cream, kind: "baseline", visible: state.series.baseline },
          { label: "입력 충격", value: data.scenarioReturn, y: 198, color: data.scenarioReturn >= 0 ? red : blue, kind: "scenario", visible: state.series.scenario }
        ];
    const zero = portfolio ? "" : `<line x1="${range.x(0).toFixed(1)}" y1="31" x2="${range.x(0).toFixed(1)}" y2="253" stroke="${cream}" stroke-dasharray="4 5" opacity=".48"/>`;
    const marks = rows.map(row => {
      const valueText = portfolio ? money(row.value) : pct(row.value);
      const tooltip = `${row.label} · ${portfolio ? money(row.value) : precisePct(row.value)} · 모델 기준일 ${data.basisDate || "미확인"} · ${data.horizon}거래일 단일 시점`;
      const dim = state.focus !== "both" && state.focus !== row.kind && row.kind !== "input" ? ".3" : "1";
      const x = range.x(row.value).toFixed(1);
      return `<g class="fig-stress-svg-row" opacity="${dim}"><text x="28" y="${row.y + 5}" font-size="18">${escape(row.label)}</text><line x1="195" y1="${row.y}" x2="805" y2="${row.y}" stroke="${cream}" opacity=".24"/>${row.visible ? `<g class="fig-stress-point" tabindex="0" data-stress-tip="${escape(tooltip)}" aria-label="${escape(tooltip)}"><circle cx="${x}" cy="${row.y}" r="9" fill="${row.color}" stroke="${cream}" stroke-width="2"/><circle cx="${x}" cy="${row.y}" r="18" fill="transparent"/></g>` : ""}<text x="980" y="${row.y + 5}" text-anchor="end" font-size="20" style="fill:${row.color}">${row.visible ? escape(valueText) : "숨김"}</text></g>`;
    }).join("");
    return `<svg class="fig-stress-svg fig-stress-endpoints" viewBox="0 0 1000 305" role="img" aria-label="${escape(portfolio ? "개인 포트폴리오 평가금액" : "지원 종목 동일금액 바스켓 수익률")} 5거래일 단일 시점 비교">${zero}${marks}${range.html}</svg>`;
  }

  function displayName(code, run, assetNames) {
    const lotName = (run?.portfolioLots || []).find(lot => String(lot.code) === code)?.name;
    const masterName = assetNames instanceof Map ? assetNames.get(code) : assetNames?.[code];
    return String(lotName || masterName || code);
  }

  function assetRows(data, run, state, assetNames) {
    const hidden = new Set(state.hiddenAssets);
    const rows = data.assets.filter(row => !hidden.has(row.asset_id));
    if (!rows.length) return `<div class="fig-stress-empty" role="status">표시할 종목이 없습니다. 종목 표시에서 다시 선택하세요.</div>`;
    const values = [0];
    for (const row of rows) {
      values.push(row.baseline_model_return_pct, row.scenario_return_pct);
      const interval = row.model_interval_90_return_pct;
      if (interval) values.push(interval.lower, interval.upper);
    }
    const min = Math.min(...values), max = Math.max(...values), span = Math.max(max - min, .2);
    const low = min - .1 * span, high = max + .1 * span;
    const percent = value => Math.max(0, Math.min(100, (value - low) / (high - low) * 100)).toFixed(3);
    const body = rows.map(row => {
      const code = row.asset_id, name = displayName(code, run, assetNames);
      const label = name === code ? code : `${name} (${code})`;
      const interval = row.model_interval_90_return_pct;
      const intervalTip = interval ? `${label} · 종목별 90% 명목 모델 구간 ${precisePct(interval.lower)} ~ ${precisePct(interval.upper)} · 모델 기준일 ${data.basisDate || "미확인"}` : "";
      const intervalMark = interval && state.series.scenario ? `<span class="fig-stress-interval" style="left:${percent(interval.lower)}%;width:${(Number(percent(interval.upper)) - Number(percent(interval.lower))).toFixed(3)}%" tabindex="0" data-stress-tip="${escape(intervalTip)}" aria-label="${escape(intervalTip)}"></span>` : "";
      const point = (kind, value, visible) => visible ? `<span class="fig-stress-mark is-${kind} ${kind === "scenario" && value < 0 ? "is-negative" : ""}" style="left:${percent(value)}%;opacity:${state.focus !== "both" && state.focus !== kind ? ".34" : "1"}" data-series="${kind}" tabindex="0" data-stress-tip="${escape(`${label} · ${kind === "baseline" ? "무충격 기준선" : "입력 충격"} ${precisePct(value)} · 모델 기준일 ${data.basisDate || "미확인"} · ${data.horizon}거래일 단일 시점`)}" aria-label="${escape(`${label} ${kind === "baseline" ? "무충격 기준선" : "입력 충격"} ${pct(value)}`)}"></span>` : "";
      return `<div class="fig-stress-row" role="listitem"><strong title="${escape(label)}">${escape(label)}</strong><div class="fig-stress-track"><span class="fig-stress-zero" style="left:${percent(0)}%" aria-hidden="true"></span>${intervalMark}${point("baseline", row.baseline_model_return_pct, state.series.baseline)}${point("scenario", row.scenario_return_pct, state.series.scenario)}</div><span style="color:${row.scenario_return_pct >= 0 ? red : blue}">${state.series.scenario ? escape(pct(row.scenario_return_pct)) : "입력 충격 숨김"}</span></div>`;
    }).join("");
    return `<div class="fig-stress-asset-list" role="list" aria-label="종목별 5거래일 수익률과 종목별 90% 모델 구간"><div class="fig-stress-axis"><span>종목별 수익률</span><span>${escape(pct(low))} ~ ${escape(pct(high))} · 0% 기준선</span></div>${body}</div>`;
  }

  function picker(data, state, run, assetNames) {
    if (!data || data.error) return `<div class="fig-stress-picker"><button type="button" disabled>종목 표시 0/0</button></div>`;
    const hidden = new Set(state.hiddenAssets), query = state.search.trim().toLocaleLowerCase();
    const options = data.assets.map(row => {
      const code = row.asset_id, selected = !hidden.has(code);
      const name = displayName(code, run, assetNames);
      const searchText = `${code} ${name}`.toLocaleLowerCase();
      return `<button type="button" class="fig-stress-picker-option" data-p63-asset-option data-search="${escape(searchText)}" data-gx="p63-chart-toggle-asset" data-code="${escape(code)}" aria-pressed="${selected}" ${query && !searchText.includes(query) ? "hidden" : ""}><span aria-hidden="true">${selected ? "☑" : "□"}</span>${escape(name === code ? code : `${name} (${code})`)}</button>`;
    }).join("");
    return `<details class="fig-stress-picker" ${state.pickerOpen ? "open" : ""}><summary>종목 표시 ${data.assets.filter(row => !hidden.has(row.asset_id)).length}/${data.assets.length}</summary><div class="fig-stress-picker-menu"><input type="search" data-p63-chart-search value="${escape(state.search)}" placeholder="종목명·코드 검색" aria-label="종목명 또는 코드 검색"><div class="fig-stress-picker-list">${options}</div></div></details>`;
  }

  function render({ run = null, mode = "market", model = "ridge", state: rawState = null, assetNames = null } = {}) {
    const state = stateOf(rawState), result = run?.stressResult;
    const data = result?.assets?.length ? derive(result) : null;
    const portfolio = mode === "portfolio", title = portfolio ? "개인 포트폴리오" : "지원 종목 동일금액 바스켓";
    const stamp = data && !data.error && data.basisDate ? ` · 모델 기준일 ${data.basisDate}` : "";
    const scope = portfolio ? "조회 시세 × 보유 주수 투입금액" : "지원 종목당 100만 원 가상 투입 · 코스피 지수 아님";
    const header = `<div class="fig-stress-head"><div><h3 class="fig-stress-title">${escape(title)}</h3><p class="fig-stress-meta">${escape(scope)} · ${escape(modelName(data?.model || model))} · ${escape(data?.horizon || 5)}거래일${escape(stamp)}</p></div></div>`;
    const buttons = `<div class="fig-stress-view" role="group" aria-label="그래프 표시 구분"><button type="button" data-gx="p63-chart-view" data-view="total" class="${state.view === "total" ? "is-active" : ""}" aria-pressed="${state.view === "total"}">${portfolio ? "전체 평가금액" : "전체 수익률"}</button><button type="button" data-gx="p63-chart-view" data-view="assets" class="${state.view === "assets" ? "is-active" : ""}" aria-pressed="${state.view === "assets"}">종목별</button></div>`;
    const series = `<div class="fig-stress-series" role="group" aria-label="시나리오 강조"><button type="button" data-gx="p63-chart-series" data-series="baseline" class="${state.series.baseline ? "is-active" : ""}" aria-pressed="${state.series.baseline}">무충격 기준선</button><button type="button" data-gx="p63-chart-series" data-series="scenario" class="${state.series.scenario ? "is-active" : ""}" aria-pressed="${state.series.scenario}">입력 충격</button></div>`;
    const controls = `<div class="fig-stress-controls">${buttons}${series}${state.view === "assets" ? picker(data,state,run,assetNames) : ""}<button type="button" class="fig-stress-reset" data-gx="p63-chart-reset" aria-label="그래프 표시 초기화">초기화</button></div>`;
    let plot;
    if (data?.error) plot = `<div class="fig-stress-empty" role="alert">${escape(data.error)}</div>`;
    else if (!data) plot = `<div class="fig-stress-empty" role="status">${escape(run?.azureStatus === "preparing" ? "실제 모델 계산 중입니다." : run?.azureError || "변수를 설정하고 PLAY를 누르면 실제 5거래일 결과가 표시됩니다.")}</div>`;
    else plot = state.view === "assets" ? assetRows(data, run, state, assetNames) : endpointSvg(data, mode, state);
    const foot = `<div class="fig-stress-foot"><span>과거 가격 이력 API 미연결 · 중간 시점 경로 없음</span><span>엔진 반환 단일 시점 결과 · 화면 값은 반올림</span></div>`;
    return `<div class="fig-stress-chart" data-stress-view="${state.view}">${header}${controls}<div class="fig-stress-plot">${plot}</div>${foot}<div class="fig-stress-tooltip" role="tooltip" hidden></div></div>`;
  }

  const api = { derive, render };
  root.whatIfStressChart = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
