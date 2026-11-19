(() => {
  'use strict';
  const API = '/api';
  const POLL_MS = 15_000;
  const MAX_DEBATES = 12;
  const state = { running: false, inFlight: false, timer: null, events: new Map(), errors: new Map() };
  const el = id => document.getElementById(id);
  const fmt = value => {
    if (!value) return '시각 미확인';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '시각 미확인' : date.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul', hour12: false });
  };
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const safeHttpsUrl = value => {
    try { const url = new URL(value); return url.protocol === 'https:' ? url.href : ''; }
    catch { return ''; }
  };
  const titleForStatus = status => ({accepted:'접수됨',running:'진행 중',completed:'완료',failed:'실패'})[status] || status || '상태 미확인';

  async function getJson(path) {
    const response = await fetch(path, { cache: 'no-store', credentials: 'same-origin' });
    const contentType = response.headers.get('content-type') || '';
    if (response.redirected && /login/i.test(new URL(response.url).pathname)) throw new Error('로그인이 필요합니다. 먼저 Google 로그인 후 다시 열어 주세요.');
    if (!response.ok) throw new Error(`뉴스 API 요청 실패 (${response.status})`);
    if (!contentType.includes('application/json')) throw new Error('API가 JSON 대신 HTML을 반환했습니다. 인증 또는 API 연결을 확인해 주세요.');
    return response.json();
  }

  async function loadEvents(debate) {
    const existing = state.events.get(debate.debate_id) || { cursor: 0, evidence: null };
    if (existing.complete) return existing;
    const payload = await getJson(`${API}/debates/${encodeURIComponent(debate.debate_id)}/events?after_seq=${existing.cursor}&limit=500`);
    for (const event of payload.events || []) {
      if (event.type === 'debate.evidence_ready') existing.evidence = event;
    }
    existing.cursor = payload.next_after_seq ?? existing.cursor;
    existing.complete = ['completed', 'failed', 'cancelled'].includes(debate.status);
    state.events.set(debate.debate_id, existing);
    state.errors.delete(debate.debate_id);
    return existing;
  }

  function renderNews(news) {
    const citations = (Array.isArray(news.citations) ? news.citations : []).map(item => ({...item, safeUrl: safeHttpsUrl(item.url)})).filter(item => item.safeUrl);
    const queryLinks = (Array.isArray(news.search_query_urls) ? news.search_query_urls : []).map(safeHttpsUrl).filter(Boolean);
    return `<article class="news-item">
      <div class="news-title">${escapeHtml(news.asset_name || news.asset_id || '종목 뉴스')}</div>
      <div class="news-meta">종목 코드 ${escapeHtml(news.asset_id || '미확인')} · 근거 ${escapeHtml(news.source_id || '미확인')}</div>
      ${citations.length ? `<div class="links">${citations.map((item, index) => `<a href="${escapeHtml(item.safeUrl)}" target="_blank" rel="noopener noreferrer">기사 출처 ${index + 1}: ${escapeHtml(item.title || item.safeUrl)}</a>`).join('')}</div>` : '<div class="message">기사 출처가 응답에 없습니다.</div>'}
      ${queryLinks.length ? `<div class="links">${queryLinks.map((url, index) => `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">Bing 검색어 ${index + 1}</a>`).join('')}</div>` : ''}
    </article>`;
  }

  function render(debates, checkedAt) {
    const items = debates.map(debate => {
      const cached = state.events.get(debate.debate_id);
      const evidence = cached?.evidence?.payload;
      const news = Array.isArray(evidence?.web_news) ? evidence.web_news : [];
      const newsStatus = evidence?.news_status || (cached ? 'no_evidence' : 'pending');
      const statusClass = ['ok','partial'].includes(newsStatus) && news.length ? 'ok' : ['disabled','failed','budget_exceeded'].includes(newsStatus) ? newsStatus : '';
      let body;
      if (state.errors.has(debate.debate_id)) body = `<div class="error">${escapeHtml(state.errors.get(debate.debate_id))}</div>`;
      else if (!evidence) body = `<div class="message">뉴스 근거 수집 대기 중 · 토론 상태 ${escapeHtml(titleForStatus(debate.status))}</div>`;
      else if (news.length) body = `<div class="news-list">${news.map(renderNews).join('')}</div>`;
      else if (newsStatus === 'disabled') body = '<div class="message">뉴스 수집 기능이 비활성화된 상태로 토론이 실행됐습니다.</div>';
      else if (newsStatus === 'failed') body = '<div class="message">뉴스 조회에 실패했습니다. 토론 상세 로그의 오류를 확인해 주세요.</div>';
      else if (newsStatus === 'budget_exceeded') body = '<div class="message">뉴스 검색 일일 한도에 도달했습니다.</div>';
      else body = '<div class="message">수집한 기사 근거가 없습니다. 검색 결과가 없거나 기간·출처 조건에 맞는 기사가 없을 수 있습니다.</div>';
      const checked = cached?.evidence?.created_at ? ` · 뉴스 근거 ${fmt(cached.evidence.created_at)}` : '';
      return `<article class="debate">
        <div class="debate-head"><div><h2>토론 ${escapeHtml(debate.debate_id)}</h2><div class="meta">${escapeHtml(debate.trigger || '토론')} · 시작 ${fmt(debate.created_at)}${checked}</div></div><span class="badge ${statusClass}">${escapeHtml(newsStatus === 'no_evidence' ? '근거 대기' : newsStatus === 'pending' ? titleForStatus(debate.status) : `뉴스 ${newsStatus}`)}</span></div>
        ${body}
      </article>`;
    }).join('');
    el('debates').innerHTML = items || '<div class="empty">이 계정의 토론 기록이 없습니다. 뉴스는 토론 실행 시 함께 수집됩니다.</div>';
    const newsCount = debates.reduce((sum, debate) => sum + (state.events.get(debate.debate_id)?.evidence?.payload?.web_news?.length || 0), 0);
    el('debate-count').textContent = `${debates.length}건`;
    el('news-count').textContent = `${newsCount}건`;
    el('last-check').textContent = fmt(checkedAt);
    el('updated').textContent = `마지막 API 확인 ${fmt(checkedAt)} · ${POLL_MS / 1000}초마다 자동 갱신`;
  }

  async function refresh() {
    if (state.inFlight) return;
    state.inFlight = true;
    const connection = el('connection');
    connection.className = 'status';
    connection.textContent = '뉴스 API 확인 중';
    try {
      const result = await getJson(`${API}/debates?limit=${MAX_DEBATES}`);
      const debates = (result.debates || []).slice(0, MAX_DEBATES);
      await Promise.all(debates.map(async debate => {
        try { await loadEvents(debate); }
        catch (error) { state.errors.set(debate.debate_id, error.message || '토론 이벤트를 불러오지 못했습니다.'); }
      }));
      const hasNews = debates.some(debate => (state.events.get(debate.debate_id)?.evidence?.payload?.web_news || []).length);
      connection.className = `status ${hasNews ? 'ok' : ''}`;
      connection.textContent = hasNews ? '뉴스 수신 확인' : 'API 연결됨 · 뉴스 대기';
      render(debates, new Date().toISOString());
    } catch (error) {
      connection.className = 'status bad';
      connection.textContent = 'API 연결 확인 필요';
      el('debates').innerHTML = `<div class="error">${escapeHtml(error.message || '뉴스 API에 연결하지 못했습니다.')}</div>`;
      el('debate-count').textContent = '—';
      el('news-count').textContent = '—';
      el('last-check').textContent = fmt(new Date().toISOString());
    } finally {
      state.inFlight = false;
      if (state.running) state.timer = setTimeout(refresh, POLL_MS);
    }
  }

  el('refresh').addEventListener('click', () => { clearTimeout(state.timer); refresh(); });
  state.running = true;
  refresh();
  window.addEventListener('pagehide', () => { state.running = false; clearTimeout(state.timer); });
})();
