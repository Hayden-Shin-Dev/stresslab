const el = id => document.getElementById(id);
const quotes = new Map(), seen = new Set();
let socket, timer, running = false, generation = 0, received = 0, duplicates = 0, older = 0, lastMessage;
const time = value => value ? new Date(value).toLocaleString('ko-KR', {timeZone: 'Asia/Seoul', hour12: false}) : '미확인';
const number = value => value == null ? '미확인' : Number(value).toLocaleString('ko-KR');
// 2026-11-11 민철 수정: 연결 인증과 현재값은 APIM -> 공통 API로 요청합니다.
const host = '/api/quotes';
function accept(list, live) {
  for (const q of list) {
    if (!['quote_event', 'quote_latest'].includes(q.record_type) || q.is_mock !== false) continue;
    if (live) { received++; lastMessage = new Date().toISOString(); }
    const prev = quotes.get(q.asset_id);
    const stamp = item => Date.parse(item?.event_time || item?.received_at || '') || 0;
    if (prev && stamp(q) < stamp(prev)) { if (live) older++; continue; }
    if (prev?.event_id && prev.event_id === q.event_id) { if (live) duplicates++; continue; }
    quotes.set(q.asset_id, {...q, browser_at: new Date().toISOString()});
  }
  render();
}
async function snapshot(g) {
  try {
    const response = await fetch(`${host}/latest`, {cache:'no-store'});
    if (!response.ok) throw new Error('snapshot');
    const data = await response.json();
    if (running && generation === g) accept(data.quotes, false);
  } catch { if (!quotes.size) el('state').textContent = '현재가 불러오기 실패'; }
}
function render() {
  el('rows').replaceChildren();
  for (const [, q] of [...quotes].sort(([a], [b]) => a.localeCompare(b))) {
    const age = q.event_time ? (Date.now() - Date.parse(q.event_time)) / 1000 : null;
    const tr = document.createElement('tr');
    for (const value of [q.asset_id, `${q.venue} / ${q.session}`, number(q.price), number(q.trade_volume), number(q.cumulative_volume), time(q.event_time), time(q.received_at), time(q.browser_at), age == null ? '미확인' : age < 0 ? '시각 확인 필요' : age.toFixed(1), q.date_inferred == null ? '미확인' : q.date_inferred ? '예' : '아니요']) {
      const td = document.createElement('td'); td.textContent = value; tr.append(td);
    }
    el('rows').append(tr);
  }
  el('counts').textContent = `수신 ${received}건 / 중복 ${duplicates}건 / 이전 체결 ${older}건 / 마지막 수신 ${time(lastMessage)}`;
}
async function connect(g) {
  if (!running || generation !== g) return;
  el('state').textContent = '연결 중';
  snapshot(g);
  try {
    const endpoint = `${host}/negotiate`;
    const response = await fetch(endpoint, {method: 'POST', cache: 'no-store'});
    if (!response.ok) throw new Error(`연결 인증 실패 (${response.status})`);
    const {url} = await response.json();
    if (!running || generation !== g) return;
    socket = new WebSocket(url);
    socket.onopen = () => { el('state').textContent = '연결됨'; snapshot(g); };
    socket.onmessage = ({data}) => {
      try {
        const message = JSON.parse(data);
        accept(message.type === 'quote_batch' ? message.quotes : [message], true);
        el('state').textContent = '연결됨';
        render();
      } catch { el('state').textContent = '수신 메시지 형식 확인 필요'; }
    };
    socket.onclose = () => {
      if (running && generation === g) {
        el('state').textContent = '재연결 중';
        timer = setTimeout(() => connect(g), 3000);
      }
    };
    socket.onerror = () => { el('state').textContent = 'WebSocket 연결 오류'; };
  } catch (error) {
    if (generation === g && running) {
      el('state').textContent = '재연결 중';
      timer = setTimeout(() => connect(g), 5000);
    }
  }
}
function stop() { running = false; generation++; clearTimeout(timer); if (socket) { socket.onclose = null; socket.close(); } }
running = true;
connect(generation);
window.addEventListener('pagehide', stop);
// This timer updates age labels only. It does not fetch quotes.
setInterval(render, 1000);
