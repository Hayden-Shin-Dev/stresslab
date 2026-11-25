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
  let menu=picker.querySelector(':scope > .ws-agent-dropdown');
  if(!menu){
   const options=[...picker.querySelectorAll(':scope > .fig-shared-agent-option')];
   if(options.length){menu=document.createElement('details');menu.className='ws-agent-dropdown';menu.open=true;const summary=document.createElement('summary');summary.textContent='에이전트 선택';const list=document.createElement('div');list.className='ws-agent-dropdown-list';options.forEach(option=>list.append(option));menu.append(summary,list);picker.append(menu);}
  }
  const count=picker.querySelectorAll('[data-role-choice]:checked').length;
  const summary=picker.querySelector('.ws-agent-dropdown > summary');
  if(summary)summary.textContent=`분석 에이전트 · ${count}명 선택`;
  if(menu)menu.open=true;
  let note=picker.querySelector('.ws-agent-selection-note');
  if(!note){note=document.createElement('small');note.className='ws-agent-selection-note';note.setAttribute('role','status');picker.append(note);}
  note.textContent=count?'':'! 답변할 에이전트를 한 명 이상 선택해 주세요. 입력한 질문은 유지됩니다.';
  note.classList.toggle('is-warning',!count);
  if(!picker.querySelector(':scope > .rm-info')){const info=document.createElement('button');info.type='button';info.className='rm-info';info.dataset.tip='질문은 여기서 선택한 에이전트에게만 전달됩니다. 각 에이전트는 자기 역할(거시·리스크 등) 관점에서 답합니다.';info.setAttribute('aria-label','에이전트 선택 도움말');info.textContent='i';picker.querySelector(':scope > .ws-agent-dropdown')?.after(info);}
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
  const w=data.workspace||{},r=data.run;
  // Draft selection (w.sources) vs. evidence actually sent with the last debate
  // (run.debateSources). Only fields present in state are shown; nothing is inferred.
  const appliedRun=w.researchMode?w.researchRun:r;
  const appliedKeys=new Set((appliedRun?.debateSources||[]).map(x=>x.kind+':'+x.id));
  const debateState=appliedRun?.azureStatus;
  const sourceState=x=>{if(!appliedKeys.has(x.kind+':'+x.id))return ['pending','○','반영 대기'];if(debateState==='debating')return ['running','…','반영 중'];if(debateState==='failed')return ['failed','!','반영 실패'];return ['applied','✓','반영됨'];};
  const chips=(w.sources||[]).map((x,i)=>`<span class="ws-chip">${x.kind==='news'&&/^https:\/\//.test(x.id)?`<a href="${esc(x.id)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>`:x.kind==='document'?`<a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${encodeURIComponent(x.id)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>`:esc(x.title)} <small class="ws-source-state is-${sourceState(x)[0]}" title="${esc(x.status||'선택됨')}"><b aria-hidden="true">${sourceState(x)[1]}</b> ${sourceState(x)[2]}</small><button type="button" data-ws="remove-source" data-index="${i}" aria-label="${esc(x.title)} 근거 선택 취소">×</button></span>`).join('');
  for(const label of t.content.querySelectorAll('.fig-shared-agent-option')){label.title=label.textContent.trim().replace(/\s+/g,' ');}
  syncAgentSelection(t.content.querySelector('.fig-shared-agent-picker'));
  const question=t.content.querySelector('.fig-chat-compose textarea');
  if(question)question.setAttribute('aria-label','상단에서 선택한 분석 에이전트에게 질문');
  const busy=w.busy;
  const pendingCount=(w.sources||[]).filter(x=>!appliedKeys.has(x.kind+':'+x.id)).length;
  const kinds={market:'시세',news:'뉴스',document:'문서'};
  const applied=appliedRun?.debateSources||[];
  const titleOf=x=>(w.sources||[]).find(y=>y.kind===x.kind&&y.id===x.id)?.title||'제목 미확인';
  const debateLabel=debateState==='failed'?['failed','!','토론 실패']:!appliedRun?.debateId?['none','○','토론 미시작']:debateState==='debating'?['running','…','토론 진행 중']:['applied','✓','완료'];
  const evidenceActive=w.agentView==='evidence';
  const appliedSummary=`<details class="ws-applied"><summary><span>반영된 근거</span> <small class="ws-source-state is-${debateLabel[0]}"><b aria-hidden="true">${debateLabel[1]}</b> ${debateLabel[2]}${appliedRun?.debateId?` · 자료 ${applied.length}건`:''}</small></summary><div class="ws-applied-body" role="region" aria-label="이번 대화에 반영된 근거"><dl><dt>연결 분석</dt><dd>${esc(w.researchMode?'엔진 연결 해제 · 독립 리서치':r?.azureAnalysisId||'미연결')}${!w.researchMode&&r?` · ${(r.stressMode||data.stressMode)==='portfolio'?'선택 보유 자산':'독립 종목'}`:''}</dd><dt>토론</dt><dd>${appliedRun?.debateId||debateState==='failed'?esc(debateLabel[2])+(appliedRun.autoSummary?' · 자동 요약(스트레스 결과만 사용)':'')+(debateState==='failed'&&appliedRun.azureError?' · '+esc(appliedRun.azureError):''):'아직 시작한 토론이 없습니다.'}</dd><dt>적용 자료</dt><dd>${applied.length?Object.entries(kinds).map(([k,l])=>`${l} ${applied.filter(x=>x.kind===k).length}`).join(' · '):'추가 자료 없음'}</dd>${applied.length?`<dt>출처</dt><dd><ul>${applied.map(x=>`<li>${esc(kinds[x.kind]||x.kind)} · ${esc(titleOf(x))}</li>`).join('')}</ul></dd>`:''}${appliedRun?.startedAt?`<dt>기준 시각</dt><dd>${esc(new Date(appliedRun.startedAt).toLocaleString('ko-KR'))}</dd>`:''}</dl><p>각 답변이 실제로 사용한 근거는 답변 아래 '사용 근거 보기'에서 확인합니다.</p></div></details>`;
  const sourceMarkup=take('.fig-data-panel');
  const group=t.content.querySelector('.fig-data-chat-group');
  group.outerHTML=`<section class="ws-screen ws-side-panel" aria-label="자료와 에이전트 대화">
   <header class="ws-header"><h2>뿌꾸 AI Agent</h2>${data.showAgentClose ? '<button type="button" data-ws="global-close" aria-label="자료와 대화 닫기">×</button>' : ''}</header>
   <nav class="ws-agent-tabs" role="tablist" aria-label="AI Agent 화면"><button type="button" role="tab" id="ws-tab-evidence" aria-controls="ws-view-evidence" aria-selected="${evidenceActive}" tabindex="${evidenceActive?'0':'-1'}" data-agent-view="evidence">자료 토론설정</button><button type="button" role="tab" id="ws-tab-agent" aria-controls="ws-view-agent" aria-selected="${!evidenceActive}" tabindex="${evidenceActive?'-1':'0'}" data-agent-view="agent">에이전트 대화</button></nav>
   <div class="ws-resource-region" id="ws-view-evidence" role="tabpanel" aria-labelledby="ws-tab-evidence" aria-label="자료 탐색과 선택" ${evidenceActive?'':'hidden'}>
   <section class="ws-zone ws-zone-settings" aria-labelledby="ws-zone-settings-title"><div class="ws-zone-head"><h3 id="ws-zone-settings-title">자료 · 토론 설정</h3>${pendingCount?`<span class="ws-source-state is-pending"><b aria-hidden="true">○</b> 반영 대기 ${pendingCount}건</span>`:''}<button type="button" class="rm-info" data-tip="자동 요약은 스트레스 결과만 사용합니다. 실시간 데이터·뉴스·문서를 고른 뒤 '선택 근거로 새 토론'을 눌러야 새 토론에 반영됩니다. 이미 받은 답변의 근거는 바뀌지 않습니다." aria-label="자료 · 토론 설정 도움말">i</button></div>
   ${take('.fig-shared-agent-picker')}
   <div class="ws-target-slot"></div>
   <div class="ws-evidence" aria-label="선택 근거">${chips||'<span class="ws-evidence-empty">선택한 추가 자료 없음</span>'}</div>
   <div class="ws-start-row"><button type="button" data-ws="start" ${busy?'disabled':''}>${busy?'토론 진행 중':'선택 근거로 새 토론'}</button></div></section>
   </div>
   <section class="ws-agent-view" id="ws-view-agent" role="tabpanel" aria-labelledby="ws-tab-agent" aria-label="에이전트 대화" ${evidenceActive?'hidden':''}>
   <header class="ws-conversation-heading"><h2>에이전트 대화</h2><button type="button" class="rm-info" data-tip="답변은 연결된 스트레스 결과와 실제로 반영된 근거만 사용합니다. 자료를 선택만 한 상태에서는 답변에 쓰이지 않습니다." aria-label="에이전트 대화 도움말">i</button>${appliedSummary}</header>
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
   screen.querySelector('.fig-live-state-panel')?.toggleAttribute('hidden',active!=='scenario');
   main.before(nav);
   const source=t.content.ownerDocument.createElement('section');
   source.id='scenario-source-panel';
   source.className='scenario-source-panel ws-inline-data';
   source.setAttribute('role','tabpanel');
   source.setAttribute('aria-labelledby','scenario-tab-'+active);
   source.hidden=active==='scenario';
   if(!source.hidden)source.innerHTML=`${active==='market'?'<button type="button" data-ws="market-add">이 시장 스냅샷을 근거로 선택</button>':''}${sourceMarkup}`;
   main.after(source);
  }
  const overlay=t.content.querySelector('.fig-scenario-overlay');overlay.classList.add('ws-scenario-overlay');
  return overlay.outerHTML;
 };
})();
