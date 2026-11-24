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

  function comparisonCards(data, run, state, assetNames, assetUniverse, quotes, priceSeries, selectedCode, historyStatus = {}) {
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
    const controls = `<div class="fig-stress-compare" role="group" aria-label="비교 종목 선택"><strong>종목 비교 <span>${selected.length}/4</span></strong><small>최대 4개 · 표시 선택만 변경 · 계산 대상 유지</small><div class="fig-stress-compare-options">${compareOptions}</div>${selected.length ? `<button type="button" class="fig-stress-compare-clear" data-gx="p63-chart-compare-clear">비교 선택 해제</button>` : ""}</div>`;
    const results = new Map((data?.assets || []).map(row => [row.asset_id, row]));
    const currentByCode = new Map((quotes || []).filter(q => q?.dateConfirmed === true && q?.code && Number.isFinite(Number(q.price)) && Number(q.price) > 0).map(q => [String(q.code), q]));
    const seriesFor = code => Array.isArray(priceSeries?.[code])
      ? [...new Map(priceSeries[code].filter(p => finite(p?.price) && p.price > 0 && Number.isFinite(Date.parse(p.at))).map(p=>[Date.parse(p.at),p])).values()].sort((a,b)=>Date.parse(a.at)-Date.parse(b.at)).slice(-1500)
      : [];
    const historyStates = codes.map(code => ({
      code,
      name: known.get(code) || code,
      count: seriesFor(code).length,
      quote: currentByCode.get(code)
    }));
    const historyDetail = historyStates.map(item => `${item.name} ${item.count}/2`).join(" · ");
    const hasInsufficientHistory = !historyStates.length || historyStates.some(item => item.count < 2);
    const historyTitle = codes.some(code=>historyStatus[code]==='loading') ? "과거 일봉 조회 중" : codes.some(code=>historyStatus[code]==='error') ? "과거 일봉 조회 실패 · 수신된 관측값만 표시" : hasInsufficientHistory ? "시계열 데이터 부족" : "실제 시계열 표시 중";
    const historyCopy = codes.map(code=>`${escape(known.get(code)||code)}: ${{loading:'조회 중',ready:'일별 종가',empty:'조회 기간 데이터 없음',error:'조회 실패'}[historyStatus[code]]||'접속 후 수신 관측'} · ${seriesFor(code).length}건`).join(' / ') + ' · 일봉과 장중 체결은 하나의 선에 혼합하지 않습니다.';
    const historyNotice = `<aside class="fig-stress-history-status ${hasInsufficientHistory ? "is-waiting" : "is-ready"}" role="note" aria-label="실제 종목 시계열 상태"><span class="fig-stress-history-status-mark" aria-hidden="true">${hasInsufficientHistory ? "i" : "✓"}</span><div><strong>${historyTitle}</strong><p>${historyCopy}</p>${codes.some(code=>["error","empty"].includes(historyStatus[code]))?'<button type="button" data-gx="p63-history-retry">일봉 다시 조회</button>':""}</div></aside>`;
    const pctText = value => `${value > 0 ? "+" : ""}${Number(value).toLocaleString("ko-KR", { maximumFractionDigits: 2 })}%`;
    const pointPrice = (price, ret) => price != null && finite(ret) ? price * (1 + ret / 100) : null;
    const renderCard = code => {
      const name = known.get(code) || code, quote = currentByCode.get(code), candles = seriesFor(code);
      const lastSeries = candles.at(-1);
      const spot = quote?.price > 0 ? Number(quote.price) : lastSeries?.price || null;
      const result = results.get(code), interval = result?.model_interval_90_return_pct;
      const baselineRet = finite(result?.baseline_model_return_pct) ? result.baseline_model_return_pct : null;
      const positiveRet = interval && finite(interval.upper) ? interval.upper : null;
      const negativeRet = interval && finite(interval.lower) ? interval.lower : null;
      const basis = run?.priceSnapshot?.[code]?.price || null;
      const scenario = pointPrice(basis,result?.scenario_return_pct);
      const baseline = pointPrice(basis, baselineRet), positive = pointPrice(basis, positiveRet), negative = pointPrice(basis, negativeRet);
      const values = [...candles.map(p => p.price), ...(spot ? [spot] : []), basis, baseline, scenario, positive, negative].filter(finite);
      let svg = `<div class="fig-stress-time-empty" role="status">${spot ? `현재 관측값 ${money(spot)} · 새 체결이 들어오면 실제 시계열이 쌓입니다.` : "실시간 실제 시세를 받으면 종목 시계열이 표시됩니다."}</div>`;
      if (values.length) {
        const min = Math.min(...values), max = Math.max(...values), span = Math.max(max - min, Math.max(Math.abs(max) * .004, 1)), lo = min - span * .12, hi = max + span * .12;
        const x = i => candles.length <= 1 ? 250 : 42 + i / (candles.length - 1) * 238;
        const y = value => 34 + (hi - value) / (hi - lo) * 150;
        const grid = [0, 1, 2, 3].map(i => { const val = hi - (hi - lo) * i / 3, yy = 34 + i * 50; return `<line x1="42" y1="${yy}" x2="450" y2="${yy}" class="fig-stress-gridline"/><text x="35" y="${yy + 4}" text-anchor="end" class="fig-stress-y-label">${escape(money(val))}</text>`; }).join("");
        const actual = candles.map((p, i) => `${x(i).toFixed(1)},${y(p.price).toFixed(1)}`).join(" ");
        const actualLine = candles.length > 1 ? `<polyline points="${actual}" class="fig-stress-actual-line"/>` : candles.length === 1 ? `<circle cx="${x(0)}" cy="${y(candles[0].price)}" r="4" class="fig-stress-actual-dot"><title>실제 관측 ${escape(money(candles[0].price))} · ${escape(candles[0].at)}</title></circle>` : "";
        const actualDots = candles.length > 1 ? candles.filter((_, i) => i === 0 || i === candles.length - 1 || i % Math.ceil(candles.length / 8) === 0).map(p => { const i = candles.indexOf(p); return `<circle cx="${x(i)}" cy="${y(p.price)}" r="2.7" class="fig-stress-actual-dot"><title>실제 관측 ${escape(money(p.price))} · ${escape(p.at)}</title></circle>`; }).join("") : "";
        const band = finite(negative)&&finite(positive)?`<line class="fig-stress-model-range" x1="420" y1="${y(negative)}" x2="420" y2="${y(positive)}"><title>90% 조건부 모델 구간 · ${escape(pctText(negativeRet))} ~ ${escape(pctText(positiveRet))}</title></line>`:"";
        const marks = [
          { label: "긍정 · 90% 상단", ret: positiveRet, value: positive, klass: "positive" },
          { label: "기준선 · 무충격", ret: baselineRet, value: baseline, klass: "baseline" },
          { label: "입력 중심", ret: result?.scenario_return_pct, value: scenario, klass: "scenario" },
          { label: "부정 · 90% 하단", ret: negativeRet, value: negative, klass: "negative" },
        ].filter(point => finite(point.value)).map(point => `<g class="fig-stress-forecast-point is-${point.klass}" tabindex="0" aria-label="${escape(name)} ${escape(point.label)} ${escape(pctText(point.ret))} · ${escape(money(point.value))}"><circle cx="420" cy="${y(point.value)}" r="6"/><title>${escape(point.label)} ${escape(pctText(point.ret))} · ${escape(money(point.value))}</title></g><text x="432" y="${y(point.value) + 4}" class="fig-stress-forecast-label is-${point.klass}">${escape(point.label.split(" · ")[0])}</text>`).join("");
        const split = basis ? `<line x1="340" y1="22" x2="340" y2="196" class="fig-stress-now-line"/><circle cx="340" cy="${y(basis)}" r="4.5" class="fig-stress-current-dot"><title>분석 당시 기준가 ${escape(money(basis))}</title></circle><text x="340" y="214" text-anchor="middle" class="fig-stress-x-label">분석 기준가</text>` : "";
        const dateLabel = candles.length ? `<text x="42" y="214" class="fig-stress-x-label">${escape(new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", ...(historyStatus[code]==="ready"?{year:"2-digit"}:{hour:"2-digit",minute:"2-digit",hourCycle:"h23"}) }).format(new Date(candles[0].at)))}</text><text x="280" y="214" text-anchor="end" class="fig-stress-x-label">${escape(new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", month: "2-digit", day: "2-digit", ...(historyStatus[code]==="ready"?{year:"2-digit"}:{hour:"2-digit",minute:"2-digit",hourCycle:"h23"}) }).format(new Date(lastSeries.at)))}</text>` : "";
        const futureLabel = result ? `<text x="420" y="214" text-anchor="middle" class="fig-stress-x-label">+${escape(data.horizon)}거래일</text>` : "";
        svg = `<svg class="fig-stress-time-svg" viewBox="-60 0 560 232" role="img" aria-label="${escape(name)} 실제 관측 시계열과 5거래일 모델 종점 결과">${grid}${actualLine}${actualDots}${split}${band}${marks}${dateLabel}${futureLabel}</svg>`;
      }
      const forecastText = (price, ret) => finite(ret)
        ? `${price == null ? "기준가 미확인 · 가격 환산 보류" : money(price)} · ${pctText(ret)}`
        : result ? "모델 구간 미제공" : "분석 결과 없음 · PLAY 필요";
      const rows = [
        [quote ? "최신 참고 시세" : "마지막 과거 관측", spot ? money(spot) : "시세 미확인", quote?.tradeAt || lastSeries?.at || "시각 미확인", "observed"],
        ["분석 당시 기준가", basis ? money(basis) : "기준가 미확인", run?.priceSnapshot?.[code]?.at || "가격 환산 보류", "observed"],
        ["긍정 · 90% 상단", forecastText(positive,positiveRet), "조건부 구간 상단", "positive"],
        ["기준선 · 무충격", forecastText(baseline,baselineRet), "무충격 중심값 · 구간 중심 아님", "baseline"],
        ["입력 충격 중심", forecastText(pointPrice(basis,result?.scenario_return_pct),result?.scenario_return_pct), "충격 조건부 중심값", "scenario"],
        ["부정 · 90% 하단", forecastText(negative,negativeRet), "조건부 구간 하단", "negative"],
      ];
      const table = `<table class="fig-stress-value-table"><thead><tr><th>구분</th><th>환산 가격 · 수익률</th><th>기준</th></tr></thead><tbody>${rows.map(row => `<tr class="is-${row[3]}"><th>${escape(row[0])}</th><td>${escape(row[1])}</td><td>${escape(row[2])}</td></tr>`).join("")}</tbody></table>`;
      const historyLabel = candles.length >= 2
        ? `실제 관측 ${candles.length}건 · 선 표시`
        : candles.length === 1
          ? "실제 관측 1/2건 · 다음 확인 시세를 기다리는 중"
          : spot
            ? "현재값은 있으나 확인된 체결 시각이 없어 선에 포함하지 않음"
            : "확인된 실제 시세 시각을 기다리는 중";
      const emptyHistory = `<div class="fig-stress-series-note ${candles.length < 2 ? "is-waiting" : "is-ready"}"><strong>${escape(historyLabel)}</strong><span>${candles.length < 2 ? "선 표시에 필요한 실제 가격이 부족합니다. 일봉 조회 상태를 확인해 주세요." : "실제 수신 가격을 날짜순으로 표시합니다. 모델 가격은 분석 당시 기준 가격으로 환산합니다."}</span></div>`;
      return `<article class="fig-stress-compare-card"><header><h4>${escape(name)}</h4><strong>${escape(code)}</strong><button type="button" data-gx="p63-chart-card-focus" data-code="${escape(code)}" aria-label="${escape(name)} 차트 집중 보기">집중 보기</button><small>${result ? `실행 결과 · ${escape(data.horizon)}거래일` : "실행 전"}</small></header><small class="handoff-chart-scroll-hint">좁은 창에서는 그래프·수치 표를 좌우로 탐색할 수 있습니다.</small>${svg}${emptyHistory}${table || (!spot ? `<p class="fig-stress-time-empty">실시간 시세가 연결되면 그래프와 현재값을 표시합니다.</p>` : "")}</article>`;
    };
    const visible = state.focusedAsset && codes.includes(state.focusedAsset) ? [state.focusedAsset] : codes;
    const cards = visible.map(renderCard).join("");
    const layouts = `<div class="fig-stress-controls" role="group" aria-label="차트 배열">${[1,2,3,4].map(n=>`<button type="button" data-gx="p63-chart-columns" data-columns="${n}" aria-pressed="${state.layoutColumns===n}">${n}열</button>`).join("")}${state.focusedAsset?'<button type="button" data-gx="p63-chart-card-focus" data-code="">전체 차트로 복귀</button>':''}</div>`;
    return `<div class="fig-stress-comparison-view">${controls}${layouts}${historyNotice}<div class="fig-stress-compare-grid" style="grid-template-columns:repeat(${state.focusedAsset?1:Math.min(state.layoutColumns,Math.max(1,visible.length))},minmax(0,1fr))">${cards || `<p class="fig-stress-empty" role="status">종목을 선택하면 실제 시세 시계열과 스트레스테스트 결과를 함께 확인합니다.</p>`}</div><p class="fig-stress-interval-note">엔진은 5거래일 단일 시점 결과만 반환합니다. 실제 과거 관측값은 실선, 긍정·기준선·부정 결과는 5거래일 종점으로만 표시합니다. 미래 중간 경로는 만들지 않습니다.</p></div>`;
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
    else if (!portfolio) plot = comparisonCards(data && !data.error ? data : null, run, state, assetNames, assetUniverse, quotes, priceSeries, selectedCode, historyStatus);
    else if (!data) plot = `<div class="fig-stress-empty" role="status">${escape(run?.azureStatus === "preparing" ? "실제 모델 계산 중입니다." : run?.azureError || "변수를 설정하고 PLAY를 누르면 실제 5거래일 결과가 표시됩니다.")}</div>`;
    else plot = state.view === "assets" ? assetRows(data, run, state, assetNames) : endpointSvg(data, mode, state);
    const foot = `<div class="fig-stress-foot"><span>${portfolio ? "내 포트폴리오 통합 결과 · 그래프 위 ‘종목 비교’에서 전환" : "종목별 개별 결과 · 포트폴리오 합산 제외"}</span><span>엔진의 5거래일 결과는 종점만 표시</span></div>`;
    return `<div class="fig-stress-chart" data-stress-mode="${portfolio ? "portfolio" : "comparison"}" data-stress-view="${state.view}">${header}${controls}<div class="fig-stress-plot">${plot}</div>${foot}<div class="fig-stress-tooltip" role="tooltip" hidden></div></div>`;
  }

  const api = { derive, render };
  root.whatIfStressChart = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
