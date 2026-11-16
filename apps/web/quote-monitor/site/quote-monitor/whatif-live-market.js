/* Updates V3.8's existing stock table from the shared validated market feed. */
(() => {
  'use strict';

  const MAX_ROWS = 3;
  let latestDelivery = window.WHATIF_MARKET_DELIVERY || {};
  let pendingFrame = false;

  const valid = s => !!s && s.is_mock === false && s.record_type === 'market_state_snapshot';
  const time = value => {
    if (!value || !Number.isFinite(Date.parse(value))) return '미확인';
    return new Intl.DateTimeFormat('ko-KR', {
      timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }).format(new Date(value));
  };
  const percent = (value, digits = 2) => {
    if (value == null || value === '' || !Number.isFinite(Number(value))) return '—';
    return `${Number(value).toLocaleString('ko-KR', { maximumFractionDigits: digits })}%`;
  };
  const volume = value => {
    if (value == null || value === '' || !Number.isFinite(Number(value))) return '—';
    return Number(value).toLocaleString('ko-KR', { maximumFractionDigits: 0 });
  };
  const changeClass = value => {
    const n = Number(value);
    return !Number.isFinite(n) || n === 0 ? '' : n > 0 ? 'whatif-live-change-positive' : 'whatif-live-change-negative';
  };
  const cell = (text, className = '') => {
    const td = document.createElement('td');
    td.textContent = text;
    if (className) td.className = className;
    return td;
  };
  const emptyCell = message => {
    const tr = document.createElement('tr');
    const td = cell(message, 'whatif-stock-empty whatif-live-empty');
    td.colSpan = 8;
    tr.append(td);
    return tr;
  };
  const connection = delivery => ({
    connected: '실시간 연결됨',
    connecting: '연결 중',
    reconnecting: '재연결 중',
    disconnected: '연결 끊김',
  }[delivery.websocket_status] || (delivery.error ? '연결 확인 필요' : '연결 대기'));

  function renderCard(card) {
    const snapshot = valid(window.WHATIF_MARKET_STATE) ? window.WHATIF_MARKET_STATE : null;
    const delivery = latestDelivery || window.WHATIF_MARKET_DELIVERY || {};
    const assets = snapshot && Array.isArray(snapshot.assets) ? [...snapshot.assets] : [];
    assets.sort((a, b) => String(a.asset_id || '').localeCompare(String(b.asset_id || '')));
    const visible = assets.slice(0, MAX_ROWS);
    const stamp = snapshot && (snapshot.last_event_time || snapshot.last_completed_bar_end || snapshot.as_of);
    const stampMs = stamp && Number.isFinite(Date.parse(stamp)) ? Date.parse(stamp) : null;
    const ageMs = stampMs == null ? null : Math.max(0, Date.now() - stampMs);
    const stale = !!snapshot && (delivery.stale === true || ageMs == null || ageMs > 120_000);
    const ageBucket = ageMs == null ? null : Math.floor(ageMs / 15_000);
    const key = JSON.stringify([
      snapshot?.snapshot_id, snapshot?.as_of, delivery.websocket_status,
      delivery.stale, delivery.last_message_at, delivery.last_poll_ok,
      delivery.error, stale, ageBucket,
      visible.map(a => [a.asset_id, a.sector_id, a.return_since_previous_close_pct,
        a.return_since_open_pct, a.return_5m_pct, a.volatility_30m_pct,
        a.volume_since_open, a.complete_since_open]),
    ]);
    if (card.dataset.whatifLiveKey === key) return;
    card.dataset.whatifLiveKey = key;

    const badge = card.querySelector('.whatif-stock-table-heading small');
    const scroll = card.querySelector('.whatif-stock-table-scroll');
    const foot = card.querySelector('.whatif-stock-table-foot');
    if (!badge || !scroll || !foot) return;

    const stateLabel = !snapshot ? connection(delivery) : stale ? '데이터 갱신 지연' : connection(delivery);
    if (badge.dataset.whatifLiveStatus !== stateLabel) {
      badge.textContent = snapshot
        ? `${snapshot.valid_asset_count ?? assets.length}/${snapshot.expected_asset_count ?? assets.length}종목 · ${snapshot.quality_status || '품질 미확인'} · ${stateLabel}`
        : stateLabel;
      badge.dataset.whatifLiveStatus = stateLabel;
      badge.setAttribute('role', 'status');
      badge.setAttribute('aria-live', 'polite');
    }

    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const header = document.createElement('tr');
    for (const title of ['종목', '업종', '전일 대비 %', '시가 대비 %', '5분 %', '30분 변동성 %', '누적 거래량', '완전 수신']) {
      const th = document.createElement('th');
      th.scope = 'col';
      th.textContent = title;
      header.append(th);
    }
    thead.append(header);
    const tbody = document.createElement('tbody');

    if (!snapshot) {
      tbody.append(emptyCell(delivery.error || '실제 시장 스냅샷 수신 대기 중입니다. 모의 데이터는 표시하지 않습니다.'));
    } else if (!visible.length) {
      tbody.append(emptyCell('실제 스냅샷에 표시할 종목이 없습니다.'));
    } else {
      for (const asset of visible) {
        const tr = document.createElement('tr');
        const complete = asset.complete_since_open == null ? '판정 불가' : asset.complete_since_open ? '완료' : '미완료';
        tr.append(
          cell(String(asset.asset_id || '종목 미확인')),
          cell(String(asset.sector_id || '미분류')),
          cell(percent(asset.return_since_previous_close_pct), changeClass(asset.return_since_previous_close_pct)),
          cell(percent(asset.return_since_open_pct), changeClass(asset.return_since_open_pct)),
          cell(percent(asset.return_5m_pct, 3), changeClass(asset.return_5m_pct)),
          cell(percent(asset.volatility_30m_pct, 3)),
          cell(volume(asset.volume_since_open ?? asset.observed_volume ?? asset.cumulative_volume)),
          cell(complete),
        );
        tbody.append(tr);
      }
    }
    table.append(thead, tbody);
    scroll.replaceChildren(table);

    if (!snapshot) {
      foot.textContent = delivery.error || '시장 스냅샷이 도착하면 실제 수신값만 표시합니다.';
    } else {
      const age = ageMs == null ? '미확인' : `${Math.floor(ageMs / 1000)}초`;
      const lastReceive = delivery.last_message_at ? time(delivery.last_message_at) : '미확인';
      foot.textContent = `기준 시각 ${time(snapshot.as_of)} · 경과 ${age} · 마지막 수신 ${lastReceive} · 표 ${visible.length}/${assets.length}종목 · snapshot_id ${snapshot.snapshot_id || '미확인'}`;
    }
  }

  function sync() {
    pendingFrame = false;
    document.querySelectorAll('.whatif-stock-table-card').forEach(renderCard);
  }
  function scheduleSync() {
    if (pendingFrame) return;
    pendingFrame = true;
    requestAnimationFrame(sync);
  }

  document.addEventListener('whatif:market-state-updated', event => {
    latestDelivery = event.detail?.delivery || window.WHATIF_MARKET_DELIVERY || {};
    scheduleSync();
  });
  latestDelivery = window.WHATIF_MARKET_DELIVERY || latestDelivery;
  const observer = new MutationObserver(scheduleSync);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  sync();
  setInterval(scheduleSync, 15_000);
})();
