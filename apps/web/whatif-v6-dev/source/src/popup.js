/* V4.1: V4.0 audio/movement preserved, V3.9 financial functions reused. */
const P41={tab:'agent',contexts:{},events:[],pending:{},requests:new Map(),version:0,bridge:false,bridgeChecked:false,featureRendering:false,lastTrigger:null,observer:null,jobClock:0};
const A41=WhatIfAgentContract;
gxNames.office='WHAT IF 사무실';gxNames.myroom='개인실 · 마이 룸';
gxPeople.forEach((p,i)=>{persona(p.id).avatar=GX_ASSETS['portrait_'+(i+1)];});
const p41BaseRender=render,p41BaseAction=gxPriorAction,p41BaseChat=chatPanel,p41BaseCollabChat=collabChat,p41BaseBubble=renderBubble;
const p41UserAvatar=userAvatar;
userAvatar=function(size='',preview=false){const src=preview?(S.profilePhotoDraft??S.profile.photo):S.profile.photo;if(validProfilePhoto(src))return p41UserAvatar(size,preview);return `<img class="account-avatar p41-player-portrait ${size}" src="${GX_ASSETS[GX.playerKind==='female'?'portrait_female':'portrait_host']}" alt="주인공 픽셀 프로필" draggable="false">`;};
function p41Icon(n){return `<img class="p41-icon" src="${GX_ASSETS['icon_'+n]}" alt="" aria-hidden="true">`;}
function p41Scope(){return GX.panel==='collab'&&S.collab.started?'collab/'+S.collab.room:'personal/'+(['document','news'].includes(S.sub)?S.sub:'scenario');}
function p41ChatKey(){return p41Scope().startsWith('collab/')?'collab':p41Scope().split('/')[1];}
function p41Context(scope=p41Scope()){
 const collaborative=scope.startsWith('collab/'),run=collaborative?S.collab.shared?.run:currentRun();
 const context={version:'context-'+P41.version,run:run?A41.copy(run):null,event:P41.contexts[scope]||null};
 if(collaborative){context.shared=S.collab.shared?A41.copy(S.collab.shared):null;return context;}
 if(scope.endsWith('/document'))context.document=S.docReady?{name:S.docName,kind:S.docKind,text:(S.docContent||'').slice(0,18000),extracted:!!S.docContent}:null;
 if(scope.endsWith('/news'))context.news=chosenNews().map(n=>({id:n.id,title:n.title,published_at:n.publishedAt||n.time,source:n.source,mock:true}));
 context.holdings=A41.copy(S.holdings||[]);return context;
}
function p41Event(type,summary,data={}){
 if(!GX.chat)return;
 const scope=p41Scope();if(scope.startsWith('collab/')&&['holdings','memo','cloud','profile'].includes(type))return;
 const ev={id:'event-'+(++P41.version),type,summary,at:new Date().toISOString(),data:A41.copy(data),scope};P41.contexts[scope]=ev;P41.events.push(ev);P41.events=P41.events.slice(-80);
}
gxWalkable=function(room,x,y){if(!Number.isFinite(x)||!Number.isFinite(y))return false;if(room==='myroom')return (x>=615&&x<=1030&&y>=445&&y<=755)||(x>=325&&x<=1030&&y>=650&&y<=785);return x>=365&&x<=1295&&y>=400&&y<=760;};
gxSetRoom=function(room){
 const privateRoom=room==='myroom';if(room==='meeting'){if(GX.room!=='office')gxSetRoom('office');return gxOpen('collab');}
 GX.roomPositions[GX.room]={x:GX.player.x,y:GX.player.y};GX.room=privateRoom?'myroom':'office';Object.assign(GX.player,GX.roomPositions[GX.room]||{x:800,y:710},{dir:0,walking:false});
 GX.path=[];GX.keys.clear();GX.panel=null;S.modal=null;S.drawer=false;S.myroom.modal='';S.screen=privateRoom?'myroom':'agent';S.tab='chat';P41.tab='agent';
 GX.npcs=privateRoom?[]:gxPeople.map((p,i)=>({...p,x:500+(i%2)*580,y:490+Math.floor(i/2)*190,dir:0,path:[],walking:false,next:[11500,47000,28500,67500][i],phase:'work'}));gxFx('door');render();
};
gxBackground=function(){return GX.room==='myroom'?'myroom':'office';};
gxHotspots=function(){return GX.room==='myroom'?[
 {id:'memo',x:490,y:420,stand:[650,570],name:'분석 노트',kind:'tool',tool:'memo'},
 {id:'back',x:760,y:775,stand:[760,725],name:'사무실',kind:'room',room:'office'}
 ]:[{id:'sim',x:760,y:305,stand:[760,450],name:'차트 시뮬레이터',kind:'sim'},{id:'meeting',x:1100,y:375,stand:[1050,450],name:'함께 분석',kind:'collab'},{id:'myroom',x:1400,y:540,stand:[1250,560],name:'개인실',kind:'room',room:'myroom'}];};
