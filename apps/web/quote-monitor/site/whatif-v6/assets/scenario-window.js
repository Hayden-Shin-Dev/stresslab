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

  window.whatIfScenarioDataPanel = function (data) {
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
    return `${sourceSelector(mode)}
      <div class="fig-data-toolbar">
        <label class="fig-search-field"><img src="${icon("Search.svg")}" alt=""><input id="p57-filter" type="search" placeholder="Search..." aria-label="종목 목록 검색" value="${escape(data.query || "")}"></label>
        <button class="fig-icon-button fig-filter-button" type="button" data-gx="p57-data-tab" data-tab="${isIndicators ? "quotes" : "indicators"}" aria-label="${isIndicators ? "종목 시세" : "장중 지표"}"><img src="${icon("filter.svg")}" alt=""></button>
        <button class="fig-icon-button fig-live-button" type="button" data-gx="p57-live-mode" aria-label="실시간 시세 연결" title="실시간 시세 연결"><img src="${image("play-arrow.png")}" alt=""></button>
        <button class="fig-icon-button fig-refresh-button" type="button" data-gx="p57-refresh" ${data.busy || mode === "attachment" ? "disabled" : ""} aria-label="실시간 시세 새로고침" title="실시간 시세 새로고침"><img src="${icon("refresh-small.svg")}" alt=""></button>
      </div>
      <div class="fig-quote-head ${isIndicators ? "is-indicators" : ""}" aria-hidden="true"><span>종목</span><span>${isIndicators ? "등락률" : "현재가"}</span><span>시각</span></div>
      <div class="fig-quote-list" role="list" aria-label="${escape(status)}">
        ${rowHTML || `<div class="fig-quote-empty" role="status">${term ? "검색 결과가 없습니다." : data.busy ? "실시간 데이터를 확인하고 있습니다." : "표시할 시세 데이터가 없습니다."}</div>`}
      </div>
      <div class="fig-quote-footer"><span>${pageStart}-${pageEnd} of ${total}</span><span>Rows per page:</span><strong>10 <img src="${icon("chevron-down.svg")}" alt=""></strong></div>`;
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
      <span>영철</span>
      <input type="checkbox" data-role-choice="${escape(role.id)}" ${selected.has(role.id) ? "checked" : ""} aria-label="영철 에이전트 선택">
    </label>`).join("");
    const messages = data.messages || "";
    const prompts = ["현재 시장 상태는?", "추가로 확인할 자료를 알려주세요", "근거 수치를 알려주세요"];
    const questionButtons = prompts.map((question) => `<button type="button" data-action="quick" data-text="${escape(question)}">${escape(question)}</button>`).join("");
    const runPanel = data.run ? (data.runSummary || "") : "";
    const runError = data.runError ? `<p class="fig-run-error" role="alert">${escape(data.runError)}</p>` : "";
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
      <p class="fig-chat-status">AI 에이전트 채팅이 실행되었습니다</p>
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
            <div class="fig-results-bay" data-node-id="46:1009">${runPanel}${runError}</div>
          </section>
          <div class="fig-data-tabs" role="tablist" aria-label="데이터 패널">
            <button class="is-active" type="button" role="tab" aria-selected="true" data-gx="p57-live-mode" title="${escape(data.dataSourceTitle || "실시간 시세 API")}">실시간 데이터</button>
            <button type="button" role="tab" aria-selected="false" data-gx="panel" data-panel="news">뉴스</button>
            <button type="button" role="tab" aria-selected="false" data-gx="panel" data-panel="document">문서</button>
          </div>
          <section class="fig-data-panel p57-data" data-node-id="46:1056" aria-label="실시간 데이터 및 종목 시세">
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
