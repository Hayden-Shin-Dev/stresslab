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
  return `<select id="ws-agent-target" data-ws-role aria-label="답변할 팀원 선택">${previous}<option value="all"${all?' selected':''}>전체 선택</option>
   ${agents.map(agent=>`<option value="${esc(agent.id)}"${single===agent.id?' selected':''}>${esc(agent.label||agent.name)}</option>`).join('')}</select>`;
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
    return `<tr><th scope="row">${esc(x.label||x.title||'인용 지표')}</th><td data-raw-value="${esc(x.value)}" data-raw-unit="${esc(x.unit)}"><strong>${esc(number)}</strong> <span>${esc(unit)}</span></td><td>${esc(stamp)}${x.quality&&x.quality!=='unverified'?`<small>${esc(({valid:'검증됨',partial:'일부 미완전',stale:'지연',user_input:'입력값',computed:'계산값'})[x.quality]||x.quality)}</small>`:''}</td></tr>`;
   }).join('');
   return `<div class="ws-metric-table" role="region" aria-label="${esc(group)} 수치 근거" tabindex="0"><table><caption>${esc(group)} · 인용 수치</caption><thead><tr><th scope="col">지표</th><th scope="col">값 · 단위</th><th scope="col">기준 시점</th></tr></thead><tbody>${body}</tbody></table>${ratio?'<p>비율은 원본 값 × 100으로 % 표시합니다. 상관계수와 %p는 원래 단위를 유지합니다.</p>':''}</div>`;
  }).join('');
 };
 function discussionSourceState(run){
  const applied=new Set((run?.debateSources||[]).map(source=>source.kind+':'+source.id));
  return source=>{
   if(!applied.has(source.kind+':'+source.id))return ['pending','○','반영 대기'];
   if(run?.azureStatus==='debating')return ['running','…','반영 중'];
   if(run?.azureStatus==='failed')return ['failed','!','반영 실패'];
   return ['applied','✓','반영됨'];
  };
 }
 function addUserAvatars(root){
  for(const row of root.querySelectorAll('.bubble-row.me')){
   const avatar=root.ownerDocument.createElement('img');
   avatar.src='assets/scenario-ui/images/avatar-user.png';
   avatar.alt='';avatar.className='ws-user-avatar';
   row.prepend(avatar);
  }
 }
 // New responses are appended without replacing the composer, chart or existing message nodes.
 window.whatIfRefreshScenarioConversation=(panel,data)=>{
  const list=panel.querySelector('.fig-chat-messages');
  const count=Number(list.dataset.messageCount||0);
  const follow=list.scrollHeight-list.clientHeight-list.scrollTop<2;
  if(data.messages.length>count){
   const template=panel.ownerDocument.createElement('template');
   template.innerHTML=data.messages.slice(count).map(data.renderMessage).join('');
   if(template.content.childNodes.length){
    list.querySelector('.fig-chat-prompts')?.remove();
    addUserAvatars(template.content);
    list.insertBefore(template.content,list.querySelector('.ws-quick-questions'));
   }
   list.dataset.messageCount=String(data.messages.length);
  }
  list.classList.toggle('has-agent-messages',data.messages.some(message=>message.azureMessageId));

  const compose=panel.querySelector('.fig-chat-compose');
  const status=panel.querySelector('.fig-chat-status');
  if(data.status){
   const next=status||panel.ownerDocument.createElement('p');
   if(!status){next.className='fig-chat-status';next.setAttribute('role','status');next.setAttribute('aria-live','polite');compose.before(next);}
   if(next.textContent!==data.status)next.textContent=data.status;
  }else status?.remove();
  for(const control of compose.querySelectorAll('textarea,button'))control.disabled=data.waiting;
  if(data.draft!==undefined){
   const input=compose.querySelector('textarea');
   if(input.value!==data.draft)input.value=data.draft;
  }

  const sourceState=discussionSourceState(data.run);
  panel.querySelectorAll('.ws-source-state').forEach((chip,index)=>{
   const source=data.sources[index];if(!source)return;
   const [state,icon,label]=sourceState(source);
   const className='ws-source-state is-'+state;
   const title=source.status||'선택됨';
   if(chip.className!==className)chip.className=className;
   if(chip.title!==title)chip.title=title;
   if(chip.textContent!==icon+' '+label){
    chip.firstElementChild.textContent=icon;
    chip.lastChild.textContent=' '+label;
   }
  });
  if(follow)list.scrollTop=list.scrollHeight;
 };
 window.whatIfScenarioConversation=data=>{
  const t=document.createElement('template');
  t.innerHTML='<section class="fig-chat-panel" aria-label="AI 에이전트 채팅">'+window.whatIfScenarioChatBody({...data,chatMin:false})+'</section>';
  const w=data.workspace||{},r=data.run;
  // Draft selection (w.sources) vs. evidence actually sent with the last debate
  // (run.debateSources). Only fields present in state are shown; nothing is inferred.
  const appliedRun=w.conversationRun||(w.researchMode?w.researchRun:r);
  const sourceState=discussionSourceState(appliedRun);
  const chips=(w.sources||[]).map((x,i)=>`<span class="ws-chip">${x.kind==='news'&&/^https:\/\//.test(x.id)?`<a href="${esc(x.id)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>`:x.kind==='document'?`<a href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${encodeURIComponent(x.id)}" target="_blank" rel="noopener noreferrer">${esc(x.title)}</a>`:esc(x.title)} <small class="ws-source-state is-${sourceState(x)[0]}" title="${esc(x.status||'선택됨')}"><b aria-hidden="true">${sourceState(x)[1]}</b> ${sourceState(x)[2]}</small><button type="button" data-ws="remove-source" data-index="${Number.isInteger(x.index)?x.index:i}" aria-label="${esc(x.title)} 근거 선택 취소">×</button></span>`).join('');
  const question=t.content.querySelector('.fig-chat-compose textarea');
  if(question){question.setAttribute('aria-label','상단에서 선택한 분석 에이전트에게 질문');question.placeholder='질문을 입력하세요';}
  const chatTab=['news','document'].includes(w.chatTab)?w.chatTab:'scenario';
  const chatTabs=[['scenario','시나리오 분석'],['news','뉴스'],['document','문서']];
  const figure=t.content.querySelector('.fig-chat-panel');
  figure.querySelector('.fig-chat-toolbar')?.remove();
  figure.querySelector('.fig-chat-shared-label')?.remove();
  figure.querySelector('.fig-send-icon').src='assets/scenario-ui/icons/send-plane.svg';
  const questions={
   scenario:['가정이 달라지면 어떻게 되나요?','추가로 확인할 근거는 무엇인가요?'],
   news:['선택한 뉴스의 핵심 내용은 무엇인가요?','추가로 확인할 보도가 있나요?'],
   document:['선택한 문서의 핵심 내용은 무엇인가요?','어떤 수치와 기준일을 확인해야 하나요?']
  };
  figure.querySelector('.fig-chat-prompts')?.remove();
  const messageList=figure.querySelector('.fig-chat-messages');
  messageList.dataset.messageCount=String(data.messageCount||0);
  addUserAvatars(messageList);
  messageList.insertAdjacentHTML('beforeend',`<div class="ws-quick-questions">${questions[chatTab].map(text=>`<button type="button" data-action="quick" data-p50-key="scenario" data-text="${esc(text)}">${esc(text)}</button>`).join('')}</div>`);
  const status=figure.querySelector('.fig-chat-status');
  if(!data.agentStatus)status.remove();
  return `<section class="ws-screen ws-side-panel ws-chat-redesign" aria-label="뿌꾸 AI 챗봇" data-chat-tab="${chatTab}">
   <nav class="ws-chat-tabs" role="tablist" aria-label="챗봇 대화 주제">
    ${chatTabs.map(([id,label])=>`<button type="button" role="tab" id="chat-tab-${id}" aria-controls="workspace-conversation" aria-selected="${chatTab===id}" tabindex="${chatTab===id?0:-1}" data-workspace-tab="${id}">${label}</button>`).join('')}
   </nav>
   <section class="ws-agent-view" id="workspace-conversation" role="tabpanel" aria-labelledby="chat-tab-${chatTab}">
    <div class="ws-discussion-bar">
     <button class="ws-chat-primary" type="button" data-ws="start">${chatTab==='scenario'?'현재 시뮬레이션 결과 분석':chatTab==='news'?'선택한 뉴스 분석':'선택한 문서 분석'}</button>
     ${discussionPicker(data.personas,data.selectedRoles)}
    <details class="ws-source-tools" ${w.discussionOpen?'open':''}>
     <summary aria-label="선택 자료" title="선택 자료"><img src="assets/scenario-ui/icons/document.svg" alt="">${w.sources?.length?` <span aria-label="선택 자료 ${w.sources.length}건">${w.sources.length}</span>`:''}</summary>
     <div class="ws-source-menu">
      ${chatTab==='scenario'?'<button type="button" data-ws="market-add">시장 관측 추가</button>':''}
      <div class="ws-evidence" aria-label="선택한 자료">${chips||'<span class="ws-evidence-empty">선택한 자료 없음</span>'}</div>
     </div>
    </details>
    </div>
    ${figure.outerHTML}
   </section>
   </section>`;
 };
 window.whatIfScenarioWindow=data=>{
  const t=document.createElement('template');t.innerHTML=legacy({...data,chatMin:false});
  const sourceMarkup=t.content.querySelector('.fig-data-panel')?.outerHTML||'';
  const w=data.workspace||{};
  t.content.querySelector('.fig-data-chat-group').outerHTML=window.whatIfScenarioConversation(data);
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
