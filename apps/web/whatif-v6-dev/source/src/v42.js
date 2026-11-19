const P42={manualChat:false,interactionAt:0};
const p42SetRoom=gxSetRoom,p42Open=gxOpen,p42Render=render,p42Action=gxAction,p42OnAction=onAction,p42Frame=gxFrame,p42Step=gxStepActor;
const p42Settings=settingsPage;
settingsPage=function(){return p42Settings().replace('WHAT IF V3.2','WHAT IF V4.2');};
function p42Spot(others=[]){for(let i=0;i<80;i++){const p=gxNearest('office',400+Math.random()*850,430+Math.random()*290);if(p&&others.every(a=>Math.hypot(a.x-p.x,a.y-p.y)>130))return p;}return gxNearest('office',700,600);}
gxSetRoom=function(room){P42.aiOpen=false;const r=p42SetRoom(room);const spawn=gxNearest(GX.room,GX.player.x,GX.player.y);if(spawn)Object.assign(GX.player,spawn);if(GX.room==='office'){const used=[];for(const [i,a] of GX.npcs.entries()){Object.assign(a,p42Spot(used),{path:[],next:Infinity,idleStart:P41.jobClock,actAt:P41.jobClock+4300+i*1700+Math.random()*1800,speed:.75+Math.random()*.6});used.push(a);}gxDraw(performance.now());}return r;};
gxOpen=function(panel){P42.aiOpen=['sim','document','news'].includes(panel);GX.soundOpen=false;return p42Open(panel);};
gxStepActor=function(a,dt){return p42Step(a,a===GX.player?dt:dt*(a.speed||1));};
gxFrame=function(now){const blocked=GX.chatModal||GX.panel||GX.soundOpen||S.modal||S.myroom.modal||S.myroom.paused||document.hidden||document.activeElement?.matches('input,textarea,select');const reduce=S.preferences.reducedMotion||matchMedia('(prefers-reduced-motion:reduce)').matches;
 if(GX.phase==='game'&&!blocked&&!reduce)for(const a of GX.npcs){a.next=Infinity;if(a.path.length){a.wasMoving=true;}else if(a.wasMoving){a.wasMoving=false;a.idleStart=P41.jobClock;a.actAt=P41.jobClock+4300+Math.random()*6500;}else if(P41.jobClock>=a.actAt){const target=p59Destination(a);a.path=gxPath('office',a,target);a.wasMoving=true;a.actAt=Infinity;}}
 p42Frame(now);
};
gxDraw=function(now){if(GX.phase!=='game')return;const cv=document.querySelector('.gx-stage canvas');if(!cv)return;const c=cv.getContext('2d');c.imageSmoothingEnabled=false;const bg=gxImage(gxBackground());c.fillStyle='#142438';c.fillRect(0,0,1536,864);if(bg.complete&&bg.naturalWidth)c.drawImage(bg,0,0,1536,864);
 const tint={morning:'#ffca8712',day:'#ffecb109',afternoon:'#aa649614',night:'#06113c33'};if(GX.room==='myroom'){c.fillStyle=tint[S.myroom.time]||tint.day;c.fillRect(0,0,1536,864);}
 for(const a of [...GX.npcs,{...GX.player,key:GX.playerKind,name:'나',isPlayer:true},...(GX.companion?[{...GX.companion,isCompanion:true}]:[])].sort((a,b)=>a.y-b.y)){if(a.isCompanion){ppukkuDraw(c,a,now);continue;}const idle=!a.isPlayer&&!a.walking&&!a.path.length,im=gxImage((idle?'idle_':'sprite_')+a.key);if(!im.complete||!im.naturalWidth)continue;const size=GX.room==='myroom'?300:150;let frame=0;if(idle){let t=((P41.jobClock-(a.idleStart||0))%4500+4500)%4500;const times=[600,350,500,500,700,500,400,500].map(t=>t/0.9);while(frame<7&&t>=times[frame])t-=times[frame++];}else frame=a.walking?Math.floor(now/160)%4:0;
 c.fillStyle='#07131c44';c.beginPath();c.ellipse(a.x,a.y,22,7,0,0,7);c.fill();c.save();if(a.isPlayer&&typeof P58!=='undefined'&&P58.arrival)c.globalAlpha=Math.max(0,Math.min(1,(now-P58.arrival.at-450)/900));if(typeof p49Glowing==='function'&&p49Glowing(a.id))c.filter=P49_GLOW;c.drawImage(im,frame*256,idle?0:a.dir*256,256,256,a.x-size/2,a.y-size*.90625,size,size);c.restore();c.font=(a.isPlayer?'bold 14px ':'14px ')+'Pretendard';c.textAlign='center';c.fillStyle=a.isPlayer?'#fff29a':'#f2e5c8';c.shadowColor=a.isPlayer?'#292015':'transparent';c.shadowBlur=a.isPlayer?3:0;c.fillText(a.isPlayer?(S.profile.name||'나'):a.name,a.x,a.y+24);c.shadowBlur=0;}
};
const p42Use=gxUse;
gxUse=function(h){if(GX.panel||S.modal||S.myroom.modal||GX.soundOpen)return;if(performance.now()-P42.interactionAt<350)return;P42.interactionAt=performance.now();return p42Use(h);};
gxAction=function(action,el){
 if(['sheets','sheet-select'].includes(action))return;
 if(action==='chat-open'){gxFx('click');GX.chat=true;GX.chatMin=false;return render();}
 if(action==='chat-reset'){gxFx('click');P42.manualChat=false;GX.window=null;return render();}
 if(action==='account'){GX.soundOpen=false;S.modal=null;S.myroom.modal='';}
 if(action==='tool'){GX.panel=null;S.modal=null;S.drawer=false;GX.soundOpen=false;}
 if(action==='sound-open'){GX.panel=null;S.modal=null;S.drawer=false;S.myroom.modal='';}
 if(action==='logout'){S.authenticated=false;S.collab.started=false;S.collab.queue=[];pauseDiscussion();stopCallMedia();GX.path=[];GX.keys.clear();}
 return p42Action(action,el);
};
onAction=function(action,el){
 if(action==='v31-account-page'){GX.panel='account';S.accountTab=el.dataset.tab==='holdings'?'quickholdings':el.dataset.tab;S.modal=null;S.myroom.modal='';return render();}
 if(action==='signout')return gxAction('logout',el);
 return p42OnAction(action,el);
};
accountPage=function(){const tab=S.accountTab||'profile';const quick='<section class="p42-account-summary"><h2>내 종목 한눈에 보기</h2><p>등록 '+S.holdings.length+'개 · 개인 보관 내역</p>'+(S.holdings.length?'<ul>'+S.holdings.slice(0,5).map(h=>'<li><b>'+E(h.name)+'</b><span>'+(h.mode==='quantity'?Number(h.quantity).toLocaleString('ko-KR')+'주':won(h.amount))+'</span></li>').join('')+'</ul>':'<p>등록한 종목이 없습니다.</p>')+gxButton('panel','내 보유종목 관리로 이동','gx-small','data-panel="holdings"')+'</section>';
 return '<div class="account-layout"><aside class="panel account-nav">'+userAvatar('lg')+'<strong>'+E(S.profile.name)+'</strong>'+[['profile','프로필'],['holdings','내 종목 요약'],['settings','설정']].map(([id,label])=>'<button data-action="v31-account-page" data-tab="'+id+'">'+label+'</button>').join('')+gxButton('logout','로그아웃')+'</aside><div class="account-content">'+(tab==='quickholdings'?quick:tab==='settings'?settingsPage():profilePage())+'</div></div>';
};
function p42LayoutChat(){const w=document.querySelector('.gx-chat-window'),world=document.querySelector('.gx-world');if(!w||!world)return;const area=world.getBoundingClientRect();if(!P42.manualChat){const width=Math.min(420,innerWidth-90),height=Math.max(300,area.height);Object.assign(w.style,{left:Math.max(70,innerWidth-width-12)+'px',top:area.top+'px',width:width+'px',height:height+'px'});GX.window={x:parseFloat(w.style.left),y:area.top,w:width,h:height};}
}
gxBindWindow=function(){P41.observer?.disconnect();const w=document.querySelector('.gx-chat-window');if(!w)return;
 const begin=(e,edge)=>{if(!edge&&e.target.closest('button'))return;e.preventDefault();P42.manualChat=true;const initial=w.getBoundingClientRect(),sx=e.clientX,sy=e.clientY,grip=e.currentTarget;grip.setPointerCapture(e.pointerId);
  const move=ev=>{let x=initial.x,y=initial.y,width=initial.width,height=initial.height,dx=ev.clientX-sx,dy=ev.clientY-sy;if(!edge){x+=dx;y+=dy;}else{if(edge.includes('e'))width+=dx;if(edge.includes('s'))height+=dy;if(edge.includes('w')){width-=dx;x+=dx;}if(edge.includes('n')){height-=dy;y+=dy;}}width=Math.min(innerWidth-80,Math.max(280,width));height=Math.min(innerHeight-12,Math.max(300,height));x=Math.max(65,Math.min(x,innerWidth-width-4));y=Math.max(4,Math.min(y,innerHeight-height-4));Object.assign(w.style,{left:x+'px',top:y+'px',width:width+'px',height:height+'px'});GX.window={x,y,w:width,h:height};};
  const end=()=>{grip.removeEventListener('pointermove',move);grip.removeEventListener('pointerup',end);grip.removeEventListener('pointercancel',end);gxSave();};grip.addEventListener('pointermove',move);grip.addEventListener('pointerup',end);grip.addEventListener('pointercancel',end);
 };
 w.querySelector('.gx-chat-grip').addEventListener('pointerdown',e=>begin(e,''));
 for(const edge of ['n','e','s','w','ne','nw','se','sw']){const handle=document.createElement('div');handle.className='p42-resize p42-'+edge;handle.dataset.edge=edge;handle.setAttribute('aria-label','챗봇 '+edge+' 크기 조절');handle.addEventListener('pointerdown',e=>begin(e,edge));w.appendChild(handle);}
};
render=function(){p42Render();if(GX.phase!=='game')return;S.appVersion='4.2.0';const root=document.querySelector('.p41-app');root?.classList.add('p42-app');root?.setAttribute('data-agent-open',String(!!P42.aiOpen&&P41.tab==='agent'));if(!P42.aiOpen)document.querySelector('.p41-main-tabs [data-panel="sim"]')?.classList.remove('active');document.querySelectorAll('[data-gx="sheets"]').forEach(e=>e.remove());
 document.querySelectorAll('[data-gx="chat-open"]').forEach(e=>e.innerHTML=p41Icon(16)+'<span>AI 챗봇</span>');const help=document.querySelector('.p41-chat-foot small');if(help)help.textContent='제목 끌기 · 창 테두리에서 크기 조절';p42LayoutChat();
};
const p42Fx=gxFx;
gxFx=function(kind='click'){if(kind!=='step')return p42Fx(kind);gxAudioInit();if(!gxAudio||!GX.sound.enabled)return;gxTone(110,.045,gxFxBus,'triangle',.018);};
document.addEventListener('click',e=>{if(e.target.closest('button[data-action]'))gxFx('click');},true);
window.WHATIF_QA.open=panel=>gxOpen(panel);
window.WHATIF_QA.world=()=>({player:{...GX.player},playerKind:GX.playerKind,actorSize:GX.room==='myroom'?300:150,npcs:GX.npcs.map(a=>({id:a.id,x:a.x,y:a.y,walking:a.walking,actAt:a.actAt,path:a.path.length})),chat:GX.window});
