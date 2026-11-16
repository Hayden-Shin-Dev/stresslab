// 내 보유 종목 화면. Static Web Apps 로그인 + 연결된 토론 API(/api/me/holdings)를 씁니다.
// 같은 주소(/api)로 부르므로 CORS 설정이 필요 없고, 로그인 정보는 SWA가 API로 넘겨 줍니다.
export function mountHoldings(root, onChange = () => {}) {
let active = true;
let loaded = false;
const controller = new AbortController();
root.innerHTML = `<p class="service-note">저장하면 계정의 보유 종목 목록 전체가 변경됩니다.</p>
<table><thead><tr><th style="width:40%">종목</th><th style="width:45%">보유 금액(원)</th><th></th></tr></thead>
<tbody id="rows"></tbody><tfoot><tr><th>합계</th><th id="total" class="num">0</th><th></th></tr></tfoot></table>
<button id="add" type="button" disabled>종목 추가</button> <button id="save" type="button" disabled>저장</button>
<button id="retry" type="button" hidden>다시 불러오기</button><div id="msg" role="status" aria-live="polite"></div>`;
const el = id => root.querySelector('#' + id);

// 선택할 수 있는 종목: 시장 상태·스트레스 분석 대상(코스피 시가총액 상위 20, kospi_market_cap_top20_20261030).
// 대상이 바뀌면 이 목록과 API의 ALLOWED_ASSETS를 같이 바꿉니다.
const ASSETS = [
  ['005930', '삼성전자'], ['000660', 'SK하이닉스'], ['373220', 'LG에너지솔루션'], ['207940', '삼성바이오로직스'],
  ['005380', '현대차'], ['005935', '삼성전자우'], ['000270', '기아'], ['068270', '셀트리온'],
  ['105560', 'KB금융'], ['012450', '한화에어로스페이스'], ['034020', '두산에너빌리티'], ['055550', '신한지주'],
  ['028260', '삼성물산'], ['012330', '현대모비스'], ['402340', 'SK스퀘어'], ['032830', '삼성생명'],
  ['086790', '하나금융지주'], ['006400', '삼성SDI'], ['009150', '삼성전기'], ['034730', 'SK'],
];
const NAME = Object.fromEntries(ASSETS);
const won = v => Number(v || 0).toLocaleString('ko-KR');

function msg(text, cls = '') { el('msg').textContent = text; el('msg').className = cls; }

function addRow(assetId = '', amount = '') {
  const tr = document.createElement('tr');
  const code = Object.assign(document.createElement('select'), {ariaLabel: '종목'});
  code.append(new Option('종목 선택', ''));
  for (const [id, name] of ASSETS) code.append(new Option(`${name} (${id})`, id));
  if (assetId && !NAME[assetId]) code.append(new Option(`${assetId} (대상 밖)`, assetId));
  code.value = assetId;
  code.addEventListener('change', syncOptions);
  const amt = Object.assign(document.createElement('input'),
    {value: amount === '' ? '' : won(amount), placeholder: '예: 5,000,000', inputMode: 'numeric', ariaLabel: '보유 금액(원)'});
  amt.className = 'num';
  amt.addEventListener('input', () => {
    const digits = amt.value.replace(/[^0-9]/g, '');
    amt.value = digits ? won(digits) : '';
    total();
  });
  const del = Object.assign(document.createElement('button'), {type: 'button', textContent: '삭제'});
  del.addEventListener('click', () => { tr.remove(); total(); syncOptions(); });
  for (const node of [code, amt, del]) { const td = document.createElement('td'); td.append(node); tr.append(td); }
  el('rows').append(tr);
  syncOptions();
}

// 다른 줄에서 이미 고른 종목은 선택할 수 없게 합니다(중복 저장 방지).
function syncOptions() {
  const selects = [...el('rows').querySelectorAll('select')];
  const used = new Set(selects.map(s => s.value).filter(Boolean));
  for (const s of selects) for (const o of s.options) o.disabled = !!o.value && o.value !== s.value && used.has(o.value);
}

function read() {
  return [...el('rows').children].map(tr => {
    const code = tr.querySelector('select'), amt = tr.querySelector('input');
    return {asset_id: code.value, amount_krw: Number(amt.value.replace(/[^0-9]/g, ''))};
  }).filter(h => h.asset_id || h.amount_krw);
}

function total() { el('total').textContent = won(read().reduce((s, h) => s + (h.amount_krw || 0), 0)); }

function show(data) {
  if (!Array.isArray(data.holdings)) throw new Error('보유 종목 응답을 확인할 수 없습니다.');
  onChange(data.holdings);
  el('rows').replaceChildren();
  for (const h of data.holdings) addRow(h.asset_id, h.amount_krw);
  if (!data.holdings.length) addRow();
  total();
}

async function api(path, options = {}) {
  const res = await fetch('/api' + path, {credentials: 'same-origin', signal: controller.signal, headers: {'Content-Type': 'application/json'}, ...options});
  const body = await res.json().catch(() => ({}));
  if (res.status === 401 || res.redirected) {
    location.assign('/login?returnTo=%2Fapp%2Fportfolio');
    throw new Error('다시 로그인해 주세요.');
  }
  if (!res.ok) {
    const d = body.detail;
    const detail = typeof d === 'string' ? d : d && d.errors ? `${d.message}\n${d.errors.join('\n')}`
      : Array.isArray(d) ? d.map(e => e.msg).join('\n') : `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return body;
}

async function start() {
  el('save').disabled = true;
  el('add').disabled = true;
  el('retry').hidden = true;
  msg('보유 종목을 불러오는 중입니다.');
  try {
    const data = await api('/me/holdings');
    if (!active) return;
    show(data);
    loaded = true;
    el('save').disabled = false;
    el('add').disabled = false;
    msg('');
  } catch (e) {
    if (!active) return;
    loaded = false;
    msg('보유 종목을 불러오지 못했습니다: ' + e.message, 'err');
    el('retry').hidden = false;
  }
}

el('retry').addEventListener('click', start);
el('add').addEventListener('click', () => addRow());
el('save').addEventListener('click', async () => {
  if (!loaded) return;
  const holdings = read();
  const bad = holdings.find(h => !/^[0-9A-Z]{6}$/.test(h.asset_id) || !(h.amount_krw > 0));
  if (bad) { msg('각 줄에서 종목을 고르고 금액을 0보다 크게 넣어 주세요.', 'err'); return; }
  el('save').disabled = true;
  try {
    const data = await api('/me/holdings', {method: 'PUT', body: JSON.stringify({holdings})});
    if (!active) return;
    show(data);
    msg(`저장했습니다 (${holdings.length}종목).`, 'ok');
  } catch (e) {
    if (active) msg(e.message, 'err');
  } finally {
    if (active) el('save').disabled = false;
  }
});

start();
return () => { active = false; controller.abort(); };
}
