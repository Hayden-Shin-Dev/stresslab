/* Replace only the scenario right-hand sources/chat group. Keep the original page intact. */
(() => {
 const legacy=window.whatIfScenarioWindow;
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const questionRoles={kim:'macro',yoon:'market',shin:'risk',kang:'portfolio'};
 // The same stored selection drives new debates and follow-up questions.
 window.whatIfScenarioQuestionTargets=selectedRoles=>[...new Set((Array.isArray(selectedRoles)?selectedRoles:[]).map(id=>Object.hasOwn(questionRoles,id)?questionRoles[id]:null).filter(Boolean))];
 function discussionPicker(personas, selectedRoles){
  const agents=(personas||[]).filter(agent=>Object.hasOwn(questionRoles,agent.id));
  const selected=agents.filter(agent=>(selectedRoles||[]).includes(agent.id));
  const all=agents.length>0&&selected.length===agents.length;
  const single=!all&&selected.length===1?selected[0].id:null;
  const previous=all||single?'':`<option value="" selected disabled hidden>${selected.length?selected.length+'명':'팀원 선택'}</option>`;
  return `<label class="ws-discussion-label" for="ws-agent-target">자료 토론 설정</label>
   <select id="ws-agent-target" data-ws-role>${previous}<option value="all"${all?' selected':''}>전체</option>
   ${agents.map(agent=>`<option value="${esc(agent.id)}"${single===agent.id?' selected':''}>${esc(agent.name)}</option>`).join('')}</select>`;
 }
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
  const w=data.workspace||{},r=data.run;
  // Draft selection (w.sources) vs. evidence actually sent with the last debate
  // (run.debateSources). Only fields present in state are shown; nothing is inferred.
  const appliedRun=w.researchMode?w.researchRun:r;
  const appliedKeys=new Set((appliedRun?.debateSources||[]).map(x=>x.kind+':'+x.id));
  const debateState=appliedRun?.azureStatus;
  const sourceState=x=>{if(!appliedKeys.has(x.kind+':'+x.id))return ['pending','○','반영 대기'];if(debateState==='debating')return ['running','…','반영 중'];if(debateState==='failed')return ['failed','!','반영 실패'];return ['applied','✓','반영됨'];};
  const chips=(w.sources||[]).map((x,i)=>`<span class="ws-chip">${x.kind==='news'&&/^https:\/\//.test(x.id)?`<a href="${esc(x.id)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>`:x.kind==='document'?`<a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${encodeURIComponent(x.id)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>`:esc(x.title)} <small class="ws-source-state is-${sourceState(x)[0]}" title="${esc(x.status||'선택됨')}"><b aria-hidden="true">${sourceState(x)[1]}</b> ${sourceState(x)[2]}</small><button type="button" data-ws="remove-source" data-index="${i}" aria-label="${esc(x.title)} 근거 선택 취소">×</button></span>`).join('');
  const question=t.content.querySelector('.fig-chat-compose textarea');
  if(question)question.setAttribute('aria-label','상단에서 선택한 분석 에이전트에게 질문');
  const busy=w.busy;
  const sourceMarkup=take('.fig-data-panel');
  const group=t.content.querySelector('.fig-data-chat-group');
  group.outerHTML=`<section class="ws-screen ws-side-panel" aria-label="자료와 에이전트 대화">
   <header class="ws-header"><h2>뿌꾸 AI Agent</h2>${data.showAgentClose ? '<button type="button" data-ws="global-close" aria-label="자료와 대화 닫기">×</button>' : ''}</header>
   <section class="ws-agent-view" aria-label="에이전트 대화">
   <header class="ws-conversation-heading"><h2>에이전트 대화</h2></header>
   <div class="ws-discussion-bar">
   ${discussionPicker(data.personas,data.selectedRoles)}
   <details class="ws-source-tools" ${w.discussionOpen?'open':''}>
   <summary>+ 자료 추가${w.sources?.length?` <span aria-label="선택 자료 ${w.sources.length}건">${w.sources.length}</span>`:''}</summary>
   <div class="ws-source-menu">
   <button type="button" data-ws="market-add">시장 관측 추가</button>
   <div class="ws-evidence" aria-label="선택한 자료">${chips||'<span class="ws-evidence-empty">선택한 자료 없음</span>'}</div>
   <button type="button" data-ws="start" ${busy?'disabled':''}>토론 시작</button>
   </div>
   </details>
   </div>
   ${take('.fig-chat-panel')}</section>
   </section>`;
  const screen=t.content.querySelector('.fig-scenario-screen');
  if(!data.showAgentClose){
   const active=['market','news','document'].includes(w.tool)?w.tool:'scenario';
   screen.dataset.workspaceTab=active;
   const tabs=[['scenario','시나리오 분석'],['market','실시간 데이터'],['news','뉴스'],['document','문서']];
   const nav=t.content.ownerDocument.createElement('nav');
   nav.className='scenario-main-tabs';
   nav.setAttribute('role','tablist');
   nav.setAttribute('aria-label','분석 작업');
   nav.innerHTML=tabs.map(([id,label])=>`<button type="button" role="tab" id="scenario-tab-${id}" aria-controls="${id==='scenario'?'scenario-analysis-panel':'scenario-source-panel'}" aria-selected="${active===id}" tabindex="${active===id?0:-1}" data-workspace-tab="${id}">${label}</button>`).join('');
   const main=screen.querySelector('.fig-main-panel');
   main.id='scenario-analysis-panel';
   main.setAttribute('role','tabpanel');
   main.setAttribute('aria-labelledby','scenario-tab-scenario');
   main.hidden=active!=='scenario';
   screen.querySelector('.scenario-live-observations')?.toggleAttribute('hidden',active!=='scenario');
   screen.querySelector('.fig-live-state-panel')?.toggleAttribute('hidden',active!=='scenario');
   main.before(nav);
   const source=t.content.ownerDocument.createElement('section');
   source.id='scenario-source-panel';
   source.className='scenario-source-panel ws-inline-data';
   source.setAttribute('role','tabpanel');
   source.setAttribute('aria-labelledby','scenario-tab-'+active);
   source.hidden=active==='scenario';
   if(!source.hidden)source.innerHTML=sourceMarkup;
   main.after(source);
  }
  const overlay=t.content.querySelector('.fig-scenario-overlay');overlay.classList.add('ws-scenario-overlay');
  return overlay.outerHTML;
 };
})();
