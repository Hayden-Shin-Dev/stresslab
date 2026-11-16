/* Updates V3.8's existing stock table from the shared validated market feed. */
(() => {
  'use strict';

  const STOCK_NAMES = {
    '005930':'삼성전자','000660':'SK하이닉스','373220':'LG에너지솔루션','207940':'삼성바이오로직스',
    '005380':'현대차','005935':'삼성전자우','000270':'기아','068270':'셀트리온','105560':'KB금융',
    '012450':'한화에어로스페이스','034020':'두산에너빌리티','055550':'신한지주','028260':'삼성물산',
    '012330':'현대모비스','402340':'SK스퀘어','032830':'삼성생명','086790':'하나금융지주',
    '006400':'삼성SDI','009150':'삼성전기','034730':'SK',
  };
  const QUOTE_API = '/api/quotes';
  const quotes = new Map();
  let quoteStatus = 'connecting';
  let quoteCheckedAt = null;
  let quoteError = null;
  let quoteSocket = null;
  let quoteRetryTimer = null;
  let quoteRetryDelay = 3000;
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
    // The column header already carries the percent unit, matching the reference table.
    return Number(value).toLocaleString('ko-KR', { maximumFractionDigits: digits });
  };
  const volume = value => {
    if (value == null || value === '' || !Number.isFinite(Number(value))) return '계산 불가';
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
    if (!strip) {
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
      strip.append(state, freshness, refresh);
      heading.after(strip);
    }
    const refresh = strip.querySelector('.whatif-live-refresh');
    if (refresh && !refresh.dataset.bound) {
      refresh.dataset.bound = 'true';
      refresh.setAttribute('aria-label', '실시간 시장 데이터를 지금 새로고침');
      refresh.addEventListener('click', () => {
        refresh.disabled = true;
        refresh.textContent = '조회 중';
        document.dispatchEvent(new Event('whatif:market-state-refresh'));
        loadQuotes();
        window.setTimeout(() => {
          refresh.disabled = false;
          refresh.textContent = '새로고침';
        }, 1200);
      });
    }
    return strip;
  }

  function ensureStockViews(card, heading, strip, scroll) {
    let tabs = card.querySelector('.whatif-stock-card-tabs');
    if (!tabs) {
      tabs = document.createElement('div');
      tabs.className = 'whatif-stock-card-tabs';
      tabs.setAttribute('role', 'tablist');
      tabs.setAttribute('aria-label', '종목 데이터 보기');
      for (const [view, label] of [['ranking', '국내 주식'], ['metrics', '장중 지표']]) {
        const button = document.createElement('button');
        button.type = 'button';
        button.dataset.stockView = view;
        button.setAttribute('role', 'tab');
        button.setAttribute('aria-selected', String(view === 'ranking'));
        button.textContent = label;
        tabs.append(button);
      }
      const list = document.createElement('div');
      list.className = 'whatif-ranking-list';
      list.setAttribute('role', 'tabpanel');
      list.setAttribute('aria-label', '실시간 국내 주식 순위');
      strip.after(tabs);
      tabs.after(list);
    }
    const title = heading.querySelector('h3');
    if (title && title.textContent !== '국내 주식') title.textContent = '국내 주식';
    bindTabs(card);
    setStockView(card, card.dataset.stockView || 'ranking');
  }

  function bindTabs(card) {
    const tabs = [...card.querySelectorAll('[data-stock-view]')];
    if (!tabs.length || card.dataset.stockTabsBound) return;
    card.dataset.stockTabsBound = 'true';
    tabs.forEach(tab => tab.addEventListener('click', () => setStockView(card, tab.dataset.stockView)));
    setStockView(card, card.dataset.stockView || 'ranking');
  }

  function setStockView(card, view) {
    if (card.dataset.stockView === view && card.dataset.stockViewBound === 'true') return;
    card.dataset.stockView = view;
    card.dataset.stockViewBound = 'true';
    card.querySelectorAll('[data-stock-view]').forEach(tab => {
      const active = tab.dataset.stockView === view;
      if (tab.classList.contains('is-active') !== active) tab.classList.toggle('is-active', active);
      if (tab.getAttribute('aria-selected') !== String(active)) tab.setAttribute('aria-selected', String(active));
    });
    const ranking = card.querySelector('.whatif-ranking-list');
    const metrics = card.querySelector('.whatif-stock-table-scroll');
    if (ranking) ranking.hidden = view !== 'ranking';
    if (metrics) metrics.hidden = view !== 'metrics';
  }

  function acceptQuotes(list) {
    for (const quote of list || []) {
      if (!quote || quote.is_mock !== false || !['quote_event', 'quote_latest'].includes(quote.record_type)) continue;
      if (!quote.asset_id || !Number.isFinite(Number(quote.price))) continue;
      const previous = quotes.get(quote.asset_id);
      const stamp = item => Date.parse(item?.event_time || item?.received_at || '') || 0;
      if (previous && stamp(quote) < stamp(previous)) continue;
      quotes.set(quote.asset_id, quote);
    }
  }

  async function loadQuotes() {
    try {
      const response = await fetch(`${QUOTE_API}/latest`, { cache: 'no-store' });
      if (!response.ok) throw new Error(`시세 API 응답 ${response.status}`);
      const payload = await response.json();
      acceptQuotes(payload.quotes || payload.data?.quotes || []);
      quoteCheckedAt = Date.now();
      quoteError = null;
      scheduleSync();
    } catch (error) {
      quoteCheckedAt = Date.now();
      quoteError = error.message || '현재 시세를 가져오지 못했습니다.';
      scheduleSync();
    }
  }

  function scheduleQuoteReconnect() {
    if (quoteRetryTimer) return;
    quoteRetryTimer = setTimeout(() => {
      quoteRetryTimer = null;
      connectQuotes();
    }, quoteRetryDelay);
    quoteRetryDelay = Math.min(15000, Math.round(quoteRetryDelay * 1.5));
  }

  async function connectQuotes() {
    try {
      quoteStatus = 'connecting';
      scheduleSync();
      const response = await fetch(`${QUOTE_API}/negotiate`, { method: 'POST', cache: 'no-store' });
      if (!response.ok) throw new Error(`시세 스트림 연결 실패 (${response.status})`);
      const payload = await response.json();
      if (!payload.url) throw new Error('시세 스트림 주소가 없습니다.');
      const socket = new WebSocket(payload.url);
      quoteSocket = socket;
      socket.onopen = () => {
        if (quoteSocket !== socket) return;
        quoteStatus = 'connected';
        quoteRetryDelay = 3000;
        scheduleSync();
        loadQuotes();
      };
      socket.onmessage = event => {
        try {
          const message = JSON.parse(event.data);
          acceptQuotes(message.type === 'quote_batch' ? message.quotes : [message]);
          scheduleSync();
        } catch { quoteError = '시세 메시지를 해석하지 못했습니다.'; scheduleSync(); }
      };
      socket.onerror = () => { quoteError = '시세 스트림 오류'; socket.close(); };
      socket.onclose = () => {
        if (quoteSocket !== socket) return;
        quoteSocket = null;
        quoteStatus = 'reconnecting';
        scheduleSync();
        scheduleQuoteReconnect();
      };
    } catch (error) {
      quoteStatus = 'reconnecting';
      quoteError = error.message || '시세 스트림에 연결하지 못했습니다.';
      scheduleSync();
      scheduleQuoteReconnect();
    }
  }

  function renderRanking(card, assets, stamp) {
    const list = card.querySelector('.whatif-ranking-list');
    if (!list) return;
    const byCode = new Map(assets.map(asset => [String(asset.asset_id), asset]));
    const rows = [...quotes.values()].map(quote => ({
      quote,
      asset: byCode.get(String(quote.asset_id)) || null,
      volume: Number(quote.cumulative_volume ?? byCode.get(String(quote.asset_id))?.volume_since_open ?? 0),
    })).filter(row => row.asset || quotes.size > 0)
      .sort((a, b) => b.volume - a.volume)
      .slice(0, 10);
    const sourceStamp = `${stamp || ''}|${rows.map(row => `${row.quote.asset_id}:${row.quote.price}:${row.quote.cumulative_volume}:${row.asset?.return_since_previous_close_pct}`).join(',')}`;
    if (!rows.length) {
      const empty = quoteError || '실시간 시세 수신을 기다리고 있습니다.';
      if (list.dataset.sourceStamp !== sourceStamp || list.textContent !== empty) list.textContent = empty;
      list.dataset.sourceStamp = sourceStamp;
      return;
    }
    if (list.dataset.sourceStamp === sourceStamp) return;
    const fragment = document.createDocumentFragment();
    rows.forEach((row, index) => {
      const code = String(row.quote.asset_id);
      const item = document.createElement('article');
      item.className = 'whatif-ranking-row';
      const rank = document.createElement('span');
      rank.className = 'whatif-ranking-number';
      rank.textContent = String(index + 1);
      const nameBlock = document.createElement('div');
      nameBlock.className = 'whatif-ranking-name';
      const name = document.createElement('strong');
      name.textContent = STOCK_NAMES[code] || code;
      const detail = document.createElement('small');
      detail.textContent = `${code} · 누적 ${Number.isFinite(row.volume) ? row.volume.toLocaleString('ko-KR') : '—'}주`;
      nameBlock.append(name, detail);
      const quoteBlock = document.createElement('div');
      quoteBlock.className = 'whatif-ranking-quote';
      const price = document.createElement('strong');
      price.textContent = Number(row.quote.price).toLocaleString('ko-KR');
      const change = document.createElement('span');
      const changeValue = row.asset?.return_since_previous_close_pct;
      change.textContent = changeValue == null ? '—' : `${Number(changeValue).toLocaleString('ko-KR', {maximumFractionDigits: 2})}%`;
      const changeNumber = Number(changeValue);
      change.className = changeNumber > 0 ? 'whatif-live-change-positive' : changeNumber < 0 ? 'whatif-live-change-negative' : '';
      quoteBlock.append(price, change);
      item.append(rank, nameBlock, quoteBlock);
      fragment.append(item);
    });
    list.replaceChildren(fragment);
    list.dataset.sourceStamp = sourceStamp;
  }

  function renderCard(card) {
    const snapshot = valid(window.WHATIF_MARKET_STATE) ? window.WHATIF_MARKET_STATE : null;
    const delivery = latestDelivery || window.WHATIF_MARKET_DELIVERY || {};
    const assets = snapshot && Array.isArray(snapshot.assets) ? [...snapshot.assets] : [];
    assets.sort((a, b) => String(a.asset_id || '').localeCompare(String(b.asset_id || '')));
    const stamp = snapshot && (snapshot.last_event_time || snapshot.last_completed_bar_end || snapshot.as_of);
    const stampMs = stamp && Number.isFinite(Date.parse(stamp)) ? Date.parse(stamp) : null;
    const ageMs = stampMs == null ? null : Math.max(0, Date.now() - stampMs);
    const tableKey = JSON.stringify([
      snapshot?.snapshot_id, snapshot?.as_of, snapshot ? null : delivery.error,
      assets.map(a => [a.asset_id, a.sector_id, a.return_since_previous_close_pct,
        a.return_since_open_pct, a.return_5m_pct, a.volatility_30m_pct,
        a.volume_since_open, a.observed_volume, a.cumulative_volume, a.complete_since_open]),
    ]);
    const badge = card.querySelector('.whatif-stock-table-heading small');
    const heading = card.querySelector('.whatif-stock-table-heading');
    const scroll = card.querySelector('.whatif-stock-table-scroll');
    const foot = card.querySelector('.whatif-stock-table-foot');
    if (!badge || !heading || !scroll || !foot) return;
    const strip = ensureStatusStrip(card, heading);
    ensureStockViews(card, heading, strip, scroll);
    const connectionNode = strip.querySelector('.whatif-live-connection');
    const freshnessNode = strip.querySelector('.whatif-live-freshness');

    const quoteStamps = [...quotes.values()].map(q => Date.parse(q.event_time || q.received_at || '')).filter(Number.isFinite);
    const quoteStamp = quoteStamps.length ? Math.max(...quoteStamps) : null;
    const quoteAge = quoteStamp == null ? null : Math.max(0, Date.now() - quoteStamp);
    const quoteStale = quoteAge == null || quoteAge > 120_000;
    const connectionState = quoteStatus === 'connected' ? (quoteStale ? 'connected-stale' : 'connected')
      : quoteStatus === 'connecting' || quoteStatus === 'reconnecting' ? 'pending' : 'offline';
    const nextConnectionClass = `whatif-live-connection is-${connectionState}`;
    if (connectionNode.className !== nextConnectionClass) connectionNode.className = nextConnectionClass;
    setText(connectionNode, quoteStatus === 'connected'
      ? (quoteStale ? '시세 스트림 · 갱신 지연' : '실시간 시세 연결됨')
      : quoteStatus === 'reconnecting' ? '시세 재연결 중' : quoteStatus === 'connecting' ? '시세 연결 중' : '시세 연결 확인 필요');
    const checkedLabel = quoteCheckedAt ? time(new Date(quoteCheckedAt).toISOString()) : '미확인';
    const ageLabel = quoteAge == null ? '실제 시세 대기' : `${Math.floor(quoteAge / 1000)}초 전 시세`;
    setText(freshnessNode, `${quotes.size}종목 수신 · ${ageLabel} · API 확인 ${checkedLabel}${quoteError ? ` · ${quoteError}` : ''}`);
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
      } else if (!assets.length) {
        tbody.append(emptyCell('실제 스냅샷에 표시할 종목이 없습니다.'));
      } else {
        for (const asset of assets) {
          const tr = document.createElement('tr');
          const complete = asset.complete_since_open == null ? '판정 불가' : asset.complete_since_open ? '예' : '아니요';
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

    renderRanking(card, assets, stamp);
    setStockView(card, card.dataset.stockView || 'ranking');

    if (!snapshot) {
      setText(foot, delivery.error || '시장 스냅샷이 도착하면 실제 수신값만 표시합니다.');
    } else {
      const age = ageMs == null ? '미확인' : `${Math.floor(ageMs / 1000)}초`;
      const lastCheck = delivery.last_poll_at ? time(delivery.last_poll_at) : '미확인';
      const session = snapshot.session_verified === false ? ' · 공급자 장 세션 미검증' : '';
      const source = delivery.source === 'webpubsub' ? 'WebSocket' : delivery.source === 'current' ? '현재값 API' : '확인 중';
      setText(foot, `종목 순위는 실제 quote_latest 누적 거래량 기준입니다. 실시간 현재가·체결 데이터는 /api/quotes, 등락·장중 지표는 /api/market-state에서 종목 코드로 결합합니다. 기준 ${time(stamp)} · ${age} 경과 · 시장 API 확인 ${lastCheck} · ${source}${session} · ${assets.length}개 종목 지표`);
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
  loadQuotes();
  connectQuotes();
  setInterval(loadQuotes, 15_000);
  window.addEventListener('pagehide', () => {
    clearTimeout(quoteRetryTimer);
    if (quoteSocket) { quoteSocket.onclose = null; quoteSocket.close(); quoteSocket = null; }
  }, { once: true });
  const observer = new MutationObserver(scheduleSync);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  sync();
  setInterval(scheduleSync, 15_000);
})();
