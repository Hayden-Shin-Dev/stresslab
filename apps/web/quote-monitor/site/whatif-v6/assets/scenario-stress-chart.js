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
      compareAssets: Array.isArray(state.compareAssets) ? [...new Set(state.compareAssets.map(String))].slice(0, 4) : [],
      search: typeof state.search === "string" ? state.search : "",
      focus: ["baseline", "scenario"].includes(state.focus) ? state.focus : "both",
      layoutColumns: [1,2,3,4].includes(state.layoutColumns) ? state.layoutColumns : 2,
      focusedAsset: typeof state.focusedAsset === "string" ? state.focusedAsset : "",
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
    const visibleRows = data.assets.filter(row => !hidden.has(row.asset_id));
    const compare = new Set(state.compareAssets.filter(code => visibleRows.some(row => row.asset_id === code)));
    const rows = compare.size ? visibleRows.filter(row => compare.has(row.asset_id)) : visibleRows;
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
      const intervalTip = interval ? `${label} · 90% 모델 예측 구간 ${precisePct(interval.lower)} ~ ${precisePct(interval.upper)} · 모델 기준일 ${data.basisDate || "미확인"} · ${data.horizon}거래일` : "모델 구간 미제공";
      const intervalMark = interval && state.series.scenario ? `<span class="fig-stress-interval" style="left:${percent(interval.lower)}%;width:${(Number(percent(interval.upper)) - Number(percent(interval.lower))).toFixed(3)}%" tabindex="0" data-stress-tip="${escape(intervalTip)}" aria-label="${escape(intervalTip)}"><i class="fig-stress-cap fig-stress-cap-low" aria-hidden="true"></i><i class="fig-stress-cap fig-stress-cap-high" aria-hidden="true"></i></span>` : "";
      const point = (kind, value, visible) => visible ? `<span class="fig-stress-mark is-${kind} ${kind === "downside" ? "is-negative" : ""}" style="left:${percent(value)}%;opacity:${state.focus !== "both" && state.focus !== (kind === "baseline" ? "baseline" : "scenario") ? ".34" : "1"}" data-series="${kind}" tabindex="0" data-stress-tip="${escape(`${label} · ${kind === "baseline" ? "기준선·무충격" : kind === "upside" ? "긍정·90% 상단" : kind === "downside" ? "부정·90% 하단" : "입력 충격 중심값"} ${precisePct(value)} · 모델 기준일 ${data.basisDate || "미확인"} · ${data.horizon}거래일 단일 시점`)}" aria-label="${escape(`${label} ${kind === "baseline" ? "기준선" : kind === "upside" ? "긍정 90% 상단" : kind === "downside" ? "부정 90% 하단" : "입력 충격 중심값"} ${pct(value)}`)}"></span>` : "";
      const rangeLabel = interval && state.series.scenario ? `<span class="fig-stress-range-label">부정 ${escape(pct(interval.lower))} · 긍정 ${escape(pct(interval.upper))}</span>` : `<span class="fig-stress-range-label">${state.series.scenario ? "90% 구간 없음" : "시나리오 숨김"}</span>`;
      return `<div class="fig-stress-row" role="listitem"><strong title="${escape(label)}">${escape(label)}</strong><div class="fig-stress-track"><span class="fig-stress-zero" style="left:${percent(0)}%" aria-hidden="true"></span>${intervalMark}${point("baseline", row.baseline_model_return_pct, state.series.baseline)}${point("scenario", row.scenario_return_pct, state.series.scenario)}${interval && state.series.scenario ? point("downside", interval.lower, true) + point("upside", interval.upper, true) : ""}</div><span class="fig-stress-range-values">${rangeLabel}<b>${state.series.baseline ? `기준선 ${escape(pct(row.baseline_model_return_pct))}` : ""}</b></span></div>`;
    }).join("");
    const compareOptions = visibleRows.map(row => {
      const code = row.asset_id, name = displayName(code, run, assetNames), selected = compare.has(code);
      const disabled = !selected && compare.size >= 4;
      return `<button type="button" class="fig-stress-compare-option ${selected ? "is-selected" : ""}" data-gx="p63-chart-compare-asset" data-code="${escape(code)}" aria-pressed="${selected}" ${disabled ? "disabled" : ""}><span>${selected ? "✓" : "+"}</span>${escape(name)} (${escape(code)})</button>`;
    }).join("");
    const compareControl = `<div class="fig-stress-compare" role="group" aria-label="비교 종목 선택"><strong>비교 종목 <span>${compare.size}/4</span></strong><small>${compare.size ? "선택 종목만 표시 중" : "최대 4개까지 선택"}</small><div class="fig-stress-compare-options">${compareOptions}</div>${compare.size ? `<button type="button" class="fig-stress-compare-clear" data-gx="p63-chart-compare-clear">비교 선택 해제</button>` : ""}</div>`;
    return `<div class="fig-stress-asset-list" role="list" aria-label="종목별 5거래일 점 구간 그래프"><div class="fig-stress-legend"><span><i class="is-baseline"></i>기준선</span><span><i class="is-upside"></i>긍정 · 90% 상단</span><span><i class="is-downside"></i>부정 · 90% 하단</span></div>${compareControl}<div class="fig-stress-axis"><span>${compare.size ? `선택한 종목 비교 · ${rows.length}종목` : "종목별 5거래일 수익률"}</span><span>${escape(pct(low))} ~ ${escape(pct(high))} · 0% 기준선</span></div>${body}<p class="fig-stress-interval-note">긍정·부정은 해당 종목 엔진 90% 구간의 상단·하단 끝점입니다. 보장 수익이나 전체 시장 지수가 아닙니다.</p></div>`;
  }

  /* Stock comparison as ONE overlaid line chart (up to 4 stocks).
     Every series shares one unit: % change against that stock's immutable
     analysis price. Lines are only real observations; the engine's 5-day
     result is drawn as endpoint marks and a vertical 90% bar per stock —
     never as a connecting future path. Series differ by colour AND dash
     pattern AND marker shape, so the chart does not rely on colour alone. */
  const SERIES = [
    { color: "#8a4b14", dash: "", shape: "circle", label: "실선 · 원" },
    { color: "#2f6b4f", dash: "9 5", shape: "square", label: "긴 점선 · 사각" },
    { color: "#7a3e8c", dash: "3 4", shape: "diamond", label: "짧은 점선 · 마름모" },
    { color: "#a8740c", dash: "10 4 2 4", shape: "triangle", label: "점-대시 · 삼각" }
  ];
  function shapeSvg(shape, cx, cy, r, attrs) {
    if (shape === "square") return `<rect x="${(cx - r).toFixed(1)}" y="${(cy - r).toFixed(1)}" width="${(2 * r).toFixed(1)}" height="${(2 * r).toFixed(1)}" ${attrs}/>`;
    if (shape === "diamond") return `<polygon points="${cx},${(cy - r * 1.25).toFixed(1)} ${(cx + r * 1.25).toFixed(1)},${cy} ${cx},${(cy + r * 1.25).toFixed(1)} ${(cx - r * 1.25).toFixed(1)},${cy}" ${attrs}/>`;
    if (shape === "triangle") return `<polygon points="${cx},${(cy - r * 1.3).toFixed(1)} ${(cx + r * 1.2).toFixed(1)},${(cy + r * .9).toFixed(1)} ${(cx - r * 1.2).toFixed(1)},${(cy + r * .9).toFixed(1)}" ${attrs}/>`;
    return `<circle cx="${cx}" cy="${cy.toFixed ? cy.toFixed(1) : cy}" r="${r}" ${attrs}/>`;
  }

  function comparisonOverlay(data, run, state, assetNames, assetUniverse, quotes, priceSeries, selectedCode, historyStatus = {}) {
    const known = new Map();
    for (const asset of assetUniverse || []) {
      if (asset?.code && /^\d{6}$/.test(String(asset.code))) known.set(String(asset.code), String(asset.name || asset.code));
      else if (asset?.asset_id && /^\d{6}$/.test(String(asset.asset_id))) known.set(String(asset.asset_id), String(asset.name || asset.asset_id));
    }
    for (const row of data?.assets || []) known.set(row.asset_id, displayName(row.asset_id, run, assetNames));
    for (const code of Object.keys(priceSeries || {})) if (/^\d{6}$/.test(code) && !known.has(code)) known.set(code, displayName(code, run, assetNames));
    const options = [...known].map(([code, name]) => ({ code, name }));
    const selected = state.compareAssets.filter(code => known.has(code)).slice(0, 4);
    const codes = selected.length ? selected : (known.has(String(selectedCode || "")) ? [String(selectedCode)] : options.slice(0, 1).map(x => x.code));
    const compareOptions = options.map(({ code, name }) => {
      const active = selected.includes(code), disabled = !active && selected.length >= 4;
      return `<button type="button" class="fig-stress-compare-option ${active ? "is-selected" : ""}" data-gx="p63-chart-compare-asset" data-code="${escape(code)}" aria-pressed="${active}" ${disabled ? "disabled" : ""}><span>${active ? "✓" : "+"}</span>${escape(name)} (${escape(code)})</button>`;
    }).join("");
    const controls = `<div class="fig-stress-compare" role="group" aria-label="비교 종목 선택"><strong>종목 비교 <span>${selected.length}/4</span></strong><small>최대 4개 · 한 그래프에 겹쳐 표시 · 계산 대상 유지</small><div class="fig-stress-compare-options">${compareOptions}</div>${selected.length ? `<button type="button" class="fig-stress-compare-clear" data-gx="p63-chart-compare-clear">비교 선택 해제</button>` : ""}</div>`;
    const results = new Map((data?.assets || []).map(row => [row.asset_id, row]));
    const currentByCode = new Map((quotes || []).filter(q => q?.dateConfirmed === true && q?.code && Number.isFinite(Number(q.price)) && Number(q.price) > 0).map(q => [String(q.code), q]));
    const seriesFor = code => Array.isArray(priceSeries?.[code])
      ? [...new Map(priceSeries[code].filter(p => finite(p?.price) && p.price > 0 && Number.isFinite(Date.parse(p.at))).map(p => [Date.parse(p.at), p])).values()].sort((a, b) => Date.parse(a.at) - Date.parse(b.at)).slice(-1500)
      : [];
    const historyStates = codes.map(code => ({ code, name: known.get(code) || code, count: seriesFor(code).length }));
    const hasInsufficientHistory = !historyStates.length || historyStates.some(item => item.count < 2);
    const historyTitle = codes.some(code => historyStatus[code] === "loading") ? "과거 일봉 조회 중" : codes.some(code => historyStatus[code] === "error") ? "과거 일봉 조회 실패 · 수신된 관측값만 표시" : hasInsufficientHistory ? "시계열 데이터 부족" : "실제 시계열 표시 중";
    const historyCopy = codes.map(code => `${escape(known.get(code) || code)}: ${{ loading: "조회 중", ready: "일별 종가", empty: "조회 기간 데이터 없음", error: "조회 실패" }[historyStatus[code]] || "접속 후 수신 관측"} · ${seriesFor(code).length}건`).join(" / ") + " · 일봉과 장중 체결은 하나의 선에 혼합하지 않습니다.";
    const historyNotice = `<aside class="fig-stress-history-status ${hasInsufficientHistory ? "is-waiting" : "is-ready"}" role="note" aria-label="실제 종목 시계열 상태"><span class="fig-stress-history-status-mark" aria-hidden="true">${hasInsufficientHistory ? "i" : "✓"}</span><div><strong>${historyTitle}</strong><p>${historyCopy}</p>${codes.some(code => ["error", "empty"].includes(historyStatus[code])) ? `<button type="button" data-gx="p63-history-retry">일봉 다시 조회</button>` : ""}</div></aside>`;
    const pctText = value => `${value > 0 ? "+" : ""}${Number(value).toLocaleString("ko-KR", { maximumFractionDigits: 2 })}%`;
    const pointPrice = (price, ret) => price != null && finite(ret) ? price * (1 + ret / 100) : null;
    const forecastText = (price, ret, result) => finite(ret)
      ? `${price == null ? "기준가 미확인 · 가격 환산 보류" : money(price)} · ${pctText(ret)}`
      : result ? "모델 구간 미제공" : "분석 결과 없음 · PLAY 필요";

    // Per-stock series in % of the analysis price (or the last observation when
    // the analysis price is unknown, which the table states explicitly).
    const series = codes.map((code, i) => {
      const style = SERIES[i % SERIES.length], name = known.get(code) || code;
      const candles = seriesFor(code), quote = currentByCode.get(code);
      const basis = run?.priceSnapshot?.[code]?.price || null;
      const ref = basis || candles.at(-1)?.price || (quote?.price > 0 ? Number(quote.price) : null);
      const result = results.get(code), interval = result?.model_interval_90_return_pct;
      const history = ref ? candles.map(p => ({ t: Date.parse(p.at), at: p.at, price: p.price, v: (p.price / ref - 1) * 100 })) : [];
      return {
        code, name, style, candles, quote, basis, ref, result, history,
        scenario: finite(result?.scenario_return_pct) ? result.scenario_return_pct : null,
        baseline: finite(result?.baseline_model_return_pct) ? result.baseline_model_return_pct : null,
        lower: interval && finite(interval.lower) ? interval.lower : null,
        upper: interval && finite(interval.upper) ? interval.upper : null
      };
    });
    const focus = state.focusedAsset && codes.includes(state.focusedAsset) ? state.focusedAsset : "";
    const values = [0];
    for (const s of series) {
      for (const p of s.history) values.push(p.v);
      for (const v of [s.scenario, s.baseline, s.lower, s.upper]) if (finite(v)) values.push(v);
    }
    let svg = `<div class="fig-stress-time-empty" role="status">실시간 실제 시세나 분석 결과를 받으면 종목 비교 그래프가 표시됩니다.</div>`;
    const plotted = series.some(s => s.history.length || finite(s.scenario) || finite(s.baseline));
    if (plotted) {
      const min = Math.min(...values), max = Math.max(...values), span = Math.max(max - min, .5);
      const lo = min - span * .12, hi = max + span * .12;
      const top = 28, bottom = 236, left = 70, histRight = 440, nowX = 500, endX = 620;
      const y = v => top + (hi - v) / (hi - lo) * (bottom - top);
      const times = series.flatMap(s => s.history.map(p => p.t));
      const t0 = Math.min(...times), t1 = Math.max(...times);
      const x = t => times.length < 2 || t1 === t0 ? histRight : left + (t - t0) / (t1 - t0) * (histRight - left);
      const grid = [0, 1, 2, 3, 4].map(k => {
        const val = hi - (hi - lo) * k / 4, yy = y(val);
        return `<line x1="${left}" y1="${yy.toFixed(1)}" x2="${endX + 80}" y2="${yy.toFixed(1)}" class="fig-stress-gridline"/><text x="${left - 8}" y="${(yy + 4).toFixed(1)}" text-anchor="end" class="fig-stress-y-label">${escape(pctText(val))}</text>`;
      }).join("");
      const zero = `<line x1="${left}" y1="${y(0).toFixed(1)}" x2="${endX + 80}" y2="${y(0).toFixed(1)}" class="fig-stress-zero-line"/>`;
      const nowLine = `<line x1="${nowX}" y1="${top - 10}" x2="${nowX}" y2="${bottom}" class="fig-stress-now-line"/><text x="${nowX}" y="${bottom + 20}" text-anchor="middle" class="fig-stress-x-label">분석 기준가</text>`;
      const futureLabel = data ? `<text x="${endX + 22}" y="${bottom + 20}" text-anchor="middle" class="fig-stress-x-label">+${escape(data.horizon)}거래일 종점</text>` : "";
      const dateLabel = times.length ? `<text x="${left}" y="${bottom + 20}" class="fig-stress-x-label">${escape(new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit" }).format(new Date(t0)))}</text>` : "";
      const layers = series.map((s, i) => {
        const { color, dash, shape } = s.style;
        const dim = focus && focus !== s.code ? " is-dimmed" : "";
        const dashAttr = dash ? ` stroke-dasharray="${dash}"` : "";
        const pts = s.history.map(p => `${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
        const line = s.history.length > 1
          ? `<polyline points="${pts}" class="fig-stress-actual-line" style="stroke:${color}"${dashAttr}><title>${escape(s.name)} 실제 관측 ${s.history.length}건 · 분석 기준가 대비 %</title></polyline>`
          : s.history.length === 1 ? shapeSvg(shape, x(s.history[0].t).toFixed(1), y(s.history[0].v), 4, `class="fig-stress-actual-dot" style="stroke:${color}"`) : "";
        const basisDot = s.basis ? shapeSvg(shape, nowX, y(0), 4.5, `class="fig-stress-current-dot" style="stroke:${color};fill:#fffcf3"`) : "";
        const ex = endX + i * 14;
        // Without the analysis price the history is relative to the last
        // observation while model returns are relative to the analysis price;
        // mixing them on one axis would mislead, so endpoints are table-only.
        if (!s.basis) return `<g class="fig-stress-series${dim}" data-code="${escape(s.code)}">${line}</g>`;
        const band = finite(s.lower) && finite(s.upper)
          ? `<line class="fig-stress-model-range" x1="${ex}" y1="${y(s.lower).toFixed(1)}" x2="${ex}" y2="${y(s.upper).toFixed(1)}" style="stroke:${color}"><title>${escape(s.name)} 90% 조건부 모델 구간 ${escape(pctText(s.lower))} ~ ${escape(pctText(s.upper))}</title></line>`
          : "";
        const marks = [
          { klass: "positive", label: "긍정 · 90% 상단", v: s.upper, r: 3, fill: color },
          { klass: "baseline", label: "기준선 · 무충격", v: s.baseline, r: 5, fill: "#fffcf3" },
          { klass: "scenario", label: "입력 중심", v: s.scenario, r: 6, fill: color },
          { klass: "negative", label: "부정 · 90% 하단", v: s.lower, r: 3, fill: color }
        ].filter(m => finite(m.v)).map(m => {
          const price = pointPrice(s.basis, m.v);
          const text = `${s.name} ${m.label} ${pctText(m.v)}${price != null ? " · " + money(price) : ""}`;
          return `<g class="fig-stress-forecast-point is-${m.klass}" tabindex="0" aria-label="${escape(text)}">${shapeSvg(shape, ex, y(m.v), m.r, `style="stroke:${color};fill:${m.fill}"`)}<title>${escape(text)}</title></g>`;
        }).join("");
        return `<g class="fig-stress-series${dim}" data-code="${escape(s.code)}">${line}${basisDot}${band}${marks}</g>`;
      }).join("");
      svg = `<svg class="fig-stress-time-svg fig-stress-overlay-svg" viewBox="0 0 720 270" role="img" aria-label="${escape(series.map(s => s.name).join(", "))} 실제 관측 시계열(분석 기준가 대비 %)과 5거래일 모델 종점 결과">${grid}${zero}${nowLine}${layers}${dateLabel}${futureLabel}</svg>`;
    }
    const legend = `<div class="fig-stress-overlay-legend" role="group" aria-label="비교 종목 범례 · 선택하면 해당 종목 강조">${series.map(s => {
      const { color, dash, shape, label } = s.style;
      const swatch = `<svg viewBox="0 0 34 14" width="34" height="14" aria-hidden="true"><line x1="1" y1="7" x2="33" y2="7" style="stroke:${color};stroke-width:2.5"${dash ? ` stroke-dasharray="${dash}"` : ""}/>${shapeSvg(shape, 17, 7, 4, `style="stroke:${color};fill:${color}"`)}</svg>`;
      return `<button type="button" data-gx="p63-chart-card-focus" data-code="${escape(focus === s.code ? "" : s.code)}" aria-pressed="${focus === s.code}" title="${escape(label)}">${swatch}<span>${escape(s.name)} (${escape(s.code)})</span></button>`;
    }).join("")}${focus ? `<button type="button" data-gx="p63-chart-card-focus" data-code="">전체 차트로 복귀</button>` : ""}</div>`;
    const marksLegend = `<p class="fig-stress-overlay-key">선 = 실제 관측(분석 기준가 대비 %) · 큰 채운 도형 = 입력 충격 중심 · 빈 도형 = 무충격 기준선 · 세로 막대 = 90% 조건부 구간 · 미래 경로는 그리지 않습니다</p>`;
    const body = series.map(s => {
      const latest = s.quote ? money(Number(s.quote.price)) : s.candles.at(-1) ? money(s.candles.at(-1).price) : "-";
      return `<tr data-code="${escape(s.code)}"><th scope="row"><span class="fig-stress-overlay-swatch" style="background:${s.style.color}" aria-hidden="true"></span>${escape(s.name)} <small>${escape(s.code)}</small></th><td>${s.basis ? escape(money(s.basis)) : "기준가 미확인"}</td><td class="is-scenario">${escape(forecastText(pointPrice(s.basis, s.scenario), s.scenario, s.result))}</td><td class="is-baseline">${escape(forecastText(pointPrice(s.basis, s.baseline), s.baseline, s.result))}</td><td class="is-negative">${escape(forecastText(pointPrice(s.basis, s.lower), s.lower, s.result))}</td><td class="is-positive">${escape(forecastText(pointPrice(s.basis, s.upper), s.upper, s.result))}</td><td>${escape(latest)}</td></tr>`;
    }).join("");
    const table = `<div class="fig-stress-overlay-tablewrap"><table class="fig-stress-value-table fig-stress-overlay-table"><caption>종목별 5거래일 결과 · 분석 기준가 환산 가격과 수익률</caption><thead><tr><th scope="col">종목</th><th scope="col">분석 기준가</th><th scope="col">입력 충격 중심</th><th scope="col">기준선 · 무충격</th><th scope="col">부정 · 90% 하단</th><th scope="col">긍정 · 90% 상단</th><th scope="col">최신 참고 시세</th></tr></thead><tbody>${body}</tbody></table></div>`;
    return `<div class="fig-stress-comparison-view">${controls}${historyNotice}<figure class="fig-stress-overlay">${legend}${svg}${marksLegend}</figure>${codes.length ? table : `<p class="fig-stress-empty" role="status">종목을 선택하면 실제 시세 시계열과 스트레스테스트 결과를 함께 확인합니다.</p>`}<p class="fig-stress-interval-note">엔진은 5거래일 단일 시점 결과만 반환합니다. 실제 과거 관측값은 선, 긍정·기준선·부정 결과는 5거래일 종점으로만 표시합니다. 미래 중간 경로는 만들지 않습니다.</p></div>`;
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

  function render({ run = null, mode = "market", model = "ridge", state: rawState = null, assetNames = null, assetUniverse = [], quotes = [], priceSeries = {}, selectedCode = "", historyStatus = {} } = {}) {
    const state = stateOf(rawState), result = run?.stressResult;
    const data = result?.assets?.length ? derive(result) : null;
    const portfolio = mode === "portfolio", title = portfolio ? "나의 포트폴리오 스트레스 결과" : "종목별 스트레스 비교";
    const stamp = data && !data.error && data.basisDate ? ` · 모델 기준일 ${data.basisDate}` : "";
    const scope = portfolio ? "선택한 보유 종목 범위의 평가금액 · 미선택 보유분 제외" : "종목별 독립 계산 · 포트폴리오 합계와 분리 · KOSPI 지수 아님";
    const modeSwitch = `<div class="fig-stress-mode-switch" role="group" aria-label="분석 공간 선택"><button type="button" data-gx="p63-chart-mode" data-mode="market" aria-pressed="${!portfolio}">종목 비교</button><button type="button" data-gx="p63-chart-mode" data-mode="portfolio" aria-pressed="${portfolio}">나의 포트폴리오</button></div>`;
    const header = `<div class="fig-stress-head"><div><h3 class="fig-stress-title">${escape(title)}</h3><p class="fig-stress-meta">${escape(scope)} · ${escape(modelName(data?.model || model))} · ${escape(data?.horizon || 5)}거래일${escape(stamp)}</p></div>${modeSwitch}</div>`;
    const buttons = portfolio ? `<div class="fig-stress-view" role="group" aria-label="그래프 표시 구분"><button type="button" data-gx="p63-chart-view" data-view="total" class="${state.view === "total" ? "is-active" : ""}" aria-pressed="${state.view === "total"}">전체 평가금액</button><button type="button" data-gx="p63-chart-view" data-view="assets" class="${state.view === "assets" ? "is-active" : ""}" aria-pressed="${state.view === "assets"}">종목별</button></div>` : `<div class="fig-stress-view" role="note">${data && !data.error ? `${data.assets.length}개 종목별 결과` : "실시간 시계열 · 실행 결과"}</div>`;
    const series = portfolio ? "" : `<div class="fig-stress-legend"><span><i class="is-baseline"></i>기준선</span><span><i class="is-upside"></i>긍정 · 90% 상단</span><span><i class="is-downside"></i>부정 · 90% 하단</span></div>`;
    const controls = `<div class="fig-stress-controls">${buttons}${series}${state.view === "assets" ? picker(data,state,run,assetNames) : ""}<button type="button" class="fig-stress-reset" data-gx="p63-chart-reset" aria-label="그래프 표시 초기화">초기화</button></div>`;
    let plot;
    if (data?.error) plot = `<div class="fig-stress-empty" role="alert">${escape(data.error)}</div>`;
    else if (!portfolio) plot = comparisonOverlay(data && !data.error ? data : null, run, state, assetNames, assetUniverse, quotes, priceSeries, selectedCode, historyStatus);
    else if (!data) plot = `<div class="fig-stress-empty" role="status">${escape(run?.azureStatus === "preparing" ? "실제 모델 계산 중입니다." : run?.azureError || "변수를 설정하고 PLAY를 누르면 실제 5거래일 결과가 표시됩니다.")}</div>`;
    else plot = state.view === "assets" ? assetRows(data, run, state, assetNames) : endpointSvg(data, mode, state);
    const foot = `<div class="fig-stress-foot"><span>${portfolio ? "내 포트폴리오 통합 결과 · 그래프 위 ‘종목 비교’에서 전환" : "종목별 개별 결과 · 포트폴리오 합산 제외"}</span><span>엔진의 5거래일 결과는 종점만 표시</span></div>`;
    return `<div class="fig-stress-chart" data-stress-mode="${portfolio ? "portfolio" : "comparison"}" data-stress-view="${state.view}">${header}${controls}<div class="fig-stress-plot">${plot}</div>${foot}<div class="fig-stress-tooltip" role="tooltip" hidden></div></div>`;
  }

  const api = { derive, render };
  root.whatIfStressChart = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
