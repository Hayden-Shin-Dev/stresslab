// 2026-11-11 민철 추가: 기존 배포 모델을 공통 API에서 호출합니다. 브라우저에 키를 두지 않습니다.
const el = id => document.getElementById(id);
const names = {'005930':'삼성전자','000660':'SK하이닉스','207940':'삼성바이오로직스','005380':'현대차','005935':'삼성전자우','000270':'기아','068270':'셀트리온','105560':'KB금융','012450':'한화에어로스페이스','034020':'두산에너빌리티','055550':'신한지주','028260':'삼성물산','012330':'현대모비스','032830':'삼성생명','086790':'하나금융지주','006400':'삼성SDI','009150':'삼성전기','034730':'SK'};
let supported = [];
const num = (v,d=2) => Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d});
async function api(path, body) {
  const r = await fetch('/api'+path, {method:body===undefined?'GET':'POST',cache:'no-store',headers:{'Content-Type':'application/json'}, ...(body===undefined?{}:{body:JSON.stringify(body)})});
  if (r.redirected || r.status===401) { location.href='/login.html?next=/stress.html'; throw Error('로그인이 필요합니다.'); }
  if (!(r.headers.get('content-type')||'').includes('application/json')) throw Error(`API 응답을 확인하세요 (${r.status}).`);
  const j=await r.json(); if (!r.ok) throw Error(typeof j.detail==='string'?j.detail:JSON.stringify(j.detail||j)); return j;
}
function row(id='', amount=50000000) {
  if (el('positions').children.length>=20) return;
  const tr=document.createElement('tr'), select=document.createElement('select'), input=document.createElement('input'), remove=document.createElement('button');
  select.setAttribute('aria-label','종목');
  for(const a of supported) select.add(new Option(`${names[a]||a} (${a})`,a));
  if(id)select.value=id;
  input.type='number';input.min='1';input.max='10000000000000';input.step='any';input.required=true;input.value=amount;input.setAttribute('aria-label','보유 평가금액 원');
  remove.type='button';remove.textContent='삭제';remove.onclick=()=>tr.remove();
  for(const n of [select,input,remove]) {const td=document.createElement('td');td.append(n);tr.append(td);} el('positions').append(tr);
}
el('add').onclick=()=>row();
el('load').onclick=async()=>{try {
  const j=await api('/me/holdings');
  const list=j.holdings||[];
  const excluded=list.filter(x=>!supported.includes(x.asset_id));
  el('positions').replaceChildren();for(const x of list.filter(x=>supported.includes(x.asset_id))) row(x.asset_id,x.amount_krw);
  el('message').textContent=excluded.length?`현재 ML 미지원 종목은 제외했습니다: ${excluded.map(x=>x.asset_id).join(', ')}`:list.length?'불러왔습니다.':'저장한 보유 종목이 없습니다.';
}catch(e){el('message').textContent=e.message;}};
el('form').onsubmit=async e=>{e.preventDefault();el('run').disabled=true;el('result').hidden=true;el('message').textContent='계산 중';try {
  const positions=[...el('positions').children].map(tr=>({asset_id:tr.querySelector('select').value,value_krw:Number(tr.querySelector('input').value)}));
  const j=await api('/stress/analyze',{positions,model:el('model').value,shocks:{fx_pct:Number(el('fx').value),us_rate_bp:Number(el('rate').value),wti_pct:Number(el('wti').value),vix_points:Number(el('vix').value)}});
  el('results').replaceChildren();
  for(const a of j.assets){const tr=document.createElement('tr');for(const v of [names[a.asset_id]||a.asset_id,num(a.baseline_model_return_pct)+'%',num(a.scenario_return_pct)+'%',num(a.change_from_baseline_pp),num(a.hypothetical_pnl_krw,0),num(a.shock_incremental_pnl_krw,0)]){const td=document.createElement('td');td.textContent=v;tr.append(td);}el('results').append(tr);}
  el('summary').textContent=`전체 가상 손익 ${num(j.portfolio_hypothetical_pnl_krw,0)}원 / 무충격 대비 변화 ${num(j.portfolio_shock_incremental_pnl_krw,0)}원`;
  const m=j.assets[0].model_output;
  el('version').textContent=`입력 기준일 ${m.feature_as_of_trading_date} / 모델 ${j.model} / ${m.package_id} / ${m.dataset_version}`;
  el('raw').textContent=JSON.stringify(j,null,2);el('result').hidden=false;el('message').textContent='계산 완료';
  lastRun=j.ai_handoff&&j.ai_handoff.ready?j.analysis_id:null;el('debate').disabled=!lastRun;el('turns').replaceChildren();
  el('dmsg').textContent=lastRun?'':'결과 저장에 실패해 토론을 열 수 없습니다. 다시 계산하세요.';
}catch(e){el('message').textContent=e.message;}finally{el('run').disabled=false;}};
try{const m=await api('/stress/support');supported=m.supported_assets;el('support').textContent=`배포 모델 지원 ${supported.length}종목`;
  row(supported.includes('005930')?'005930':supported[0]);if(supported.includes('005380'))row('005380');el('run').disabled=false;
}catch(e){el('message').textContent=e.message;}

// 같은 분석 결과(analysis_id)로 4인 토론. 실제 화면은 Web PubSub(pubsub.url)로 받는 게 맞고, 여기서는 3초마다 이벤트를 조회합니다.
let lastRun=null, pollTimer=null;
const ROLE={macro:'김진우 · 거시경제',market:'윤서연 · 장중 시장',risk:'신강호 · 리스크',portfolio:'강유나 · 포트폴리오'};
el('debate').onclick=async()=>{if(!lastRun)return;el('debate').disabled=true;el('turns').replaceChildren();el('dmsg').textContent='토론 요청 중';
  try{const d=await api('/debates',{run_id:lastRun});el('dmsg').textContent='토론 진행 중 (1~2분)';poll(d.debate_id,0);}
  catch(e){el('dmsg').textContent=e.message;el('debate').disabled=false;}};
async function poll(id,after){clearTimeout(pollTimer);let done=false;
  try{const r=await api(`/debates/${id}/events?after_seq=${after}`);
    for(const ev of r.events||[]){after=Math.max(after,ev.seq);const p=ev.payload||{};
      if(ev.type==='message.created'||ev.type==='debate.summary'){const div=document.createElement('div'),b=document.createElement('b'),t=document.createElement('p');
        b.textContent=ev.type==='debate.summary'?'요약':`${ROLE[p.role]||p.role} · ${p.phase||''}`;t.style.whiteSpace='pre-wrap';
        t.textContent=p.display_text||p.summary_text||'';div.append(b,t);el('turns').append(div);}
      if(ev.type==='debate.completed'){done=true;el('dmsg').textContent='토론 완료';}
      if(ev.type==='debate.failed'){done=true;el('dmsg').textContent='토론 실패: '+(p.reason||'');}}
  }catch(e){el('dmsg').textContent=e.message;}
  if(done){el('debate').disabled=false;return;} pollTimer=setTimeout(()=>poll(id,after),3000);}
