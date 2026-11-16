/* Shared market-state transport for both the main workspace and live monitor. */
(() => {
  'use strict';

  // Use the same authenticated APIM route as the existing quote-monitor page.
  const API = '/api/market-state';
  const STALE_AFTER_MS = 120_000;
  let socket = null;
  let retryTimer = null;
  let pollTimer = null;
  let freshnessTimer = null;
  let pollInFlight = null;
  let retryDelay = 3_000;
  let active = true;
  let socketStatus = 'disconnected';
  let lastPollOk = null;
  let lastPollAt = null;
  let lastMessageAt = null;
  let lastSnapshotAt = null;
  let lastSource = null;
  let lastError = null;
  let lastNotificationKey = '';

  function valid(snapshot) {
    return !!snapshot && snapshot.record_type === 'market_state_snapshot' && snapshot.is_mock === false;
  }

  function notify() {
    const snapshot = window.WHATIF_MARKET_STATE || null;
    const stamp = snapshot && (snapshot.last_event_time || snapshot.last_completed_bar_end || snapshot.as_of);
    const sourceTime = stamp ? Date.parse(stamp) : NaN;
    const ageMs = Number.isFinite(sourceTime) ? Math.max(0, Date.now() - sourceTime) : null;
    window.WHATIF_MARKET_DELIVERY = {
      age_seconds: ageMs == null ? null : Math.floor(ageMs / 1000),
      stale: ageMs == null || ageMs > STALE_AFTER_MS,
      persisted: typeof snapshot?.persisted === 'boolean' ? snapshot.persisted : null,
      last_poll_ok: lastPollOk,
      last_poll_at: lastPollAt ? new Date(lastPollAt).toISOString() : null,
      websocket_status: socketStatus,
      last_message_at: lastMessageAt ? new Date(lastMessageAt).toISOString() : null,
      last_snapshot_at: lastSnapshotAt ? new Date(lastSnapshotAt).toISOString() : null,
      source: lastSource,
      error: lastError,
    };
    const notificationKey = [snapshot?.snapshot_id, window.WHATIF_MARKET_DELIVERY.stale, socketStatus, lastPollOk, lastPollAt, lastMessageAt, lastSource, lastError].join('|');
    if (notificationKey === lastNotificationKey) return;
    lastNotificationKey = notificationKey;
    document.dispatchEvent(new CustomEvent('whatif:market-state-updated', {
      detail: { snapshot, delivery: window.WHATIF_MARKET_DELIVERY },
    }));
  }

  function accept(snapshot, source) {
    if (!valid(snapshot)) return false;
    const previous = window.WHATIF_MARKET_STATE;
    const previousTime = Date.parse(previous?.as_of || '');
    const nextTime = Date.parse(snapshot.as_of || '');
    if (previous && Number.isFinite(previousTime) && Number.isFinite(nextTime) && nextTime < previousTime) return false;
    if (source === 'webpubsub') lastMessageAt = Date.now();
    const changed = !previous || previous.snapshot_id !== snapshot.snapshot_id || previous.as_of !== snapshot.as_of;
    if (changed) {
      window.WHATIF_MARKET_STATE = snapshot;
      lastSnapshotAt = Date.now();
      lastSource = source;
    }
    lastError = null;
    notify();
    return true;
  }

  async function loadCurrent() {
    if (!active || pollInFlight) return pollInFlight;
    pollInFlight = (async () => {
      try {
        const response = await fetch(`${API}/current`, { cache: 'no-store' });
        if (!response.ok) throw new Error(`현재 스냅샷 조회 실패 (${response.status})`);
        const payload = await response.json();
        const snapshot = payload.snapshot || payload.data?.snapshot || payload;
        if (!valid(snapshot)) throw new Error('실제 시장 스냅샷이 없습니다.');
        lastPollOk = true;
        lastPollAt = Date.now();
        lastError = null;
        // A newer WebSocket snapshot can win a race with this HTTP response.
        // The API request still succeeded even when its older value is ignored.
        accept(snapshot, 'current');
      } catch (error) {
        lastPollOk = false;
        lastPollAt = Date.now();
        lastError = error.message || '현재 스냅샷을 불러오지 못했습니다.';
      }
      notify();
    })();
    try { await pollInFlight; } finally { pollInFlight = null; }
    return undefined;
  }

  function scheduleReconnect() {
    if (!active || retryTimer) return;
    retryTimer = setTimeout(() => {
      retryTimer = null;
      connect();
    }, retryDelay);
    retryDelay = Math.min(15_000, Math.round(retryDelay * 1.5));
  }

  async function connect() {
    if (!active || socketStatus === 'connecting') return;
    socketStatus = 'connecting';
    lastError = null;
    notify();
    try {
      const response = await fetch(`${API}/negotiate`, { method: 'POST', cache: 'no-store' });
      if (!response.ok) throw new Error(`실시간 연결 주소 발급 실패 (${response.status})`);
      const payload = await response.json();
      if (!payload.url) throw new Error('실시간 연결 주소가 없습니다.');
      if (!active) return;
      const nextSocket = new WebSocket(payload.url);
      socket = nextSocket;
      nextSocket.onopen = () => {
        if (!active || socket !== nextSocket) return;
        socketStatus = 'connected';
        retryDelay = 3_000;
        notify();
        loadCurrent();
      };
      nextSocket.onmessage = event => {
        try {
          const message = JSON.parse(event.data);
          const snapshot = message.snapshot || message.data?.snapshot || message.data || message;
          if (!accept(snapshot, 'webpubsub')) {
            lastError = '실시간 메시지에 유효한 시장 스냅샷이 없습니다.';
            notify();
          }
        } catch (error) {
          lastError = '실시간 메시지를 해석하지 못했습니다.';
          notify();
        }
      };
      nextSocket.onerror = () => {
        lastError = '실시간 WebSocket 연결 오류';
        notify();
        nextSocket.close();
      };
      nextSocket.onclose = () => {
        if (!active || socket !== nextSocket) return;
        socket = null;
        socketStatus = 'reconnecting';
        notify();
        scheduleReconnect();
      };
    } catch (error) {
      socketStatus = 'reconnecting';
      lastError = error.message || '실시간 연결을 시작하지 못했습니다.';
      notify();
      scheduleReconnect();
    }
  }

  function stop() {
    active = false;
    clearTimeout(retryTimer);
    clearInterval(pollTimer);
    clearInterval(freshnessTimer);
    retryTimer = null;
    pollTimer = null;
    freshnessTimer = null;
    if (socket) {
      socket.onclose = null;
      socket.close();
      socket = null;
    }
  }

  window.WHATIF_MARKET_DELIVERY = {
    age_seconds: null,
    stale: true,
    persisted: null,
    last_poll_ok: null,
    last_poll_at: null,
    websocket_status: 'connecting',
    last_message_at: null,
    last_snapshot_at: null,
    source: null,
    error: null,
  };
  document.addEventListener('whatif:market-state-refresh', () => {
    loadCurrent();
    if (active && (!socket || socket.readyState > WebSocket.OPEN)) {
      socketStatus = 'reconnecting';
      scheduleReconnect();
      notify();
    }
  });
  loadCurrent();
  connect();
  pollTimer = setInterval(loadCurrent, 15_000);
  freshnessTimer = setInterval(notify, 15_000);
  window.addEventListener('pagehide', stop, { once: true });
  window.addEventListener('online', () => {
    if (active && (!socket || socket.readyState > WebSocket.OPEN)) {
      socketStatus = 'reconnecting';
      scheduleReconnect();
    }
  });
})();
