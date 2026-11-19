(() => {
  'use strict';
  const API = '/api';
  const POLL_MS = 15_000;
  const state = { debateId: '', socket: null, cursor: 0, seen: new Set(), reconnectTimer: null, pollTimer: null, pollInFlight: false };
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date = value => {
    if (!value) return '시각 미확인';
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? '시각 미확인' : parsed.toLocaleString('ko-KR', {timeZone:'Asia/Seoul', hour12:false});
  };

  async function json(path) {
    const response = await fetch(path, {cache:'no-store', credentials:'same-origin'});
    const type = response.headers.get('content-type') || '';
    if (response.redirected && /login/i.test(new URL(response.url).pathname)) throw new Error('로그인이 필요합니다. Google 로그인 후 다시 시도하세요.');
    if (!response.ok) throw new Error(`API 요청 실패 (${response.status})`);
    if (!type.includes('application/json')) throw new Error('API가 JSON 대신 HTML을 반환했습니다. 로그인과 API 연결을 확인하세요.');
    return response.json();
  }

  function chip(id, text, kind='') { const node=el(id); node.textContent=text; node.className=`chip ${kind}`.trim(); }
  function renderEvent(event, source) {
    if (!event || (!event.event_id && !event.seq)) return;
    const key=event.event_id || `${event.debate_id}:${event.seq}`;
    if (state.seen.has(key)) return;
    state.seen.add(key);
    const wrap=document.createElement('article'); wrap.className='event';
    const head=document.createElement('div'); head.className='event-head';
    const name=document.createElement('span'); name.className='event-type'; name.textContent=event.type || '이벤트';
    const time=document.createElement('span'); time.textContent=`${source} · #${event.seq ?? '?'} · ${date(event.created_at)}`;
    const body=document.createElement('pre'); body.textContent=JSON.stringify(event.payload || {}, null, 2);
    head.append(name,time); wrap.append(head,body);
    const container=el('events');
    const empty=container.querySelector('.empty'); if (empty) empty.remove();
    container.prepend(wrap);
    el('event-count').textContent=String(state.seen.size);
    if (Number.isFinite(event.seq)) state.cursor=Math.max(state.cursor,event.seq);
  }

  async function replay() {
    if (!state.debateId || state.pollInFlight) return;
    state.pollInFlight=true;
    try {
      const result=await json(`${API}/debates/${encodeURIComponent(state.debateId)}/events?after_seq=${state.cursor}&limit=500`);
      for (const event of result.events || []) renderEvent(event,'API 재생');
      chip('api-state','이벤트 API 연결됨','ok');
    } catch (error) { chip('api-state',error.message || '이벤트 API 실패','bad'); }
    finally {
      state.pollInFlight=false;
      clearTimeout(state.pollTimer);
      state.pollTimer=setTimeout(replay,POLL_MS);
    }
  }

  function closeSocket() {
    clearTimeout(state.reconnectTimer);
    if (state.socket) { state.socket.onclose=null; state.socket.close(); state.socket=null; }
  }

  async function connectSocket() {
    if (!state.debateId) return;
    closeSocket(); chip('socket-state','WebSocket 연결 중');
    try {
      const result=await json(`${API}/debates/${encodeURIComponent(state.debateId)}/negotiate`);
      if (!result.url) throw new Error('실시간 연결 주소가 없습니다.');
      const socket=new WebSocket(result.url); state.socket=socket;
      socket.onopen=()=>{ if(state.socket===socket) chip('socket-state','WebSocket 연결됨','ok'); };
      socket.onmessage=message=>{
        try { const event=JSON.parse(message.data); if(event.debate_id===state.debateId) renderEvent(event,'WebSocket'); }
        catch { chip('socket-state','메시지 해석 오류','bad'); }
      };
      socket.onerror=()=>{ if(state.socket===socket) chip('socket-state','WebSocket 오류','bad'); };
      socket.onclose=()=>{
        if(state.socket!==socket || !state.debateId) return;
        chip('socket-state','재연결 대기');
        state.reconnectTimer=setTimeout(connectSocket,3000);
      };
    } catch (error) {
      chip('socket-state',error.message || 'WebSocket 연결 실패','bad');
      state.reconnectTimer=setTimeout(connectSocket,5000);
    }
  }

  async function connectSelected() {
    const id=el('debate-select').value;
    if (!id) { chip('debate-state','토론 미선택'); return; }
    state.debateId=id; state.cursor=0; state.seen.clear();
    clearTimeout(state.pollTimer); closeSocket();
    el('events').innerHTML='<div class="empty">토론 이벤트를 불러오는 중입니다.</div>';
    el('event-count').textContent='0';
    chip('debate-state',id);
    try {
      const status=await json(`${API}/debates/${encodeURIComponent(id)}`);
      el('status-detail').textContent=`상태 ${status.status || '미확인'} · 생성 ${date(status.created_at)} · 마지막 변경 ${date(status.updated_at)} · run_id ${status.run_id || '—'}`;
    } catch (error) { el('status-detail').textContent=error.message || '토론 상태를 불러오지 못했습니다.'; }
    await replay();
    await connectSocket();
  }

  async function loadDebates() {
    chip('api-state','토론 목록 확인 중');
    try {
      const result=await json(`${API}/debates?limit=30`);
      const select=el('debate-select'), previous=select.value;
      select.replaceChildren();
      for (const debate of result.debates || []) {
        const option=document.createElement('option'); option.value=debate.debate_id;
        option.textContent=`${debate.debate_id} · ${debate.status || '상태 미확인'} · ${date(debate.created_at)}`;
        select.append(option);
      }
      if (!select.options.length) {
        const option=document.createElement('option'); option.value=''; option.textContent='토론 기록이 없습니다'; select.append(option);
        chip('api-state','API 연결됨 · 토론 없음','ok');
        el('status-detail').textContent='토론 기록이 없습니다. 기존 분석 화면에서 토론을 시작한 뒤 다시 불러오세요.';
        return;
      }
      if ([...select.options].some(option=>option.value===previous)) select.value=previous;
      chip('api-state',`API 연결됨 · 토론 ${select.options.length}건`,'ok');
    } catch (error) {
      chip('api-state','토론 API 연결 실패','bad');
      el('status-detail').textContent=error.message || '토론 목록을 불러오지 못했습니다.';
      el('debate-select').innerHTML='<option value="">로그인 또는 API 연결을 확인하세요</option>';
    }
  }

  el('connect').addEventListener('click',connectSelected);
  el('reload').addEventListener('click',loadDebates);
  window.addEventListener('pagehide',()=>{closeSocket();clearTimeout(state.pollTimer);});
  loadDebates();
})();
