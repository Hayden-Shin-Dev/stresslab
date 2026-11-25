(function () {
  const assetRoot = "./assets/scenario-ui/";
  const image = (name) => `${assetRoot}images/${name}`;
  const icon = (name) => `${assetRoot}icons/${name}`;
  const chart = (name) => `${assetRoot}chart/${name}`;
  const escape = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
  })[char]);


  // Identity-only copy of ingestion/kiwoom/universe.json; never seed quote values.
  window.whatIfScenarioDefaultAssets = Object.freeze([{"code": "005930", "name": "삼성전자", "market": "KOSPI"}, {"code": "000660", "name": "SK하이닉스", "market": "KOSPI"}, {"code": "005935", "name": "삼성전자우", "market": "KOSPI"}, {"code": "402340", "name": "SK스퀘어", "market": "KOSPI"}, {"code": "009150", "name": "삼성전기", "market": "KOSPI"}, {"code": "373220", "name": "LG에너지솔루션", "market": "KOSPI"}, {"code": "207940", "name": "삼성바이오로직스", "market": "KOSPI"}, {"code": "005380", "name": "현대차", "market": "KOSPI"}, {"code": "105560", "name": "KB금융", "market": "KOSPI"}, {"code": "032830", "name": "삼성생명", "market": "KOSPI"}, {"code": "028260", "name": "삼성물산", "market": "KOSPI"}, {"code": "068270", "name": "셀트리온", "market": "KOSPI"}, {"code": "006400", "name": "삼성SDI", "market": "KOSPI"}, {"code": "055550", "name": "신한지주", "market": "KOSPI"}, {"code": "000270", "name": "기아", "market": "KOSPI"}, {"code": "034730", "name": "SK", "market": "KOSPI"}, {"code": "012450", "name": "한화에어로스페이스", "market": "KOSPI"}, {"code": "034020", "name": "두산에너빌리티", "market": "KOSPI"}, {"code": "086790", "name": "하나금융지주", "market": "KOSPI"}, {"code": "012330", "name": "현대모비스", "market": "KOSPI"}]);
  function withDefaultAssets(rows, key = "code") {
    const actual = new Map(rows.map(row => [row[key], row]));
    const defaults = window.whatIfScenarioDefaultAssets.map(asset => ({
      [key]: asset.code, name: asset.name, market: asset.market,
      ...actual.get(asset.code)
    }));
    const known = new Set(defaults.map(row => row[key]));
    return defaults.concat(rows.filter(row => !known.has(row[key])));
  }

  function formatLongTime(value) {
    if (!value || !Number.isFinite(Date.parse(value))) return "미확인";
    const d = new Date(value);
    const date = new Intl.DateTimeFormat("ko-KR", {
      timeZone: "Asia/Seoul", year: "numeric", month: "long", day: "numeric", weekday: "long"
    }).format(d).replace("년 ", " ");
    const parts = new Intl.DateTimeFormat("ko-KR", {
      timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23"
    }).formatToParts(d).reduce((out, part) => (out[part.type] = part.value, out), {});
    const time = `${parts.hour}시 ${parts.minute}분 ${parts.second}초`;
    return `${date} | ${time}`;
  }

  function sourceSelector(mode) {
    return `<select id="p57-source" class="fig-sr-only" aria-label="시세 데이터 모드">
      <option value="attachment" ${mode === "attachment" ? "selected" : ""}>첨부 스냅샷</option>
      <option value="live" ${mode === "live" ? "selected" : ""}>실제 API</option>
    </select>`;
  }

  function marketNumber(value, digits = 2) {
    return value == null || value === "" || !Number.isFinite(Number(value))
      ? "계산 불가"
      : Number(value).toLocaleString("ko-KR", { maximumFractionDigits: digits });
  }

  function marketBoolean(value) {
    return value == null ? "판정 불가" : value === true ? "예" : value === false ? "아니요" : "판정 불가";
  }

  function marketStamp(value) {
    if (!value || !Number.isFinite(Date.parse(value))) return "기준 시각 미확인";
    return new Intl.DateTimeFormat("ko-KR", {
      timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23"
    }).format(new Date(value));
  }

  function marketTable(headers, rows, label, kind) {
    const head = headers.map((header) => `<th scope="col">${escape(header)}</th>`).join("");
    const body = rows.length
      ? rows.map((cells) => `<tr>${cells.map((cell) => `<td>${escape(cell)}</td>`).join("")}</tr>`).join("")
      : `<tr><td colspan="${headers.length}">관측 항목이 없습니다.</td></tr>`;
    return `<div class="fig-live-market-tablewrap is-${kind}" role="region" aria-label="${escape(label)}" data-live-scroll tabindex="0"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  window.whatIfScenarioMarketStatePanel = function (data = {}, runSummary = "", runError = "", hasRun = false) {
    const snapshot = data.snapshot?.record_type === "market_state_snapshot" && data.snapshot.is_mock === false ? data.snapshot : null;
    const delivery = data.delivery || {};
    const portfolio = data.group === "portfolio";
    const tabs = portfolio ? ["portfolio", "result"] : ["assets", "sectors", "market"];
    const tab = tabs.includes(data.tab) ? data.tab : tabs[0];
    const assets = withDefaultAssets(Array.isArray(snapshot?.assets) ? snapshot.assets : [], "asset_id");
    const sectors = Array.isArray(snapshot?.sectors) ? snapshot.sectors : [];
    const stamp = snapshot?.last_event_time || snapshot?.last_completed_bar_end || snapshot?.as_of;
    const age = delivery.age_seconds != null && Number.isFinite(Number(delivery.age_seconds)) ? Number(delivery.age_seconds)
      : stamp && Number.isFinite(Date.parse(stamp)) ? Math.max(0, Math.floor((Date.now() - Date.parse(stamp)) / 1000)) : null;
    const stale = delivery.stale === true || age == null || age > 120;
    const stream = delivery.websocket_status === "connected";
    const status = !snapshot ? "실제 시장 데이터 수신 대기"
      : stale ? delivery.last_poll_ok ? "마지막 관측값 · 새 체결 대기" : "원본 데이터 갱신 지연"
      : stream ? "실시간 스트림 연결됨"
      : delivery.last_poll_ok ? "현재값 조회됨 · 스트림 재연결 중" : "실시간 연결 확인 중";
    const quality = ({valid:"지표 검증됨",partial:"일부 지표 미완전",stale:"원본 지연",unverified:"검증 대기"})[snapshot?.quality_status]
      || snapshot?.quality_status || "품질 미확인";
    const count = snapshot ? `${snapshot.valid_asset_count ?? assets.length}/${snapshot.expected_asset_count ?? assets.length}종목` : "관측 대기";
    const tabButtons = (portfolio ? [["result", "실행 결과"]] : [["assets", "종목"], ["sectors", "업종"], ["market", "시장"]])
      .map(([key, name]) => `<button type="button" data-gx="p57-market-state-tab" data-tab="${key}" role="tab" aria-selected="${tab === key}" class="${key === "result" ? "is-primary " : ""}${tab === key ? "is-active" : ""}">${name}</button>`).join("");
    const portfolioButton = `<button type="button" class="fig-portfolio-view is-primary" data-gx="p63-portfolio-view" role="tab" aria-selected="${tab === "portfolio"}">나의 포트폴리오 (${new Set((data.portfolioLots || []).map(lot => lot.code)).size})</button>`;
    let content;
    if (tab === "portfolio") {
      const lots = data.portfolioLots || [], rows = data.portfolioResults || [];
      const groups = new Map();
      lots.forEach((lot, index) => {
        const code = String(lot.code || "");
        if (!groups.has(code)) groups.set(code, { code, name: lot.name || code, quantity: 0, indices: [], selectedValue: 0 });
        const group = groups.get(code);
        group.quantity += Number(lot.quantity) || 0;
        group.indices.push(index);
        group.selectedValue += (Number(lot.quantity) || 0) * (Number(lot.price) || 0);
      });
      const body = [...groups.values()].map((group) => {
        const result = rows.find((row) => row.asset_id === group.code);
        const changedQuantity=result&&data.portfolioQuantities?.[group.code]!=null&&data.portfolioQuantities[group.code]!==group.quantity;
        const prices = group.indices.map((index) => Number(data.portfolioPrices?.[index]));
        const executedPrice = result && prices.length && prices.every((price) => Number.isFinite(price) && price > 0 && price === prices[0]) ? prices[0] : null;
        const selectedPrices = group.indices.map((index) => Number(lots[index].price));
        const selectedPrice = selectedPrices.length && selectedPrices.every((price) => Number.isFinite(price) && price > 0 && price === selectedPrices[0]) ? selectedPrices[0] : null;
        const priceText = selectedPrice == null ? "시세 미확인" : `${marketNumber(selectedPrice, 0)}원`;
        const amountText = selectedPrice == null ? "—" : marketNumber(group.selectedValue, 0);
        const range = result?.model_interval_90_return_pct;
        const rangeText = range && range.lower != null && range.upper != null ? `${marketNumber(range.lower)}% ~ ${marketNumber(range.upper)}%` : "—";
        const remove = group.indices.map((index) => `<button type="button" data-gx="p63-remove-lot" data-index="${index}" aria-label="${escape(group.name)} ${index + 1}번 보유분 ${escape(lots[index].quantity)}주 삭제">${escape(lots[index].quantity)}주 삭제</button>`).join(" ");
        const avg = Number(lots[group.indices[0]]?.avgPurchasePrice);
        const purchase = Number.isFinite(avg) && avg > 0 ? avg * group.quantity : null;
        const valuation = Number.isFinite(selectedPrice) ? selectedPrice * group.quantity : null;
        const pnl = purchase !== null && valuation !== null ? valuation - purchase : null;
        return `<tr><th scope="row">${escape(group.name)} (${escape(group.code)})</th><td>${escape(group.quantity)}주</td><td>${purchase === null ? "미입력" : `${escape(marketNumber(avg, 0))}원`}</td><td>${purchase === null ? "—" : `${escape(marketNumber(purchase, 0))}원`}</td><td>${escape(priceText)}</td><td>${amountText === "—" ? "—" : `${escape(amountText)}원`}</td><td>${pnl === null ? "—" : `${escape(marketNumber(pnl, 0))}원`}</td><td>${result ? `${escape(marketNumber(result.scenario_return_pct))}%${changedQuantity?"<small>보유 수량 변경 · 재실행 필요</small>":""}` : "선택 미포함 · 미실행"}</td><td>${escape(rangeText)}</td><td>${result ? `${escape(marketNumber(result.hypothetical_pnl_krw, 0))}원<small>실행 투입 ${escape(marketNumber(result.holding_krw, 0))}원 · 시세 ${executedPrice == null ? "미확인" : `${escape(marketNumber(executedPrice, 0))}원`}</small>` : "—"}</td><td>${remove}</td></tr>`;
      }).join("");
      content = lots.length ? `<div class="fig-live-market-tablewrap is-portfolio" role="region" aria-label="내 포트폴리오" data-live-scroll tabindex="0"><table><caption>서버에 저장된 보유 종목입니다. 조회 시세는 마지막으로 수신한 실제 값이며, 수신 전에는 저장 시점 값입니다. 실행 결과는 모델 기준일 ${escape(data.portfolioBasisDate || "미확인")}의 API 값입니다. 과거 실행 손익은 당시 보유 규모로 고정되며, 선택하지 않은 종목은 분석에 포함되지 않습니다.</caption><thead><tr><th scope="col">종목</th><th scope="col">보유 주수</th><th scope="col">평균 매입가</th><th scope="col">총 매입금액</th><th scope="col">조회 시세</th><th scope="col">평가금액</th><th scope="col">평가손익</th><th scope="col">입력 충격 수익률</th><th scope="col">종목별 90% 모델 구간</th><th scope="col">입력 충격 가상 손익</th><th scope="col">보유분 관리</th></tr></thead><tbody>${body}</tbody></table></div>` : `<div class="fig-live-market-empty" role="status"><div><strong>보유 종목을 추가해 자산 영향을 확인하세요.</strong><p>실시간 종목에서 수량과 평균 매입가를 입력하면 이곳에 저장됩니다.</p><button type="button" data-gx="p57-market-state-tab" data-tab="assets">기본 20종목에서 자산 추가</button></div></div>`;
    } else if (tab === "result") {
      content = `<div class="fig-live-market-results" role="region" aria-label="시나리오 실행 결과" tabindex="0">${runSummary || (!runError ? '<p>분석 대상과 충격 변수를 설정한 뒤 PLAY를 누르세요. 실행 결과를 이곳에서 비교할 수 있습니다.</p>' : "")}${runError}</div>`;
    } else if (!snapshot && tab !== "assets") {
      content = `<div class="fig-live-market-empty" role="status">${escape(delivery.error || "실제 시장 스냅샷을 기다리고 있습니다. 모의 데이터는 표시하지 않습니다.")}</div>`;
    } else if (tab === "assets") {
      const rows = [...assets].sort((a, b) => String(a.asset_id || "").localeCompare(String(b.asset_id || "")));
      content = `<div class="fig-live-market-tablewrap is-assets" role="region" aria-label="실시간 종목 관측 표" data-live-scroll tabindex="0"><table><thead><tr>${["종목 / 내 보유종목", "업종", "전일 대비 %", "시가 대비 %", "5분 %", "30분 변동성 %", "누적 거래량", "완전 수신"].map(h => `<th scope="col">${escape(h)}</th>`).join("")}</tr></thead><tbody>${rows.map(asset => `<tr><td class="fig-holding-picker"><button type="button" data-gx="p63-add-lot" data-code="${escape(asset.asset_id)}" aria-label="${escape(asset.asset_id)} 보유 자산 입력">${escape(asset.name || asset.asset_id || "미확인")} · ${escape(asset.asset_id)} · ${(data.portfolioLots || []).some(lot => lot.code === asset.asset_id) ? "보유 중 · 추가" : "자산 추가"}</button></td><td>${escape(asset.sector_id || "미분류")}</td><td>${escape(marketNumber(asset.return_since_previous_close_pct))}</td><td>${escape(marketNumber(asset.return_since_open_pct))}</td><td>${escape(marketNumber(asset.return_5m_pct, 3))}</td><td>${escape(marketNumber(asset.volatility_30m_pct, 3))}</td><td>${escape(marketNumber(asset.volume_since_open, 0))}</td><td>${escape(marketBoolean(asset.complete_since_open))}</td></tr>`).join("")}</tbody></table></div>`;
    } else if (tab === "sectors") {
      content = marketTable(
        ["업종", "종목", "5분 평균 %", "하락 비율", "방향"],
        sectors.map((sector) => [
          sector.sector_id || "미분류", `${sector.valid_asset_count ?? "—"}/${sector.expected_asset_count ?? "—"}`,
          marketNumber(sector.mean_return_5m_pct, 3), marketNumber(sector.declining_ratio, 3),
          sector.recent_direction || "미확인"
        ]), "실시간 업종 관측 표", "sectors"
      );
    } else {
      const market = snapshot.market || {};
      content = `<p class="fig-live-market-scope">시장 전체 (관측 종목 동일가중, 코스피 지수 아님)</p>` + marketTable(
        ["지표", "값"], [
          ["최근 5분 방향", market.recent_direction || "미확인"],
          ["최근 5분 평균 등락률 %", marketNumber(market.mean_return_5m_pct, 3)],
          ["하락 종목 비율", marketNumber(snapshot.declining_ratio, 3)],
          ["전일 종가 대비 평균 %", marketNumber(market.mean_return_since_previous_close_pct, 3)],
          ["오늘 시가 대비 평균 %", marketNumber(market.mean_return_since_open_pct, 3)],
          ["60분 종목 간 동조화", marketNumber(market.mean_correlation_60m, 4)],
          ["60분 동반 하락 비율", marketNumber(market.joint_down_ratio_60m, 3)],
          ["업종 분류 비율", marketNumber(market.sector_classification_coverage, 2)]
        ], "실시간 시장 관측 표", "market"
      );
    }
    if (portfolio) return `<div class="fig-live-market-tabs" role="tablist" aria-label="포트폴리오와 실행 결과">${portfolioButton}${tabButtons}</div>${content}`;
    return `<header class="fig-live-market-head"><h3>실시간 데이터</h3><span class="fig-live-market-status ${!snapshot ? "is-waiting" : stale ? "is-stale" : "is-live"}" role="status">${escape(status)}</span><small>${escape(count)} · ${escape(quality)}</small><button type="button" data-gx="p57-market-state-refresh" aria-label="시장 데이터 새로고침">새로고침</button></header>
      <div class="fig-live-market-tabs" role="tablist" aria-label="시장 데이터 구분">${tabButtons}<span>원본 기준 ${escape(marketStamp(stamp))}</span></div>
      ${content}
      <footer class="fig-live-market-foot"><span>출처: ${escape(snapshot?.source || "시장 상태 API")} · ${escape(snapshot?.universe_id || "관측 범위 미확인")}</span><span>${snapshot ? `완전 수신 ${assets.filter((asset) => asset.complete_since_open === true).length}/${assets.length}` : "실제 관측값만 표시"}</span></footer>`;
  };

  window.whatIfScenarioLiveMarketStatePanel = function (data = {}) {
    const runSummary = typeof data.runSummary === "string" ? data.runSummary : "";
    const runError = data.runError ? `<p class="fig-run-error" role="alert">${escape(data.runError)}</p>` : "";
    return `<section class="fig-results-bay fig-live-market fig-live-state-panel" data-node-id="46:1009" aria-label="포트폴리오와 실행 결과">
      ${window.whatIfScenarioMarketStatePanel({ ...data, group: "portfolio", tab: data.portfolioTab }, runSummary, runError, Boolean(runSummary || runError))}
    </section>`;
  };

  function sourceTable({ kind, label, columns, rows, empty, scrollKey = kind }) {
    const colgroup = columns.map(([, size]) => `<col class="source-col-${size}">`).join("");
    const header = columns.map(([name, size, align]) =>
      `<th scope="col" class="source-align-${align || "left"}">${size === "action" ? `<span class="fig-sr-only">${name}</span>` : name}</th>`
    ).join("");
    const body = rows || `<tr><td colspan="${columns.length}" class="source-table-empty"><span role="status">${escape(empty)}</span></td></tr>`;
    return `<div class="source-table-scroll" data-source-table-scroll="${escape(scrollKey)}" role="region" aria-label="${escape(label)} 표 스크롤" tabindex="0">
      <table class="source-table source-table--${kind}" aria-label="${escape(label)}">
        <colgroup>${colgroup}</colgroup>
        <thead><tr>${header}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
  }

  function sourceNumber(value, unit = "") {
    return Number.isFinite(value) ? value.toLocaleString("ko-KR") + unit : "—";
  }

  function sourceChange(value) {
    if (!Number.isFinite(value)) return '<td class="source-align-right">—</td>';
    const direction = value > 0 ? "up" : value < 0 ? "down" : "flat";
    const sign = value > 0 ? "+" : "";
    const arrow = direction === "up" ? "▲" : direction === "down" ? "▼" : "";
    return `<td class="source-align-right source-change-${direction}"><span aria-hidden="true">${arrow}</span> ${sign}${value.toFixed(2)}%</td>`;
  }

  function sourceTime(value) {
    if (!value || !Number.isFinite(Date.parse(value))) return "—";
    return `<time datetime="${escape(value)}" title="${escape(formatLongTime(value))}">${escape(marketStamp(value))}</time>`;
  }

  window.whatIfScenarioDataPanel = function (data) {
    if (data.panel === "news") return window.whatIfScenarioNewsPanel(data.news || {});
    if (data.panel === "document") return window.whatIfScenarioDocumentPanel(data.document || {});
    const market = data.market || {};
    const rawRows = withDefaultAssets(Array.isArray(market.rows) ? market.rows : []);
    const term = String(data.query || "").normalize("NFKC").toLowerCase().replace(/[^가-힣a-z0-9]/g, "");
    const normalize = (value) => String(value || "").normalize("NFKC").toLowerCase().replace(/[^가-힣a-z0-9]/g, "");
    const rows = rawRows.filter((row) => !term || normalize(`${row.name} ${row.code} ${row.sector}`).includes(term));
    rows.sort((a, b) => data.sort === "name"
      ? String(a.name || "").localeCompare(String(b.name || ""), "ko")
      : (b.volume ?? -1) - (a.volume ?? -1));
    const isIndicators = data.tab === "indicators";
    const mode = data.mode || "attachment";
    const status = data.source || "미연결";
    const heldCodes = new Set((data.portfolioLots || []).map(lot => lot.code));
    const columns = [
      ["보유 자산", "action", "center"], ["번호", "rank", "center"], ["종목", "subject"],
      ...(isIndicators
        ? [["업종", "sector"], ["전일 대비", "number", "right"], ["시가 대비", "number", "right"],
           ["5분 변동", "number", "right"], ["30분 변동성", "number", "right"]]
        : [["현재가", "number", "right"], ["전일 대비", "number", "right"], ["체결량", "number", "right"]]),
      ["누적 거래량", "volume", "right"], ["체결 시각", "time"], ["수집 시각", "time"]
    ];
    const rowHTML = rows.map((row, index) => {
      const chosen = heldCodes.has(row.code);
      const name = escape(row.name || "종목 미확인");
      const code = escape(row.code || "—");
      const sector = escape(row.sector || "—");
      const actionTitle = `${name} ${chosen ? "보유 중 · 자산 추가" : "보유 자산 입력"}`;
      return `<tr data-code="${code}" data-source-row="${code}"${chosen ? ' class="is-selected"' : ""}>
        <td class="source-align-center"><button class="source-table-action" type="button" data-gx="p63-add-lot" data-code="${code}" aria-label="${actionTitle}" title="${actionTitle}">${chosen ? "✓" : "+"}</button></td>
        <td class="source-align-center source-rank">${index + 1}</td>
        <th scope="row" class="source-subject"><strong title="${name}">${name}</strong><small>${code}</small></th>
        ${isIndicators
          ? `<td class="source-sector" title="${sector}">${sector}</td>${sourceChange(row.changePct)}${sourceChange(row.openPct)}${sourceChange(row.fiveMinute)}<td class="source-align-right">${sourceNumber(row.volatility30, "%")}</td>`
          : `<td class="source-align-right">${sourceNumber(row.price)}</td>${sourceChange(row.changePct)}<td class="source-align-right">${sourceNumber(row.tradeVolume, "주")}</td>`}
        <td class="source-align-right">${sourceNumber(row.volume, "주")}</td>
        <td class="source-time">${sourceTime(row.tradeAt)}</td>
        <td class="source-time">${sourceTime(row.collectedAt || row.receivedAt)}</td>
      </tr>`;
    }).join("");
    const total = rows.length;
    const table = sourceTable({
      kind: isIndicators ? "indicators" : "quotes",
      label: isIndicators ? "장중 종목 지표" : "실시간 종목 시세",
      columns, rows: rowHTML,
      empty: term ? "검색 결과가 없습니다." : data.busy ? "실시간 데이터를 확인하고 있습니다." : "표시할 시세 데이터가 없습니다."
    });
    const activeTabTitle = mode === "attachment"
      ? `${status} · 클릭하면 실제 API 시세를 요청합니다.`
      : `${status} · 실제 API 시세`;
    const lastTrade = market.lastTradeAt || market.receivedAt;
    const quoteIsStale = mode === "live" && (market.status === "stale" || market.stale === true);
    const quoteStatus = mode === "attachment" ? "연습 데이터 · 실제 시세 아님"
      : quoteIsStale ? `원본 시세 갱신 지연 · 마지막 체결 ${marketStamp(lastTrade)}`
      : market.status === "connected" || market.status === "partial" ? `API 시세 · 마지막 체결 ${marketStamp(lastTrade)}`
      : `${status} · 마지막 체결 ${marketStamp(lastTrade)}`;
    return `${sourceSelector(mode)}
      <div class="fig-data-toolbar">
        <label class="fig-search-field"><img src="${icon("Search.svg")}" alt=""><input id="p57-filter" name="stock-search" type="search" autocomplete="off" placeholder="종목명 · 코드 검색" aria-label="종목 목록 검색" value="${escape(data.query || "")}"></label>
        <button class="fig-icon-button fig-filter-button" type="button" data-gx="p57-data-tab" data-tab="${isIndicators ? "quotes" : "indicators"}" aria-label="${isIndicators ? "종목 시세" : "장중 지표"}"><img src="${icon("filter.svg")}" alt=""></button>
        <button class="fig-icon-button fig-live-button" type="button" data-gx="p57-live-mode" aria-label="실시간 시세 연결" title="${escape(activeTabTitle)}"><img src="${image("play-arrow.png")}" alt=""></button>
        <button class="fig-icon-button fig-refresh-button" type="button" data-gx="p57-refresh" ${data.busy || mode === "attachment" ? "disabled" : ""} aria-label="실시간 시세 새로고침" title="실시간 시세 새로고침"><img src="${icon("refresh-small.svg")}" alt=""></button>
      </div>
      <p class="fig-quote-status ${quoteIsStale ? "is-stale" : ""}" role="status">${escape(quoteStatus)}</p>
      ${table}
      <div class="fig-quote-footer"><span>${total}종목</span><span>보유 자산 입력 후 포트폴리오에 저장</span></div>`;
  };

  window.whatIfScenarioNewsPanel = function (data) {
    const modes = [["all", "전체"], ["politics", "정치"], ["economy", "경제"], ["society", "사회"], ["company", "기업별"]];
    const selected = new Set(data.selected || []);
    const rows = Array.isArray(data.rows) ? data.rows : [];
    const publishers = Array.isArray(data.publishers) ? data.publishers : [];
    const modeLabel = modes.find(([id]) => id === data.mode)?.[1] || "전체";
    const statusText = data.busy ? (data.progress || "최근 뉴스를 확인하고 있습니다.")
      : data.status === "connected" ? `Google News RSS · 조회 ${data.updatedAt || "시각 미확인"}`
      : data.status === "partial" ? `일부 주제 미수신 · ${data.error} · 조회 ${data.updatedAt || "시각 미확인"}`
      : data.status === "error" ? `${data.error || "뉴스 데이터를 가져오지 못했습니다."}${data.stale ? " · 이전 조회 결과 표시 중" : ""}`
      : "최근 뉴스를 불러오는 중입니다.";
    const rowHTML = rows.map((row, index) => {
      const checked = selected.has(row.id);
      const title = escape(row.title || "제목 미확인");
      const publisher = escape(row.publisher || "언론사 미확인");
      const category = {politics:"정치",economy:"경제",society:"사회",company:"기업"}[row.category] || "뉴스";
      return `<tr data-source-row="${escape(row.id)}"${checked ? ' class="is-selected"' : ""}>
        <td class="source-align-center"><button type="button" class="source-table-action" data-gx="p57-news-select" data-id="${escape(row.id)}" aria-pressed="${checked}" aria-label="${title} ${checked ? "선택 취소" : "분석에 추가"}">${checked ? "✓" : "+"}</button></td>
        <td class="source-align-center source-rank">${index + 1}</td>
        <th scope="row" class="source-subject"><strong title="${title}">${title}</strong></th>
        <td class="source-category">${category}</td>
        <td class="source-publisher" title="${publisher}">${publisher}</td>
        <td class="source-time">${sourceTime(row.publishedAt)}</td>
        <td class="source-align-center">${row.url ? `<a class="source-open" href="${escape(row.url)}" target="_blank" rel="noopener noreferrer" aria-label="${title} 기사 새 창에서 보기">보기 ↗</a>` : "—"}</td>
      </tr>`;
    }).join("");
    const table = sourceTable({
      kind: "news",
      label: `${modeLabel} 뉴스 목록`,
      columns: [["선택", "action", "center"], ["번호", "rank", "center"], ["기사 제목", "subject"], ["분류", "category"], ["언론사", "publisher"], ["게재 시각", "time"], ["원문", "open", "center"]],
      rows: rowHTML,
      empty: data.busy ? "최신 기사를 확인하고 있습니다." : data.status === "error" ? "연결된 뉴스 데이터가 없습니다. 잠시 후 다시 실행해 주세요."
        : data.query ? "검색 결과가 없습니다." : data.publisher ? "선택한 언론사의 뉴스가 없습니다." : "표시할 기사가 없습니다. 새로고침해 주세요."
    });
    return `<div class="fig-news-panel">
      <div class="fig-news-toolbar">
        <label class="fig-search-field"><img src="${icon("Search.svg")}" alt=""><input id="p57-news-filter" name="news-search" type="search" autocomplete="off" placeholder="제목 · 언론사 검색" aria-label="뉴스 제목과 언론사 검색" value="${escape(data.query || "")}"></label>
        <button class="fig-news-run-fetch" type="button" data-gx="p57-news-refresh" ${data.busy ? "disabled" : ""}>${data.busy ? "가져오는 중" : "실시간 뉴스 데이터 실행"}</button>
      </div>
      <div class="fig-news-categories" role="tablist" aria-label="뉴스 주제 분류">
        ${modes.map(([id, label]) => `<button type="button" role="tab" aria-selected="${data.mode === id}" class="${data.mode === id ? "is-active" : ""}" data-gx="p57-news-mode" data-mode="${id}">${label}</button>`).join("")}
        <select id="p57-news-publisher" aria-label="언론사 필터"><option value="">언론사 전체</option>${publishers.map((publisher) => `<option value="${escape(publisher)}" ${data.publisher === publisher ? "selected" : ""}>${escape(publisher)}</option>`).join("")}</select>
      </div>
      ${data.mode === "company" ? `<div class="fig-news-company"><label for="p57-news-company">기업</label><select id="p57-news-company" aria-label="기사 조회 기업">${(data.companies || []).map((company) => `<option value="${escape(company.name)}" ${data.company === company.name ? "selected" : ""}>${escape(company.name)} · ${escape(company.code || "")}</option>`).join("")}</select><button type="button" data-gx="p57-news-company-refresh" ${data.busy ? "disabled" : ""}>최근 3개월 조회</button></div>` : ""}
      <div class="fig-news-heading ${data.mode === "company" ? "is-company" : ""}"><strong>${data.mode === "company" ? escape(data.company || "기업") + " 관련 기사" : modeLabel + " 최근 뉴스"}</strong><span>${rows.length}건 · ${data.mode === "company" ? "최근 3개월" : "주제별 필터"}</span></div>
      <p class="fig-news-status ${data.mode === "company" ? "is-company" : ""} ${data.status === "error" ? "is-error" : ""}" role="status" aria-live="polite">${escape(statusText)}</p>
      ${table}
      <div class="fig-news-footer"><span>${selected.size}건 추가 · <span class="fig-news-credit">Google News RSS</span> · 기사 본문 미수집</span><button type="button" data-gx="p57-news-send" data-has-articles="${selected.size > 0}" ${selected.size && data.canAnalyze ? "" : "disabled"}>에이전트 실행</button></div>
    </div>`;
  };

  window.whatIfScenarioDocumentPanel = function (data) {
    const views = [["original", "DART 공시원문 활용"], ["major", "주요공시 및 재무정보 제공"], ["bulk", "대용량 재무정보 제공"]];
    const company = data.company || null;
    const dateLabel = (value) => {
      const date = String(value || "");
      return /^\d{8}$/.test(date) ? `${date.slice(0, 4)}.${date.slice(4, 6)}.${date.slice(6, 8)}` : date || "미확인";
    };
    const status = data.busy ? (data.progress || "DART 자료를 불러오는 중입니다.")
      : data.status === "error" ? (data.error || "DART 자료를 가져오지 못했습니다.")
      : data.status === "ready" ? `DART 응답 · ${escape(data.updatedAt || "조회 완료")}`
      : "회사를 찾고 ‘공시 조회’를 눌러 DART 자료를 불러오세요.";
    const subtabs = views.map(([id, label]) => `<button type="button" role="tab" aria-selected="${data.view === id}" class="${data.view === id ? "is-active" : ""}" data-gx="p57-doc-view" data-view="${id}">${label}</button>`).join("");
    const companyName = company ? `${escape(company.corp_name)}${company.stock_code ? ` · ${escape(company.stock_code)}` : ""}` : "회사를 선택하세요";
    const companyResults = (data.companies || []).map((row) => `<button type="button" class="fig-doc-company-option" data-gx="p57-doc-company-pick" data-corp="${escape(row.corp_code)}" data-name="${escape(row.corp_name)}" data-stock="${escape(row.stock_code || "")}"><strong>${escape(row.corp_name)}</strong><small>${escape(row.stock_code || "비상장/기타법인")} · ${escape(row.corp_code)}</small></button>`).join("");
    const companySearch = `<div class="fig-doc-company-search"><label class="fig-search-field"><img src="${icon("Search.svg")}" alt=""><input id="p57-doc-company-query" type="search" maxlength="100" placeholder="회사명 또는 종목코드" aria-label="DART 회사 검색" value="${escape(data.companyQuery || "")}"></label><button type="button" data-gx="p57-doc-company-search" ${data.companyBusy || !String(data.companyQuery || "").trim() ? "disabled" : ""}>${data.companyBusy ? "찾는 중" : "회사 찾기"}</button></div>${companyResults ? `<div class="fig-doc-company-results" role="listbox" aria-label="회사 검색 결과">${companyResults}</div>` : data.companyStatus ? `<div class="fig-doc-company-results fig-doc-company-message" role="status">${escape(data.companyStatus)}</div>` : ""}<div class="fig-doc-company-current"><span>선택 회사</span><strong>${companyName}</strong></div>`;
    const majorModes = `<div class="fig-doc-content-mode" role="tablist" aria-label="주요공시 및 재무정보"><button type="button" role="tab" aria-selected="${data.contentMode === "major"}" class="${data.contentMode === "major" ? "is-active" : ""}" data-gx="p57-doc-content-mode" data-mode="major">주요공시</button><button type="button" role="tab" aria-selected="${data.contentMode === "financials"}" class="${data.contentMode === "financials" ? "is-active" : ""}" data-gx="p57-doc-content-mode" data-mode="financials">재무정보</button></div>`;
    const dateFilters = `<div class="fig-doc-filters"><label>시작일<input id="p57-doc-begin" type="date" value="${escape(data.begin || "")}" aria-label="공시 조회 시작일"></label><label>종료일<input id="p57-doc-end" type="date" value="${escape(data.end || "")}" aria-label="공시 조회 종료일"></label><select id="p57-doc-type" aria-label="공시 유형"><option value="" ${!data.publicationType ? "selected" : ""}>전체 공시</option><option value="A" ${data.publicationType === "A" ? "selected" : ""}>정기공시</option><option value="B" ${data.publicationType === "B" ? "selected" : ""}>주요사항</option><option value="C" ${data.publicationType === "C" ? "selected" : ""}>발행공시</option><option value="D" ${data.publicationType === "D" ? "selected" : ""}>지분공시</option><option value="E" ${data.publicationType === "E" ? "selected" : ""}>기타</option></select><button type="button" class="fig-doc-query" data-gx="p57-doc-refresh" ${data.busy || !company ? "disabled" : ""}>공시 조회</button></div>`;
    const records = Array.isArray(data.records) ? data.records : [];
    const page = Math.max(1, Number(data.page) || 1);
    const totalPages = Math.max(1, Number(data.totalPage) || 1);
    const columns = [
      ["번호", "rank", "center"], ["공시 제목", "subject"], ["회사", "publisher"],
      ["제출인", "publisher"], ["접수일", "number"], ["접수번호", "time"], ["상세", "open", "center"]
    ];
    const rows = records.map((row, index) => {
      const title = escape(row.report_nm || "공시 제목 미확인");
      const issuer = escape(row.corp_name || company?.corp_name || "—");
      const filer = escape(row.flr_nm || "—");
      const receipt = String(row.rcept_no || "");
      const canOpen = /^\d{14}$/.test(receipt);
      return `<tr data-source-row="${escape(receipt || String(index))}">
        <td class="source-align-center source-rank">${index + 1}</td>
        <th scope="row" class="source-subject" title="${title}">${title}</th>
        <td class="source-publisher" title="${issuer}">${issuer}</td>
        <td class="source-publisher" title="${filer}">${filer}</td>
        <td class="source-time">${escape(dateLabel(row.rcept_dt))}</td>
        <td class="source-time">${escape(receipt || "—")}</td>
        <td class="source-align-center">${canOpen ? `<button type="button" class="source-table-action source-doc-detail" data-gx="p57-doc-open" data-receipt="${receipt}" aria-label="${title} 상세 팝업 열기">보기 ↗</button>` : "—"}</td>
      </tr>`;
    }).join("");
    const disclosureTable = sourceTable({
      kind: "disclosures", label: "DART 공시 목록", columns, rows,
      scrollKey: `disclosures:${data.view}:${company?.corp_code || ""}:${page}`,
      empty: data.busy ? "공시 목록을 불러오고 있습니다." : data.status === "error" ? "조회에 실패했습니다. 검색 조건을 확인하고 다시 요청해 주세요."
        : !company ? "회사 검색 후 공시를 조회할 수 있습니다."
        : data.status === "ready" ? "조건에 맞는 공시가 없습니다. 기간을 넓혀 다시 조회해 주세요." : "조건을 선택한 뒤 공시를 조회해 주세요."
    });
    const disclosureArea = `<div class="fig-doc-list-heading"><strong>${data.view === "major" ? "주요공시" : "공시원문 목록"}</strong><span>${records.length}건 표시 · 전체 ${Number(data.totalCount) || 0}건</span><div class="fig-doc-pages"><button type="button" data-gx="p57-doc-page" data-page="${Math.max(1, page - 1)}" ${data.busy || page <= 1 ? "disabled" : ""} aria-label="이전 공시 페이지">‹</button><span>${page}/${totalPages}</span><button type="button" data-gx="p57-doc-page" data-page="${Math.min(totalPages, page + 1)}" ${data.busy || page >= totalPages ? "disabled" : ""} aria-label="다음 공시 페이지">›</button></div></div>${disclosureTable}`;
    const currentPeriod = escape(data.financials?.[0]?.thstrm_nm || "당기"), previousPeriod = escape(data.financials?.[0]?.frmtrm_nm || "전기"), currency = escape(data.financials?.[0]?.currency || "DART 응답 단위");
    const financialRows = (data.financials || []).filter((row) => !data.statementSection || row.sj_div === data.statementSection).map((row) => `<tr><th scope="row"><span>${escape(row.sj_nm || row.sj_div || "계정")}</span><strong>${escape(row.account_nm || "계정명 미확인")}</strong></th><td>${escape(row.thstrm_amount || "—")}</td><td>${escape(row.frmtrm_amount || "—")}</td></tr>`).join("");
    const financialArea = `<div class="fig-doc-finance-tools"><label>사업연도<input id="p57-doc-year" type="number" min="2000" max="2099" value="${escape(data.year || "")}" aria-label="사업연도"></label><select id="p57-doc-report-code" aria-label="보고서 유형"><option value="11011" ${data.reportCode === "11011" ? "selected" : ""}>사업보고서</option><option value="11012" ${data.reportCode === "11012" ? "selected" : ""}>반기보고서</option><option value="11013" ${data.reportCode === "11013" ? "selected" : ""}>1분기보고서</option><option value="11014" ${data.reportCode === "11014" ? "selected" : ""}>3분기보고서</option></select><select id="p57-doc-fs-div" aria-label="재무제표 기준"><option value="CFS" ${data.fsDiv === "CFS" ? "selected" : ""}>연결재무제표</option><option value="OFS" ${data.fsDiv === "OFS" ? "selected" : ""}>별도재무제표</option></select><button type="button" data-gx="p57-doc-finance-fetch" ${data.financialBusy || !company ? "disabled" : ""}>재무 조회</button></div><div class="fig-doc-finance-bar"><strong>${escape(company?.corp_name || "회사 미선택")} 재무 계정</strong><select id="p57-doc-section" aria-label="재무제표 구분"><option value="">전체 계정</option><option value="BS" ${data.statementSection === "BS" ? "selected" : ""}>재무상태표</option><option value="IS" ${data.statementSection === "IS" ? "selected" : ""}>손익계산서</option><option value="CIS" ${data.statementSection === "CIS" ? "selected" : ""}>포괄손익계산서</option><option value="CF" ${data.statementSection === "CF" ? "selected" : ""}>현금흐름표</option><option value="SCE" ${data.statementSection === "SCE" ? "selected" : ""}>자본변동표</option></select></div><div class="fig-doc-finance-list"><table><thead><tr><th>계정과목</th><th>${currentPeriod}</th><th>${previousPeriod}</th></tr></thead><tbody>${financialRows || `<tr><td colspan="3" class="fig-doc-finance-empty">${data.financialBusy ? "재무정보를 불러오고 있습니다." : data.financialStatus === "error" ? escape(data.financialError || "재무정보 조회에 실패했습니다.") : data.financials?.length ? "선택한 재무제표에 계정이 없습니다." : "회사를 고르고 사업연도·보고서 유형을 선택한 뒤 ‘재무 조회’를 눌러 주세요."}</td></tr>`}</tbody></table></div><div class="fig-doc-finance-foot"><span>${data.financials?.length || 0}개 계정 · ${currency} 단위 응답 그대로 표시</span><button type="button" data-gx="p57-doc-finance-csv" ${data.financials?.length ? "" : "disabled"}>CSV 저장</button></div>`;
    const detailFields = Object.entries(data.modal?.detail_fields || {}).map(([label, value]) => `<tr><th scope="row">${escape(label)}</th><td>${escape(value)}</td></tr>`).join("");
    const detailStatus = data.modal?.detail_status === "loading" ? "주요사항보고서 구조화 상세를 확인하고 있습니다."
      : data.modal?.detail_status === "error" ? escape(data.modal?.detail_error || "상세 항목을 불러오지 못했습니다.")
      : data.modal?.detail_status === "empty" ? "이 공시 접수번호에 연결된 구조화 상세 항목이 없습니다. 아래 원문을 확인해 주세요."
      : data.modal?.detail_status === "unavailable" ? "이 보고서 유형은 구조화 상세 API가 제공되지 않습니다. 아래 원문에서 확인해 주세요."
      : "공시 상세 항목은 DART 원문을 기준으로 확인할 수 있습니다.";
    const detailSection = `<section class="fig-doc-modal-details"><strong>${data.modal?.detail_type ? escape(data.modal.detail_type) : "공시 상세"}</strong>${detailFields ? `<table aria-label="공시 상세 항목"><tbody>${detailFields}</tbody></table>` : `<p role="status">${detailStatus}</p>`}</section>`;
    const sourceLink = "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do";
    const xbrl = data.records?.find((row) => /^\d{14}$/.test(row.rcept_no || "") && /사업보고서|반기보고서|분기보고서/.test(row.report_nm || ""));
    const xbrlCode = !xbrl ? "11011" : /반기보고서/.test(xbrl.report_nm) ? "11012" : /1분기보고서/.test(xbrl.report_nm) ? "11013" : /3분기보고서/.test(xbrl.report_nm) ? "11014" : "11011";
    const bulkArea = `<div class="fig-doc-bulk-card"><span class="fig-doc-stamp">DART · OPEN API</span><strong>분기별 재무제표 대량 파일</strong><p>OpenDART는 XBRL로 제출된 정기보고서 재무제표를 분기별 TXT 일괄 파일로 제공합니다. 제공 대상과 기준일은 원본 페이지에서 확인하세요.</p><a href="${sourceLink}" target="_blank" rel="noopener noreferrer">공식 일괄다운로드 안내 ↗</a></div><div class="fig-doc-bulk-card is-secondary"><strong>선택 회사의 XBRL 원문</strong><p>${escape(xbrl ? `${xbrl.corp_name || company?.corp_name || "선택 회사"} · ${xbrl.report_nm} · 접수 ${xbrl.rcept_no}` : company ? "정기보고서 접수번호를 찾으려면 공시원문 탭에서 조회해 주세요." : "회사를 선택한 다음 공시원문 탭에서 조회해 주세요.")}</p><label>보고서 유형<select id="p57-doc-bulk-report"><option value="11011" ${xbrlCode === "11011" ? "selected" : ""}>사업보고서</option><option value="11012" ${xbrlCode === "11012" ? "selected" : ""}>반기보고서</option><option value="11013" ${xbrlCode === "11013" ? "selected" : ""}>1분기보고서</option><option value="11014" ${xbrlCode === "11014" ? "selected" : ""}>3분기보고서</option></select></label><button type="button" data-gx="p57-doc-xbrl-download" data-receipt="${escape(xbrl?.rcept_no || "")}" ${data.xbrlBusy || !xbrl ? "disabled" : ""}>${data.xbrlBusy ? "XBRL 받는 중" : "선택 보고서 XBRL ZIP 받기"}</button></div><p class="fig-doc-bulk-note">분기별 일괄 파일은 TXT, 선택 보고서 원문 API는 XBRL ZIP 형식입니다.</p>`;
    const body = data.view === "bulk" ? `${companySearch}${bulkArea}` : `${companySearch}${data.view === "major" ? majorModes : ""}${data.view === "major" && data.contentMode === "financials" ? financialArea : `${dateFilters}${`<p class="fig-doc-status ${data.status === "error" ? "is-error" : ""}" role="status" aria-live="polite">${escape(status)}</p>`}${disclosureArea}`}`;
    const preview = data.modal?.preview_status === "loading"
      ? `<p role="status">DART 공시 원문 본문을 불러오고 있습니다.</p>`
      : data.modal?.preview_status === "ready"
        ? `${data.modal.preview_html ? `<div class="fig-doc-content">${data.modal.preview_html}</div>` : `<pre>${escape(data.modal.preview_text || "")}</pre>`}${data.modal.preview_truncated ? `<p class="fig-doc-preview-note">미리보기 일부만 표시했습니다. 전체 원문은 아래 링크나 ZIP 파일에서 확인하세요.</p>` : ""}`
        : data.modal?.preview_status === "empty"
          ? `<p role="status">${escape(data.modal.preview_error || "표시할 본문 텍스트가 없습니다. 아래 DART 원문 링크나 ZIP 파일에서 확인해 주세요.")}</p>`
          : `<p class="is-error" role="alert">${escape(data.modal?.preview_error || "공시 원문 본문을 불러오지 못했습니다. 아래 링크나 ZIP 파일에서 확인해 주세요.")}</p>`;
    const modal = data.modal ? `<div class="fig-doc-modal-shade"><section class="fig-doc-modal" role="dialog" aria-modal="true" aria-labelledby="p57-doc-modal-title" data-receipt="${escape(data.modal.rcept_no || "")}"><header><div><span>DART 공시원문</span><h2 id="p57-doc-modal-title">${escape(data.modal.report_nm || "공시 상세")}</h2></div><button type="button" data-gx="p57-doc-close" aria-label="공시 팝업 닫기">×</button></header><div class="fig-doc-modal-meta"><strong>${escape(data.modal.corp_name || "회사 미확인")}</strong><span>제출인 ${escape(data.modal.flr_nm || "미확인")}</span><span>접수일 ${escape(dateLabel(data.modal.rcept_dt))}</span><span>접수번호 ${escape(data.modal.rcept_no || "미확인")}</span></div>${detailSection}<div class="fig-doc-viewer" aria-label="DART 공시 원문 본문">${preview}</div><footer><button type="button" data-ws="document-add">토론 근거로 선택</button><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${encodeURIComponent(data.modal.rcept_no || "")}" target="_blank" rel="noopener noreferrer">DART 원문 새 창에서 보기 ↗</a><button type="button" data-gx="p57-doc-download" ${data.downloadBusy ? "disabled" : ""}>${data.downloadBusy ? "원문 ZIP 받는 중" : "원문 ZIP 다운로드"}</button></footer></section></div>` : "";
    return `<div class="fig-doc-panel is-${escape(data.view || "original")}"><div class="fig-doc-subtabs" role="tablist" aria-label="DART 문서 유형">${subtabs}</div>${body}<div class="fig-doc-source-note">출처: 금융감독원 OpenDART · 공시 제출 원자료</div>${modal}</div>`;
  };

  window.whatIfScenarioWindow = function (data) {
    const sim = data.sim || {};
    const displayNumber = (value) => value === "" || value == null || Number(value) === 0 ? "" : value;
    const rate = displayNumber(Number(sim.rate) * 100);
    const fx = displayNumber(sim.fx);
    const oil = displayNumber(sim.oil);
    const vix = displayNumber(sim.vix);
    const rows = data.personas || [];
    const selected = new Set(data.selectedRoles || []);
    const avatarFiles = ["avatar-kim.png", "avatar-yoon.png", "avatar-shin.png", "avatar-kang.png"];
    const people = rows.map((role, index) => `<label class="fig-shared-agent-option">
      <img src="${image(role.image || avatarFiles[index % avatarFiles.length])}" width="20" height="20" alt="">
      <span>${escape(role.name)}<small>${escape(role.role)}</small></span>
      <input type="checkbox" data-role-choice="${escape(role.id)}" ${selected.has(role.id) ? "checked" : ""} aria-label="${escape(role.name)} ${escape(role.role)} 에이전트 선택">
    </label>`).join("");
    const messages = data.messages || "";
    const hasMessages = Boolean(messages.trim());
    const agentStatus = data.agentStatus || (!data.run && !hasMessages ? "분석 실행 후 AI에게 질문할 수 있습니다." : "");
    const hasAgentMessages = Boolean(data.hasAgentMessages);
    const prompts = ["현재 시장 상태는?", "추가로 확인할 자료를 알려주세요", "근거 수치를 알려주세요"];
    const questionButtons = prompts.map((question) => `<button type="button" data-action="quick" data-text="${escape(question)}">${escape(question)}</button>`).join("");
    const chartContent = `<div class="fig-dynamic-chart">${data.chartHTML || ""}</div>`;
    const chartPeriods = window.whatIfStressChart.periods;
    const chartPeriod = chartPeriods.has(data.chartPeriod) ? data.chartPeriod : "day";
    const chartRepresentation = ["line", "candle", "ohlc"].includes(data.chartRepresentation) ? data.chartRepresentation : "line";
    const chartTools = `<label class="fig-chart-menu"><span>차트 주기</span><select data-gx="p63-chart-period" aria-label="차트 주기">${[...chartPeriods].map(([value,label])=>`<option value="${value}" ${chartPeriod===value?"selected":""}>${label}</option>`).join("")}</select></label><label class="fig-chart-menu"><span>표현 방식</span><select data-gx="p63-chart-representation" aria-label="차트 표현 방식">${[["line","선"],["candle","캔들"],["ohlc","OHLC"]].map(([value,label])=>`<option value="${value}" ${chartRepresentation===value?"selected":""}>${label}</option>`).join("")}</select></label>`;
    const chartNavigation = `<div class="scenario-chart-navigation" role="group" aria-label="차트 구간 탐색"><button type="button" data-gx="p63-chart-navigate" data-move="older" aria-label="이전 구간">‹</button><button type="button" data-gx="p63-chart-navigate" data-move="out" aria-label="차트 축소">−</button><button type="button" data-gx="p63-chart-navigate" data-move="in" aria-label="차트 확대">+</button><button type="button" data-gx="p63-chart-navigate" data-move="newer" aria-label="다음 구간">›</button><button type="button" data-gx="p63-chart-navigate" data-move="latest">오늘로</button></div>`;
    const chatBody = data.chatMin ? `<button class="fig-chat-launcher" type="button" data-gx="chat-open">AI Agent 대화 열기</button>` : `
      <div class="fig-chat-toolbar" aria-label="AI 에이전트 도구">
        <button type="button" data-gx="account" aria-label="프로필"><img class="fig-account-icon" src="${icon("person.svg")}" alt=""></button>
        <button class="fig-mini-play" type="button" data-action="analyze-run" data-id="${escape(data.run?.id || "")}" ${data.run ? "" : "disabled"} aria-label="선택된 에이전트 분석 실행"><img src="${image("play-arrow.png")}" alt=""></button>
      </div>
      <div class="fig-chat-shared-label">공통 에이전트 대화</div>
      <div class="fig-chat-messages ${hasAgentMessages ? "has-agent-messages" : ""}" id="chat-scroll" aria-live="polite">${hasMessages ? messages : `<div class="fig-chat-prompts">${questionButtons}</div>`}</div>
      <p class="fig-chat-status" role="status" aria-live="polite" ${agentStatus ? "" : "hidden"}>${escape(agentStatus)}</p>
      <div class="fig-chat-compose">
        <img class="fig-chat-user" src="${image("avatar-user.png")}" width="35" height="35" alt="">
        <textarea data-chat-input="scenario" name="scenario-question" autocomplete="off" rows="1" placeholder="결과나 근거에 대해 질문하세요" aria-label="AI 에이전트에게 질문">${escape(data.draft || "")}</textarea>
        <button type="button" data-action="send-chat" data-key="scenario" aria-label="메시지 보내기"><img class="fig-send-icon" src="${icon("send.svg")}" alt=""></button>
      </div>`;

    return `<div class="fig-scenario-overlay" style="--fig-scale:${Number(data.scale) || 1}">
      <div class="fig-scenario-frame">
        <div class="fig-scenario-screen" role="dialog" aria-modal="true" aria-label="국내 주식 시나리오 시뮬레이션" data-node-id="46:987">
          <button class="fig-home" type="button" data-gx="feature-close" aria-label="시나리오 창 닫기"><img src="${image("home.png")}" alt=""></button>
          <section class="fig-main-panel" data-node-id="46:988" aria-label="시나리오 분석">
            <div class="fig-model-row">
              <label class="fig-stress-mode-label" for="fig-stress-mode">스트레스 테스트 구분</label>
              <select class="fig-select fig-stress-mode" id="fig-stress-mode" aria-label="스트레스 테스트 구분"><option value="market" ${data.stressMode === "portfolio" ? "" : "selected"}>종목 분석</option><option value="portfolio" ${data.stressMode === "portfolio" ? "selected" : ""}>포트폴리오 분석</option></select>
              <label class="fig-model-label" for="fig-model-select">분석 모델</label>
              <select class="fig-select fig-model-select" id="fig-model-select" aria-label="스트레스 테스트 모델"><option value="ridge" ${data.stressModel === "catboost" ? "" : "selected"}>Ridge</option><option value="catboost" ${data.stressModel === "catboost" ? "selected" : ""}>CatBoost</option></select>
              <label class="fig-period-label" for="fig-period-select">분석 거래일</label>
              <select class="fig-select fig-period-select" id="fig-period-select" aria-describedby="fig-analysis-horizon-status">
                ${[1, 5, 20].map(days => `<option value="${days}" ${days === Number(data.sim?.horizon || 5) ? "selected" : ""}>${days}거래일</option>`).join("")}
              </select>
              <small id="fig-analysis-horizon-status" class="fig-horizon-status" role="status"></small>
            </div>
            <div class="scenario-shock-row">
            <div class="fig-shock-panel" aria-label="시나리오 입력값">
              <label class="fig-shock-group fig-shock-rate"><span>미국 10년 국채 금리 변화량</span><span class="fig-shock-input"><input type="number" name="shock-rate" inputmode="decimal" autocomplete="off" step="1" data-sim="rate" data-unit="bp" value="${escape(rate)}" aria-label="미국 10년 국채 금리 변화량"><b>bp</b></span></label>
              <label class="fig-shock-group fig-shock-fx"><span>원/달러 환율 변화율</span><span class="fig-shock-input"><input type="number" name="shock-fx" inputmode="decimal" autocomplete="off" step="0.1" data-sim="fx" value="${escape(fx)}" aria-label="원달러 환율 변화율"><b>%</b></span></label>
              <label class="fig-shock-group fig-shock-oil"><span>WTI 유가 변화율</span><span class="fig-shock-input"><input type="number" name="shock-oil" inputmode="decimal" autocomplete="off" step="0.1" data-sim="oil" value="${escape(oil)}" aria-label="WTI 유가 변화율"><b>%</b></span></label>
              <label class="fig-shock-group fig-shock-vix"><span>시장불안충격 · VIX 변화량</span><span class="fig-shock-input"><input type="number" name="shock-vix" inputmode="decimal" autocomplete="off" step="0.1" data-sim="vix" value="${escape(vix)}" aria-label="시장불안충격 VIX 변화량"><b>pt</b></span></label>
            </div>
              <div class="scenario-play-actions">
                <label class="scenario-news-toggle"><input type="checkbox" role="switch" data-scenario-news>실시간 뉴스 반영</label>
            <button class="fig-run-button" type="button" data-action="run-sim" aria-label="시뮬레이션 실행">PLAY <img src="${image("play-arrow.png")}" alt=""></button>
              </div>
            </div>
            <div class="scenario-run-status" hidden></div>
            <div class="fig-chart-panel" data-node-id="46:990">
              <div class="fig-chart-tools">
                <button type="button" class="fig-chart-refresh" data-gx="p63-chart-reset" aria-label="차트 표시 초기화"><img src="${icon("refresh.svg")}" alt=""></button>
                ${chartNavigation}${chartTools}
                <button type="button" data-gx="p63-analysis-detail">분석 상세</button>
                <button type="button" class="fig-chart-expand" data-gx="p63-chart-zoom" aria-label="집중 보기" title="집중 보기"><img src="${icon("expand.svg")}" alt=""><span>집중 보기</span></button>
              </div>
              ${chartContent}
              <div class="scenario-bottom-panels">
                ${window.whatIfScenarioLiveMarketStatePanel({ ...(data.liveMarketState || {}), runSummary: data.run ? data.runSummary : "", runError: data.runError })}
                <section class="fig-results-bay fig-live-market scenario-live-observations" aria-label="실시간 데이터">
                  ${window.whatIfScenarioMarketStatePanel(data.liveMarketState)}
                </section>
              </div>
            </div>
          </section>
          <div class="fig-data-chat-group" role="group" aria-label="실시간 데이터 뉴스 문서와 공통 에이전트 채팅">
          <div class="fig-shared-agent-picker" role="group" aria-label="실시간 데이터 뉴스 문서 공통 분석 에이전트 선택"><strong>분석 에이전트</strong>${people}</div>
          <div class="fig-data-tabs" role="tablist" aria-label="데이터 패널">
            <button class="${(data.activePanel || "market") === "market" ? "is-active" : ""}" type="button" role="tab" aria-selected="${(data.activePanel || "market") === "market"}" data-gx="p57-live-mode" title="${escape(data.dataSourceTitle || "실시간 시세 API")}">실시간 데이터</button>
            <button class="${data.activePanel === "news" ? "is-active" : ""}" type="button" role="tab" aria-selected="${data.activePanel === "news"}" data-gx="p57-news-tab">뉴스</button>
            <button class="${data.activePanel === "document" ? "is-active" : ""}" type="button" role="tab" aria-selected="${data.activePanel === "document"}" data-gx="p57-document-tab">문서</button>
          </div>
          <section class="fig-data-panel p57-data" data-node-id="46:1056" aria-label="${data.activePanel === "news" ? "뉴스 데이터" : data.activePanel === "document" ? "DART 문서 데이터" : "실시간 데이터 및 종목 시세"}">
            ${window.whatIfScenarioDataPanel(data.marketPanel)}
          </section>
          <section class="fig-chat-panel" data-node-id="46:1161" aria-label="AI 에이전트 채팅">${chatBody}</section>
          </div>
          ${data.chartZoom ? `<dialog class="fig-stress-zoom" aria-label="집중 보기 · 차트"><div class="fig-stress-zoom-tools">${chartNavigation}${chartTools}<button type="button" data-gx="p63-chart-zoom" aria-label="집중 보기 닫기" title="집중 보기 닫기">축소</button></div><div class="fig-dynamic-chart">${data.expandedChartHTML || data.chartHTML || ""}</div></dialog>` : ""}
          <i class="fig-right-edge fig-right-edge-top" aria-hidden="true"></i>
          <i class="fig-right-edge fig-right-edge-bottom" aria-hidden="true"></i>
        </div>
      </div>
    </div>`;
  };

})();
