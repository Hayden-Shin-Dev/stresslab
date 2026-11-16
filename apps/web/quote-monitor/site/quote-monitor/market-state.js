const API = 'https://ca-marketstate-whatif-dev.proudfield-489f3ad8.koreacentral.azurecontainerapps.io/market-state';
const el = id => document.getElementById(id);
let socket, timer, running = true, generation = 0, received = 0, duplicates = 0, older = 0, snap, browserAt, source;
const seen = new Set();
const time = v => v ? new Date(v).toLocaleString('ko-KR', {timeZone: 'Asia/Seoul', hour12: false}) : '미확인';
const num = (v, d = 2) => v == null ? '계산 불가' : Number(v).toLocaleString('ko-KR', {maximumFractionDigits: d});
const yes = v => v == null ? '판정 불가' : v ? '예' : '아니요';
function rows(id, list) {
  el(id).replaceChildren(...list.map(cells => {
    const tr = document.createElement('tr');
    for (const c of cells) { const td = document.createElement('td'); if (c && c.cls) { td.className = c.cls; td.textContent = c.t; } else td.textContent = c; tr.append(td); }
    return tr;
  }));
}
function accept(s, from) {
  if (!s || s.record_type !== 'market_state_snapshot' || s.is_mock !== false) return;
  received++;
  if (seen.has(s.snapshot_id)) { duplicates++; render(); return; }
  if (snap && Date.parse(s.as_of) <= Date.parse(snap.as_of)) { older++; render(); return; }
  seen.add(s.snapshot_id); snap = s; browserAt = new Date().toISOString(); source = from;
  render();
}
function render() {
  el('ms-counts').textContent = `수신 ${received}건 / 중복 ${duplicates}건 / 이전 시각 ${older}건 / 마지막 갱신 ${time(browserAt)} (${source || '-'})`;
  if (!snap) return;
  const age = (Date.now() - Date.parse(snap.as_of)) / 1000;
  rows('meta', [
    ['snapshot_id', snap.snapshot_id], ['기준 시각 (as_of)', time(snap.as_of)], ['계산 시각', time(snap.computed_at)],
    ['화면 수신', time(browserAt)], ['기준 시각 경과 초', age.toFixed(0)], ['품질 상태', snap.quality_status],
    ['연결 상태', snap.connection_status], ['세션 인증', yes(snap.session_verified)], ['장 구분', snap.market_phase],
    ['계산 종목 / 전체', `${snap.valid_asset_count} / ${snap.expected_asset_count}`], ['종목 범위', snap.universe_id],
  ]);
  const m = snap.market || {};
  rows('market', [
    ['최근 5분 방향', m.recent_direction], ['최근 5분 평균 등락률 %', num(m.mean_return_5m_pct, 3)],
    ['하락 종목 비율', num(snap.declining_ratio, 3)], ['전일 종가 대비 평균 %', num(m.mean_return_since_previous_close_pct, 3)],
    ['오늘 시가 대비 평균 %', num(m.mean_return_since_open_pct, 3)], ['60분 종목 간 동조화', num(m.mean_correlation_60m, 4)],
    ['60분 동반 하락 비율', num(m.joint_down_ratio_60m, 3)], ['업종 분류 비율', num(m.sector_classification_coverage, 2)],
  ]);
  rows('signals', (snap.signals || []).map(s => [s.kind, num(s.value, 3), s.threshold, s.triggered ? {t: '발생', cls: 'on'} : yes(s.triggered)]));
  rows('sectors', (snap.sectors || []).map(s => [s.sector_id, `${s.valid_asset_count}/${s.expected_asset_count}`, num(s.mean_return_5m_pct, 3), num(s.declining_ratio, 3), s.recent_direction]));
  rows('assets', [...(snap.assets || [])].sort((a, b) => a.asset_id.localeCompare(b.asset_id)).map(a => [
    a.asset_id, a.sector_id ?? '미분류', num(a.return_since_previous_close_pct), num(a.return_since_open_pct), num(a.return_5m_pct, 3),
    num(a.volatility_30m_pct, 3), num(a.volume_since_open, 0), yes(a.complete_since_open)]));
}
async function connect(g) {
  if (!running || generation !== g) return;
  el('ms-state').textContent = '연결 중';
  try {
    const r = await fetch(`${API}/negotiate`, {method: 'POST', cache: 'no-store'});
    if (!r.ok) throw new Error(`연결 주소 발급 실패 (${r.status})`);
    const {url} = await r.json();
    if (!running || generation !== g) return;
    socket = new WebSocket(url);
    socket.onopen = async () => {
      el('ms-state').textContent = '연결됨';
      // 접속 직후 현재값을 먼저 채웁니다. 이후 값은 Web PubSub으로만 받습니다.
      try { const c = await fetch(`${API}/current`, {cache: 'no-store'}); if (c.ok) accept((await c.json()).snapshot, '현재값 조회'); } catch {}
    };
    socket.onmessage = ({data}) => {
      try { accept(JSON.parse(data), 'Web PubSub'); el('ms-state').textContent = '연결됨'; }
      catch { el('ms-state').textContent = '수신 메시지 형식 확인 필요'; }
    };
    socket.onclose = () => { if (running && generation === g) { el('ms-state').textContent = '재연결 중'; timer = setTimeout(() => connect(g), 3000); } };
    socket.onerror = () => { el('ms-state').textContent = 'WebSocket 연결 오류'; };
  } catch (e) {
    if (running && generation === g) { el('ms-state').textContent = `재연결 중 (${e.message})`; timer = setTimeout(() => connect(g), 5000); }
  }
}
connect(generation);
window.addEventListener('pagehide', () => { running = false; generation++; clearTimeout(timer); if (socket) { socket.onclose = null; socket.close(); } });
// 경과 초 표시만 갱신합니다. 조회하지 않습니다.
setInterval(render, 1000);
