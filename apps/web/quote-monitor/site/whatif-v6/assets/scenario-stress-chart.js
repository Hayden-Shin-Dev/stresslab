/* Render observations and conditional simulation paths with separate styling. */
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
        !Number.isSafeInteger(result.horizon_trading_days) || result.horizon_trading_days <= 0 ||
        result.horizon_trading_days > 366) return bad();
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

  const scenarioKinds = [
    { key: "positive", name: "긍정", color: "#ae302a", dash: "0" },
    { key: "baseline", name: "기준", color: "#8a5914", dash: "7 4" },
    { key: "negative", name: "부정", color: "#255a99", dash: "3 4" }
  ];

  function dailyPath(raw, horizon, endpoint) {
    const anchors = new Map([[0, 0]]);
    const supplied = new Map();
    const validReturn = value => finite(value) && value > -100;
    for (const point of Array.isArray(raw) ? raw : []) {
      if (Number.isInteger(point?.day) && point.day > 0 && point.day <= horizon && validReturn(point.return_pct)) {
        anchors.set(point.day, point.return_pct);
        supplied.set(point.day, point);
      }
    }
    if (validReturn(endpoint)) anchors.set(horizon, endpoint);
    const sorted = [...anchors].sort(([a], [b]) => a - b);
    const points = new Map();
    let previousClose = 0;
    for (let i = 1; i < sorted.length; i++) {
      const [fromDay, from] = sorted[i - 1];
      const [toDay, to] = sorted[i];
      const fromLog = Math.log1p(from / 100);
      const delta = Math.log1p(to / 100) - fromLog;
      for (let day = fromDay + 1; day <= toDay; day++) {
        const close = day === toDay ? to : 100 * Math.expm1(fromLog + delta * (day - fromDay) / (toDay - fromDay));
        const src = supplied.get(day);
        const open = src?.open_return_pct, high = src?.high_return_pct, low = src?.low_return_pct;
        const fullBar = src?.return_pct === close && [open, high, low].every(validReturn) &&
          low <= Math.min(open, close) && high >= Math.max(open, close);
        points.set(day, {
          close,
          open: fullBar ? open : previousClose,
          high: fullBar ? high : Math.max(previousClose, close),
          low: fullBar ? low : Math.min(previousClose, close),
          estimatedClose: day !== toDay,
          estimatedBar: !fullBar
        });
        previousClose = close;
      }
    }
    return points;
  }

  function approvedNews(news, run) {
    const result = run?.stressResult;
    if (!result || news?.status !== "approved" || news.version !== "V1.6-r8" || news.analysis_id !== run.id ||
        news.horizon_trading_days !== run.horizon || news.model !== result.model ||
        !news.basis_date || news.basis_date !== result.model_context?.as_of_trading_date ||
        !Array.isArray(news.assets) || news.assets.length !== result.assets.length ||
        !news.window?.start_at || !news.window?.end_at ||
        !Number.isFinite(Date.parse(news.window.start_at)) ||
        !Number.isFinite(Date.parse(news.window.end_at)) || Date.parse(news.window.start_at) > Date.parse(news.window.end_at) ||
        !Array.isArray(news.sources) || !news.sources.some(source => /^https:\/\//.test(source?.url || ""))) return null;
    for (const row of result.assets) {
      const asset = news.assets.find(x => x?.asset_id === row.asset_id);
      if (!asset || !finite(asset.basis_price) || asset.basis_price !== run.priceSnapshot?.[row.asset_id]?.price) return null;
      const returns = scenarioKinds.map(({ key }) => asset.scenarios?.[key]?.return_pct);
      if (!returns.every(v => finite(v) && v > -100) || returns[0] < returns[1] || returns[1] < returns[2]) return null;
    }
    return news;
  }

  const periods = new Map([
    ["auto", "자동"], ["day", "일봉"], ["week", "주봉"], ["month", "월봉"], ["year", "연봉"],
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
      showNews: state.showNews !== false,
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

  const tradingDate = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' });
  function dateKey(at) {
    const fields = Object.fromEntries(tradingDate.formatToParts(new Date(at)).map(({type,value})=>[type,value]));
    return fields.year + "-" + fields.month + "-" + fields.day;
  }
  const positive = (...values) => values
    .map(value => typeof value === "string" && value.trim() ? Number(value.replace(/,/g, "")) : value)
    .find(value => finite(value) && value > 0);
  const validBar = (open, high, low, close) =>
    [open, high, low, close].every(value => finite(value) && value > 0) &&
    high >= Math.max(open, close) && low <= Math.min(open, close);
  function normalizeDailyHistory(payload, code) {
    if ((payload?.asset_id ?? payload?.code) !== code || !Array.isArray(payload.rows))
      throw new Error("history_format");
    const byDate = new Map();
    for (const row of payload.rows) {
      const at = row?.at ?? row?.date ?? row?.Date ?? row?.trading_date ?? row?.trade_date ?? row?.stck_bsop_date;
      const date = typeof at === "string" && /^\d{8}$/.test(at)
        ? [at.slice(0,4),at.slice(4,6),at.slice(6)].join("-") : at;
      if (typeof date !== "string" || !Number.isFinite(Date.parse(date))) continue;
      const bar = row.ohlc ?? row;
      const price = positive(bar.close, bar.Close, bar.close_price, bar.closePrice, bar.stck_clpr, row.price);
      if (!price) continue;
      const open = positive(bar.open, bar.Open, bar.open_price, bar.openPrice, bar.stck_oprc);
      const high = positive(bar.high, bar.High, bar.high_price, bar.highPrice, bar.stck_hgpr);
      const low = positive(bar.low, bar.Low, bar.low_price, bar.lowPrice, bar.stck_lwpr);
      const key = dateKey(date);
      const full = validBar(open,high,low,price);
      const previous=byDate.get(key);
      if (!full && previous && validBar(previous.open,previous.high,previous.low,previous.price)) continue;
      const boundsValid = (high == null || high >= Math.max(open ?? price,price)) &&
        (low == null || low <= Math.min(open ?? price,price));
      const known = Object.fromEntries(Object.entries({open,high,low}).filter(([,value])=>value!=null));
      byDate.set(key, { price, at: key, interval: "1d",
        ...(boundsValid ? known : {}),
        ...(row.adjusted === true || payload.price_basis === "adjusted" ? {adjusted:true} : {}) });
    }
    return [...byDate.values()].sort((a,b) => a.at.localeCompare(b.at));
  }

  function normalizeEventHistory(payload, codes, period) {
    if (payload?.period !== period || payload.source !== "quote_events" || !payload.series)
      throw new Error("history_format");
    return Object.fromEntries(codes.map(code => {
      if (!Array.isArray(payload.series[code])) throw new Error("history_format");
      return [code, payload.series[code].flatMap(row => {
        const { at, price, open, high, low, volume } = row;
        if (!Number.isFinite(Date.parse(at)) || !finite(price) || price <= 0) return [];
        const bar = validBar(open,high,low,price) ? {open,high,low} : {};
        return [{at:period === "day" ? dateKey(at) : at,observedAt:at,price,...bar,
          volume:finite(volume)&&volume>=0?volume:undefined,interval:period === "day" ? "1d" : period,source:payload.source}];
      })];
    }));
  }

  const observationCache = new WeakMap();
  function historyForPeriod(raw, period, adjusted) {
    const intraday = period === "tick" || period.startsWith("minute");
    // Calendar observations are replaced on fetch. Live ticks are edited in place.
    if (!intraday && !observationCache.has(raw)) observationCache.set(raw,new Map());
    const cache = intraday ? null : observationCache.get(raw);
    const cacheKey = period + ":" + adjusted;
    if (cache?.has(cacheKey)) return cache.get(cacheKey);
    if (period === "tick") {
      const ticks = raw.filter(row => row.interval !== "1d" && finite(row.price) &&
        row.price > 0 && Number.isFinite(Date.parse(row.at))).slice(-1500);
      const byTime = new Map();
      for (const row of ticks) {
        const time = Date.parse(row.at);
        if (!byTime.has(time)) byTime.set(time, []);
        byTime.get(time).push(row);
      }
      return [...byTime.entries()].sort(([a],[b])=>a-b).flatMap(([time,rows])=>
        rows.map((row,index)=>({...row,t:time+index/rows.length})));
    }
    const minutes = Number(period.split("-")[1]) || 1;
    const observations = new Map();
    for (const row of raw) {
      const t = Date.parse(row.at);
      if (!finite(t) || !finite(row.price) || row.price <= 0 ||
          (adjusted && row.adjusted !== true && !["quote_events","quotes/latest"].includes(row.source)) || (intraday === (row.interval === "1d"))) continue;
      observations.set(t, {...row,t});
    }
    const sorted = [...observations.values()].sort((a,b)=>a.t-b.t);
    if (period === "day") {
      const result = sorted.slice(-1500);
      if (cache) cache.set(cacheKey,result);
      return result;
    }
    const buckets = new Map();
    for (const row of sorted) {
      const time = row.t + 9 * 3600000;
      const date = new Date(time);
      const year = date.getUTCFullYear(), month = date.getUTCMonth();
      const day = Date.UTC(year,month,date.getUTCDate());
      let key;
      if (intraday) key = Math.floor(time/(minutes*60000)) * (minutes*60000) - 9*3600000;
      else if (period === "year") key = Date.UTC(year,0,1);
      else if (period === "month") key = Date.UTC(year,month,1);
      else key = day - ((date.getUTCDay()+6)%7)*86400000;
      const previous=buckets.get(key);
      const open=previous ? previous.open : intraday ? row.open ?? row.price : row.open;
      const high=intraday ? row.high ?? row.price : row.high;
      const low=intraday ? row.low ?? row.price : row.low;
      // Only the first session needs an opening price. The extremes
      // require all observed sessions' highs and lows.
      buckets.set(key, {
        t:key, at:row.at, first:previous?.first ?? row.at, price:row.price, open, observedAt:row.observedAt,
        high:previous ? finite(previous.high)&&finite(high)?Math.max(previous.high,high):undefined : high,
        low:previous ? finite(previous.low)&&finite(low)?Math.min(previous.low,low):undefined : low,
        volume:previous ? finite(previous.volume)&&finite(row.volume)?previous.volume+row.volume:undefined : row.volume
      });
    }
    const result=[...buckets.values()];
    if (cache) cache.set(cacheKey,result);
    return result;
  }

  function latestLabel(quote) {
    return `최신 관측 ${quote.time} · ${money(quote.price)}`;
  }

  function dateRangeHandles(range, left, right, bottom) {
    if (!range || range.days.length<2) return "";
    const {days,first,last}=range;
    const handle=(part,index,x)=>`<g class="fig-quote-range-handle" transform="translate(${x} ${bottom})" data-range-part="${part}"
      role="slider" tabindex="0" aria-label="${part==="first"?"시작 거래일":"끝 거래일"}" aria-valuemin="1"
      aria-valuemax="${days.length}" aria-valuenow="${index+1}" aria-valuetext="${escape(days[index])}">
      <rect x="-9" y="-7" width="18" height="23" rx="3"/><path d="M-2 0v8M2 0v8"/><title>${escape(days[index])}</title></g>`;
    return handle("first",first,left)+handle("last",last,right);
  }

  function priceSamples(rows, capacity, retainedTime) {
    if (rows.length <= capacity) return rows;
    const chunkSize = Math.ceil(rows.length * 4 / capacity);
    const samples = [];
    const sessionDay = ({t}) => Math.floor((t + 9 * 3600000) / 86400000);
    for (let start=0;start<rows.length;start+=chunkSize) {
      const end = Math.min(start + chunkSize, rows.length)-1;
      const selected = new Set([start,end]);
      let low=start, high=start;
      let day=sessionDay(rows[start]);
      for (let i=start+1;i<=end;i++) {
        if (rows[i].t===retainedTime) selected.add(i);
        if (rows[i].price < rows[low].price) low=i;
        if (rows[i].price > rows[high].price) high=i;
        const nextDay=sessionDay(rows[i]);
        if (nextDay!==day) {
          selected.add(i-1);
          selected.add(i);
          day=nextDay;
        }
      }
      selected.add(low);
      selected.add(high);
      for (const i of [...selected].sort((a,b)=>a-b)) samples.push(rows[i]);
    }
    return samples;
  }

  const volumeLabel=new Intl.NumberFormat("ko-KR");
  function observationTooltip(point, name, period, clock) {
    const date = at => dateKey(at).slice(2).replaceAll("-", ".");
    const day = clock
      ? date(point.at)+" "+clock.format(period==="tick" ? new Date(point.at) : point.t)
      : point.first && point.first!==point.at ? date(point.first)+" ~ "+date(point.at) : date(point.at);
    const rows = point.candle ? [
      ["open","시가",money(point.candle.open)],
      ["high","고가",money(point.candle.high)],
      ["low","저가",money(point.candle.low)],
      ["close","종가",money(point.price)]
    ] : [[period==="tick"?"trade":"close",period==="tick"?"체결가":"종가",money(point.price)]];
    if(period!=="tick"){
      rows.push(["volume","거래량",finite(point.volume)?volumeLabel.format(point.volume)+"주":"—"]);
    }
    const text = name+" · "+day+"\n"+rows.map(([,label,value])=>label+" "+value).join(" · ");
    return {text, attributes:`data-stress-tip="${escape(text)}" data-quote-card="${escape(JSON.stringify({day,name,rows}))}"`};
  }

  function comparisonOverlay(data, run, state, assetNames, assetUniverse, priceSeries, quoteHistory, expanded = false, availableWidth = 0, draftConditions = {}) {
    const known = new Map();
    for (const asset of assetUniverse || []) {
      if (asset?.code && /^\d{6}$/.test(String(asset.code))) known.set(String(asset.code), String(asset.name || asset.code));
      else if (asset?.asset_id && /^\d{6}$/.test(String(asset.asset_id))) known.set(String(asset.asset_id), String(asset.name || asset.asset_id));
    }
    for (const row of data?.assets || []) known.set(row.asset_id, displayName(row.asset_id, run, assetNames));
    for (const code of Object.keys(priceSeries || {})) if (/^\d{6}$/.test(code) && !known.has(code)) known.set(code, displayName(code, run, assetNames));
    const codes = state.compareAssets.filter(code => known.has(code));
    const news = data && run?.newsScenarios?.status === "approved" ? approvedNews(run.newsScenarios,run) : null;
    const results = new Map((data?.assets || []).map(row => [row.asset_id, row]));

    const { period, representation } = state;
    const periodName = periods.get(period);
    const intraday = period === "tick" || period.startsWith("minute");
    const fullHistory = new Map(codes.map(code => [code, historyForPeriod(
      priceSeries[code] || [],
      period,
      run?.priceSnapshot?.[code]?.adjusted === true && results.has(code)
    )]));
    const periodDates=[...new Set([...fullHistory.values()].flatMap(rows=>rows.map(row=>row.t)))].sort((a,b)=>a-b);
    const limit=quoteHistory?.range ? periodDates.length : state.limit;
    const offset=Math.min(state.offset,Math.max(0,periodDates.length-limit));
    const windowEnd=periodDates.length-offset, windowStart=Math.max(0,windowEnd-limit);
    const visibleDates=periodDates.slice(windowStart,windowEnd);
    const firstTime=visibleDates[0],lastTime=visibleDates.at(-1);
    const observationsByCode=new Map([...fullHistory].map(([code,rows])=>[code,rows.filter(row=>row.t>=firstTime&&row.t<=lastTime)]));
    const missingHistory=!periodDates.length;
    const needsHistory = codes.length && (quoteHistory || codes.some(code=>run?.priceSnapshot?.[code]?.adjusted!==true||!results.has(code)));
    const tickCapped = period === "tick" && quoteHistory?.limit && [...fullHistory.values()].some(rows=>rows.length>=quoteHistory.limit);
    let historyNotice = "";
    if (needsHistory && quoteHistory?.status === "error") {
      historyNotice = '<p class="scenario-chart-status" role="status">시세를 불러오지 못했습니다. <button type="button" data-gx="p63-history-retry">다시 조회</button></p>';
    } else if (needsHistory && missingHistory) {
      const message = quoteHistory?.status === "loading" ? "시세를 불러오는 중입니다."
        : intraday ? "선택한 날짜와 시각에 체결 내역이 없습니다." : "이 기간의 시세가 없습니다.";
      historyNotice = `<p class="scenario-chart-status" role="status">${message}</p>`;
    } else if (tickCapped) {
      historyNotice = `<p class="scenario-chart-status" role="status">종목별 최근 ${quoteHistory.limit.toLocaleString("ko-KR")}틱을 표시합니다. 조회 시각을 선택해 이전 체결을 확인하세요.</p>`;
    }
    const historyControls = intraday && quoteHistory?.tradeDate && codes.length
      ? `<label class="fig-chart-menu"><span>거래일 (KST)</span><input type="date" data-gx="p63-trade-date" aria-label="거래일 (KST)" min="${escape(quoteHistory.availableFrom)}" max="${escape(quoteHistory.today)}" value="${escape(quoteHistory.tradeDate)}"/></label>${period === "tick" ? `<label class="fig-chart-menu"><span>틱 조회 시각</span><input type="time" data-gx="p63-tick-minute" aria-label="틱 조회 시각" value="${escape(quoteHistory.minute)}"/></label>` : ""}` : "";
    const pointPrice = (price, ret) => price != null && finite(ret) ? price * (1 + ret / 100) : null;

    const series = codes.map((code, i) => {
      const style = SERIES[i % SERIES.length], name = known.get(code) || code;
      const candles = observationsByCode.get(code);
      const basis = run?.priceSnapshot?.[code]?.price || null;
      const result = results.get(code), interval = result?.model_interval_90_return_pct;
      const history = candles.map(p => ({
        t:p.t, at:p.at, first:p.first, price:p.price, observedAt:p.observedAt, volume:p.volume,
        candle: validBar(p.open,p.high,p.low,p.price) ? p : null
      }));
      const baseReturns = {positive:interval?.upper, baseline:result?.scenario_return_pct, negative:interval?.lower};
      const approved = news?.assets.find(asset => asset.asset_id === code)?.scenarios;
      const projections = scenarioKinds.filter(kind=>state.visible[kind.key]).map(kind=>{
        const before=baseReturns[kind.key];
        const base=dailyPath(result?.daily_scenarios?.[kind.key],data?.horizon,before);
        const after=approved?.[kind.key];
        const alternate=dailyPath(after?.daily_returns,data?.horizon,after?.return_pct);
        return {...kind,before,base,alternate,showAfter:state.showNews&&Boolean(after),
          points:state.showNews&&after?alternate:base};
      }).filter(kind=>kind.base.size||kind.alternate.size);
      return {
        code, name, style, basis, result, history, projections,
        plotResult: Boolean(result && offset===0 && quoteHistory?.showProjection!==false && projections.length)
      };
    });
    const focus = state.focusedAsset && codes.includes(state.focusedAsset) ? state.focusedAsset : "";
    const plotWidth = expanded ? Math.max(340, innerWidth - 32) : Math.max(520, Math.round(availableWidth || 1000));
    const plotHeight = expanded ? Math.max(240, innerHeight - 130) : Math.max(355, Math.min(510, Math.round(plotWidth*.46)));
    const values = [];
    for (const s of series) {
      if (state.visible.history) for (const p of s.history) {
        values.push(p.price);
        if (p.candle && representation !== "line") values.push(p.candle.low,p.candle.high);
      }
      if (s.plotResult && s.basis) {
        values.push(s.basis);
        for (const mark of s.projections) for (const point of mark.points.values())
          values.push(pointPrice(s.basis,point.close), ...(representation === "line" ? [] :
            [pointPrice(s.basis,point.high),pointPrice(s.basis,point.low)]));
      }
    }
    const assumptions=run?.inputSnapshot?.conditions||run?.conditions||draftConditions;
    const shock=(value,unit)=>finite(Number(value))?`${Number(value)>0?"+":""}${Number(value).toLocaleString("ko-KR",{maximumFractionDigits:2})}${unit}`:"—";
    const shocks=[['금리',shock(Number(assumptions.rate)*100,"bp")],['원/달러',shock(assumptions.fx,"%")],['WTI',shock(assumptions.oil,"%")],['VIX',shock(assumptions.vix,"pt")]];
    let svg = `<div class="fig-stress-time-empty" role="status">차트에 표시할 시세가 없습니다.</div>`;
    const plotted = values.length > 0;
    if (plotted) {
      const min = values.reduce((a,b)=>Math.min(a,b),Infinity);
      const max = values.reduce((a,b)=>Math.max(a,b),-Infinity), span = Math.max(max - min, max*.005, 1);
      const lo = Math.max(0,min - span * .12), hi = max + span * .12;
      const hasResult = series.some(s => s.plotResult && s.basis);
      // Keep the basis caption on its own row below the observation dates.
      const top = hasResult ? 80 : 42, bottom = plotHeight - (hasResult ? 62 : 40), left = hi>=1e6?100:88, right = plotWidth - 18;
      const dateLabelY = bottom + 24;
      const basisLabelY = bottom + 46;
      const nowX = hasResult ? left + (right - left) * (data.horizon === 20 ? .40 : .62) : right;
      const histRight = hasResult ? nowX - 10 : right;
      const labeled = series.find(item=>item.code===focus) || (series.length===1?series[0]:null);
      const reserveEndCards=Boolean(hasResult&&plotWidth>=(data?.horizon===20?900:700)&&labeled?.plotResult&&labeled.basis);
      const showEndCards=reserveEndCards;
      const endX = right - (reserveEndCards ? 136 : representation === "line" ? 8 : Math.min(36, (right - nowX) / (data?.horizon || 1) * .42));
      const dayX = day => nowX + (endX - nowX) * day / data.horizon;
      const slotWidth = hasResult ? Math.min(16, (endX - nowX) * .76 / data.horizon / (series.length * scenarioKinds.length)) : 0;
      const glyphOffset = (seriesIndex, key) => representation === "line" ? 0 :
        (seriesIndex * scenarioKinds.length + scenarioKinds.findIndex(kind => kind.key === key)
          - (series.length * scenarioKinds.length - 1) / 2) * slotWidth;
      const y = v => top + (hi - v) / (hi - lo) * (bottom - top);
      const slots = new Map(visibleDates.map((time,index)=>[time,index]));
      const cadence = (histRight-left) / Math.max(1,visibleDates.length);
      const x = t => left + (slots.get(t)+.5)*cadence;
      const barSlot = Math.max(1,Math.min(19,cadence*.8/Math.max(1,series.length)));
      const grid = Array.from({length:7},(_,k)=>k).map(k => {
        const val = hi - (hi - lo) * k / 6, yy = y(val);
        return `<line x1="${left}" y1="${yy.toFixed(1)}" x2="${right}" y2="${yy.toFixed(1)}" class="fig-stress-gridline"/><text x="${left - 8}" y="${(yy + 4).toFixed(1)}" text-anchor="end" class="fig-stress-y-label">${escape(money(val))}</text>`;
      }).join("");
      const zero = labeled?.plotResult && labeled.basis
        ? `<line x1="${left}" y1="${y(labeled.basis)}" x2="${right}" y2="${y(labeled.basis)}" class="fig-stress-zero-line"/>` : "";
      const startX = Math.min(right-182, Math.max(left, nowX-86));
      const nowLine = hasResult ? `<line x1="${nowX}" y1="57" x2="${nowX}" y2="${bottom}" class="fig-stress-now-line"/><g class="fig-projection-start"><rect x="${startX}" y="10" width="182" height="48" rx="4"/><text x="${startX+9}" y="25" class="fig-projection-caption">테스트 시작</text><text x="${startX+9}" y="39">${escape(shocks.slice(0,2).map(row=>row.join(' ')).join(' · '))}</text><text x="${startX+9}" y="52">${escape(shocks.slice(2).map(row=>row.join(' ')).join(' · '))}</text></g><text x="${nowX}" y="${basisLabelY}" text-anchor="middle" class="fig-stress-x-label fig-stress-basis-label">분석 기준</text>` : "";
      const futureLabel = hasResult ? Array.from({length:data.horizon},(_,i)=>{
        const day=i+1, px=dayX(day);
        return `<path d="M${px} ${bottom}v5" class="fig-stress-gridline"/><text x="${px}" y="${dateLabelY}" text-anchor="middle" class="fig-stress-x-label fig-projection-day">${data.horizon <= 5 && plotWidth >= 640 ? day + "일차" : "+" + day}</text>`;
      }).join("") : "";
      const dates = visibleDates;
      const tickCount = Math.min(dates.length, plotWidth < 620 ? 4 : 7);
      const spansYears = dates.length>0&&new Date(dates[0]).getUTCFullYear()!==new Date(dates.at(-1)).getUTCFullYear();
      const multiDay = intraday && dates.length && dateKey(dates[0])!==dateKey(dates.at(-1));
      const formatTime = new Intl.DateTimeFormat("ko-KR", { timeZone: "Asia/Seoul", ...(intraday
        ? { ...(multiDay?{month:"numeric",day:"numeric"}:{}), hour: "2-digit", minute: "2-digit", ...(period === "tick" ? {second:"2-digit"} : {}), hourCycle: "h23" }
        : period === "year" ? { year: "numeric" } : period === "month" ? { year:"2-digit",month:"short" } : { ...(spansYears?{year:"2-digit"}:{}), month:"2-digit",day:"2-digit" }) });
      const dateLabels = Array.from({length: tickCount}, (_, i) => {
        const t = dates[Math.round(i * (dates.length - 1) / Math.max(1, tickCount - 1))];
        return `<text x="${x(t)}" y="${dateLabelY}" text-anchor="${i === tickCount - 1 ? "end" : i === 0 ? "start" : "middle"}" class="fig-stress-x-label fig-stress-date-label">${escape(formatTime.format(t))}</text>`;
      }).join("");
      const header = `<text x="${left}" y="23" class="fig-chart-caption">${escape(periodName)} · 가격 (원)</text>`;
      const clock=intraday?new Intl.DateTimeFormat("en-GB",{timeZone:"Asia/Seoul",
        hour:"2-digit",minute:"2-digit",...(period==="tick"?{second:"2-digit"}:{}),hourCycle:"h23"}):null;
      let previousCard=top-62;
      const endCards=showEndCards?labeled.projections
        .filter(mark=>mark.points.has(data.horizon))
        .sort((a,b)=>b.points.get(data.horizon).close-a.points.get(data.horizon).close)
        .map((mark,index,all)=>{
          const value=mark.points.get(data.horizon).close, terminalPrice=pointPrice(labeled.basis,value), py=y(terminalPrice);
          const cy=Math.min(bottom-54-(all.length-index-1)*61,Math.max(py-26,previousCard+61));
          previousCard=cy;
          const labelY=cy+14;
          const endpointX=endX+glyphOffset(series.indexOf(labeled),mark.key);
          const valueLines=mark.showAfter?`<text x="${right-115}" y="${cy+30}">뉴스 반영 전 <tspan font-weight="700">${finite(mark.before)?escape(pct(mark.before)):"—"}</tspan></text><text x="${right-115}" y="${cy+45}">뉴스 반영 후 <tspan font-weight="700">${escape(pct(value))}</tspan></text>`:
            `<text x="${right-115}" y="${cy+33}" font-weight="700">${escape(pct(value))}</text>${terminalPrice===null?"":`<text x="${right-115}" y="${cy+46}">${escape(money(terminalPrice))}</text>`}`;
          return `<g class="fig-projection-end-card is-${mark.key}"><path d="M${endpointX} ${py}L${right-124} ${cy+26}" stroke="${mark.color}" fill="none"/><rect x="${right-123}" y="${cy}" width="123" height="54" rx="4"/><text x="${right-115}" y="${labelY}" font-weight="700">${mark.name}</text>${valueLines}</g>`;
        }).join(""):"";
      const [retainedAsset,retainedPeriod,retainedTime]=quoteHistory?.retainedPoint?.split(":")||[];
      const layers = series.map((s, seriesIndex) => {
        const { color, dash, shape } = s.style;
        const dim = focus && focus !== s.code ? " is-dimmed" : "";
        const dashAttr = dash ? ` stroke-dasharray="${dash}"` : "";
        const priceY = value => y(pointPrice(s.basis,value));
        const pinnedTime=s.code===retainedAsset&&period===retainedPeriod?Number(retainedTime):undefined;
        const drawn = priceSamples(s.history, Math.max(500, plotWidth), pinnedTime).map(point=>({
          ...point,tooltip:observationTooltip(point,s.name,period,clock),key:escape([s.code,period,point.t].join(":"))
        }));
        const pts = representation==='line' ? drawn.map(p => `${x(p.t).toFixed(1)},${y(p.price).toFixed(1)}`).join(" ") : "";
        const line = s.history.length > 1
          ? `<polyline points="${pts}" class="fig-stress-actual-line" style="stroke:${color}"${dashAttr}><title>${escape(s.name)} 실제 관측 ${s.history.length}건 · 가격 (원)</title></polyline>`
          : s.history.length === 1 ? shapeSvg(shape, x(s.history[0].t), y(s.history[0].price), 4, `class="fig-stress-actual-dot" style="stroke:${color}"`) : "";
        const candleWidth = Math.max(1, Math.min(15,barSlot*.75));
        const barX = t => x(t)+(seriesIndex-(series.length-1)/2)*barSlot;
        const hitPoints=state.visible.history ? drawn.map(point=>
          `<circle cx="${representation==="line"?x(point.t):barX(point.t)}" cy="${y(point.price)}" r="8"
            class="fig-stress-hit" data-quote-key="${point.key}" ${point.tooltip.attributes} pointer-events="none"/>`).join("") : "";
        const observations = !state.visible.history ? "" : representation === "line" ? line : drawn.map(p => {
          const px = barX(p.t);
          if (!p.candle) return `<path class="fig-history-close-only" d="M${px-2.8} ${y(p.price)}h5.6" stroke="${color}" stroke-width="2" data-quote-key="${p.key}" ${p.tooltip.attributes}><title>${escape(p.tooltip.text)}</title></path>`;
          const { open, high, low, price: close } = p.candle;
          const level = y;
          const o = level(open), c = level(close), half = candleWidth / 2;
          const stroke = representation==="ohlc"
            ? close>=open?"#357a24":"#ad2b27"
            : close>=open?"#b92f2a":"#2a5292";
          const stem = `<path d="M${px} ${level(high)}V${level(low)}" stroke="${stroke}" />`;
          const body = representation === "candle"
            ? `<rect x="${px - half}" y="${Math.min(o, c)}" width="${candleWidth}" height="${Math.max(1, Math.abs(c - o))}" fill="${stroke}" />`
            : `<path d="M${px - half} ${o}H${px}M${px} ${c}H${px + half}" stroke="${stroke}" />`;
          return `<g class="fig-history-ohlc" data-history-representation="${representation}" style="--fig-candle-stroke:${stroke}" data-quote-key="${p.key}" ${p.tooltip.attributes}><title>${escape(p.tooltip.text)}</title>${stem}${body}</g>`;
        }).join("");
        const last = s.history.at(-1);
        const quote = quoteHistory?.range?.latest?.[s.code];
        const latest = state.visible.history && last && quote && last.price===quote.price && Date.parse(quote.at) === Date.parse(last.observedAt)
          ? `<circle class="fig-quote-last-point" data-last-code="${escape(s.code)}" data-last-price="${last.price}" data-last-at="${escape(last.observedAt)}" cx="${representation==="line"?x(last.t):barX(last.t)}" cy="${y(last.price)}" r="4" fill="${color}" stroke="#fffdf5" stroke-width="1.5"><title>${escape(s.name+" · "+latestLabel(quote))}</title></circle>`
          : "";
        const basisDot = s.basis ? shapeSvg(shape, nowX, y(s.basis), 4.5, `class="fig-stress-current-dot" style="stroke:${color};fill:#fffcf3"`) : "";
        if (!s.plotResult || !s.basis) return `<g class="fig-stress-series${dim}" data-code="${escape(s.code)}">${observations}${latest}${hitPoints}</g>`;
        const marks = s.projections.map(mark => {
          const endpoint = mark.points.get(data.horizon)?.close;
          const points = [...mark.points];
          const stroke=series.length>1?s.style.color:mark.color;
          const path = [...(s.basis ? [[0, { close: 0 }]] : []), ...points]
            .map(([day, value], index) => `${index ? "L" : "M"}${dayX(day)} ${priceY(value.close)}`).join("");
          const resultLine = representation === "line"
            ? `<path class="fig-projection-line" d="${path}" stroke="${stroke}" stroke-dasharray="${mark.dash}" fill="none" stroke-width="2"/>` : "";
          const valueLabel = value => money(pointPrice(s.basis, value));
          const glyphs = points.map(([day, bar]) => {
            const px = dayX(day) + glyphOffset(seriesIndex,mark.key);
            const py = priceY(bar.close);
            const isLine = representation === "line";
            const labels = isLine ? `종가 ${valueLabel(bar.close)} · ${pct(bar.close)}`
              : `시가 ${valueLabel(bar.open)} · 고가 ${valueLabel(bar.high)} · 저가 ${valueLabel(bar.low)} · 종가 ${valueLabel(bar.close)}`;
            const text = `${s.name} · ${day}일차 · ${mark.name}\n${labels}`;
            let icon = shapeSvg(s.style.shape, px, py, 3.4, `fill="${stroke}"`);
            if (!isLine) {
              const openY = priceY(bar.open), half = Math.max(.6, slotWidth * .36);
              const stem = `<path d="M${px} ${priceY(bar.high)}V${priceY(bar.low)}" stroke="${stroke}" stroke-width="1.4"/>`;
              const body = representation === "candle"
                ? `<rect x="${px-half}" y="${Math.min(openY,py)}" width="${half*2}" height="${Math.max(1,Math.abs(py-openY))}" fill="${bar.close >= bar.open ? "#fffaf0" : stroke}" stroke="${stroke}"/>`
                : `<path d="M${px-half} ${openY}H${px}M${px} ${py}H${px+half}" stroke="${stroke}" stroke-width="1.6"/>`;
              icon = stem + body;
            }
            return `<g class="fig-stress-forecast-point is-${mark.key}" data-day="${day}" tabindex="0" aria-label="${escape(text)}" data-stress-tip="${escape(text)}" data-plot-x="${px}" data-plot-y="${py}">${icon}<circle class="fig-forecast-hit" cx="${px}" cy="${py}" r="8" fill="transparent"/></g>`;
          }).join("");
          const label=finite(endpoint)&&series.length===1&&!news?`<title>${escape(mark.name+" "+pct(endpoint))}</title>`:"";
          return `<g class="fig-projection">${label}${resultLine}${glyphs}</g>`;
        }).join("");
        return `<g class="fig-stress-series${dim}" data-code="${escape(s.code)}">${observations}${latest}${basisDot}<g data-forecast-style="${representation}">${marks}</g>${hitPoints}</g>`;
      }).join("");
      const forecastArea = hasResult ? `<rect x="${nowX}" y="${top}" width="${right-nowX}" height="${bottom-top}" class="fig-projection-zone"/>` : "";
      const range=quoteHistory?.range;
      const rangeData=range?.days.length?` data-quote-range data-days="${range.days.join(",")}" data-range-first="${range.first}" data-range-last="${range.last}"`:"";
      svg = `<svg class="fig-stress-time-svg fig-stress-overlay-svg" viewBox="0 0 ${plotWidth} ${plotHeight}" data-period-count="${periodDates.length}" data-history-status="${escape(quoteHistory?.status||"")}" data-chart-start="${left}" data-chart-end="${right}" data-history-end="${histRight}" data-chart-top="${top}" data-chart-bottom="${bottom}" data-cursor-period="${period}" data-cursor-dates="${visibleDates.join(",")}" data-price-min="${lo}" data-price-max="${hi}" data-forecast-start="${nowX}" data-forecast-end="${endX}" data-forecast-days="${hasResult?data.horizon:0}"${rangeData} role="group" aria-label="${escape(series.map(s => s.name).join(", "))} 실제 시세와 시뮬레이션 경로">${header}${forecastArea}${grid}${zero}${nowLine}${layers}${endCards}${dateLabels}${futureLabel}${dateRangeHandles(range,left,histRight,bottom)}<g class="scenario-cursor" aria-hidden="true" pointer-events="none" visibility="hidden"><path class="scenario-crosshair" fill="none"/><g class="scenario-cursor-badge" data-cursor-date><rect height="22" rx="3"/><text y="15" text-anchor="middle"/></g><g class="scenario-cursor-badge" data-cursor-price><rect height="22" rx="3"/><text y="15" text-anchor="middle"/></g></g></svg>`;
    }
    const legend = `<div class="fig-stress-overlay-legend" role="group" aria-label="비교 종목 범례 · 선택하면 해당 종목 강조">${series.map(s => {
      const { color, dash, shape, label } = s.style;
      const swatch = `<svg viewBox="0 0 34 14" width="34" height="14" aria-hidden="true"><line x1="1" y1="7" x2="33" y2="7" style="stroke:${color};stroke-width:2.5"${dash ? ` stroke-dasharray="${dash}"` : ""}/>${shapeSvg(shape, 17, 7, 4, `style="stroke:${color};fill:${color}"`)}</svg>`;
      const quote=quoteHistory?.range?.latest?.[s.code];
      const price=quote?`<span class="fig-quote-legend-latest" data-latest-code="${escape(s.code)}" data-latest-at="${escape(quote.at)}" data-latest-price="${quote.price}">${money(quote.price)}</span>`:"";
      const hint=quote?label+" · "+latestLabel(quote):label;
      return `<button type="button" data-gx="p63-chart-card-focus" data-code="${escape(focus === s.code ? "" : s.code)}" aria-pressed="${focus === s.code}" title="${escape(hint)}">${swatch}<span>${escape(s.name)} (${escape(s.code)})</span>${price}</button>`;
    }).join("")}${focus ? `<button type="button" data-gx="p63-chart-card-focus" data-code="">전체 차트로 복귀</button>` : ""}</div>`;
    const layers=[['history','실제 시세'],['positive','긍정'],['baseline','기준'],['negative','부정']];
    const layerControls=`<div class="scenario-chart-layers" role="group" aria-label="차트 표시 항목">${layers.map(([id,label])=>`<button type="button" data-gx="p63-chart-layer" data-layer="${id}" aria-pressed="${state.visible[id]}">${label}</button>`).join('')}</div>`;
    const title=series.length===1?series[0].name:series.length?'종목 비교':'시나리오 차트';
    const chartTitle=`<h3 class="scenario-chart-title">${escape(title)}${run&&data?`<small>${data.horizon}거래일</small>`:""}</h3>`;
    const basis=`<div class="fig-chart-basis"><strong>${run?"분석 기준":"입력 가정"}</strong><span>${run?[data?.basisDate&&'모델 '+data.basisDate,(data?.horizon||run.horizon)+'거래일'].filter(Boolean).map(escape).join(' · '):""}</span><span>금리 ${shock(Number(assumptions.rate)*100,"bp")}</span><span>원/달러 ${shock(assumptions.fx,"%")}</span><span>WTI ${shock(assumptions.oil,"%")}</span><span>VIX ${shock(assumptions.vix,"pt")}</span></div>`;
    const pending=run?.newsScenarios?.status==="pending";
    const newsControl=run?.inputSnapshot?.includeNews
      ? `<button type="button" data-gx="p63-news-view" aria-pressed="${!!news&&state.showNews}" ${news?"":"disabled"}>뉴스 반영 표시</button>`
      : "";
    const cards=series.filter(s=>s.plotResult&&(!focus||focus===s.code)).map(s=>{
      const rows=['baseline','positive','negative'].map(key=>s.projections.find(mark=>mark.key===key))
        .filter(mark=>mark?.points.has(data.horizon)).map(mark=>{
        const after=mark.points.get(data.horizon).close;
        return `<div class="fig-news-result-card is-${mark.key}" style="--scenario-color:${mark.color}"><dt>${mark.name}</dt><dd>${mark.showAfter?`<span>뉴스 반영 전 <b>${finite(mark.before)?pct(mark.before):"—"}</b></span><span>뉴스 반영 후 <b>${pct(after)}</b></span>`:`<b>${pct(after)}</b>`}</dd></div>`;
      }).join("");
      return rows?`<div><strong>${escape(s.name)}</strong><dl>${rows}</dl></div>`:"";
    }).join("");
    const newsStatus=pending
      ? '<p class="scenario-chart-status" role="status">뉴스 영향을 검토하고 있습니다.</p>' : "";
    const sources=news&&state.showNews?`<details class="scenario-chart-news"><summary>뉴스 반영 근거</summary><p>${escape(news.summary||"")}</p><p>${escape(news.window.start_at)} ~ ${escape(news.window.end_at)}</p><ul>${news.sources.filter(x=>/^https:\/\//.test(x?.url||"")).map(x=>`<li><a href="${escape(x.url)}" target="_blank" rel="noopener noreferrer">${escape(x.title||"원문")}</a></li>`).join("")}</ul></details>`:"";
    return `<div class="fig-stress-comparison-view"><figure class="fig-stress-overlay"><div class="scenario-chart-heading">${chartTitle}${basis}</div><div class="fig-scenario-chart-controls">${layerControls}${newsControl}${historyControls}</div>${svg}${legend}</figure>${historyNotice}${newsStatus}${cards?`<div class="fig-news-results" aria-label="시나리오 종료 수익률">${cards}</div>`:""}${sources}</div>`;
  }

  function render({ run = null, mode = "market", model = "ridge", state: rawState = null, assetNames = null, assetUniverse = [], priceSeries = {}, quoteHistory = null, expanded = false, plotWidth = 0, conditions = {} } = {}) {
    const state = stateOf(rawState), result = run?.stressResult;
    const data = result?.assets?.length ? derive(result) : null;
    const portfolio = mode === "portfolio";
    const plot=data?.error?`<div class="fig-stress-empty" role="alert">${escape(data.error)}</div>`
      :comparisonOverlay(data,run,state,assetNames,assetUniverse,priceSeries,quoteHistory,expanded,plotWidth,conditions);
    const summary=portfolio&&data&&!data.error&&!expanded?`<div class="scenario-portfolio-total">포트폴리오 예상 평가금액 <strong>${escape(money(data.scenarioValue))}</strong> <span>${escape(pct(data.scenarioReturn))}</span></div>`:'';
    return `<div class="fig-stress-chart" data-stress-mode="comparison"><div class="fig-stress-plot">${plot}${summary}</div><div class="fig-stress-tooltip" role="tooltip" hidden></div></div>`;
  }

  const api = { derive, normalizeDailyHistory, normalizeEventHistory, render, periods, approvedNews };
  root.whatIfStressChart = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
