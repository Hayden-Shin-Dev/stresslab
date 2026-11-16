/* Renders the shared live market feed on the existing diagnostic route. */
const el = id => document.getElementById(id);
let snap = window.WHATIF_MARKET_STATE || null;
let delivery = window.WHATIF_MARKET_DELIVERY || {};
let lastRenderedSnapshotId = null;
const time = value => value ? new Date(value).toLocaleString('ko-KR', {timeZone: 'Asia/Seoul', hour12: false}) : '미확인';
const num = (value, digits = 2) => value == null || !Number.isFinite(Number(value)) ? '계산 불가' : Number(value).toLocaleString('ko-KR', {maximumFractionDigits: digits});
const yes = value => value == null ? '판정 불가' : value ? '예' : '아니요';
function rows(id, list) {
  const target = el(id);
  if (!target) return;
  target.replaceChildren(...list.map(cells => {
    const tr = document.createElement('tr');
    for (const cell of cells) {
      const td = document.createElement('td');
      if (cell && typeof cell === 'object' && 't' in cell) {
        td.className = cell.cls || '';
        td.textContent = cell.t;
      } else td.textContent = cell == null ? '미확인' : String(cell);
      tr.append(td);
    }
    return tr;
  }));
}
function render() {
  const status = el('ms-state');
  const stamp = snap && (snap.last_event_time || snap.last_completed_bar_end || snap.as_of);
  const stampMs = stamp && Number.isFinite(Date.parse(stamp)) ? Date.parse(stamp) : null;
  const ageSeconds = stampMs == null ? null : Math.max(0, Math.floor((Date.now() - stampMs) / 1000));
  const stale = ageSeconds == null || ageSeconds > 120;
  const websocket = delivery.websocket_status || 'disconnected';
  const connected = websocket === 'connected';

  if (status) {
    if (!snap) status.textContent = delivery.error || (websocket === 'connecting' ? '실시간 데이터 연결 중' : '실시간 데이터 수신 대기');
    else if (connected && !stale) status.textContent = '실시간 스트림 연결됨 · 최신 시장값 수신 중';
    else if (connected && stale) status.textContent = '스트림 연결됨 · 원본 데이터 갱신 지연';
    else if (delivery.last_poll_ok && !stale) status.textContent = '현재값 조회 가능 · 실시간 스트림 재연결 중';
    else if (delivery.last_poll_ok && stale) status.textContent = '스냅샷 조회됨 · 데이터 갱신 지연';
    else status.textContent = delivery.error || '실시간 연결을 확인하고 있습니다.';
    status.className = `ms-state ${!snap || (!connected && !delivery.last_poll_ok) ? 'is-offline' : stale ? 'is-stale' : 'is-live'}`;
  }

  const assets = snap?.assets || [];
  const complete = assets.filter(asset => asset.complete_since_open === true).length;
  const age = ageSeconds == null ? '기준 시각 미확인' : `기준값 ${ageSeconds}초 전`;
  const lastCheck = delivery.last_poll_at ? ` · API 확인 ${time(delivery.last_poll_at)}` : '';
  const lastStream = delivery.last_message_at ? ` · 스트림 메시지 ${time(delivery.last_message_at)}` : '';
  const counts = el('ms-counts');
  if (counts) {
    counts.textContent = snap
      ? `${snap.valid_asset_count ?? assets.length}/${snap.expected_asset_count ?? assets.length}종목 · 시가 이후 완전 ${complete}/${assets.length} · ${snap.quality_status === 'partial' ? '일부 지표 미완전' : snap.quality_status || '품질 미확인'} · 원본 기준 ${time(stamp)} · ${age}${lastCheck}${lastStream}`
      : '실제 시장 스냅샷 수신을 기다리고 있습니다. 모의 데이터는 표시하지 않습니다.';
  }

  if (!snap) return;
  const newSnapshot = snap.snapshot_id !== lastRenderedSnapshotId;
  if (!newSnapshot) return;
  lastRenderedSnapshotId = snap.snapshot_id;
  rows('meta', [
    ['snapshot_id', snap.snapshot_id], ['원본 기준 시각', time(stamp)], ['계산 시각', time(snap.computed_at)],
    ['기준값 경과 초', ageSeconds == null ? '미확인' : ageSeconds], ['화면 수신 경로', delivery.source || '확인 중'],
    ['스냅샷 품질', snap.quality_status], ['연결 상태', snap.connection_status],
    ['세션 확인', yes(snap.session_verified)], ['장 구분', snap.market_phase],
    ['계산 종목 / 전체', `${snap.valid_asset_count} / ${snap.expected_asset_count}`], ['종목 범위', snap.universe_id],
    ['데이터 제공자', snap.source],
  ]);
  const market = snap.market || {};
  rows('market', [
    ['최근 5분 방향', market.recent_direction], ['최근 5분 평균 등락률 %', num(market.mean_return_5m_pct, 3)],
    ['하락 종목 비율', num(snap.declining_ratio, 3)], ['전일 종가 대비 평균 %', num(market.mean_return_since_previous_close_pct, 3)],
    ['오늘 시가 대비 평균 %', num(market.mean_return_since_open_pct, 3)], ['60분 종목 간 동조화', num(market.mean_correlation_60m, 4)],
    ['60분 동반 하락 비율', num(market.joint_down_ratio_60m, 3)], ['업종 분류 비율', num(market.sector_classification_coverage, 2)],
  ]);
  rows('signals', (snap.signals || []).map(signal => [signal.kind, num(signal.value, 3), signal.threshold, signal.triggered ? {t: '발생', cls: 'on'} : yes(signal.triggered)]));
  rows('sectors', (snap.sectors || []).map(sector => [sector.sector_id, `${sector.valid_asset_count}/${sector.expected_asset_count}`, num(sector.mean_return_5m_pct, 3), num(sector.declining_ratio, 3), sector.recent_direction]));
  rows('assets', [...assets].sort((a, b) => a.asset_id.localeCompare(b.asset_id)).map(asset => [
    asset.asset_id, asset.sector_id ?? '미분류', num(asset.return_since_previous_close_pct), num(asset.return_since_open_pct), num(asset.return_5m_pct, 3),
    num(asset.volatility_30m_pct, 3), num(asset.volume_since_open, 0), yes(asset.complete_since_open),
  ]));
}

document.addEventListener('whatif:market-state-updated', event => {
  snap = event.detail?.snapshot || window.WHATIF_MARKET_STATE || null;
  delivery = event.detail?.delivery || window.WHATIF_MARKET_DELIVERY || {};
  render();
});
el('ms-refresh')?.addEventListener('click', event => {
  const button = event.currentTarget;
  button.disabled = true;
  button.textContent = '조회 중';
  document.dispatchEvent(new Event('whatif:market-state-refresh'));
  window.setTimeout(() => { button.disabled = false; button.textContent = '지금 새로고침'; }, 1200);
});
render();
window.setInterval(() => {
  delivery = window.WHATIF_MARKET_DELIVERY || delivery;
  render();
}, 1000);
