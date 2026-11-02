const el = id => document.getElementById(id);
const quotes = new Map(), seen = new Set();
let socket, timer, running = false, generation = 0, received = 0, duplicates = 0, older = 0, lastMessage;
const time = value => value ? new Date(value).toLocaleString('ko-KR', {timeZone: 'Asia/Seoul', hour12: false}) : '미확인';
const number = value => value == null ? '미확인' : Number(value).toLocaleString('ko-KR');
function render() {
  el('rows').replaceChildren();
  for (const [, q] of [...quotes].sort(([a], [b]) => a.localeCompare(b))) {
    const age = q.event_time ? (Date.now() - Date.parse(q.event_time)) / 1000 : null;
    const tr = document.createElement('tr');
    for (const value of [q.asset_id, `${q.venue} / ${q.session}`, number(q.price), number(q.trade_volume), number(q.cumulative_volume), time(q.event_time), time(q.received_at), time(q.browser_at), age == null ? '미확인' : age < 0 ? '시각 확인 필요' : age.toFixed(1), q.date_inferred ? '예' : '아니요']) {
      const td = document.createElement('td'); td.textContent = value; tr.append(td);
    }
    el('rows').append(tr);
  }
  el('counts').textContent = `수신 ${received}건 / 중복 ${duplicates}건 / 이전 체결 ${older}건 / 마지막 수신 ${time(lastMessage)}`;
}
async function connect(g) {
  if (!running || generation !== g) return;
  el('state').textContent = '연결 중';
  try {
    const endpoint = 'https://func-whatif-dev-h6a0ebd4c6duhzg2.koreacentral-01.azurewebsites.net/api/quotes/negotiate';
    const response = await fetch(endpoint, {method: 'POST', cache: 'no-store'});
    if (!response.ok) throw new Error(`연결 인증 실패 (${response.status})`);
    const {url} = await response.json();
    if (!running || generation !== g) return;
    socket = new WebSocket(url);
    socket.onopen = () => { el('state').textContent = '연결됨'; };
    socket.onmessage = ({data}) => {
      try {
        const message = JSON.parse(data);
        for (const q of (message.type === 'quote_batch' ? message.quotes : [message])) {
        if (q.record_type !== 'quote_event' || q.is_mock !== false) continue;
        received++; lastMessage = new Date().toISOString();
        if (seen.has(q.event_id)) { duplicates++; continue; }
        seen.add(q.event_id);
        if (seen.size > 20000) seen.delete(seen.values().next().value);
        const id = `${q.asset_id}:${q.venue}`, prev = quotes.get(id);
        if (prev?.event_time && (!q.event_time || Date.parse(q.event_time) < Date.parse(prev.event_time))) { older++; continue; }
        quotes.set(id, {...q, browser_at: lastMessage});
        }
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
