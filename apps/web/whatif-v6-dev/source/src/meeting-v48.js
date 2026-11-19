/* Spatial presentation around the existing V4.7 collaboration/data contracts. */
const M48={view:'room',nick:null,exit:null,previousChat:null,motion:true};
const m48Render=render,m48Open=gxOpen,m48GX=gxAction,m48Action=onAction;
const m48AiTile=aiTile;
aiTile=function(id){return m48AiTile(id).replace('class="ai-tile-photo"','class="m48-ai-photo"');};
const m48Chart=C.chartHTML;
C.chartHTML=function(options){const html=m48Chart(options);return options?.id==='meeting-simulation'?html.replaceAll('font-size="12"','font-size="16"').replaceAll('font-size="13"','font-size="16"'):html;};
function m48RestoreChat(){if(M48.previousChat){GX.chat=M48.previousChat.open;GX.chatMin=M48.previousChat.min;M48.previousChat=null;}}
gxOpen=function(panel){if(panel==='collab'){M48.view='room';if(!M48.previousChat)M48.previousChat={open:GX.chat,min:GX.chatMin};GX.chat=false;GX.chatMin=false;}else if(GX.panel==='collab'){m48RestoreChat();}return m48Open(panel);};
function m48Leave(destination){if(S.collab.started){M48.exit=destination;return onAction('v33-leave',document.createElement('button'));}stopCallMedia();pauseDiscussion();GX.panel=null;m48RestoreChat();if(destination?.room)return gxSetRoom(destination.room);render();}
gxAction=function(action,el){
 if(action==='m48-start'){gxFx('click');M48.view='computer';if(!S.collab.started)return onAction('start-room',el);return render();}
 if(action==='m48-room'){gxFx('click');M48.view='room';GX.chat=false;return render();}
 if(action==='m48-office')return m48Leave({room:'office'});
 if(action==='m48-people')return onAction('invite',el);
 if(action==='m48-detach'){GX.chat=true;GX.chatMin=false;return render();}
 if(action==='m48-motion'){M48.motion=!M48.motion;return render();}
 if(GX.panel==='collab'&&action==='feature-close')return M48.view==='computer'?gxAction('m48-room',el):m48Leave({room:'office'});
 if(GX.panel==='collab'&&action==='room'&&el.dataset.room!=='meeting')return m48Leave({room:el.dataset.room});
 if(GX.panel==='collab'&&action==='chat-open'){M48.view='computer';if(!S.collab.started)return gxAction('m48-start',el);}
 return m48GX(action,el);
};
onAction=function(action,el){
 if(action==='close-modal')M48.exit=null;
 if(action==='v33-confirm-leave'){const dest=M48.exit;M48.exit=null;const out=m48Action(action,el);M48.view='room';GX.chat=false;if(dest){GX.panel=null;m48RestoreChat();if(dest.room)gxSetRoom(dest.room);else render();}else render();return out;}
 return m48Action(action,el);
};
function m48Launch(){
 const splash=GX.phase==='splash',reduce=S.preferences.reducedMotion||matchMedia('(prefers-reduced-motion:reduce)').matches||!M48.motion;
 const picture=GX_ASSETS[splash?'splash48':'login48'];
 document.querySelector('#app').innerHTML=`<section class="gx-launch m48-launch ${splash?'m48-splash':'m48-login'} ${reduce?'m48-still':''}"><div class="m48-art" aria-hidden="true"><img src="${picture}" alt=""></div>${splash?`<div class="m48-title"><small>TIME INVESTOR · 2008</small><h1>WHAT IF</h1><p>다시 만나는 시장, 새롭게 쓰는 투자 일지</p></div><div class="m48-start">${gxButton('continue','여정 시작','gx-primary')}<small>2008년의 WHAT IF 회사로</small></div>${gxButton('m48-motion',M48.motion?'화면 움직임 끄기':'화면 움직임 켜기','m48-motion')}`:`<div class="m48-login-heading"><strong>WHAT IF</strong><span>TIME INVESTOR · 2008</span></div><section class="gx-login-cover m48-login-card" aria-label="게임 로그인"><small>서울지점 · 시장분석팀</small><h1>다시, 2008년으로</h1><p>함께 살펴보고, 나만의 가정을 기록하세요.</p><label for="gx-nickname">체험 닉네임<input id="gx-nickname" value="${E(M48.nick??S.profile.name??'시간 여행자')}" maxlength="24" autocomplete="nickname"></label><fieldset class="m48-character"><legend>주인공 선택</legend>${[['male','남자 주인공','portrait_host'],['female','여자 주인공','portrait_female']].map(([id,name,im])=>gxButton('player-'+id,`<img src="${GX_ASSETS[im]}" alt=""><span>${name}</span>`,'gx-small '+(GX.playerKind===id?'selected':''),`aria-pressed="${GX.playerKind===id}"`)).join('')}</fieldset>${gxButton('enter','로그인 · 체험 시작','gx-primary')}${gxButton('enter','게스트로 시작','gx-small')}<p class="m48-local">로컬 체험 · 실제 계정 인증 미연결</p>${gxButton('back-splash','타이틀로 돌아가기','gx-small')}</section>`}<div class="gx-launch-sound">${gxButton('sound-open',p41Icon(4)+'사운드 설정')}</div>${GX.soundOpen?gxSoundHTML():''}</section>`;
 const scene=document.querySelector('.m48-launch');scene.addEventListener('pointermove',e=>{if(reduce)return;const b=scene.getBoundingClientRect();scene.style.setProperty('--m48-x',((e.clientX-b.x)/b.width-.5).toFixed(3));scene.style.setProperty('--m48-y',((e.clientY-b.y)/b.height-.5).toFixed(3));});scene.addEventListener('pointerleave',()=>{scene.style.setProperty('--m48-x',0);scene.style.setProperty('--m48-y',0);});
}
function m48RoomHTML(){
 const order=['kim','yoon','shin','kang'],xs=[32,45.5,58.5,72];
 return `<section class="m48-room" aria-label="2008년 회의실 착석 장면"><div class="m48-room-stage"><img class="m48-room-bg" src="${GX_ASSETS.meeting_room48}" alt="블라인드와 가을 액자, 나무 회의 테이블과 큰 디스플레이가 있는 2008년 회의실"><canvas class="m48-seated" width="1672" height="941" aria-label="맞은편 AI 네 명과 선택한 주인공이 착석한 회의 테이블"></canvas>${order.map((id,i)=>`<button class="m48-name ${S.collab.agents.includes(id)?'':'m48-excluded'}" style="left:${xs[i]}%;top:50.5%" data-gx="m48-people">${E(persona(id).name)}<small>${S.collab.agents.includes(id)?(S.collab.speaker===id?'발언 중':persona(id).role):'참여 제외'}</small></button>`).join('')}<div class="m48-host-label">${E(S.profile.name)} · 호스트</div><div class="m48-wall"><strong>WHAT IF · 함께 분석</strong><span>${S.collab.shared?E(S.collab.shared.title):'공유 대기'}</span><small>${S.collab.shared?'현재 회의의 공유 자료':'컴퓨터에서 자료를 함께 살펴보세요.'}</small></div><button class="m48-desk" data-gx="m48-start" aria-label="컴퓨터 화면으로 함께 분석">${p41Icon(5)}<span>컴퓨터 화면 확대</span></button></div><footer class="m48-room-tools"><span>나 1명 · AI ${S.collab.agents.length}명</span>${gxButton('m48-start',S.collab.started?'분석 화면 이어보기':'함께 분석하기','gx-primary')}${gxButton('m48-people','참가자 · AI 팀원')}${gxButton('m48-office','사무실로')}</footer></section>`;
}
function m48Draw(now=0){
 const cv=document.querySelector('.m48-seated');if(!cv)return;const c=cv.getContext('2d'),w=cv.width,h=cv.height,im=gxImage('meeting_seated48');c.clearRect(0,0,w,h);c.imageSmoothingEnabled=false;if(!im.complete||!im.naturalWidth)return;
 const crop=(index,x,y,dh,opacity=1)=>{const dw=dh*362/490;c.save();c.globalAlpha=opacity;if(index<4&&typeof p49Glowing==='function'&&p49Glowing(['kim','yoon','shin','kang'][index]))c.filter=P49_GLOW;c.drawImage(im,index*362,122,362,490,x-dw/2,y,dw,dh);c.restore();};
 const reduce=S.preferences.reducedMotion||matchMedia('(prefers-reduced-motion:reduce)').matches;const ids=['kim','yoon','shin','kang'];
 const upper=gxImage('meeting_upper55');
 if(upper.complete&&upper.naturalWidth)for(let i=0;i<4;i++){const size=h*.29,x=w*[.32,.455,.585,.72][i],y=h*.235;c.save();c.globalAlpha=S.collab.agents.includes(ids[i])?1:.35;if(typeof p49Glowing==='function'&&p49Glowing(ids[i]))c.filter=P49_GLOW;const sprite=i===2?gxImage('meeting_youngcheol56'):upper;if(sprite.complete&&sprite.naturalWidth)c.drawImage(sprite,i===2?0:i*256,0,256,256,x-size/2,y,size,size);c.restore();}

 crop(GX.playerKind==='female'?5:4,w*.55,h*.62,h*.28);
 const bg=gxImage('meeting_room48');if(bg.complete&&bg.naturalWidth)c.drawImage(bg,bg.naturalWidth*.482,bg.naturalHeight*.775,bg.naturalWidth*.145,bg.naturalHeight*.225,w*.482,h*.775,w*.145,h*.225);
 const pet=gxImage('ppukku_idle_06_greeting');if(pet.complete&&pet.naturalWidth){c.save();if(typeof p49Glowing==='function'&&p49Glowing('ppukku'))c.filter=P49_GLOW;c.drawImage(pet,0,0,256,256,w*.645,h*.78,h*.16,h*.16);c.restore();}
}
function m48Tick(now){if(!document.hidden&&GX.phase==='game'&&GX.panel==='collab'&&M48.view==='room')m48Draw(now);requestAnimationFrame(m48Tick);}requestAnimationFrame(m48Tick);
render=function(){
 const nick=document.querySelector('#gx-nickname');if(nick)M48.nick=nick.value;
 m48Render();if(GX.phase!=='game'){m48Launch();return;}S.appVersion='4.8.0';const root=document.querySelector('.ui47');if(!root)return;root.classList.add('ui48');
 const secondary=root.querySelector('.modal,.mr35-modal-card,.gx-settings');if(secondary){secondary.setAttribute('aria-modal','true');secondary.setAttribute('tabindex','-1');}
 if(GX.panel!=='collab')return;
 root.classList.add('m48-collab');root.setAttribute('data-agent-open','false');root.classList.remove('ap47-chat-docked');
 root.querySelectorAll('.p41-main-tabs button.active').forEach(b=>b.classList.remove('active'));
 const feature=root.querySelector('.p41-feature'),world=root.querySelector('.gx-world');
 if(M48.view==='room'){
  root.classList.add('m48-in-room');feature?.closest('.v45-notebook-wrap')?.classList.add('m48-hidden');root.querySelector('.v45-modal-shade')?.classList.add('m48-hidden');world.innerHTML=m48RoomHTML();world.inert=!!secondary;
  root.querySelectorAll(':scope>header,:scope>aside,:scope>nav').forEach(e=>e.inert=!!secondary);root.querySelector('.gx-chat-fab')?.classList.add('m48-hidden');m48Draw();
  if(!secondary)world.querySelector('[data-gx="m48-start"]')?.focus({preventScroll:true});
 }else if(feature){
  root.classList.add('m48-in-computer');feature.classList.add('m48-computer');world.style.backgroundImage='url("'+GX_ASSETS.meeting_room48+'")';
  const head=feature.querySelector('.gx-window-head'),back=head.querySelector('[data-gx="feature-close"]');if(back){back.dataset.gx='m48-room';back.textContent='회의실로 돌아가기';}const title=head.querySelector('h2');if(title)title.textContent='WHAT IF · 함께 분석';
  const subhead=feature.querySelector('.collab-v33>.page-title-row'),invite=subhead?.querySelector('[data-action="invite"]');if(invite)head.insertBefore(invite,back);subhead?.remove();
  const simHead=feature.querySelector('.call-sim-head'),sourceButton=simHead?.querySelector('button'),workTabs=feature.querySelector('.meeting-workspace-tabs');if(sourceButton&&workTabs){sourceButton.classList.add('m48-source-shortcut');workTabs.append(sourceButton);simHead.remove();}
  if(GX.chat&&!GX.chatMin){feature.querySelectorAll('.meeting-chat').forEach(e=>e.remove());feature.classList.add('m48-detached');}else{const chat=feature.querySelector('.meeting-chat');if(chat){const button=document.createElement('button');button.dataset.gx='m48-detach';button.className='gx-small m48-chat-pop';button.textContent='대화창 분리';chat.querySelector('.panel-header')?.append(button);}}
  feature.querySelectorAll('.meeting-avatar .account-avatar,.ai-tile-photo').forEach(e=>e.style.objectPosition='center');
 }
 if(secondary){secondary.querySelector('button,input,textarea,select')?.focus({preventScroll:true});}
};
window.addEventListener('keydown',e=>{
 if(GX.phase!=='game')return;const modal=document.querySelector('.modal-wrap .modal,.gx-settings,.mr35-modal-card');
 if(e.key==='Tab'&&modal){const f=[...modal.querySelectorAll('button,input,select,textarea,[tabindex]')].filter(x=>!x.disabled&&x.getClientRects().length);if(f.length&&((e.shiftKey&&document.activeElement===f[0])||(!e.shiftKey&&document.activeElement===f.at(-1)))){e.preventDefault();(e.shiftKey?f.at(-1):f[0]).focus();}return;}
 if(e.key==='Escape'&&!document.querySelector('.p512-period-menu[open]')&&GX.panel==='collab'&&!S.modal&&!S.myroom.modal&&!GX.soundOpen){e.preventDefault();e.stopImmediatePropagation();if(GX.chat&&!GX.chatMin){GX.chat=false;return render();}if(M48.view==='computer'){M48.view='room';return render();}m48Leave({room:'office'});}
},true);
window.WHATIF_QA.meeting48=()=>({view:M48.view,started:S.collab.started,agents:[...S.collab.agents],kind:GX.playerKind,shared:S.collab.shared?.title||null,motion:M48.motion,media:{camera:!!callUI.camera,mic:!!callUI.mic,screen:!!callUI.screen,hand:callUI.hand}});
