/* The deployed stress API returns one five-trading-day endpoint per asset.
   Keep its numbers separate from display coordinates; never synthesize a path. */
(function (root) {
  "use strict";

  const escape = value => String(value ?? "").replace(/[&<>"']/g, ch => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[ch]);
  const finite = value => typeof value === "number" && Number.isFinite(value);
  const money = value => `${Math.round(value).toLocaleString("ko-KR")}원`;
  const pct = value => `${value > 0 ? "+" : ""}${value.toLocaleString("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
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

  const periods = new Map([
    ["day", "일봉"], ["week", "주봉"], ["month", "월봉"], ["year", "연봉"],
    ...[1, 3, 5, 10, 15, 30, 45, 60].map(n => [n === 1 ? "minute" : "minute-" + n, n + "분봉"]),
    ["tick", "1틱"]
  ]);

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
      period: periods.has(state.period) ? state.period : "day",
      representation: ["candle", "ohlc"].includes(state.representation) ? state.representation : "line",
      pickerOpen: state.pickerOpen === true,
      visible: {history:state.visible?.history!==false,positive:state.visible?.positive!==false,baseline:state.visible?.baseline!==false,negative:state.visible?.negative!==false},
      limit: Number.isInteger(state.limit)?Math.max(10,Math.min(1500,state.limit)):60,
      offset: Number.isInteger(state.offset)?Math.max(0,state.offset):0
    };
  }

  function displayName(code, run, assetNames) {
    const lotName = (run?.portfolioLots || []).find(lot => String(lot.code) === code)?.name;
    const masterName = assetNames instanceof Map ? assetNames.get(code) : assetNames?.[code];
    return String(lotName || masterName || code);
  }

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

  function comparisonOverlay(data, run, state, assetNames, assetUniverse, quotes, priceSeries, historyStatus = {}, expanded = false) {
    const known = new Map();
    for (const asset of assetUniverse || []) {
      if (asset?.code && /^\d{6}$/.test(String(asset.code))) known.set(String(asset.code), String(asset.name || asset.code));
      else if (asset?.asset_id && /^\d{6}$/.test(String(asset.asset_id))) known.set(String(asset.asset_id), String(asset.name || asset.asset_id));
    }
    for (const row of data?.assets || []) known.set(row.asset_id, displayName(row.asset_id, run, assetNames));
    for (const code of Object.keys(priceSeries || {})) if (/^\d{6}$/.test(code) && !known.has(code)) known.set(code, displayName(code, run, assetNames));
    const codes = state.compareAssets.filter(code => known.has(code));
    const results = new Map((data?.assets || []).map(row => [row.asset_id, row]));
    const currentByCode = new Map((quotes || []).filter(q => q?.dateConfirmed === true && q?.code && Number.isFinite(Number(q.price)) && Number(q.price) > 0).map(q => [String(q.code), q]));
    const { period, representation } = state;
    const periodName = periods.get(period);
    const intraday = period === "tick" || period.startsWith("minute");
    const minutes = Number(period.split("-")[1]) || 1;
    const seriesFor = code => {
      const raw = Array.isArray(priceSeries?.[code]) ? priceSeries[code] : [];
      const observations = raw.filter(p => finite(p?.price) && p.price > 0 && Number.isFinite(Date.parse(p.at)) &&
        (intraday ? p.interval !== "1d" : p.interval === "1d"));
      const sorted = [...new Map(observations.map(p => [Date.parse(p.at), p])).values()].sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
      if (period === "tick" || period === "day") return sorted.slice(-1500);
      const buckets = new Map();
      for (const row of sorted) {
        const t = Date.parse(row.at);
        const date = new Date(t + 9 * 3600000);
        const day = Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate());
        let key;
        if (intraday) key = Math.floor((t + 9 * 3600000) / (minutes * 60000));
        else if (period === "year") key = date.getUTCFullYear();
        else if (period === "month") key = date.getUTCFullYear() * 12 + date.getUTCMonth();
        else key = day - (date.getUTCDay() + 6) % 7 * 86400000;
        const bucket = buckets.get(key);
        if (!bucket) buckets.set(key, { ...row, open: row.open ?? row.price, high: row.high ?? row.price, low: row.low ?? row.price, count: row.count || 1 });
        else buckets.set(key, { ...row, open:bucket.open, high: Math.max(bucket.high, row.high ?? row.price), low: Math.min(bucket.low, row.low ?? row.price), count: bucket.count + (row.count || 1) });
      }
      return [...buckets.values()].slice(-1500);
    };
    const fullHistory = new Map(codes.map(code => [code, seriesFor(code)]));
    const periodDates=[...new Set([...fullHistory.values()].flatMap(rows=>rows.map(row=>Date.parse(row.at))))].sort((a,b)=>a-b);
    const offset=Math.min(state.offset,Math.max(0,periodDates.length-state.limit));
    const windowEnd=periodDates.length-offset, windowStart=Math.max(0,windowEnd-state.limit);
    const firstTime=periodDates[windowStart],lastTime=periodDates[windowEnd-1];
    const observationsByCode=new Map([...fullHistory].map(([code,rows])=>[code,rows.filter(row=>Date.parse(row.at)>=firstTime&&Date.parse(row.at)<=lastTime)]));
    const missingHistory=!periodDates.length;
    const historyNotice=missingHistory&&codes.length?`<p class="scenario-chart-status" role="status">${codes.some(code=>historyStatus[code]==='loading')?'시세를 불러오는 중입니다.':intraday?'장중 체결 내역이 없습니다.':'이 기간의 시세가 없습니다.'} ${!intraday&&codes.some(code=>['error','empty'].includes(historyStatus[code]))?'<button type="button" data-gx="p63-history-retry">일봉 다시 조회</button>':''}</p>`:'';
    const pctText = value => `${value > 0 ? "+" : ""}${Number(value).toLocaleString("ko-KR", { maximumFractionDigits: 2 })}%`;
    const pointPrice = (price, ret) => price != null && finite(ret) ? price * (1 + ret / 100) : null;
    const forecastText = (price, ret) => finite(ret)
      ? (price==null?pctText(ret):`${money(price)} · ${pctText(ret)}`) : "—";

    // Per-stock series in % of the analysis price (or the last observation when
    // the analysis price is unknown, which the table states explicitly).
    const series = codes.map((code, i) => {
      const style = SERIES[i % SERIES.length], name = known.get(code) || code;
      const candles = observationsByCode.get(code), quote = currentByCode.get(code);
      const basis = run?.priceSnapshot?.[code]?.price || null;
      const ref = basis || fullHistory.get(code).at(-1)?.price || (quote?.price > 0 ? Number(quote.price) : null);
      const result = results.get(code), interval = result?.model_interval_90_return_pct;
      const history = ref ? candles.map(p => ({ t: Date.parse(p.at), at: p.at, price: p.price, candle: (p.count > 1 || [p.open,p.high,p.low].every(finite)) ? p : null, v: (p.price / ref - 1) * 100 })) : [];
      return {
        code, name, style, candles, quote, basis, ref, result, history,
        plotResult: Boolean(result && offset===0 && (state.visible.baseline || state.visible.positive || state.visible.negative)),
        scenario: finite(result?.scenario_return_pct) ? result.scenario_return_pct : null,
        baseline: finite(result?.baseline_model_return_pct) ? result.baseline_model_return_pct : null,
        lower: state.visible.negative && interval && finite(interval.lower) ? interval.lower : null,
        upper: state.visible.positive && interval && finite(interval.upper) ? interval.upper : null
      };
    });
    const focus = state.focusedAsset && codes.includes(state.focusedAsset) ? state.focusedAsset : "";
    const plotWidth = expanded ? Math.max(340, innerWidth - 32) : 823;
    const plotHeight = expanded ? Math.max(240, innerHeight - 78) : 447;
    const values = [0];
    for (const s of series) {
      for (const p of s.history) {
        values.push(p.v);
        if (p.candle && representation !== "line") values.push(...[p.candle.low, p.candle.high].map(n => (n / s.ref - 1) * 100));
      }
      if (s.result && offset===0) for (const v of [s.scenario, s.upper, s.lower]) if (finite(v)) values.push(v);
    }
    let svg = `<div class="fig-stress-time-empty" role="status">차트에 표시할 시세가 없습니다.</div>`;
    const plotted = series.some(s => s.history.length || (s.plotResult && [s.scenario,s.upper,s.lower].some(finite)));
    if (plotted) {
      const min = Math.min(...values), max = Math.max(...values), span = Math.max(max - min, .5);
      const lo = min - span * .12, hi = max + span * .12;
      const hasResult = series.some(s => s.plotResult && [s.scenario,s.upper,s.lower].some(finite));
      // Keep the basis caption on its own row below the observation dates.
      const top = 42, bottom = plotHeight - (hasResult ? 62 : 40), left = 64, right = plotWidth - 18;
      const dateLabelY = bottom + 24;
      const basisLabelY = bottom + 46;
      const nowX = hasResult ? left + (right - left) * .72 : right;
      const histRight = hasResult ? nowX - 12 : right;
      const endX = right - (plotWidth < 500 ? 48 : 110);
      const forecastSpacing = series.length>1 ? Math.min(22,(right-endX-14)/(series.length-1)) : 0;
      const y = v => top + (hi - v) / (hi - lo) * (bottom - top);
      const times = series.flatMap(s => s.history.map(p => p.t));
      const t0 = Math.min(...times), t1 = Math.max(...times);
      const x = t => times.length < 2 || t1 === t0 ? histRight : left + (t - t0) / (t1 - t0) * (histRight - left);
      const grid = Array.from({length:7},(_,k)=>k).map(k => {
        const val = hi - (hi - lo) * k / 6, yy = y(val);
        return `<line x1="${left}" y1="${yy.toFixed(1)}" x2="${right}" y2="${yy.toFixed(1)}" class="fig-stress-gridline"/><text x="${left - 8}" y="${(yy + 4).toFixed(1)}" text-anchor="end" class="fig-stress-y-label">${escape(pctText(val))}</text>`;
      }).join("");
      const zero = `<line x1="${left}" y1="${y(0).toFixed(1)}" x2="${right}" y2="${y(0).toFixed(1)}" class="fig-stress-zero-line"/>`;
      const nowLine = hasResult ? `<line x1="${nowX}" y1="${top - 10}" x2="${nowX}" y2="${bottom}" class="fig-stress-now-line"/><text x="${nowX}" y="${basisLabelY}" text-anchor="middle" class="fig-stress-x-label fig-stress-basis-label">분석 기준</text>` : "";
      const futureLabel = hasResult ? `<text x="${right}" y="${dateLabelY}" text-anchor="end" class="fig-stress-x-label">+${escape(data.horizon)}거래일 종점</text>` : "";
      const dates = [...new Set(times)].sort((a, b) => a - b);
      const tickCount = Math.min(dates.length, plotWidth < 500 ? 3 : 7);
      const formatTime = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", ...(intraday
        ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }
        : period === "year" ? { year: "numeric" } : { month: "2-digit", day: "2-digit" }) });
      const dateLabels = Array.from({length: tickCount}, (_, i) => {
        const t = dates[Math.round(i * (dates.length - 1) / Math.max(1, tickCount - 1))];
        return `<text x="${x(t)}" y="${dateLabelY}" text-anchor="${i === tickCount - 1 ? "end" : i === 0 ? "start" : "middle"}" class="fig-stress-x-label fig-stress-date-label">${escape(formatTime.format(t))}</text>`;
      }).join("");
      const header = `<text x="${left}" y="23" class="fig-chart-caption">${escape(periodName)} · ${hasResult ? "종목별 기준가" : "마지막 관측가"} 대비 등락률 (%)</text>`;
      const focusedSeries = series.find(s => s.code === focus) || (series.length === 1 ? series[0] : null);
      const labeledMarks = focusedSeries?.plotResult && plotWidth >= 500 ? [
        { label: "긍정", value: focusedSeries.upper, color: "#9c2d28" },
        { label: "기준", value: state.visible.baseline?focusedSeries.scenario:null, color: "#57463a" },
        { label: "부정", value: focusedSeries.lower, color: "#295c96" }
      ].filter(mark => finite(mark.value)).sort((a,b) => y(a.value) - y(b.value)) : [];
      let labelY = top - 24;
      const labels = labeledMarks.map((mark,i) => {
        labelY = Math.min(bottom - (labeledMarks.length - i - 1) * 22, Math.max(y(mark.value), labelY + 22));
        const px = endX + series.indexOf(focusedSeries) * forecastSpacing;
        return `<g class="fig-chart-end-label"><path d="M${px + 5} ${y(mark.value)}L${right - 3} ${labelY}" stroke="${mark.color}" fill="none"/><text x="${right - 4}" y="${labelY - 4}" text-anchor="end" fill="${mark.color}">${mark.label} ${escape(pctText(mark.value))}</text></g>`;
      }).join("");
      const layers = series.map((s, i) => {
        const { color, dash, shape } = s.style;
        const dim = focus && focus !== s.code ? " is-dimmed" : "";
        const dashAttr = dash ? ` stroke-dasharray="${dash}"` : "";
        const pts = s.history.map(p => `${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
        const line = s.history.length > 1
          ? `<polyline points="${pts}" class="fig-stress-actual-line" style="stroke:${color}"${dashAttr}><title>${escape(s.name)} 실제 관측 ${s.history.length}건 · 분석 기준가 대비 %</title></polyline>`
          : s.history.length === 1 ? shapeSvg(shape, x(s.history[0].t).toFixed(1), y(s.history[0].v), 4, `class="fig-stress-actual-dot" style="stroke:${color}"`) : "";
        const candleWidth = Math.max(2, Math.min(11, (histRight - left) / Math.max(1, s.history.length) * .6));
        const observations = !state.visible.history ? "" : representation === "line" ? line : s.history.map(p => {
          const px = x(p.t);
          if (!p.candle) return `<path d="M${px-2.8} ${y(p.v)}h5.6" stroke="${color}" stroke-width="2"><title>${escape(s.name)} · 관측 종가 ${escape(money(p.price))}</title></path>`;
          const { open, high, low, price: close } = p.candle;
          const level = n => y((n / s.ref - 1) * 100);
          const o = level(open), c = level(close), half = candleWidth / 2;
          const stroke = series.length > 1 ? color : close >= open ? "#b95b3e" : "#3c7f9f";
          const stem = `<path d="M${px} ${level(high)}V${level(low)}" stroke="${stroke}" />`;
          const body = representation === "candle"
            ? `<rect x="${px - half}" y="${Math.min(o, c)}" width="${candleWidth}" height="${Math.max(1, Math.abs(c - o))}" fill="${stroke}" />`
            : `<path d="M${px - half} ${o}H${px}M${px} ${c}H${px + half}" stroke="${stroke}" />`;
          const tooltip = `${s.name} · 관측 시가 ${money(open)} · 고가 ${money(high)} · 저가 ${money(low)} · 종가 ${money(close)}`;
          return `<g data-stress-tip="${escape(tooltip)}"><title>${escape(tooltip)}</title>${stem}${body}</g>`;
        }).join("");
        const basisDot = s.basis ? shapeSvg(shape, nowX, y(0), 4.5, `class="fig-stress-current-dot" style="stroke:${color};fill:#fffcf3"`) : "";
        const ex = endX + i * forecastSpacing;
        if (!s.plotResult) return `<g class="fig-stress-series${dim}" data-code="${escape(s.code)}">${observations}</g>`;
        const band = finite(s.lower) && finite(s.upper)
          ? `<line class="fig-stress-model-range" x1="${ex}" y1="${y(s.lower).toFixed(1)}" x2="${ex}" y2="${y(s.upper).toFixed(1)}" style="stroke:${color}"><title>${escape(s.name)} 90% 모델 구간 ${escape(pctText(s.lower))} ~ ${escape(pctText(s.upper))}</title></line>`
          : "";
        const forecastMark = (mark, yy) => {
          const attrs=`style="stroke:${color};fill:${mark.klass==='baseline'?color:'none'}"`;
          if (representation==='line') return shapeSvg(shape,ex,yy,mark.klass==='baseline'?5.5:4,attrs);
          if (mark.klass!=='baseline') return `<path d="M${ex-5} ${yy}h10" style="stroke:${color};stroke-width:2" />`;
          const origin=y(0);
          if(representation==='candle')return `<rect x="${ex-5}" y="${Math.min(origin,yy)}" width="10" height="${Math.max(2,Math.abs(yy-origin))}" fill="${color}" fill-opacity=".24" stroke="${color}" stroke-dasharray="3 2" /><path d="M${ex-6} ${yy}h12" stroke="${color}" stroke-width="2"/>`;
          return `<path d="M${ex-6} ${origin}H${ex}V${yy}h6" stroke="${color}" fill="none" stroke-width="2"/>`;
        };
        const marks = [
          { klass: "positive", label: "긍정 · 90% 상단", v: s.upper },
          { klass: "baseline", label: "기준 · 시나리오 중심", v: state.visible.baseline?s.scenario:null },
          { klass: "negative", label: "부정 · 90% 하단", v: s.lower }
        ].filter(m => finite(m.v)).map(m => {
          const price = pointPrice(s.basis, m.v);
          const text = `${s.name} ${m.label} ${pctText(m.v)}${price != null ? " · " + money(price) : ""}`;
          return `<g class="fig-stress-forecast-point is-${m.klass}" tabindex="0" aria-label="${escape(text)}" data-stress-tip="${escape(text)}">${forecastMark(m,y(m.v))}<title>${escape(text)}</title></g>`;
        }).join("");
        return `<g class="fig-stress-series${dim}" data-code="${escape(s.code)}">${observations}${basisDot}<g data-forecast-style="${representation}">${band}${marks}</g></g>`;
      }).join("");
      svg = `<svg class="fig-stress-time-svg fig-stress-overlay-svg" viewBox="0 0 ${plotWidth} ${plotHeight}" data-period-count="${periodDates.length}" data-chart-start="${left}" data-chart-end="${histRight}" data-chart-top="${top}" data-chart-bottom="${bottom}" role="img" aria-label="${escape(series.map(s => s.name).join(", "))} 실제 관측 시계열(분석 기준가 대비 %)과 5거래일 모델 종점 결과">${header}${grid}${zero}${nowLine}${layers}${labels}${dateLabels}${futureLabel}<path class="scenario-crosshair" fill="none" pointer-events="none" visibility="hidden"/></svg>`;
    }
    const legend = `<div class="fig-stress-overlay-legend" role="group" aria-label="비교 종목 범례 · 선택하면 해당 종목 강조">${series.map(s => {
      const { color, dash, shape, label } = s.style;
      const swatch = `<svg viewBox="0 0 34 14" width="34" height="14" aria-hidden="true"><line x1="1" y1="7" x2="33" y2="7" style="stroke:${color};stroke-width:2.5"${dash ? ` stroke-dasharray="${dash}"` : ""}/>${shapeSvg(shape, 17, 7, 4, `style="stroke:${color};fill:${color}"`)}</svg>`;
      return `<button type="button" data-gx="p63-chart-card-focus" data-code="${escape(focus === s.code ? "" : s.code)}" aria-pressed="${focus === s.code}" title="${escape(label)}">${swatch}<span>${escape(s.name)} (${escape(s.code)})</span></button>`;
    }).join("")}${focus ? `<button type="button" data-gx="p63-chart-card-focus" data-code="">전체 차트로 복귀</button>` : ""}</div>`;
    const layers=[['history','실제 시세'],['positive','긍정'],['baseline','기준'],['negative','부정']];
    const layerControls=`<div class="scenario-chart-layers" role="group" aria-label="차트 표시 항목">${layers.map(([id,label])=>`<button type="button" data-gx="p63-chart-layer" data-layer="${id}" aria-pressed="${state.visible[id]}">${label}</button>`).join('')}</div>`;
    const body = series.map(s => {
      const range=s.result?.model_interval_90_return_pct;
      const estimate=value=>escape(forecastText(pointPrice(s.basis,value),value));
      return `<tr data-code="${escape(s.code)}"><th scope="row"><span class="fig-stress-overlay-swatch" style="background:${s.style.color}" aria-hidden="true"></span>${escape(s.name)} <small>${escape(s.code)}</small></th><td>${s.basis ? escape(money(s.basis)) : "—"}</td><td class="is-positive">${estimate(range?.upper)}</td><td class="is-baseline">${estimate(s.scenario)}</td><td class="is-negative">${estimate(range?.lower)}</td></tr>`;
    }).join("");
    const table = body&&data ? `<div class="fig-stress-overlay-tablewrap"><table class="fig-stress-value-table fig-stress-overlay-table"><caption>5거래일 예측</caption><thead><tr><th scope="col">종목</th><th scope="col">분석 기준가</th><th scope="col">긍정 · 90% 상단</th><th scope="col">기준 · 중심</th><th scope="col">부정 · 90% 하단</th></tr></thead><tbody>${body}</tbody></table></div>` : "";
    const news=run?.newsAdjustment;
    const newsText=news?`<details class="scenario-chart-news"><summary>실시간 뉴스 반영 · VIX ${news.vix>0?'+':''}${escape(Number(news.vix.toFixed(2)))}pt</summary><p>${escape(news.summary)}</p><ul>${(news.articles||[]).filter(article=>/^https?:\/\//.test(article.url)).map(article=>`<li><a href="${escape(article.url)}" target="_blank" rel="noopener noreferrer">${escape(article.title)}</a></li>`).join('')}</ul></details>`:"";
    return `<div class="fig-stress-comparison-view"><figure class="fig-stress-overlay">${layerControls}${svg}${legend}</figure>${historyNotice}${expanded?'':table+newsText}</div>`;
  }

  function render({ run = null, mode = "market", model = "ridge", state: rawState = null, assetNames = null, assetUniverse = [], quotes = [], priceSeries = {}, historyStatus = {}, expanded = false } = {}) {
    const state = stateOf(rawState), result = run?.stressResult;
    const data = result?.assets?.length ? derive(result) : null;
    const portfolio = mode === "portfolio";
    const plot=data?.error?`<div class="fig-stress-empty" role="alert">${escape(data.error)}</div>`
      :comparisonOverlay(data,run,state,assetNames,assetUniverse,quotes,priceSeries,historyStatus,expanded);
    const summary=portfolio&&data&&!data.error&&!expanded?`<div class="scenario-portfolio-total">포트폴리오 예상 평가금액 <strong>${escape(money(data.scenarioValue))}</strong> <span>${escape(pct(data.scenarioReturn))}</span></div>`:'';
    return `<div class="fig-stress-chart" data-stress-mode="comparison"><div class="fig-stress-plot">${plot}${summary}</div><div class="fig-stress-tooltip" role="tooltip" hidden></div></div>`;
  }

  const api = { derive, render, periods };
  root.whatIfStressChart = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
