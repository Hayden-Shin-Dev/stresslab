/* PPUKKU is the chatbot's companion interface; the four analyst roles stay intact. */
const P43={clock:0,last:0,trail:[],planAt:0,chasing:false,greetingUntil:0,frame:0,mode:'idle_01_blink'};
const ppukkuIdles=['idle_01_blink','idle_02_tail','idle_03_thinking','idle_04_calculator','idle_05_chart','idle_06_greeting','idle_07_stretch','idle_08_sleepy'];
const ppukkuBaseRoom=gxSetRoom,ppukkuBaseFrame=gxFrame,ppukkuBaseRender=render,ppukkuBaseAction=gxAction;
function ppukkuSpawn(){
 const p=GX.player,candidates=[[-96,0],[96,0],[0,96],[0,-96]].map(([x,y])=>gxNearest(GX.room,p.x+x,p.y+y)).filter(Boolean);
 const point=candidates.find(a=>Math.hypot(a.x-p.x,a.y-p.y)>72)||candidates[0]||{x:p.x,y:p.y};
 GX.companion={...point,dir:0,walking:false,path:[]};P43.trail=[{x:p.x,y:p.y}];P43.chasing=false;P43.planAt=0;P43.greetingUntil=P43.clock+3200;
}
gxSetRoom=function(room){const value=ppukkuBaseRoom(room);ppukkuSpawn();gxDraw(performance.now());return value;};
function ppukkuTrailTarget(){
 let distance=0;for(let i=P43.trail.length-1;i>0;i--){const a=P43.trail[i],b=P43.trail[i-1];distance+=Math.hypot(a.x-b.x,a.y-b.y);if(distance>=85)return b;}
 return P43.trail[0]||GX.player;
}
function ppukkuFollow(dt){
 const pet=GX.companion,p=GX.player;if(!pet)return;
 const previous=P43.trail.at(-1);if(!previous||Math.hypot(p.x-previous.x,p.y-previous.y)>=12){P43.trail.push({x:p.x,y:p.y});if(P43.trail.length>160)P43.trail.shift();}
 const distance=Math.hypot(p.x-pet.x,p.y-pet.y);
 if(distance>118)P43.chasing=true;
 if(distance<76){P43.chasing=false;pet.path=[];}
 if(!P43.chasing){pet.walking=false;return;}
 if(P43.clock>=P43.planAt){pet.path=gxPath(GX.room,pet,ppukkuTrailTarget());while(pet.path[0]&&Math.hypot(pet.path[0].x-pet.x,pet.path[0].y-pet.y)<18)pet.path.shift();P43.planAt=P43.clock+420;}
 let budget=dt*(distance>240?310:260);pet.walking=false;
 while(budget>0&&pet.path.length){const next=pet.path[0],dx=next.x-pet.x,dy=next.y-pet.y,d=Math.hypot(dx,dy);if(d<1){pet.path.shift();continue;}const step=Math.min(d,budget),x=pet.x+dx/d*step,y=pet.y+dy/d*step;if(!gxWalkable(GX.room,x,y)){pet.path=[];P43.planAt=0;break;}pet.x=x;pet.y=y;pet.walking=true;pet.dir=Math.abs(dx)>Math.abs(dy)?(dx<0?1:2):(dy<0?3:0);budget-=step;if(step===d)pet.path.shift();}
 if(!pet.path.length&&distance<125)P43.chasing=false;
}
gxFrame=function(now){
 const dt=Math.min(Math.max((now-(P43.last||now))/1000,0),.05);P43.last=now;
 if(GX.phase==='game'&&!document.hidden){if(!GX.companion)ppukkuSpawn();const paused=S.myroom.paused,blocked=GX.chatModal||GX.panel||GX.soundOpen||S.modal||S.myroom.modal||document.activeElement?.matches('input,textarea,select,[contenteditable="true"]');if(!paused)P43.clock+=dt*1000;if(!paused&&!blocked)ppukkuFollow(dt);else GX.companion.walking=false;}
 ppukkuBaseFrame(now);
};
function ppukkuVisual(now){
 const reduce=S.preferences.reducedMotion||matchMedia('(prefers-reduced-motion:reduce)').matches;
 const busy=Object.values(P41.pending).some(a=>a.scope===p41Scope());let mode;
 if(GX.companion?.walking)mode='walk';else if(busy)mode=GX.panel==='sim'?'idle_05_chart':'idle_04_calculator';else if(P43.clock<P43.greetingUntil)mode='idle_06_greeting';else mode=ppukkuIdles[Math.floor(P43.clock*.9/4800)%ppukkuIdles.length];
 const frame=reduce||S.myroom.paused?0:mode==='walk'?Math.floor(now/135)%4:Math.floor(P43.clock*.9/600)%8;
 P43.mode=mode;P43.frame=frame;return{mode,frame,busy};
}
function ppukkuDraw(c,pet,now){
 const {mode,frame,busy}=ppukkuVisual(now),im=gxImage('ppukku_'+mode);if(!im.complete||!im.naturalWidth)return;
 const size=GX.room==='myroom'?192:96;c.fillStyle='#07131c44';c.beginPath();c.ellipse(pet.x,pet.y,17,5,0,0,Math.PI*2);c.fill();
 c.save();if(typeof p49Glowing==='function'&&p49Glowing('ppukku'))c.filter=P49_GLOW;c.drawImage(im,frame*256,mode==='walk'?pet.dir*256:0,256,256,pet.x-size/2,pet.y-size*.90625,size,size);c.restore();
 c.font='14px Galmuri';c.textAlign='center';c.fillStyle='#c2f4ed';c.fillText(busy?'뿌꾸 · 분석 중':'뿌꾸',pet.x,pet.y+19);ppukkuSyncHit();
}
function ppukkuSyncHit(){const hit=document.querySelector('.p43-companion-hit'),pet=GX.companion;if(!hit||!pet)return;hit.style.left=pet.x/15.36+'%';hit.style.top=pet.y/8.64+'%';}
gxAction=function(action,el){
 if(action==='ppukku-chat'){gxFx('click');GX.keys.clear();GX.path=[];GX.chat=true;GX.chatMin=false;P43.greetingUntil=P43.clock+3200;return render();}
 if(action==='chat-open')P43.greetingUntil=P43.clock+3200;
 return ppukkuBaseAction(action,el);
};
render=function(){ppukkuBaseRender();if(GX.phase!=='game')return;const root=document.querySelector('.p42-app');root?.classList.add('p43-app');
 const stage=document.querySelector('.gx-stage');if(stage){const hit=document.createElement('button');hit.type='button';hit.className='p43-companion-hit';hit.dataset.gx='ppukku-chat';hit.setAttribute('aria-label','뿌꾸 · AI 챗봇 열기');hit.title='뿌꾸를 눌러 AI 챗봇 열기';hit.innerHTML='<span>뿌꾸 · AI 챗봇</span>';stage.appendChild(hit);ppukkuSyncHit();}
 const grip=document.querySelector('.gx-chat-grip'),title=grip?.querySelector('strong');if(title){const portrait=document.createElement('img');portrait.src=GX_ASSETS.ppukku_portrait;portrait.alt='뿌꾸';portrait.className='p43-chat-face';grip.insertBefore(portrait,title);title.textContent=p41Scope().startsWith('collab/')?'뿌꾸 · 회의 대화':'뿌꾸 · AI 챗봇';}
 document.querySelectorAll('[data-gx="chat-open"] .p41-icon').forEach(im=>{im.src=GX_ASSETS.ppukku_portrait;im.alt='뿌꾸';});const welcome=document.querySelector('.gx-chat-window .chat-welcome-copy>h3');if(welcome)welcome.textContent='뿌꾸가 분석을 도와드릴게요';
};
window.WHATIF_QA.companion=()=>({x:GX.companion?.x,y:GX.companion?.y,dir:GX.companion?.dir,walking:GX.companion?.walking,path:GX.companion?.path.length,mode:P43.mode,frame:P43.frame,clock:P43.clock,size:GX.room==='myroom'?192:96,distance:GX.companion?Math.hypot(GX.player.x-GX.companion.x,GX.player.y-GX.companion.y):0,walkable:GX.companion?gxWalkable(GX.room,GX.companion.x,GX.companion.y):false});
