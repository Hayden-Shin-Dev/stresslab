/* V5.6: Korea-time home plates, contextual chat and a functional wide LCD shell. */
const P56={homeTime:null,observer:null,clock:new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'})};
function p56ValidName(value){return /^[가-힣A-Za-z0-9]{1,5}$/u.test(String(value??'').normalize('NFC').trim());}
function p56Period(date=new Date()){const h=Number(P56.clock.formatToParts(date).find(p=>p.type==='hour').value);return h>=7&&h<10?'morning':h>=10&&h<12?'forenoon':h>=12&&h<20?'afternoon':'night';}
function p56Clock(date=new Date()){
 P56.homeTime=p56Period(date);
 const el=document.querySelector('.p56-real-clock');if(el){el.dateTime=date.toISOString();el.textContent=P56.clock.format(date)+' KST';}
 const field=document.querySelector('#p41-time');if(field&&GX.room==='office'&&GX.panel!=='collab'){field.value=P56.homeTime==='forenoon'?'day':P56.homeTime;}
}
const p56Background=gxBackground;
gxBackground=function(){return GX.room==='office'?'office_'+(P56.homeTime||p56Period())+'56':p56Background();};
const p56Image=gxImage;
gxImage=function(id){const im=p56Image(id);if(id!=='meeting_youngcheol56'||!im.complete||!im.naturalWidth)return im;if(!P55.normalized.has(id))P55.normalized.set(id,p55Normalize(im,1,1));return P55.normalized.get(id);};
const p56Action=onAction;
const p56GX=gxAction;
gxAction=function(action,el){
 if(['p50-review','chat-open'].includes(action)&&p50PanelKey(GX.panel)){
  const key=p50PanelKey(GX.panel);if(action==='p50-review'&&!p50Snapshot(key))return gxToast('먼저 '+P50_LABEL[key]+'을 실행해 주세요.');
  P50.chatKey=key;S.tab='chat';S.sub=key;GX.chat=true;GX.chatMin=false;GX.keys.clear();GX.path=[];return render();
 }
 return p56GX(action,el);
};
onAction=function(action,el){
 if(action==='mr35-to-agent'){
  const id=el.dataset.persona||S.myroom.agent||'kim';S.selectedRoles=[id];S.myroom.modal='';P52.teamList=false;S.modal=null;S.drawer=false;GX.panel=null;P49.selected=null;P55.active=null;P41.tab='none';P42.aiOpen=false;GX.keys.clear();GX.path=[];persist();return gxAction('chat-open',el);
 }
 if(action==='p56-settings'){callUI.settings56=!callUI.settings56;callUI.editing=callUI.settings56;return render();}
 if(action==='v33-edit')callUI.settings56=true;
 if(action==='v33-run'){callUI.settings56=false;const result=p56Action(action,el);if(callUI.runError){callUI.settings56=true;callUI.editing=true;render();}return result;}
 return p56Action(action,el);
};
function p56Monitor(feature){
 feature.classList.add('p56-monitor');feature.insertAdjacentHTML('beforeend','<div class="p56-bezel" aria-hidden="true"><b>WHAT IF</b><span class="p56-bezel-buttons"><i></i><i></i><i></i><em></em></span></div>');
 const main=feature.querySelector('.meeting-main'),shell=feature.querySelector('.meeting-shell'),strip=feature.querySelector('.meeting-participant-strip'),head=feature.querySelector('.gx-window-head');
 if(strip&&shell)shell.before(strip);
 const top=feature.querySelector('.meeting-topline');if(top){top.classList.add('p56-meeting-status');head?.append(top);}
 const assumptions=feature.querySelector('.call-assumptions');if(assumptions){assumptions.classList.add('p56-execution');assumptions.hidden=!callUI.settings56;const draft=feature.querySelector('.call-draft-controls');if(draft)draft.hidden=!callUI.settings56;const b=document.createElement('button');b.dataset.action='p56-settings';b.className='p56-execution-toggle';b.setAttribute('aria-expanded',String(!!callUI.settings56));b.textContent='⚙ 실행 설정';feature.querySelector('.p55-call-controls')?.append(b);}
 const tools=feature.querySelector('.meeting-toolbar'),ai=feature.querySelector('.meeting-ai-controls'),note=feature.querySelector('.meeting-connection-note');if(ai)shell?.after(ai);if(tools)(ai||shell)?.after(tools);if(note)(tools||ai||shell)?.after(note);
 const media=feature.querySelector('.p51-media-bar');if(media&&head)head.append(media);
 const title=head?.querySelector('h2');if(title)title.textContent='WHAT IF · 공동 분석';
 if(main)main.setAttribute('aria-label','공동 차트와 공유 자료');
}
const p56Render=render;
render=function(){
 p56Render();if(GX.phase!=='game')return;S.appVersion='5.6.0';const root=document.querySelector('.ui55');if(!root)return;root.classList.add('ui56');
 const controls=root.querySelector('.p41-scene-controls');if(controls){const field=controls.querySelector('#p41-time'),home=GX.room==='office'&&GX.panel!=='collab';if(field){field.disabled=home;field.title=home?'서울 실제 시간에 따라 자동 변경됩니다.':'개인실 시간대';}controls.insertAdjacentHTML('beforeend','<time class="p56-real-clock" aria-label="서울 실제 시간"></time>');}
 /* V5.7 restores the private-room HUD shortcut. */
 root.querySelectorAll('[data-action="v31-toggle-meeting"]').forEach(b=>{const on=b.getAttribute('aria-checked')==='true';b.classList.add('p56-holdings-toggle');b.insertAdjacentHTML('beforeend','<b class="p56-toggle-label">'+(on?'켜짐':'꺼짐')+'</b>');});
 const monitor=root.querySelector('.m48-computer');if(monitor)p56Monitor(monitor);p56Clock();
 const paired=p50PanelKey(GX.panel)&&GX.chat&&!GX.chatMin&&!S.modal&&!S.myroom.modal&&!GX.soundOpen,chat=root.querySelector('.gx-chat-window'),feature=root.querySelector('.p41-feature');root.classList.toggle('p56-analysis-chat',!!paired);
 P56.observer?.disconnect();
 if(paired&&chat&&feature){
  chat.inert=false;feature.inert=false;feature.setAttribute('aria-modal','false');
  if(!P42.manualChat){const w=Math.min(420,innerWidth*.38);Object.assign(chat.style,{left:innerWidth-w-12+'px',top:'44px',width:w+'px',height:innerHeight-88+'px'});}
  const sync=()=>root.style.setProperty('--p56-chat-space',Math.min(innerWidth*.65,chat.getBoundingClientRect().width)+28+'px');sync();P56.observer=new ResizeObserver(sync);P56.observer.observe(chat);
 }
};
for(const id of ['office_morning56','office_forenoon56','office_afternoon56','office_night56','meeting_youngcheol56'])gxImage(id);
setInterval(()=>p56Clock(),1000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)p56Clock();});
WHATIF_QA.wide56=()=>({period:P56.homeTime,background:gxBackground(),nicknameValid:p56ValidName(document.querySelector('#gx-nickname')?.value),picks:[...V45.picks],runs:V45.runs.length,clock:document.querySelector('.p56-real-clock')?.textContent,settings:!!callUI.settings56,assets:['morning','forenoon','afternoon','night'].every(k=>gxImage('office_'+k+'56').naturalWidth===1672),normalized:P55.normalized.has('meeting_youngcheol56'),names:ASSET_MASTER.slice(0,4).map(a=>a.name)});
WHATIF_QA.time56=iso=>p56Period(new Date(iso));
WHATIF_QA.clock56=iso=>{p56Clock(iso?new Date(iso):new Date());gxDraw(performance.now());};
WHATIF_QA.room56=room=>gxSetRoom(room);
WHATIF_QA.privateDoor56=()=>{Object.assign(GX.player,{x:1250,y:560});render();};
WHATIF_QA.invalidEntry56=()=>onAction('enter',document.createElement('button'));
