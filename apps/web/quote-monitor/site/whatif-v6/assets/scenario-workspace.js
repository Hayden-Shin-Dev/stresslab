/* Replace only the scenario right-hand sources/chat group. Keep the original page intact. */
(() => {
 const legacy=window.whatIfScenarioWindow;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 window.whatIfScenarioWindow=data=>{
  const t=document.createElement('template');t.innerHTML=legacy({...data,chatMin:false});
  const take=selector=>t.content.querySelector(selector)?.outerHTML||'';
  const w=data.workspace||{},r=data.run,c=r?.conditions||{};
  const conditions=r?`5거래일 · 미국 10년 ${Number(c.rate)*100}bp · 원/달러 ${c.fx}% · WTI ${c.oil}% · VIX ${c.vix}pt`:'분석 조건을 설정하고 스트레스테스트를 실행해 주세요.';
  const chips=(w.sources||[]).map((x,i)=>`<span class="ws-chip">${x.kind==='news'&&/^https:\/\//.test(x.id)?`<a href="${esc(x.id)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>`:x.kind==='document'?`<a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${encodeURIComponent(x.id)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>`:esc(x.title)} <small>${esc(x.status||'선택됨')}</small><button type="button" data-ws="remove-source" data-index="${i}" aria-label="${esc(x.title)} 근거 선택 취소">×</button></span>`).join('');
  for(const label of t.content.querySelectorAll('.fig-shared-agent-option')){label.title=label.textContent.trim().replace(/\s+/g,' ');}
  const busy=w.busy;
  const group=t.content.querySelector('.fig-data-chat-group');
  group.outerHTML=`<section class="ws-screen ws-side-panel" aria-label="자료와 에이전트 대화">
   <header class="ws-header"><h2>자료와 에이전트 대화</h2></header>
   <div class="ws-context"><strong>${data.stressMode==='portfolio'?'나의 포트폴리오':'시장 분석 · 지원 종목 바스켓'}</strong><span>${esc(conditions)}</span><details><summary>분석 정보</summary><p>${esc(r?.azureScope||'코스피 전체 지수 예측이 아닙니다.')}</p><p>분석 ID: ${esc(r?.azureAnalysisId||'미실행')} · 실행 시각: ${esc(r?.at||r?.startedAt||r?.executedAt||r?.createdAt||r?.time||'미확인')}</p><p>관측 자료 갱신은 완료된 일별 모델 계산을 변경하지 않습니다.</p></details></div>
   ${take('.fig-shared-agent-picker')}
   <nav class="ws-tools" aria-label="근거 자료 도구"><button type="button" data-ws="market" aria-controls="ws-source-list" aria-expanded="${w.tool==='market'}">실시간 데이터</button><button type="button" data-ws="news" aria-controls="ws-source-list" aria-expanded="${w.tool==='news'}">뉴스</button><button type="button" data-ws="document" aria-controls="ws-source-list" aria-expanded="${w.tool==='document'}">문서</button><button type="button" data-ws="start" ${busy?'disabled':''}>${busy?'토론 진행 중':'선택 근거로 새 토론'}</button></nav>
   <aside class="ws-drawer ws-inline-data" id="ws-source-list" ${['market','news','document'].includes(w.tool)?'':'hidden'} role="region" aria-label="근거 자료 탐색"><header><strong>${({market:'실시간 시장 자료',news:'관련 뉴스',document:'공시 및 문서'})[w.tool]||'근거 자료'}</strong><button type="button" data-ws="close">목록 닫기</button></header><div class="ws-drawer-body">${w.tool==='market'?'<button type="button" data-ws="market-add">이 시장 스냅샷을 근거로 선택</button>':''}${take('.fig-data-panel')}</div></aside>
   <div class="ws-evidence" aria-label="선택 근거">${chips||'<span>근거를 선택하거나 분석 시점의 기본 근거로 토론하세요.</span>'}</div>
   ${take('.fig-chat-panel')}
   </section>`;
  const overlay=t.content.querySelector('.fig-scenario-overlay');overlay.classList.add('ws-scenario-overlay');
  return overlay.outerHTML;
 };
})();
