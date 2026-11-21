(function () {
  const assetRoot = "./assets/scenario-ui/";
  const image = (name) => `${assetRoot}images/${name}`;
  const icon = (name) => `${assetRoot}icons/${name}`;
  const chart = (name) => `${assetRoot}chart/${name}`;
  const escape = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"
  })[char]);

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
    const tabs = ["assets", "sectors", "market", ...(hasRun || runError ? ["result"] : [])];
    const tab = tabs.includes(data.tab) ? data.tab : "assets";
    const assets = Array.isArray(snapshot?.assets) ? snapshot.assets : [];
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
    const tabButtons = [["assets", "종목"], ["sectors", "업종"], ["market", "시장"], ...(tabs.includes("result") ? [["result", "실행 결과"]] : [])]
      .map(([key, name]) => `<button type="button" data-gx="p57-market-state-tab" data-tab="${key}" role="tab" aria-selected="${tab === key}" class="${tab === key ? "is-active" : ""}">${name}</button>`).join("");
    let content;
    if (tab === "result") {
      content = `<div class="fig-live-market-results" role="region" aria-label="시나리오 실행 결과" tabindex="0">${runSummary}${runError}</div>`;
    } else if (!snapshot) {
      content = `<div class="fig-live-market-empty" role="status">${escape(delivery.error || "실제 시장 스냅샷을 기다리고 있습니다. 모의 데이터는 표시하지 않습니다.")}</div>`;
    } else if (tab === "assets") {
      content = marketTable(
        ["종목", "업종", "전일 대비 %", "시가 대비 %", "5분 %", "30분 변동성 %", "누적 거래량", "완전 수신"],
        [...assets].sort((a, b) => String(a.asset_id || "").localeCompare(String(b.asset_id || ""))).map((asset) => [
          asset.asset_id || "미확인", asset.sector_id || "미분류", marketNumber(asset.return_since_previous_close_pct),
          marketNumber(asset.return_since_open_pct), marketNumber(asset.return_5m_pct, 3),
          marketNumber(asset.volatility_30m_pct, 3), marketNumber(asset.volume_since_open, 0),
          marketBoolean(asset.complete_since_open)
        ]), "실시간 종목 관측 표", "assets"
      );
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
    return `<header class="fig-live-market-head"><strong>실시간 시장 데이터</strong><span class="fig-live-market-status ${!snapshot ? "is-waiting" : stale ? "is-stale" : "is-live"}" role="status">${escape(status)}</span><small>${escape(count)} · ${escape(quality)}</small><button type="button" data-gx="p57-market-state-refresh" aria-label="시장 데이터 새로고침">새로고침</button></header>
      <div class="fig-live-market-tabs" role="tablist" aria-label="시장 데이터 구분">${tabButtons}<span>원본 기준 ${escape(marketStamp(stamp))}</span></div>
      ${content}
      <footer class="fig-live-market-foot"><span>출처: ${escape(snapshot?.source || "시장 상태 API")} · ${escape(snapshot?.universe_id || "관측 범위 미확인")}</span><span>${snapshot ? `완전 수신 ${assets.filter((asset) => asset.complete_since_open === true).length}/${assets.length}` : "실제 관측값만 표시"}</span></footer>`;
  };

  window.whatIfScenarioLiveMarketStatePanel = function (data = {}) {
    const runSummary = typeof data.runSummary === "string" ? data.runSummary : "";
    const runError = data.runError ? `<p class="fig-run-error" role="alert">${escape(data.runError)}</p>` : "";
    return `<section class="fig-results-bay fig-live-market fig-live-state-panel" data-node-id="46:1009" aria-label="실시간 시장 데이터">
      ${window.whatIfScenarioMarketStatePanel(data, runSummary, runError, Boolean(runSummary || runError))}
    </section>`;
  };

  window.whatIfScenarioDataPanel = function (data) {
    if (data.panel === "news") return window.whatIfScenarioNewsPanel(data.news || {});
    if (data.panel === "document") return window.whatIfScenarioDocumentPanel(data.document || {});
    const market = data.market || {};
    const rawRows = Array.isArray(market.rows) ? market.rows : [];
    const term = String(data.query || "").normalize("NFKC").toLowerCase().replace(/[^가-힣a-z0-9]/g, "");
    const normalize = (value) => String(value || "").normalize("NFKC").toLowerCase().replace(/[^가-힣a-z0-9]/g, "");
    const rows = rawRows.filter((row) => !term || normalize(`${row.name} ${row.code} ${row.sector}`).includes(term));
    rows.sort((a, b) => data.sort === "name"
      ? String(a.name || "").localeCompare(String(b.name || ""), "ko")
      : (b.volume ?? -1) - (a.volume ?? -1));
    const shown = rows.slice(0, 10);
    const isIndicators = data.tab === "indicators";
    const mode = data.mode || "attachment";
    const status = data.source || "미연결";
    const selectedName = data.selectedName || "";
    const rowHTML = shown.map((row) => {
      const chosen = row.code === data.selectedCode || row.name === selectedName;
      const mainValue = isIndicators
        ? (Number.isFinite(row.changePct) ? `${row.changePct > 0 ? "+" : ""}${row.changePct.toFixed(2)}%` : "—")
        : (Number.isFinite(row.price) ? row.price.toLocaleString("ko-KR") : "—");
      const volume = Number.isFinite(row.volume) ? row.volume.toLocaleString("ko-KR") : "—";
      const trade = formatLongTime(row.tradeAt);
      const received = formatLongTime(market.receivedAt || row.tradeAt);
      return `<button class="fig-quote-row ${chosen ? "is-selected" : ""}" type="button" data-gx="p57-pick" data-name="${escape(row.name)}" aria-pressed="${chosen}" aria-label="${escape(row.name)} ${isIndicators ? mainValue : `${mainValue}원`} 분석 대상으로 선택">
        <span class="fig-radio" aria-hidden="true">${chosen ? "✓" : ""}</span>
        <span class="fig-quote-name"><strong>${escape(row.name || "종목 미확인")}</strong><small>${escape(row.code || "—")}</small></span>
        <span class="fig-quote-price"><strong>${escape(mainValue)}</strong><small>${isIndicators ? escape(row.sector || "업종 미확인") : `누적 거래량 ${volume}`}</small></span>
        <span class="fig-quote-times"><small>체결 | ${escape(trade)}</small><small>수집 | ${escape(received)}</small><small>화면 | ${escape(received)}</small></span>
      </button>`;
    }).join("");
    const total = rows.length;
    const pageStart = total ? 1 : 0;
    const pageEnd = Math.min(10, total);
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
        <label class="fig-search-field"><img src="${icon("Search.svg")}" alt=""><input id="p57-filter" type="search" placeholder="Search..." aria-label="종목 목록 검색" value="${escape(data.query || "")}"></label>
        <button class="fig-icon-button fig-filter-button" type="button" data-gx="p57-data-tab" data-tab="${isIndicators ? "quotes" : "indicators"}" aria-label="${isIndicators ? "종목 시세" : "장중 지표"}"><img src="${icon("filter.svg")}" alt=""></button>
        <button class="fig-icon-button fig-live-button" type="button" data-gx="p57-live-mode" aria-label="실시간 시세 연결" title="${escape(activeTabTitle)}"><img src="${image("play-arrow.png")}" alt=""></button>
        <button class="fig-icon-button fig-refresh-button" type="button" data-gx="p57-refresh" ${data.busy || mode === "attachment" ? "disabled" : ""} aria-label="실시간 시세 새로고침" title="실시간 시세 새로고침"><img src="${icon("refresh-small.svg")}" alt=""></button>
      </div>
      <p class="fig-quote-status ${quoteIsStale ? "is-stale" : ""}" role="status">${escape(quoteStatus)}</p>
      <div class="fig-quote-head ${isIndicators ? "is-indicators" : ""}" aria-hidden="true"><span>종목</span><span>${isIndicators ? "등락률" : "현재가"}</span><span>시각</span></div>
      <div class="fig-quote-list" role="list" aria-label="${escape(status)}">
        ${rowHTML || `<div class="fig-quote-empty" role="status">${term ? "검색 결과가 없습니다." : data.busy ? "실시간 데이터를 확인하고 있습니다." : "표시할 시세 데이터가 없습니다."}</div>`}
      </div>
      <div class="fig-quote-footer"><span>${pageStart}-${pageEnd} of ${total}</span><span>Rows per page:</span><strong>10 <img src="${icon("chevron-down.svg")}" alt=""></strong></div>`;
  };

  window.whatIfScenarioNewsPanel = function (data) {
    const modes = [["all", "전체"], ["politics", "정치"], ["economy", "경제"], ["society", "사회"]];
    const selected = new Set(data.selected || []);
    const rows = Array.isArray(data.rows) ? data.rows : [];
    const publishers = Array.isArray(data.publishers) ? data.publishers : [];
    const modeLabel = modes.find(([id]) => id === data.mode)?.[1] || "전체";
    const statusText = data.busy ? (data.progress || "뉴스 화면 예시를 준비하는 중입니다.") : data.status === "preview"
      ? `실제 뉴스 API 미연결 · 화면 확인용 가상 데이터 · ${escape(data.updatedAt || "업데이트됨")}`
      : data.status === "error" ? (data.error || "뉴스 데이터를 가져오지 못했습니다.")
      : "실제 뉴스 API 연결 전입니다. 버튼을 누르면 화면 확인용 가상 기사를 표시합니다.";
    const rowHTML = rows.map((row) => {
      const checked = selected.has(row.id);
      const published = row.publishedAt ? formatLongTime(row.publishedAt) : "시각 미확인";
      const category = {politics:"정치",economy:"경제",society:"사회"}[row.category] || "뉴스";
      return `<div class="fig-news-row ${checked ? "is-selected" : ""}" role="listitem">
        <input type="checkbox" data-gx="p57-news-select" data-id="${escape(row.id)}" ${checked ? "checked" : ""} aria-label="${escape(row.title)} 분석 대상으로 선택">
        <span class="fig-news-rank">${category}</span>
        <span class="fig-news-content"><span class="fig-news-meta"><strong>${escape(row.publisher || row.category || "언론사 미확인")}</strong><span>${escape(published)}</span></span>
          <strong class="fig-news-title">${escape(row.title || "제목 미확인")}</strong>
        </span>
        ${row.url ? `<a class="fig-news-open" href="${escape(row.url)}" target="_blank" rel="noopener noreferrer" aria-label="${escape(row.title)} 원문 새 창에서 열기">원문 ↗</a>` : `<span class="fig-news-open is-unavailable">원문 없음</span>`}
      </div>`;
    }).join("");
    return `<div class="fig-news-panel">
      <div class="fig-news-toolbar">
        <label class="fig-search-field"><img src="${icon("Search.svg")}" alt=""><input id="p57-news-filter" type="search" placeholder="제목 · 언론사 검색" aria-label="뉴스 제목과 언론사 검색" value="${escape(data.query || "")}"></label>
        <button class="fig-news-run-fetch" type="button" data-gx="p57-news-refresh" ${data.busy ? "disabled" : ""}>${data.busy ? "가져오는 중" : "실시간 뉴스 데이터 실행"}</button>
      </div>
      <div class="fig-news-categories" role="tablist" aria-label="뉴스 주제 분류">
        ${modes.map(([id, label]) => `<button type="button" role="tab" aria-selected="${data.mode === id}" class="${data.mode === id ? "is-active" : ""}" data-gx="p57-news-mode" data-mode="${id}">${label}</button>`).join("")}
        <select id="p57-news-publisher" aria-label="언론사 필터"><option value="">언론사 전체</option>${publishers.map((publisher) => `<option value="${escape(publisher)}" ${data.publisher === publisher ? "selected" : ""}>${escape(publisher)}</option>`).join("")}</select>
      </div>
      <div class="fig-news-heading"><strong>${modeLabel} 뉴스 ${data.status === "preview" ? "예시" : "미리보기"}</strong><span>${rows.length}건 · 주제별 필터</span></div>
      <p class="fig-news-status ${data.status === "error" ? "is-error" : ""}" role="status" aria-live="polite">${escape(statusText)}</p>
      <div class="fig-news-list" role="list" aria-label="${modeLabel} 뉴스 목록">
        ${rowHTML || `<div class="fig-news-empty" role="status">${data.busy ? "최신 기사를 확인하고 있습니다." : data.status === "error" ? "연결된 뉴스 데이터가 없습니다. 잠시 후 다시 실행해 주세요." : data.query ? "검색 결과가 없습니다." : data.publisher ? "선택한 언론사의 뉴스가 없습니다." : data.status === "preview" ? "현재 분류에서 표시할 예시가 없습니다." : "‘실시간 뉴스 데이터 실행’을 눌러 화면 확인용 예시 기사를 표시하세요."}</div>`}
      </div>
      <div class="fig-news-footer"><span>${selected.size}건 선택 · <span class="fig-news-credit">UI 확인용 예시</span> · 실제 기사 미연결</span><button type="button" data-gx="p57-news-send" ${selected.size ? "" : "disabled"}>선택 뉴스 분석 실행</button></div>
    </div>`;
  };

  window.whatIfScenarioDocumentPanel = function (data) {
    const views = [["original", "DART 공시원문 활용"], ["major", "주요공시 및 재무정보 제공"], ["bulk", "대용량 재무정보 제공"]];
    const company = data.company || null;
    const dateLabel = (value) => /^\d{8}$/.test(String(value || ""))
      ? `${value.slice(0, 4)}.${value.slice(4, 6)}.${value.slice(6, 8)}` : String(value || "미확인");
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
    const rows = (data.records || []).map((row) => `<article class="fig-doc-row"><div class="fig-doc-row-main"><span class="fig-doc-row-meta"><strong>${escape(row.corp_name || company?.corp_name || "회사 미확인")}</strong><span>${dateLabel(row.rcept_dt)}</span></span><strong class="fig-doc-row-title">${escape(row.report_nm || "공시 제목 미확인")}</strong><small>${escape(row.flr_nm || "제출인 미확인")} · 접수번호 ${escape(row.rcept_no || "미확인")}</small></div><button class="fig-doc-expand" type="button" data-gx="p57-doc-open" data-receipt="${escape(row.rcept_no || "")}" aria-label="${escape(row.report_nm || "공시")} 상세 팝업 열기" ${row.rcept_no ? "" : "disabled"}><img src="${icon("expand.svg")}" alt=""></button></article>`).join("");
    const totalPages = Math.max(1, Number(data.totalPage) || 1), page = Math.max(1, Number(data.page) || 1);
    const disclosureArea = `<div class="fig-doc-list-heading"><strong>${data.view === "major" ? "주요공시" : "공시원문 목록"}</strong><span>${(data.records || []).length}건 표시 · 전체 ${Number(data.totalCount) || 0}건</span><div class="fig-doc-pages"><button type="button" data-gx="p57-doc-page" data-page="${Math.max(1, page - 1)}" ${data.busy || page <= 1 ? "disabled" : ""} aria-label="이전 공시 페이지">‹</button><span>${page}/${totalPages}</span><button type="button" data-gx="p57-doc-page" data-page="${Math.min(totalPages, page + 1)}" ${data.busy || page >= totalPages ? "disabled" : ""} aria-label="다음 공시 페이지">›</button></div></div><div class="fig-doc-list" role="list" aria-label="DART 공시 목록">${rows || `<div class="fig-doc-empty">${data.busy ? "공시 목록을 불러오고 있습니다." : data.status === "error" ? "조회에 실패했습니다. 검색 조건을 확인하고 다시 요청해 주세요." : company ? "조건에 맞는 공시가 없습니다. 기간을 넓혀 다시 조회해 주세요." : "회사 검색 후 공시를 조회할 수 있습니다."}</div>`}</div>`;
    const currentPeriod = escape(data.financials?.[0]?.thstrm_nm || "당기"), previousPeriod = escape(data.financials?.[0]?.frmtrm_nm || "전기"), currency = escape(data.financials?.[0]?.currency || "DART 응답 단위");
    const financialRows = (data.financials || []).filter((row) => !data.statementSection || row.sj_div === data.statementSection).map((row) => `<tr><th scope="row"><span>${escape(row.sj_nm || row.sj_div || "계정")}</span><strong>${escape(row.account_nm || "계정명 미확인")}</strong></th><td>${escape(row.thstrm_amount || "—")}</td><td>${escape(row.frmtrm_amount || "—")}</td></tr>`).join("");
    const financialArea = `<div class="fig-doc-finance-tools"><label>사업연도<input id="p57-doc-year" type="number" min="2000" max="2099" value="${escape(data.year || "")}" aria-label="사업연도"></label><select id="p57-doc-report-code" aria-label="보고서 유형"><option value="11011" ${data.reportCode === "11011" ? "selected" : ""}>사업보고서</option><option value="11012" ${data.reportCode === "11012" ? "selected" : ""}>반기보고서</option><option value="11013" ${data.reportCode === "11013" ? "selected" : ""}>1분기보고서</option><option value="11014" ${data.reportCode === "11014" ? "selected" : ""}>3분기보고서</option></select><select id="p57-doc-fs-div" aria-label="재무제표 기준"><option value="CFS" ${data.fsDiv === "CFS" ? "selected" : ""}>연결재무제표</option><option value="OFS" ${data.fsDiv === "OFS" ? "selected" : ""}>별도재무제표</option></select><button type="button" data-gx="p57-doc-finance-fetch" ${data.financialBusy || !company ? "disabled" : ""}>재무 조회</button></div><div class="fig-doc-finance-bar"><strong>${escape(company?.corp_name || "회사 미선택")} 재무 계정</strong><select id="p57-doc-section" aria-label="재무제표 구분"><option value="">전체 계정</option><option value="BS" ${data.statementSection === "BS" ? "selected" : ""}>재무상태표</option><option value="IS" ${data.statementSection === "IS" ? "selected" : ""}>손익계산서</option><option value="CIS" ${data.statementSection === "CIS" ? "selected" : ""}>포괄손익계산서</option><option value="CF" ${data.statementSection === "CF" ? "selected" : ""}>현금흐름표</option><option value="SCE" ${data.statementSection === "SCE" ? "selected" : ""}>자본변동표</option></select></div><div class="fig-doc-finance-list"><table><thead><tr><th>계정과목</th><th>${currentPeriod}</th><th>${previousPeriod}</th></tr></thead><tbody>${financialRows || `<tr><td colspan="3" class="fig-doc-finance-empty">${data.financialBusy ? "재무정보를 불러오고 있습니다." : data.financialStatus === "error" ? escape(data.financialError || "재무정보 조회에 실패했습니다.") : data.financials?.length ? "선택한 재무제표에 계정이 없습니다." : "회사를 고르고 사업연도·보고서 유형을 선택한 뒤 ‘재무 조회’를 눌러 주세요."}</td></tr>`}</tbody></table></div><div class="fig-doc-finance-foot"><span>${data.financials?.length || 0}개 계정 · ${currency} 단위 응답 그대로 표시</span><button type="button" data-gx="p57-doc-finance-csv" ${data.financials?.length ? "" : "disabled"}>CSV 저장</button></div>`;
    const detailFields = Object.entries(data.modal?.detail_fields || {}).map(([label, value]) => `<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join("");
    const detailStatus = data.modal?.detail_status === "loading" ? "주요사항보고서 구조화 상세를 확인하고 있습니다."
      : data.modal?.detail_status === "error" ? escape(data.modal?.detail_error || "상세 항목을 불러오지 못했습니다.")
      : data.modal?.detail_status === "empty" ? "이 공시 접수번호에 연결된 구조화 상세 항목이 없습니다. 아래 원문을 확인해 주세요."
      : data.modal?.detail_status === "unavailable" ? "이 보고서 유형은 구조화 상세 API가 제공되지 않습니다. 아래 원문에서 확인해 주세요."
      : "공시 상세 항목은 DART 원문을 기준으로 확인할 수 있습니다.";
    const detailSection = `<section class="fig-doc-modal-details"><strong>${data.modal?.detail_type ? escape(data.modal.detail_type) : "공시 상세"}</strong>${detailFields ? `<dl>${detailFields}</dl>` : `<p role="status">${detailStatus}</p>`}</section>`;
    const sourceLink = "https://opendart.fss.or.kr/disclosureinfo/fnltt/dwld/main.do";
    const xbrl = data.records?.find((row) => /^\d{14}$/.test(row.rcept_no || "") && /사업보고서|반기보고서|분기보고서/.test(row.report_nm || ""));
    const xbrlCode = !xbrl ? "11011" : /반기보고서/.test(xbrl.report_nm) ? "11012" : /1분기보고서/.test(xbrl.report_nm) ? "11013" : /3분기보고서/.test(xbrl.report_nm) ? "11014" : "11011";
    const bulkArea = `<div class="fig-doc-bulk-card"><span class="fig-doc-stamp">DART · OPEN API</span><strong>분기별 재무제표 대량 파일</strong><p>OpenDART는 XBRL로 제출된 정기보고서 재무제표를 분기별 TXT 일괄 파일로 제공합니다. 제공 대상과 기준일은 원본 페이지에서 확인하세요.</p><a href="${sourceLink}" target="_blank" rel="noopener noreferrer">공식 일괄다운로드 안내 ↗</a></div><div class="fig-doc-bulk-card is-secondary"><strong>선택 회사의 XBRL 원문</strong><p>${escape(xbrl ? `${xbrl.corp_name || company?.corp_name || "선택 회사"} · ${xbrl.report_nm} · 접수 ${xbrl.rcept_no}` : company ? "정기보고서 접수번호를 찾으려면 공시원문 탭에서 조회해 주세요." : "회사를 선택한 다음 공시원문 탭에서 조회해 주세요.")}</p><label>보고서 유형<select id="p57-doc-bulk-report"><option value="11011" ${xbrlCode === "11011" ? "selected" : ""}>사업보고서</option><option value="11012" ${xbrlCode === "11012" ? "selected" : ""}>반기보고서</option><option value="11013" ${xbrlCode === "11013" ? "selected" : ""}>1분기보고서</option><option value="11014" ${xbrlCode === "11014" ? "selected" : ""}>3분기보고서</option></select></label><button type="button" data-gx="p57-doc-xbrl-download" data-receipt="${escape(xbrl?.rcept_no || "")}" ${data.xbrlBusy || !xbrl ? "disabled" : ""}>${data.xbrlBusy ? "XBRL 받는 중" : "선택 보고서 XBRL ZIP 받기"}</button></div><p class="fig-doc-bulk-note">분기별 일괄 파일은 TXT, 선택 보고서 원문 API는 XBRL ZIP 형식입니다.</p>`;
    const body = data.view === "bulk" ? `${companySearch}${bulkArea}` : `${companySearch}${data.view === "major" ? majorModes : ""}${data.view === "major" && data.contentMode === "financials" ? financialArea : `${dateFilters}${`<p class="fig-doc-status ${data.status === "error" ? "is-error" : ""}" role="status" aria-live="polite">${escape(status)}</p>`}${disclosureArea}`}`;
    const preview = data.modal?.preview_status === "loading"
      ? `<p role="status">DART 공시 원문 본문을 불러오고 있습니다.</p>`
      : data.modal?.preview_status === "ready"
        ? `<pre>${escape(data.modal.preview_text || "")}</pre>${data.modal.preview_truncated ? `<p class="fig-doc-preview-note">미리보기 일부만 표시했습니다. 전체 원문은 아래 링크나 ZIP 파일에서 확인하세요.</p>` : ""}`
        : data.modal?.preview_status === "empty"
          ? `<p role="status">${escape(data.modal.preview_error || "표시할 본문 텍스트가 없습니다. 아래 DART 원문 링크나 ZIP 파일에서 확인해 주세요.")}</p>`
          : `<p class="is-error" role="alert">${escape(data.modal?.preview_error || "공시 원문 본문을 불러오지 못했습니다. 아래 링크나 ZIP 파일에서 확인해 주세요.")}</p>`;
    const modal = data.modal ? `<div class="fig-doc-modal-shade"><section class="fig-doc-modal" role="dialog" aria-modal="true" aria-labelledby="p57-doc-modal-title" data-receipt="${escape(data.modal.rcept_no || "")}"><header><div><span>DART 공시원문</span><h2 id="p57-doc-modal-title">${escape(data.modal.report_nm || "공시 상세")}</h2></div><button type="button" data-gx="p57-doc-close" aria-label="공시 팝업 닫기">×</button></header><div class="fig-doc-modal-meta"><strong>${escape(data.modal.corp_name || "회사 미확인")}</strong><span>제출인 ${escape(data.modal.flr_nm || "미확인")}</span><span>접수일 ${dateLabel(data.modal.rcept_dt)}</span><span>접수번호 ${escape(data.modal.rcept_no || "미확인")}</span></div>${detailSection}<div class="fig-doc-viewer" aria-label="DART 공시 원문 본문">${preview}</div><footer><a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${encodeURIComponent(data.modal.rcept_no || "")}" target="_blank" rel="noopener noreferrer">DART 원문 새 창에서 보기 ↗</a><button type="button" data-gx="p57-doc-download" ${data.downloadBusy ? "disabled" : ""}>${data.downloadBusy ? "원문 ZIP 받는 중" : "원문 ZIP 다운로드"}</button></footer></section></div>` : "";
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
    const people = rows.map((role, index) => `<label class="fig-person-row">
      <img src="${image(role.image || avatarFiles[index % avatarFiles.length])}" alt="">
      <span>${escape(role.name)}<small>${escape(role.role)}</small></span>
      <input type="checkbox" data-role-choice="${escape(role.id)}" ${selected.has(role.id) ? "checked" : ""} aria-label="${escape(role.name)} ${escape(role.role)} 에이전트 선택">
    </label>`).join("");
    const messages = data.messages || "";
    const prompts = ["현재 시장 상태는?", "추가로 확인할 자료를 알려주세요", "근거 수치를 알려주세요"];
    const questionButtons = prompts.map((question) => `<button type="button" data-action="quick" data-text="${escape(question)}">${escape(question)}</button>`).join("");
    const useStaticGraph = !data.forceDynamic && !data.run && data.chartMode === "day";
    const chartContent = useStaticGraph ? `
      <div class="fig-static-chart" aria-label="2008년 코스피 시연 차트">
        <i class="fig-chart-gridline"></i>
        <div class="fig-chart-ylabels" aria-hidden="true">${[137, 136, 135, 134, 133, 132, 131, 130, 129, 128, 127, 126, 125, 124].map((v, i) => `<span style="top:${16.5 + i * 33.03}px">${v},000</span>`).join("")}</div>
        <img class="fig-chart-history" src="${chart("history.svg")}" alt="">
        <img class="fig-chart-forecast fig-chart-up" src="${chart("forecast-up.svg")}" alt="">
        <img class="fig-chart-forecast fig-chart-down" src="${chart("forecast-down.svg")}" alt="">
        <img class="fig-chart-forecast fig-chart-base" src="${chart("forecast-base.svg")}" alt="">
        <div class="fig-chart-xlabels" aria-hidden="true">${[0, 1, 2, 3, 4].map((i) => `<span style="left:${8 + i * 17.6}%">10:00</span>`).join("")}</div>
      </div>` : `<div class="fig-dynamic-chart">${data.chartHTML || ""}</div>`;
    const chatBody = data.chatMin ? `<button class="fig-chat-launcher" type="button" data-gx="chat-open">AI Agent 대화 열기</button>` : `
      <div class="fig-chat-toolbar" aria-label="AI 에이전트 도구">
        <button type="button" data-gx="account" aria-label="프로필"><img class="fig-account-icon" src="${icon("person.svg")}" alt=""></button>
        <button class="fig-mini-play" type="button" data-action="analyze-run" data-id="${escape(data.run?.id || "")}" ${data.run ? "" : "disabled"} aria-label="선택된 에이전트 분석 실행"><img src="${image("play-arrow.png")}" alt=""></button>
        <button type="button" data-gx="chat-min" aria-label="채팅 접기">×</button>
      </div>
      <div class="fig-chat-prompts">${questionButtons}</div>
      <div class="fig-chat-people" role="group" aria-label="분석 에이전트 선택">${people}</div>
      <div class="fig-chat-messages" id="chat-scroll" aria-live="polite">${messages}</div>
      <p class="fig-chat-status">${escape(data.agentStatus || "분석 실행 후 AI에게 질문할 수 있습니다")}</p>
      <div class="fig-chat-compose">
        <img class="fig-chat-user" src="${image("avatar-user.png")}" alt="">
        <textarea data-chat-input="scenario" rows="1" placeholder="text+" aria-label="AI 에이전트에게 질문">${escape(data.draft || "")}</textarea>
        <button type="button" data-action="send-chat" data-key="scenario" aria-label="메시지 보내기"><img class="fig-send-icon" src="${icon("send.svg")}" alt=""></button>
      </div>`;

    return `<div class="fig-scenario-overlay" style="--fig-scale:${Number(data.scale) || 1}">
      <div class="fig-scenario-frame">
        <div class="fig-scenario-screen" role="dialog" aria-modal="true" aria-label="국내 주식 시나리오 시뮬레이션" data-node-id="46:987">
          <button class="fig-home" type="button" data-gx="feature-close" aria-label="시나리오 창 닫기"><img src="${image("home.png")}" alt=""></button>
          <section class="fig-main-panel" data-node-id="46:988" aria-label="시나리오 분석">
            <div class="fig-model-row">
              <img class="fig-gear" src="${image("gear.png")}" alt="">
              <span class="fig-model-label">분석 모델</span>
              <button class="fig-select fig-model-select" type="button" aria-label="분석 모델 Ridge">Ridge<img src="${icon("chevron-down.svg")}" alt=""></button>
              <button class="fig-select fig-period-select" type="button" aria-label="분석 기간 1개월">분석 1개월<img src="${icon("chevron-down.svg")}" alt=""></button>
              <span class="fig-clock" aria-label="시뮬레이션 시간">06:21</span>
            </div>
            <div class="fig-shock-panel" aria-label="시나리오 입력값">
              <label class="fig-shock-group fig-shock-rate"><span>미국 10년 국채 금리 변화량</span><span class="fig-shock-input"><input type="number" step="1" data-sim="rate" data-unit="bp" value="${escape(rate)}" aria-label="미국 10년 국채 금리 변화량"><b>bp</b></span></label>
              <label class="fig-shock-group fig-shock-fx"><span>원/달러 환율 변화율</span><span class="fig-shock-input"><input type="number" step="0.1" data-sim="fx" value="${escape(fx)}" aria-label="원달러 환율 변화율"><b>%</b></span></label>
              <label class="fig-shock-group fig-shock-oil"><span>WTI 유가 변화율</span><span class="fig-shock-input"><input type="number" step="0.1" data-sim="oil" value="${escape(oil)}" aria-label="WTI 유가 변화율"><b>%</b></span></label>
              <label class="fig-shock-group fig-shock-vix"><span>시장불안충격 · VIX 변화량</span><span class="fig-shock-input"><input type="number" step="0.1" data-sim="vix" value="${escape(vix)}" aria-label="시장불안충격 VIX 변화량"><b>pt</b></span></label>
            </div>
            <button class="fig-run-button" type="button" data-action="run-sim" aria-label="시뮬레이션 실행">PLAY <img src="${image("play-arrow.png")}" alt=""></button>
            <div class="fig-chart-panel ${data.zoom ? "is-zoomed" : ""}" data-node-id="46:990">
              <div class="fig-chart-tools">
                <button type="button" class="fig-chart-type" aria-label="차트 종류">LINE<img src="${icon("chevron-down.svg")}" alt=""></button>
                <button type="button" class="fig-chart-range ${data.chartMode === "day" ? "is-active" : ""}" data-action="chart-day" aria-label="일봉">일<img src="${icon("chevron-down.svg")}" alt=""></button>
                <button type="button" class="fig-chart-refresh" data-action="chart-today" aria-label="오늘로"><img src="${icon("refresh.svg")}" alt=""></button>
                <button type="button" class="fig-chart-expand" data-action="chart-zoom" aria-label="차트 확대"><img src="${icon("expand.svg")}" alt=""></button>
              </div>
              ${chartContent}
            </div>
          </section>
          ${window.whatIfScenarioLiveMarketStatePanel({ ...(data.liveMarketState || {}), runSummary: data.run ? data.runSummary : "", runError: data.runError })}
          <div class="fig-data-tabs" role="tablist" aria-label="데이터 패널">
            <button class="${(data.activePanel || "market") === "market" ? "is-active" : ""}" type="button" role="tab" aria-selected="${(data.activePanel || "market") === "market"}" data-gx="p57-live-mode" title="${escape(data.dataSourceTitle || "실시간 시세 API")}">실시간 데이터</button>
            <button class="${data.activePanel === "news" ? "is-active" : ""}" type="button" role="tab" aria-selected="${data.activePanel === "news"}" data-gx="p57-news-tab">뉴스</button>
            <button class="${data.activePanel === "document" ? "is-active" : ""}" type="button" role="tab" aria-selected="${data.activePanel === "document"}" data-gx="p57-document-tab">문서</button>
          </div>
          <section class="fig-data-panel p57-data" data-node-id="46:1056" aria-label="${data.activePanel === "news" ? "뉴스 데이터" : data.activePanel === "document" ? "DART 문서 데이터" : "실시간 데이터 및 종목 시세"}">
            ${window.whatIfScenarioDataPanel(data.marketPanel)}
          </section>
          <section class="fig-chat-panel" data-node-id="46:1161" aria-label="AI 에이전트 채팅">${chatBody}</section>
          <i class="fig-right-edge fig-right-edge-top" aria-hidden="true"></i>
          <i class="fig-right-edge fig-right-edge-bottom" aria-hidden="true"></i>
        </div>
      </div>
    </div>`;
  };

})();
