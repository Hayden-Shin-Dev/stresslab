/* Updates V3.8's existing stock table from the shared validated market feed. */
(() => {
  'use strict';

  const MAX_ROWS = 3;
  let latestDelivery = window.WHATIF_MARKET_DELIVERY || {};
  let pendingFrame = false;

  const valid = s => !!s && s.is_mock === false && s.record_type === 'market_state_snapshot';
  const setText = (node, value) => {
    const text = String(value ?? '');
    if (node.textContent !== text) node.textContent = text;
  };
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

  function quality(snapshot, assets) {
    const complete = assets.filter(asset => asset.complete_since_open === true).length;
    const expected = snapshot.expected_asset_count ?? assets.length;
    const validCount = snapshot.valid_asset_count ?? assets.length;
    const state = snapshot.quality_status === 'complete' ? '정상 수신'
      : snapshot.quality_status === 'partial' ? '일부 지표 미완전'
      : `품질 ${snapshot.quality_status || '미확인'}`;
    return `${validCount}/${expected}종목 · 시가 이후 완전 ${complete}/${assets.length} · ${state}`;
  }

  function ensureStatusStrip(card, heading) {
    let strip = card.querySelector('.whatif-live-status');
    if (strip) return strip;
    strip = document.createElement('div');
    strip.className = 'whatif-live-status';
    strip.setAttribute('role', 'status');
    strip.setAttribute('aria-live', 'polite');
    const state = document.createElement('span');
    state.className = 'whatif-live-connection';
    const freshness = document.createElement('span');
    freshness.className = 'whatif-live-freshness';
    const refresh = document.createElement('button');
    refresh.className = 'whatif-live-refresh';
    refresh.type = 'button';
    refresh.textContent = '새로고침';
    refresh.setAttribute('aria-label', '실시간 시장 데이터를 지금 새로고침');
    refresh.addEventListener('click', () => {
      refresh.disabled = true;
      refresh.textContent = '조회 중';
      document.dispatchEvent(new Event('whatif:market-state-refresh'));
      window.setTimeout(() => {
        refresh.disabled = false;
        refresh.textContent = '새로고침';
      }, 1200);
    });
    strip.append(state, freshness, refresh);
    heading.after(strip);
    return strip;
  }

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
    const tableKey = JSON.stringify([
      snapshot?.snapshot_id, snapshot?.as_of, snapshot ? null : delivery.error,
      visible.map(a => [a.asset_id, a.sector_id, a.return_since_previous_close_pct,
        a.return_since_open_pct, a.return_5m_pct, a.volatility_30m_pct,
        a.volume_since_open, a.complete_since_open]),
    ]);
    const badge = card.querySelector('.whatif-stock-table-heading small');
    const heading = card.querySelector('.whatif-stock-table-heading');
    const scroll = card.querySelector('.whatif-stock-table-scroll');
    const foot = card.querySelector('.whatif-stock-table-foot');
    if (!badge || !heading || !scroll || !foot) return;
    const strip = ensureStatusStrip(card, heading);
    const connectionNode = strip.querySelector('.whatif-live-connection');
    const freshnessNode = strip.querySelector('.whatif-live-freshness');

    const connectionLabel = connection(delivery);
    const connectionState = delivery.websocket_status === 'connected' ? (stale ? 'connected-stale' : 'connected')
      : delivery.websocket_status === 'connecting' || delivery.websocket_status === 'reconnecting' ? 'pending'
      : 'offline';
    connectionNode.className = `whatif-live-connection is-${connectionState}`;
    setText(connectionNode, delivery.websocket_status === 'connected'
      ? (stale ? '스트림 연결 · 데이터 지연' : '실시간 스트림 연결됨')
      : connectionLabel);
    if (snapshot) {
      const age = ageMs == null ? '기준 시각 미확인' : `${Math.floor(ageMs / 1000)}초 전 기준값`;
      setText(freshnessNode, `${time(stamp)} · ${age}`);
    } else {
      setText(freshnessNode, delivery.error || '실제 시장 스냅샷 수신을 기다리고 있습니다.');
    }
    const qualityLabel = snapshot ? quality(snapshot, assets) : '실제 데이터 연결 대기';
    if (badge.dataset.whatifLiveStatus !== qualityLabel) {
      badge.textContent = qualityLabel;
      badge.dataset.whatifLiveStatus = qualityLabel;
    }

    if (card.dataset.whatifLiveTableKey !== tableKey) {
      card.dataset.whatifLiveTableKey = tableKey;
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
    }

    if (!snapshot) {
      setText(foot, delivery.error || '시장 스냅샷이 도착하면 실제 수신값만 표시합니다.');
    } else {
      const age = ageMs == null ? '미확인' : `${Math.floor(ageMs / 1000)}초`;
      const lastCheck = delivery.last_poll_at ? time(delivery.last_poll_at) : '미확인';
      const session = snapshot.session_verified === false ? ' · 공급자 장 세션 미검증' : '';
      const source = delivery.source === 'webpubsub' ? 'WebSocket' : delivery.source === 'current' ? '현재값 API' : '확인 중';
      setText(foot, `원본 기준 ${time(stamp)} · 기준값 경과 ${age} · 마지막 API 확인 ${lastCheck} · 수신 경로 ${source}${session} · 표 ${visible.length}/${assets.length}종목 · snapshot_id ${snapshot.snapshot_id || '미확인'}`);
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
