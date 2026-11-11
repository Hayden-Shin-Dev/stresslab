// 내 보유 종목 화면. Static Web Apps 로그인 + 연결된 토론 API(/api/me/holdings)를 씁니다.
// 같은 주소(/api)로 부르므로 CORS 설정이 필요 없고, 로그인 정보는 SWA가 API로 넘겨 줍니다.
const el = id => document.getElementById(id);

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
const AFTER_SAVE = '/';   // 저장하면 돌아갈 화면 (실시간 시장 화면)
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
  el('rows').replaceChildren();
  for (const h of data.holdings) addRow(h.asset_id, h.amount_krw);
  if (!data.holdings.length) addRow();
  total();
}

async function api(path, options = {}) {
  const res = await fetch('/api' + path, {headers: {'Content-Type': 'application/json'}, ...options});
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = body.detail;
    const detail = typeof d === 'string' ? d : d && d.errors ? `${d.message}\n${d.errors.join('\n')}`
      : Array.isArray(d) ? d.map(e => e.msg).join('\n') : `HTTP ${res.status}`;
    throw new Error(detail);
  }
  return body;
}

async function start() {
  try {
    const me = await (await fetch('/.auth/me')).json();
    const p = me.clientPrincipal;
    el('who').textContent = p ? `${p.userDetails} (${p.identityProvider})` : '로그인 안 됨';
    if (!p) { location.href = '/.auth/login/aad?post_login_redirect_uri=/holdings.html'; return; }
    show(await api('/me/holdings'));
    msg('');
  } catch (e) {
    msg('보유 종목을 불러오지 못했습니다: ' + e.message, 'err');
    if (!el('rows').children.length) addRow();
  }
}

el('add').addEventListener('click', () => addRow());
el('save').addEventListener('click', async () => {
  const holdings = read();
  const bad = holdings.find(h => !/^[0-9A-Z]{6}$/.test(h.asset_id) || !(h.amount_krw > 0));
  if (bad) { msg('각 줄에서 종목을 고르고 금액을 0보다 크게 넣어 주세요.', 'err'); return; }
  el('save').disabled = true;
  try {
    show(await api('/me/holdings', {method: 'PUT', body: JSON.stringify({holdings})}));
    msg(`저장했습니다 (${holdings.length}종목). 잠시 후 시장 화면으로 이동합니다.`, 'ok');
    setTimeout(() => { location.href = AFTER_SAVE; }, 1200);
  } catch (e) {
    msg(e.message, 'err');
  } finally {
    el('save').disabled = false;
  }
});

start();