gxOpen=function(panel){
 GX.panel=panel;P41.resetScroll=true;GX.keys.clear();GX.path=[];S.modal=null;S.drawer=false;S.myroom.modal='';S.detailPage=false;
 if(['sim','document','news'].includes(panel)){P41.tab='agent';S.tab='chat';S.sub=panel==='sim'?'scenario':panel;C.setTarget(targetKey());}
 if(panel==='minutes'){P41.tab='minutes';S.tab='minutes';}if(panel==='holdings'){P41.tab='holdings';S.accountTab='holdings';}
 if(panel==='account')S.accountTab='profile';if(panel==='collab')S.tab='collab';render();
};
gxFeatureHTML=function(){
 if(!GX.panel)return '';let content='',title='';P41.featureRendering=true;
 try{
  if(GX.panel==='sim'){title='시나리오 분석';content=S.detailPage?analysisPage():scenario();}
  else if(GX.panel==='document'){title='문서 분석';content=docSection();}
  else if(GX.panel==='news'){title='실시간 뉴스';content=newsSection();}
  else if(GX.panel==='minutes'){title='회의록';content=meetingSection();}
  else if(GX.panel==='collab'){title='함께 분석';content=collabSection();}
  else if(GX.panel==='holdings'){title='내 보유종목';content=holdingsPage();}
  else if(GX.panel==='account'){title='내 정보';content=accountPage();}
  else if(GX.panel==='sheets'){title='캐릭터 도감';content=gxSheetHTML();}
 }finally{P41.featureRendering=false;}
 return `<section class="gx-window p41-feature" role="dialog" aria-modal="false" aria-label="${title}" tabindex="-1"><header class="gx-window-head"><h2>${title}</h2><span class="p41-state">${GX.panel==='collab'?'사람과 AI의 공동 분석':'작업 공간'}</span>${gxButton('feature-close','× 닫기')}</header><div class="gx-window-body">${content}</div></section>`;
};
chatPanel=function(...args){return P41.featureRendering?'':p41BaseChat(...args);};
collabChat=function(){return P41.featureRendering&&GX.chat&&!GX.chatMin?'':p41BaseCollabChat();};
gxChatHTML=function(){
 if(!GX.chat||GX.chatMin)return gxButton('chat-open',p41Icon(16)+' AI 대화 열기','gx-small gx-chat-fab');
 const defaults={x:innerWidth-440,y:190,w:420,h:Math.max(410,innerHeight-240)},r=gxClampWindow(GX.window||defaults,innerWidth,innerHeight);GX.window=r;
 const scope=p41Scope(),key=p41ChatKey(),event=P41.contexts[scope],busy=Object.values(P41.pending).some(x=>x.scope===scope);
 return `<section class="gx-chat-window" style="left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px" aria-label="AI Agent 대화창"><div class="gx-chat-grip"><strong>${key==='collab'?'회의 대화':'AI Agent'}</strong><span class="p41-state">${P41.bridge?'AI 연결됨':'AI 연결 필요'}</span><button data-gx="chat-reset" aria-label="대화창 위치 초기화">↺</button><button data-gx="chat-min" aria-label="대화창 최소화">−</button><button data-gx="chat-close" aria-label="대화창 닫기">×</button></div>${event?`<div class="p41-context"><b>작업 내용 반영</b><span>${E(event.summary)}</span></div>`:''}${busy?'<div class="p41-progress" role="status">선택한 AI가 답변을 준비하고 있어요.</div>':''}${key==='collab'?p41BaseCollabChat():p41BaseChat(key)}<div class="p41-chat-foot">${busy?gxButton('cancel-request','답변 중지'):''}<small>창 끌기 · 우하단 크기 조절</small></div></section>`;
};
renderBubble=function(m){
 if(m.kind==='p41-error')return `<div class="p41-failed" role="status"><b>${E(persona(m.persona).name)}</b><p>${E(m.text)}</p><button class="btn" data-gx="retry-role" data-job="${E(m.jobId)}" ${P41.retrying?.has(m.jobId)?'disabled':''}>${P41.retrying?.has(m.jobId)?'연결 확인 중…':'이 AI만 다시 시도'}</button></div>`;
 if(m.kind==='p41-pending')return `<div class="p41-progress">${E(persona(m.persona).name)} 응답 대기…</div>`;
 return p41BaseBubble(m);
};
function p41ToolBar(){return `<nav class="p41-dock" aria-label="개인실 자료 도구">${[['report','AI 리포트',13],['minutes','회의록',8],['sim','시뮬레이션',5],['cloud','클라우드',14],['memo','메모',15],['agent','AI 팀원',16]].map(([id,label,icon],i)=>gxButton('tool',p41Icon(icon)+`<span><kbd>${i+1}</kbd> ${label}</span>`,'gx-small',`data-tool="${id}"`)).join('')}</nav>`;}
function p41Mount(){
 document.querySelectorAll('svg[data-chart]').forEach(svg=>C.attach(svg,currentRun(),S.chartMode));attachHistoryInteractions();syncNewsSelection();syncPersonaPicker();
 if(GX.panel==='collab')mountCallMedia();if(S.myroom.modal==='memo'){mr36CanvasSetup();mr36RenderThumbs();}
 const zone=document.querySelector('#upload-zone');if(zone){zone.addEventListener('dragover',e=>e.preventDefault());zone.addEventListener('drop',e=>{e.preventDefault();if(e.dataTransfer?.files[0])handleFile(e.dataTransfer.files[0]);});}
 const scroll=document.querySelector('#chat-scroll,.collab-thread');if(scroll)scroll.scrollTop=scroll.scrollHeight;gxBindWindow();gxDraw(performance.now());
 document.querySelectorAll('.p41-feature .chat-panel').forEach(e=>e.remove());if(GX.chat&&!GX.chatMin)document.querySelectorAll('.p41-feature .meeting-chat').forEach(e=>e.remove());
 if(P41.memoDraft&&S.myroom.modal==='memo'&&MR36.memoView==='edit'&&P41.memoDraft.id===MR36.editingId){const d=P41.memoDraft;for(const [id,value]of [['mr36-note-title',d.title],['mr36-note-body',d.body],['mr36-note-date',d.date]]){const el=document.getElementById(id);if(el)el.value=value;}const cv=document.querySelector('#mr36-note-canvas');if(cv&&d.png){cv.dataset.dirty=d.dirty;cv.dataset.blank=d.blank;cv.dataset.p41Restoring='1';const image=new Image();image.onload=()=>{if(cv.isConnected){cv.getContext('2d').drawImage(image,0,0);cv.dataset.p41Restoring='0';}};image.src=d.png;}}
}
render=function(){
 if(S.myroom?.modal==='memo'&&MR36.memoView==='edit'&&document.querySelector('#mr36-note-body')){const cv=document.querySelector('#mr36-note-canvas');P41.memoDraft={id:MR36.editingId,title:document.querySelector('#mr36-note-title')?.value||'',body:document.querySelector('#mr36-note-body').value,date:document.querySelector('#mr36-note-date')?.value||mr36LocalDay(),png:cv?.dataset.p41Restoring==='1'?P41.memoDraft?.png:cv?.toDataURL('image/png'),dirty:cv?.dataset.dirty,blank:cv?.dataset.blank};}
 if(GX.panel==='account'&&S.accountTab==='profile'&&document.querySelector('#profile-name'))rememberProfileForm();
 const a=document.activeElement,focus=a?.dataset?.chatInput,sel=focus?a.selectionStart:null,scrolls=[...document.querySelectorAll('.gx-window-body,.mr35-modal-card')].map(e=>e.scrollTop);
 if(GX.phase!=='game'){p41BaseRender();return;}
 S.appVersion='4.1.0';S.chatCollapsed=false;mr36Load();
 const holdingsSignature=JSON.stringify(S.holdings),profileSignature=JSON.stringify([S.profile.name,S.profile.intro,S.profile.photo]);
 if(P41.holdingsSignature!==undefined&&P41.holdingsSignature!==holdingsSignature)p41Event('holdings','보유종목 변경 · '+S.holdings.length+'개',{count:S.holdings.length});P41.holdingsSignature=holdingsSignature;
 if(P41.profileSignature!==undefined&&P41.profileSignature!==profileSignature)p41Event('profile','프로필 변경');P41.profileSignature=profileSignature;
 if(P41.minuteSelection!==undefined&&P41.minuteSelection!==S.meetingSelected&&S.meetingSelected)p41Event('minutes','선택 회의록 열람',{meetingId:S.meetingSelected});P41.minuteSelection=S.meetingSelected;
 const newsSelection=JSON.stringify(S.newsChecked||[]);if(P41.newsSelection!==undefined&&P41.newsSelection!==newsSelection)p41Event('news','뉴스 '+(S.newsChecked||[]).length+'건 선택');P41.newsSelection=newsSelection;
 const privateRoom=GX.room==='myroom',collab=GX.panel==='collab';
 document.querySelector('#app').innerHTML=`<div class="gx-app p41-app" data-chat="${GX.chat&&!GX.chatMin}" data-private="${privateRoom}"><header class="gx-header"><span class="gx-brand">WHAT IF</span><span class="gx-version">TIME INVESTOR · V4.1</span><span class="gx-time">2008.10 · ${privateRoom?'개인실':'서울지점 · 시장분석팀'}</span><span class="gx-spacer"></span>${gxButton('chat-open',p41Icon(16)+'AI 대화')}${gxButton('sound-open',p41Icon(4)+'설정')}${gxButton('account','내 정보')}${gxButton('logout','타이틀')}</header><aside class="gx-rail" aria-label="전역 메뉴">${[['office','홈',1],['meeting','함께 분석',2],['myroom','마이 룸',3]].map(([id,label,icon])=>gxButton('room',p41Icon(icon)+`<span>${label}</span>`,'',`data-room="${id}" aria-label="${label}" ${((id==='myroom'&&privateRoom)||(id==='meeting'&&collab)||(id==='office'&&!privateRoom&&!collab))?'aria-current="page"':''}`)).join('')}${gxButton('sheets','캐릭터 도감','gx-rail-bottom')}</aside><nav class="gx-tabs p41-tabs" aria-label="홈 메뉴"><div class="p41-main-tabs">${[['sim','AI Agent','agent'],['minutes','회의록','minutes'],['holdings','내 보유종목','holdings']].map(([panel,label,tab])=>gxButton('panel',label,P41.tab===tab?'active':'',`data-panel="${panel}"`)).join('')}</div><div class="p41-subtabs">${[['sim','시나리오 분석','scenario'],['document','문서 분석','document'],['news','실시간 뉴스','news']].map(([panel,label,sub])=>gxButton('panel',label,P41.tab==='agent'&&S.sub===sub?'active':'',`data-panel="${panel}"`)).join('')}</div><span class="p41-place">${privateRoom?'MY ROOM / 개인실':'WHAT IF / 사무실'}<small>${privateRoom?'분석을 정리하고 쉬는 나만의 방':'조건을 기록하고 다음 시장을 준비하세요.'}</small></span></nav><main class="gx-world"><div class="gx-stage" tabindex="0" aria-label="${privateRoom?'개인실':'사무실'}, 방향키 또는 바닥 클릭으로 이동"><canvas width="1536" height="864"></canvas><div class="gx-company">WHAT IF <small>${privateRoom?'PRIVATE ROOM':'FINANCIAL COMPANY · 2008'}</small></div>${gxHotspots().map(h=>gxButton('interact',h.name,'gx-hotspot '+(gxNear(h)?'ready':''),`data-hotspot="${h.id}" style="left:${h.x/15.36}%;top:${h.y/8.64}%"`)).join('')}<div class="p41-scene-controls"><label>시간대<select id="p41-time">${[['morning','아침'],['day','오전'],['afternoon','오후'],['night','밤']].map(([v,l])=>`<option value="${v}" ${S.myroom.time===v?'selected':''}>${l}</option>`).join('')}</select></label>${gxButton('motion',S.myroom.paused?'▶ 동작 재개':'Ⅱ 동작 정지')}${gxButton('expand-world',S.myroom.expanded?'축소':'사무실 확대')}</div></div></main>${privateRoom?p41ToolBar():`<footer class="gx-footer"><span>방향키 / WASD · 바닥 클릭 이동 · 가까이에서 E 상호작용 · Esc 닫기</span><span id="gx-near-label"></span><span>시뮬레이션 기록</span></footer>`}${gxFeatureHTML()}${gxChatHTML()}${modal()}${S.myroom.modal?mr35Modal():''}${GX.soundOpen?gxSoundHTML():''}${GX.toast?`<div class="gx-toast" role="status">${E(GX.toast)}</div>`:''}</div>`;
 document.querySelector('.gx-stage')?.classList.toggle('p41-expanded',!!S.myroom.expanded);p41Mount();
 document.querySelectorAll('.gx-window-body,.mr35-modal-card').forEach((e,i)=>e.scrollTop=P41.resetScroll?0:scrolls[i]||0);P41.resetScroll=false;
 if(focus){const el=document.querySelector(`[data-chat-input="${focus}"]`);el?.focus({preventScroll:true});if(sel!==null)el?.setSelectionRange(sel,sel);}
};
gxDraw=function(now){
 if(GX.phase!=='game')return;const cv=document.querySelector('.gx-stage canvas');if(!cv)return;const c=cv.getContext('2d');c.imageSmoothingEnabled=false;
 const bg=gxImage(gxBackground());c.fillStyle='#142438';c.fillRect(0,0,1536,864);if(bg.complete&&bg.naturalWidth)c.drawImage(bg,0,0,1536,864);
 const themes={morning:'rgba(255,202,135,.08)',day:'rgba(255,236,177,.04)',afternoon:'rgba(170,100,150,.08)',night:'rgba(6,17,60,.20)'};c.fillStyle=themes[S.myroom.time]||themes.day;c.fillRect(0,0,1536,864);
 const actors=[...GX.npcs,{...GX.player,key:GX.playerKind,name:'나',isPlayer:true}].sort((a,b)=>a.y-b.y);
 for(const a of actors){const im=gxImage('sprite_'+a.key);if(!im.complete||!im.naturalWidth)continue;const size=a.isPlayer?(GX.room==='myroom'?205:170):150,fr=a.walking?Math.floor(now/160)%4:0;
  c.fillStyle='#07131c44';c.beginPath();c.ellipse(a.x,a.y,22,7,0,0,7);c.fill();c.drawImage(im,fr*256,a.dir*256,256,256,a.x-size/2,a.y-size*.90625,size,size);c.font='14px Galmuri';c.textAlign='center';c.fillStyle=a.isPlayer?'#d9f7ac':'#f2e5c8';c.fillText(a.name,a.x,a.y+24);
 }
};
gxFrame=function(now){
 requestAnimationFrame(gxFrame);const dt=Math.min((now-(GX.last||now))/1000,.05);GX.last=now;if(GX.phase!=='game'||document.hidden)return;
 const reduce=S.preferences.reducedMotion||matchMedia('(prefers-reduced-motion: reduce)').matches,blocked=GX.chatModal||GX.panel||GX.soundOpen||S.modal||S.myroom.modal||S.myroom.paused||document.activeElement?.matches('input,textarea,select,[contenteditable="true"]');
 if(!blocked){P41.jobClock+=dt*1000;let dx=0,dy=0;for(const k of GX.keys){if(['a','arrowleft'].includes(k))dx--;if(['d','arrowright'].includes(k))dx++;if(['w','arrowup'].includes(k))dy--;if(['s','arrowdown'].includes(k))dy++;}
  if(dx||dy){GX.path=[];const len=Math.hypot(dx,dy),nx=GX.player.x+dx/len*210*(GX.keys.has('shift')?1.8:1)*dt,ny=GX.player.y+dy/len*210*(GX.keys.has('shift')?1.8:1)*dt;if(gxWalkable(GX.room,nx,GX.player.y))GX.player.x=nx;if(gxWalkable(GX.room,GX.player.x,ny))GX.player.y=ny;GX.player.walking=true;GX.player.dir=Math.abs(dx)>Math.abs(dy)?(dx<0?1:2):(dy<0?3:0);}else{GX.player.path=GX.path;gxStepActor(GX.player,dt);}
  if(GX.player.walking&&now-gxLastStepSound>350){gxFx('step');gxLastStepSound=now;}
  if(!reduce)for(const [i,a] of GX.npcs.entries()){if(P41.jobClock>a.next&&!a.path.length){a.path=gxPath(GX.room,a,{x:500+((i*179+Math.floor(P41.jobClock/1000)*9)%650),y:460+(i%2)*200});a.next=P41.jobClock+300000;}gxStepActor(a,dt);}
 }else{GX.player.walking=false;GX.npcs.forEach(a=>a.walking=false);}
 for(const h of gxHotspots())document.querySelector(`[data-hotspot="${h.id}"]`)?.classList.toggle('ready',gxNear(h));const near=gxHotspots().find(gxNear),label=document.querySelector('#gx-near-label');if(label)label.textContent=near?'[E] '+near.name:'사무실을 자유롭게 이동하세요.';gxDraw(now);
};
gxBindWindow=function(){
 P41.observer?.disconnect();const win=document.querySelector('.gx-chat-window');if(!win)return;
 win.querySelector('.gx-chat-grip').addEventListener('pointerdown',e=>{if(e.target.closest('button'))return;const rect=win.getBoundingClientRect(),dx=e.clientX-rect.x,dy=e.clientY-rect.y,grip=e.currentTarget;grip.setPointerCapture(e.pointerId);const move=ev=>{const r=gxClampWindow({x:ev.clientX-dx,y:ev.clientY-dy,w:win.offsetWidth,h:win.offsetHeight},innerWidth,innerHeight);Object.assign(win.style,{left:r.x+'px',top:r.y+'px'});GX.window=r;};const up=()=>{grip.removeEventListener('pointermove',move);grip.removeEventListener('pointerup',up);grip.removeEventListener('pointercancel',up);gxSave();};grip.addEventListener('pointermove',move);grip.addEventListener('pointerup',up);grip.addEventListener('pointercancel',up);});
 if(window.ResizeObserver){P41.observer=new ResizeObserver(()=>{if(!win.isConnected)return;const r=win.getBoundingClientRect();GX.window={x:r.x,y:r.y,w:r.width,h:r.height};});P41.observer.observe(win);}
};
const p41OldGXAction=gxAction;
gxAction=function(action,el){
 if(action==='panel')return gxOpen(el.dataset.panel);
 if(action==='feature-close'){GX.panel=null;S.modal=null;S.detailPage=false;S.drawer=false;render();document.querySelector('.p41-main-tabs button')?.focus();return;}
 if(action==='motion'){S.myroom.paused=!S.myroom.paused;mr35Prefs();return render();}
 if(action==='expand-world'){S.myroom.expanded=!S.myroom.expanded;return render();}
 if(action==='retry-role')return p41Retry(el.dataset.job);
 if(action==='cancel-request'){for(const job of P41.requests.values())job.controller?.abort();return;}
 if(action==='logout'){for(const job of P41.requests.values())job.controller?.abort();stopCallMedia();P41.contexts={};}
 return p41OldGXAction(action,el);
};
onAction=function(action,el){
 if(action==='home')return gxSetRoom('office');if(action==='main-collab')return gxOpen('collab');if(action==='mr35-enter')return gxSetRoom('myroom');
 if(['ai-agent','tab-chat','sub-scenario'].includes(action))return gxOpen('sim');if(action==='sub-document')return gxOpen('document');if(action==='sub-news')return gxOpen('news');if(action==='tab-minutes')return gxOpen('minutes');
 if(action==='toggle-chat-panel'){GX.chat=!GX.chat;GX.chatMin=false;return render();}
 if(action==='horizon-1')return gxToast('현재는 5거래일 분석만 지원합니다.');
 if(action==='mr36-memo-new'||action==='mr35-close')P41.memoDraft=null;
 if(action==='analyze-run')return p41AnalyzeRun(el.dataset.id);
 if(action==='v31-account-page'){GX.panel=el.dataset.tab==='holdings'?'holdings':'account';P41.tab=el.dataset.tab==='holdings'?'holdings':'agent';}
 if(['v33-remove-ai','v31-toggle-collab-agent','v33-confirm-leave'].includes(action)){P41.debate=null;for(const job of P41.requests.values())if(job.scope.startsWith('collab/')&&!job.done)job.controller?.abort();}
 if(action==='mr35-to-holdings'){S.myroom.modal='';return gxOpen('holdings');}
 if(['mr35-to-sim','mr35-to-agent'].includes(action)){S.myroom.modal='';if(el.dataset.persona){S.selectedRoles=[el.dataset.persona];GX.chat=true;}return gxOpen('sim');}
 if(action==='open-minute'||action==='mr35-link-meeting')GX.panel='minutes';
 if(['mr35-link-run','mr37-open-run'].includes(action)){GX.panel='sim';P41.tab='agent';S.sub='scenario';}
 const result=p41BaseAction(action,el);
 if(action==='analyze-doc'&&S.docReady)p41Event('document','문서 분석 요청: '+S.docName,{name:S.docName,extracted:!!S.docContent});
 if(action==='analyze-news')p41Event('news','선택 뉴스 '+chosenNews().length+'건 분석 요청');
 if(action.startsWith('v31-save-holding')||action==='v31-confirm-delete')p41Event('holdings','보유종목 변경',{count:S.holdings.length});
 return result;
};
const p41RunSim=runSim;
runSim=function(){
 if(S.sim.horizon!==5){S.runError='현재는 5거래일 분석만 지원합니다. 이전 결과는 유지됩니다.';return render();}
 const bp=Number(S.sim.rate)*100;if(bp>58){S.runError='금리 충격이 확인된 연구 지원 범위를 벗어납니다. 조건을 줄여 주세요. 이전 결과는 유지됩니다.';return render();}
 const n=S.runs.length,result=p41RunSim();if(S.runs.length>n){const run=currentRun();run.appVersion='4.1.0';run.version='V4.1-'+S.runs.length;p41Event('simulation',run.targetLabel+' · 5거래일 실행 완료',{runId:run.id,version:run.version});persist();render();}return result;
};
const p41InlineSettings=inlineSettings;
inlineSettings=function(){return p41InlineSettings().replace(/data-action="horizon-1"/g,'data-action="horizon-1" disabled title="1거래일 모델은 미지원입니다"');};
document.addEventListener('pointerdown',e=>{const cv=e.target.closest('.gx-stage canvas');if(!cv||GX.chatModal||GX.panel||GX.soundOpen||S.modal||S.myroom.modal)return;e.stopImmediatePropagation();const r=cv.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*1536,y=(e.clientY-r.top)/r.height*864;const npc=GX.npcs.find(a=>Math.hypot(a.x-x,a.y-50-y)<60);if(npc){S.myroom.agent=npc.id;S.myroom.modal='agent';render();return;}GX.path=gxPath(GX.room,GX.player,{x,y});cv.parentElement.focus({preventScroll:true});},true);
document.addEventListener('change',e=>{if(e.target.id==='p41-time'){S.myroom.time=e.target.value;mr35Prefs();gxDraw(performance.now());}});
document.addEventListener('keydown',e=>{if(GX.phase!=='game'||e.target.matches('input,textarea,select')||GX.panel||S.modal||S.myroom.modal)return;if(GX.room==='myroom'&&/^[1-6]$/.test(e.key)){e.preventDefault();mr36SetModal(['report','minutes','sim','cloud','memo','agent'][Number(e.key)-1]);}});
async function p41BridgeLegacy(){if(P41.bridgeChecked)return;P41.bridgeChecked=true;if(!/^https?:$/.test(location.protocol))return;try{const r=await fetch('/api/health',{cache:'no-store'});const x=await r.json();P41.backend=r.ok;P41.bridge=!!x.azureConfigured;}catch{P41.bridge=false;}}

window.WHATIF_QA={getState:()=>({version:S.appVersion,room:GX.room,panel:GX.panel,chat:GX.chat,runs:S.runs.length,contexts:A41.copy(P41.contexts),pending:Object.keys(P41.pending),roles:[...S.selectedRoles]}),getSourceState:()=>S,enter:()=>{GX.phase='game';S.authenticated=true;gxSetRoom('office');},open:gxOpen,context:()=>p41Context(),contract:A41};
