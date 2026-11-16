/* Renders validated live market snapshots from the existing WHAT IF feed. */
(() => {
  'use strict';

  const PANEL_CLASS = 'whatif-live-market-panel';
  const MAX_ROWS = 3;
  let latestSnapshot = null;
  let latestDelivery = window.WHATIF_MARKET_DELIVERY || {};
  let syncQueued = false;

  const valid = snapshot => !!snapshot &&
    snapshot.record_type === 'market_state_snapshot' &&
    snapshot.is_mock === false;

  function createPanel() {
    const panel = document.createElement('section');
    panel.className = `panel ${PANEL_CLASS}`;
    panel.setAttribute('aria-label', '실시간 종목 데이터');
    panel.innerHTML = `
      <div class="whatif-live-market-head">
        <h2>실시간 종목 데이터</h2>
        <div class="whatif-live-market-status" data-state="connecting" role="status" aria-live="polite">
          <span class="whatif-live-market-dot" aria-hidden="true"></span>
          <span data-live-status>실시간 연결 확인 중</span>
        </div>
      </div>
      <p class="whatif-live-market-meta" data-live-meta>실제 시장 스냅샷을 기다리는 중입니다.</p>
      <div class="whatif-live-market-table-wrap" role="region" aria-label="실시간 종목 표, 가로 스크롤 가능" tabindex="0">
        <table class="whatif-live-market-table">
          <thead><tr>
            <th scope="col">종목</th><th scope="col">업종</th><th scope="col">전일 대비 %</th>
            <th scope="col">시가 대비 %</th><th scope="col">5분 %</th><th scope="col">30분 변동성 %</th>
            <th scope="col">누적 거래량</th><th scope="col">완전 수신</th>
          </tr></thead>
          <tbody data-live-rows><tr><td class="live-table-empty" colspan="8">실시간 데이터 수신 대기 중</td></tr></tbody>
        </table>
      </div>
      <p class="whatif-live-market-note" data-live-note>실제 데이터가 들어오면 종목 3개까지 표시합니다.</p>
      <div class="whatif-live-market-foot" data-live-foot>표시 값은 수신된 시장 스냅샷만 사용합니다.</div>`;
    return panel;
  }

  function syncPanels() {
    syncQueued = false;
    document.querySelectorAll('.scenario-visual').forEach(visual => {
      const graph = visual.querySelector(':scope > .scenario-chart, :scope > .chart-panel');
      if (!graph) {
        visual.classList.remove('whatif-live-market-layout');
        visual.querySelector(`:scope > .${PANEL_CLASS}`)?.remove();
        return;
      }
      visual.classList.add('whatif-live-market-layout');
      let panel = visual.querySelector(`:scope > .${PANEL_CLASS}`);
      if (!panel) {
        panel = createPanel();
        visual.append(panel);
      }
      renderPanel(panel);
    });
  }

  function scheduleSync() {
    if (syncQueued) return;
    syncQueued = true;
    requestAnimationFrame(syncPanels);
  }

  function formatTime(value) {
    if (!value || !Number.isFinite(Date.parse(value))) return '미확인';
    return new Intl.DateTimeFormat('ko-KR', {
      timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }).format(new Date(value));
  }

  function formatPercent(value, digits = 2) {
    if (value == null || value === '' || !Number.isFinite(Number(value))) return '—';
    return `${Number(value).toLocaleString('ko-KR', { maximumFractionDigits: digits })}%`;
  }

  function formatNumber(value) {
    if (value == null || value === '' || !Number.isFinite(Number(value))) return '—';
    return Number(value).toLocaleString('ko-KR', { maximumFractionDigits: 0 });
  }

  function cell(value, className = '') {
    const td = document.createElement('td');
    td.textContent = value;
    if (className) td.className = className;
    return td;
  }

  function changeClass(value) {
    const number = Number(value);
    return !Number.isFinite(number) || number === 0 ? '' : number > 0 ? 'positive' : 'negative';
  }

  function connectionLabel(delivery, stale) {
    if (delivery.error && delivery.websocket_status !== 'connected') return ['error', '데이터 연결 확인 필요'];
    if (stale) return ['stale', '데이터 갱신 지연'];
    const labels = {
      connected: ['connected', '실시간 연결됨'],
      connecting: ['connecting', '실시간 연결 중'],
      reconnecting: ['reconnecting', '실시간 재연결 중'],
      disconnected: ['error', '연결 끊김'],
    };
    return labels[delivery.websocket_status] || ['connecting', '실시간 연결 확인 중'];
  }

  function renderPanel(panel) {
    const status = panel.querySelector('[data-live-status]');
    const statusWrap = panel.querySelector('.whatif-live-market-status');
    const meta = panel.querySelector('[data-live-meta]');
    const note = panel.querySelector('[data-live-note]');
    const foot = panel.querySelector('[data-live-foot]');
    const tbody = panel.querySelector('[data-live-rows]');
    const snapshot = valid(latestSnapshot) ? latestSnapshot : null;
    const delivery = latestDelivery || {};

    if (!snapshot) {
      const [state, label] = connectionLabel(delivery, false);
      statusWrap.dataset.state = state;
      status.textContent = label;
      meta.textContent = '기준 시각 — · 수신 종목 —';
      note.textContent = delivery.error || '실제 시장 데이터 수신 대기 중입니다. 모의 데이터는 표시하지 않습니다.';
      foot.textContent = '시장 스냅샷 수신 후 종목 정보가 표시됩니다.';
      const tr = document.createElement('tr');
      const td = cell('실시간 데이터 수신 대기 중', 'live-table-empty');
      td.colSpan = 8;
      tr.append(td);
      tbody.replaceChildren(tr);
      return;
    }

    const assets = Array.isArray(snapshot.assets) ? [...snapshot.assets] : [];
    assets.sort((a, b) => String(a.asset_id || '').localeCompare(String(b.asset_id || '')));
    const visible = assets.slice(0, MAX_ROWS);
    const stamp = snapshot.last_event_time || snapshot.last_completed_bar_end || snapshot.as_of;
    const ageMs = stamp && Number.isFinite(Date.parse(stamp)) ? Math.max(0, Date.now() - Date.parse(stamp)) : null;
    const stale = delivery.stale === true || ageMs == null || ageMs > 120_000;
    const [state, label] = connectionLabel(delivery, stale);
    statusWrap.dataset.state = state;
    status.textContent = label;

    const expected = snapshot.expected_asset_count ?? assets.length;
    const validCount = snapshot.valid_asset_count ?? assets.length;
    meta.textContent = `기준 시각 ${formatTime(snapshot.as_of)} · 계산 ${validCount}/${expected}종목 · 표 ${visible.length}/${assets.length}종목`;
    note.textContent = delivery.error || (stale
      ? '마지막 스냅샷이 2분 이상 지났습니다. 새 수신을 기다립니다.'
      : `마지막 실시간 수신 ${formatTime(delivery.last_message_at)} · ${delivery.source || '시장 데이터'}`);
    foot.textContent = `품질 ${snapshot.quality_status || '미확인'} · 연결 ${snapshot.connection_status || '미확인'} · 스냅샷 ${snapshot.snapshot_id || 'ID 미확인'}`;

    if (!visible.length) {
      const tr = document.createElement('tr');
      const td = cell('수신된 종목 항목이 없습니다.', 'live-table-empty');
      td.colSpan = 8;
      tr.append(td);
      tbody.replaceChildren(tr);
      return;
    }

    tbody.replaceChildren(...visible.map(asset => {
      const tr = document.createElement('tr');
      const complete = asset.complete_since_open == null ? '판정 불가' : asset.complete_since_open ? '완료' : '미완료';
      tr.append(
        cell(String(asset.asset_id || '종목 미확인')),
        cell(String(asset.sector_id || '미분류')),
        cell(formatPercent(asset.return_since_previous_close_pct), changeClass(asset.return_since_previous_close_pct)),
        cell(formatPercent(asset.return_since_open_pct), changeClass(asset.return_since_open_pct)),
        cell(formatPercent(asset.return_5m_pct, 3), changeClass(asset.return_5m_pct)),
        cell(formatPercent(asset.volatility_30m_pct, 3)),
        cell(formatNumber(asset.volume_since_open)),
        cell(complete),
      );
      return tr;
    }));
  }

  document.addEventListener('whatif:market-state-updated', event => {
    const detail = event.detail || {};
    latestDelivery = detail.delivery || window.WHATIF_MARKET_DELIVERY || {};
    if (valid(detail.snapshot)) latestSnapshot = detail.snapshot;
    else if (valid(window.WHATIF_MARKET_STATE)) latestSnapshot = window.WHATIF_MARKET_STATE;
    scheduleSync();
  });

  if (valid(window.WHATIF_MARKET_STATE)) latestSnapshot = window.WHATIF_MARKET_STATE;
  latestDelivery = window.WHATIF_MARKET_DELIVERY || latestDelivery;
  const observer = new MutationObserver(scheduleSync);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  syncPanels();
})();
