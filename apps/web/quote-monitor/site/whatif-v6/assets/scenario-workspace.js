/* Replace only the scenario right-hand sources/chat group. Keep the original page intact. */
(() => {
 const legacy=window.whatIfScenarioWindow;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const questionRoles={kim:'macro',yoon:'market',shin:'risk',kang:'portfolio'};
 // The avatar selection is the sole question recipient source. A saved legacy
 // dropdown value must never override it; callers keep the empty-selection guard.
 window.whatIfScenarioQuestionTargets=selectedRoles=>[...new Set((Array.isArray(selectedRoles)?selectedRoles:[]).map(id=>Object.prototype.hasOwnProperty.call(questionRoles,id)?questionRoles[id]:null).filter(Boolean))];
 function syncAgentSelection(picker){
  if(!picker)return;
  const count=picker.querySelectorAll('[data-role-choice]:checked').length;
  const title=picker.querySelector(':scope > strong');
  if(title)title.textContent=`분석 에이전트 · ${count}명 선택`;
  let note=picker.querySelector('.ws-agent-selection-note');
  if(!note){note=document.createElement('small');note.className='ws-agent-selection-note';note.setAttribute('role','status');picker.append(note);}
  note.textContent=count?'위에서 선택한 에이전트에게 질문이 전달됩니다.':'답변할 에이전트를 한 명 이상 선택해 주세요. 입력한 질문은 유지됩니다.';
  note.classList.toggle('is-empty',!count);
  picker.setAttribute('aria-label','질문에 답변할 분석 에이전트 선택');
 }
 // The existing role-choice handler owns selection/persistence and does not
 // repaint the page. Update only its caption after that handler has run so the
 // question draft, caret, evidence selection and in-flight request stay intact.
 if(typeof document!=='undefined')document.addEventListener('change',event=>{
  const picker=event.target.closest?.('.fig-shared-agent-picker');
  if(picker&&event.target.matches('[data-role-choice],[data-role-all]'))queueMicrotask(()=>syncAgentSelection(picker));
 });
 // Only server-supplied structured evidence is tabulated; prose is never parsed for numbers.
 window.whatIfScenarioEvidenceTable=sources=>{
  const groups=new Map();
  for(const source of sources){
   if(typeof source.value!=='number'||!Number.isFinite(source.value))continue;
   const group=source.asset_name||'시장 · 공통 지표';
   if(!groups.has(group))groups.set(group,[]);
   groups.get(group).push(source);
  }
  return [...groups].map(([group,rows])=>{
   const ratio=rows.some(x=>x.unit==='ratio');
   const body=rows.map(x=>{
    const value=x.unit==='ratio'?x.value*100:x.value;
    const unit=({ratio:'%',corr:'상관계수',KRW:'원',count:'개',pct:'%',pp:'%p'})[x.unit]||x.unit||'';
    const stamp=x.as_of?String(x.as_of):'기준 시점 미제공';
    const number=new Intl.NumberFormat('ko-KR',{maximumFractionDigits:x.unit==='ratio'?3:4}).format(value);
    return `<tr><th scope="row">${esc(x.label||x.title||'인용 지표')}</th><td data-raw-value="${esc(x.value)}" data-raw-unit="${esc(x.unit)}"><strong>${esc(number)}</strong> <span>${esc(unit)}</span></td><td>${esc(stamp)}${x.quality?`<small>${esc(({valid:'검증됨',partial:'일부 미완전',stale:'지연',unverified:'검증 대기',user_input:'입력값',computed:'계산값'})[x.quality]||x.quality)}</small>`:''}</td></tr>`;
   }).join('');
   return `<div class="ws-metric-table" role="region" aria-label="${esc(group)} 수치 근거" tabindex="0"><table><caption>${esc(group)} · 인용 수치</caption><thead><tr><th scope="col">지표</th><th scope="col">값 · 단위</th><th scope="col">기준 시점</th></tr></thead><tbody>${body}</tbody></table>${ratio?'<p>비율은 원본 값 × 100으로 % 표시합니다. 상관계수와 %p는 원래 단위를 유지합니다.</p>':''}</div>`;
  }).join('');
 };
 window.whatIfScenarioWindow=data=>{
  const t=document.createElement('template');t.innerHTML=legacy({...data,chatMin:false});
  const take=selector=>t.content.querySelector(selector)?.outerHTML||'';
  const w=data.workspace||{},r=data.run,c=r?.conditions||{};
  const conditions=w.researchMode?'엔진 연결 해제 · 선택한 종목·보유 정보와 적용한 자료로 독립 리서치합니다.':r?`5거래일 · 미국 10년 ${Number(c.rate)*100}bp · 원/달러 ${c.fx}% · WTI ${c.oil}% · VIX ${c.vix}pt`:'분석 조건을 설정하고 스트레스테스트를 실행해 주세요.';
  const chips=(w.sources||[]).map((x,i)=>`<span class="ws-chip">${x.kind==='news'&&/^https:\/\//.test(x.id)?`<a href="${esc(x.id)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>`:x.kind==='document'?`<a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${encodeURIComponent(x.id)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>`:esc(x.title)} <small>${esc(x.status||'선택됨')}</small><button type="button" data-ws="remove-source" data-index="${i}" aria-label="${esc(x.title)} 근거 선택 취소">×</button></span>`).join('');
  for(const label of t.content.querySelectorAll('.fig-shared-agent-option')){label.title=label.textContent.trim().replace(/\s+/g,' ');}
  syncAgentSelection(t.content.querySelector('.fig-shared-agent-picker'));
  const question=t.content.querySelector('.fig-chat-compose textarea');
  if(question)question.setAttribute('aria-label','상단에서 선택한 분석 에이전트에게 질문');
  const busy=w.busy;
  const group=t.content.querySelector('.fig-data-chat-group');
  group.outerHTML=`<section class="ws-screen ws-side-panel" aria-label="자료와 에이전트 대화">
   <header class="ws-header"><h2>자료 탐색</h2><button type="button" data-ws="global-close" aria-label="자료와 대화 닫기">×</button></header>
   <div class="ws-resource-region" aria-label="자료 탐색과 선택">
   <div class="ws-context"><button class="ws-stress-link" type="button" data-ws="linked-stress">↔ 스트레스테스트 ${w.researchMode ? "연결 해제 · 분석 열기" : r?.azureAnalysisId ? "결과 연결됨" : r ? "계산 상태 확인" : "연결 전 · 분석 열기"}</button><span>${esc(r?.stressModel||data.stressModel||"Ridge")} · ${esc(r?.azureAnalysisId||"미실행")}</span><strong>${w.researchMode?'독립 리서치':(r?.stressMode||data.stressMode)==='portfolio'?'선택 보유 자산':'독립 종목 분석 · KOSPI 지수 아님'}</strong><span>${esc(conditions)}</span><details><summary>분석 정보</summary><p>${esc(r?.azureScope||'코스피 전체 지수 예측이 아닙니다.')}</p><p>분석 ID: ${esc(r?.azureAnalysisId||'미실행')} · 실행 시각: ${esc(r?.at||r?.startedAt||r?.executedAt||r?.createdAt||r?.time||'미확인')}</p><p>관측 자료 갱신은 완료된 일별 모델 계산을 변경하지 않습니다.</p></details></div>
   ${take('.fig-shared-agent-picker')}
   <nav class="ws-tools" aria-label="근거 자료 도구"><button type="button" data-ws="market" aria-controls="ws-source-list" aria-expanded="${w.tool==='market'}">실시간 데이터</button><button type="button" data-ws="news" aria-controls="ws-source-list" aria-expanded="${w.tool==='news'}">뉴스</button><button type="button" data-ws="document" aria-controls="ws-source-list" aria-expanded="${w.tool==='document'}">문서</button><button type="button" data-ws="start" ${busy?'disabled':''}>${busy?'토론 진행 중':'선택 근거로 새 토론'}</button></nav>
   <aside class="ws-drawer ws-inline-data" id="ws-source-list" ${['market','news','document'].includes(w.tool)?'':'hidden'} role="region" aria-label="근거 자료 탐색"><header><strong>${({market:'실시간 시장 자료',news:'관련 뉴스',document:'공시 및 문서'})[w.tool]||'근거 자료'}</strong><button type="button" data-ws="close">목록 닫기</button></header><div class="ws-drawer-body">${w.tool==='market'?'<button type="button" data-ws="market-add">이 시장 스냅샷을 근거로 선택</button>':''}${take('.fig-data-panel')}</div></aside>
   <div class="ws-evidence" aria-label="선택 근거">${chips||'<span>자동 요약은 스트레스 결과를 사용합니다. 추가 자료는 선택 후 새 토론으로 적용하세요.</span>'}</div>
   </div>
   <header class="ws-conversation-heading"><h2>에이전트 대화</h2><span>위 자료와 연결된 분석 결과를 함께 해석합니다</span></header>
   ${take('.fig-chat-panel')}
   </section>`;
  const overlay=t.content.querySelector('.fig-scenario-overlay');overlay.classList.add('ws-scenario-overlay');
  return overlay.outerHTML;
 };
})();
