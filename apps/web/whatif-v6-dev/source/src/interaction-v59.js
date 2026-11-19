/* V5.9: explicit navigation, camera-only self view, reserved NPC stop points. */
const P59={gap:158,guideSprite:null,skipped:0};
persona('shin').avatar=GX_ASSETS.portrait_youngcheol59;
function p59Actors(){return [...GX.npcs,P58.guide];}
function p59Destination(actor){
 const others=p59Actors().filter(a=>a!==actor),occupied=others.flatMap(a=>[{x:a.x,y:a.y},a.path?.at(-1)||a.stop59||{x:a.x,y:a.y}]).concat([{x:GX.player.x,y:GX.player.y}]);
 const free=p=>p&&gxWalkable('office',p.x,p.y)&&occupied.every(o=>Math.hypot(p.x-o.x,p.y-o.y)>=P59.gap);
 let target=null;for(let n=0;n<140;n++){const p=gxNearest('office',415+Math.random()*830,425+Math.random()*305);if(free(p)&&Math.hypot(p.x-actor.x,p.y-actor.y)>80){target=p;break;}}
 if(!target){const candidates=[];for(let x=405;x<=1270;x+=45)for(let y=425;y<=735;y+=35){const p=gxNearest('office',x,y);if(free(p))candidates.push(p);}target=candidates.sort((a,b)=>Math.hypot(b.x-actor.x,b.y-actor.y)-Math.hypot(a.x-actor.x,a.y-actor.y))[0];}
 target=target||(actor.stop59&&others.every(o=>{const q=o.path?.at(-1)||o.stop59||o;return Math.hypot(actor.stop59.x-q.x,actor.stop59.y-q.y)>=P59.gap;})?{...actor.stop59}:{x:actor.x,y:actor.y});actor.stop59={...target};return target;
}
const p59Room=gxSetRoom;
gxSetRoom=function(room){const out=p59Room(room);if(GX.room==='office'&&GX.panel!=='collab'){P58.guide.path=[];P58.guide.stop59={x:P58.guide.x,y:P58.guide.y};for(const a of p59Actors()){const close=p59Actors().some(o=>o!==a&&Math.hypot(a.x-o.x,a.y-o.y)<P59.gap);if(close){Object.assign(a,p59Destination(a),{path:[],walking:false});}a.stop59={x:a.x,y:a.y};}render();}return out;};
p58Guide=function(now,c){
 const a=P58.guide,dt=Math.min(.05,Math.max(0,(now-P58.lastDraw)/1000));P58.lastDraw=now;
 const blocked=GX.panel||GX.chatModal||GX.soundOpen||S.modal||S.myroom.modal||P58.arrival||document.hidden||now<(P58.guideHoldUntil||0)||Math.hypot(GX.player.x-a.x,GX.player.y-a.y)<150,reduce=S.preferences.reducedMotion||matchMedia('(prefers-reduced-motion:reduce)').matches;
 if(!blocked&&!reduce){if(!a.path.length&&now>a.next){a.path=gxPath('office',a,p59Destination(a));a.next=now+4500+Math.random()*7000;}gxStepActor(a,dt);}else a.walking=false;
 const walk=a.walking&&a.path.length>0,id=walk?'qa_walk59_source':'qa_idle57',im=gxImage(id);if(!im.complete||!im.naturalWidth)return;
 const cache=walk?'qa_walk59':'qa_idle57';if(!P55.normalized.has(cache))P55.normalized.set(cache,p55Normalize(im,4,walk?4:2,walk?4:8));const atlas=P55.normalized.get(cache),frame=walk?Math.floor(now/180)%4:Math.floor(now/650)%8,row=walk?a.dir:0;P59.guideSprite={asset:id,frame,row,walking:!!walk};
 c.save();if(P49.hover==='guide58')c.filter=P49_GLOW;c.drawImage(atlas,frame*256,row*256,256,256,a.x-75,a.y-136,150,150);c.restore();
 c.save();if(p510BubbleVisible(now)){const bubble=gxImage('speech_bubble');if(bubble.complete&&bubble.naturalWidth)c.drawImage(bubble,a.x-111,a.y-183,222,68);else{c.fillStyle='#fff4d6';c.fillRect(a.x-111,a.y-183,222,57);c.strokeStyle='#8d6b40';c.strokeRect(a.x-111,a.y-183,222,57);}c.font='bold 17px Pretendard';c.textAlign='center';c.fillStyle='#3b3026';c.fillText('무엇이든 물어보세요',a.x,a.y-152,192);}c.font='bold 14px Pretendard';c.lineWidth=3;c.strokeStyle='#332e27';c.strokeText('QA 안내원',a.x,a.y+24);c.fillStyle='#fff1ca';c.fillText('QA 안내원',a.x,a.y+24);c.restore();
 const hit=document.querySelector('.p58-guide-hit'),spot=document.querySelector('[data-hotspot=qa57]');if(hit){hit.style.left=a.x/15.36+'%';hit.style.top=(a.y-65)/8.64+'%';}if(spot){spot.style.left=a.x/15.36+'%';spot.style.top=(a.y+55)/8.64+'%';spot.textContent='E · 서비스 안내';}
};
const p59Spots=gxHotspots;gxHotspots=function(){return p59Spots().map(h=>h.id==='qa57'?{...h,y:P58.guide.y+55}:h);};
const p59Loading=p49Loading;
p49Loading=function(){p59Loading();const page=document.querySelector('.p49-loading');if(page&&!page.querySelector('[data-gx=p59-skip-video]'))page.insertAdjacentHTML('beforeend','<button type="button" class="p59-skip-video" data-gx="p59-skip-video">영상 건너뛰기 ⏭</button>');};
function p59OpenScenario(){P55.active='agent';P41.tab='agent';M48.view='room';GX.chat=false;GX.chatMin=false;return gxOpen('sim');}
const p59GX=gxAction;
gxAction=function(action,el){
 if(action==='p58-guide'||action==='interact'&&el?.dataset.hotspot==='qa57'){P58.guide.path=[];P58.guide.stop59={x:P58.guide.x,y:P58.guide.y};for(const a of GX.npcs){const end=a.path?.at(-1);if(end&&Math.hypot(end.x-P58.guide.x,end.y-P58.guide.y)<P59.gap)a.path=gxPath('office',a,p59Destination(a));}}
 if(action==='p59-skip-video'){if(!P49.loading)return;P59.skipped++;const video=document.querySelector('#p49-travel-video');if(video){video.pause();video.removeAttribute('src');video.load();}p49Finish();if(GX.sound.enabled)gxAudio?.resume().catch(()=>{});return;}
 if(action==='p57-scenario-shortcut'){if(S.modal||S.myroom.modal||GX.soundOpen)return;if(GX.panel==='collab'&&S.collab.started){M48.exit={panel:'sim'};return onAction('v33-leave',el);}if(GX.panel==='collab'){stopCallMedia();pauseDiscussion();GX.panel=null;}return p59OpenScenario();}
 return p59GX(action,el);
};
const p59Action=onAction;
onAction=function(action,el){const next=action==='v33-confirm-leave'?M48.exit?.panel:null;const result=p59Action(action,el);if(next==='sim')return p59OpenScenario();return result;};
function p59Camera(root){root.querySelectorAll('.human-tile:not(.demo-human)').forEach(tile=>{const video=tile.querySelector('#meeting-self-video'),avatar=tile.querySelector('.meeting-avatar');if(!video)return;tile.dataset.camera=callUI.camera?'on':'off';video.hidden=!callUI.camera;if(avatar){avatar.hidden=!!callUI.camera;avatar.setAttribute('aria-hidden',String(!!callUI.camera));}if(callUI.camera&&video.srcObject!==callUI.camera){video.srcObject=callUI.camera;video.play().catch(()=>{});}else if(!callUI.camera&&video.srcObject)video.srcObject=null;});}
const p59Render=render;
render=function(){if(GX.phase==='game'){S.myroom.paused=false;S.myroom.expanded=false;}p59Render();if(GX.phase!=='game')return;S.appVersion='5.9.0';const root=document.querySelector('.ui58');if(!root)return;root.classList.add('ui59');root.querySelectorAll('.p58-time-note,[data-gx=motion],[data-gx=expand-world]').forEach(e=>e.remove());p59Camera(root);
 const secondary=!!(S.modal||S.myroom.modal||GX.soundOpen),rail=root.querySelector('.gx-rail');root.classList.toggle('p59-rail-free',!!GX.panel&&!secondary);if(rail){rail.inert=secondary;const selected=GX.panel==='sim';rail.querySelectorAll('[data-room]').forEach(b=>{if(selected){b.classList.remove('p49-nav-active');b.setAttribute('aria-pressed','false');b.removeAttribute('aria-current');}});const shortcut=rail.querySelector('[data-gx=p57-scenario-shortcut]');if(shortcut){shortcut.inert=secondary;shortcut.setAttribute('aria-pressed',String(selected));shortcut.classList.toggle('p49-nav-active',selected);if(selected)shortcut.setAttribute('aria-current','page');else shortcut.removeAttribute('aria-current');}}
 if(GX.room==='myroom'){const b=root.querySelector('[data-tool=minutes]');if(b){b.innerHTML='<img class="p55-slot-art p59-archive-slot" src="'+GX_ASSETS.menu_archive59+'" alt="2 문서함">';b.title='2 문서함';b.setAttribute('aria-label','2 문서함');}const card=root.querySelector('.mr35-modal-card');if(card&&S.myroom.modal==='minutes')card.querySelectorAll('.mr35-pill').forEach(e=>{if(e.textContent.trim()==='예시 회의록')e.remove();});}
};
gxImage('qa_walk59_source');
WHATIF_QA.interaction59=()=>({gap:P59.gap,skipped:P59.skipped,guideSprite:P59.guideSprite,portrait:persona('shin').avatar,actors:p59Actors().map(a=>({id:a.id||'guide',x:a.x,y:a.y,walking:a.walking,path:a.path?.length||0,target:a.path?.at(-1)||a.stop59||{x:a.x,y:a.y}}))});
WHATIF_QA.plan59=()=>{for(const a of p59Actors())a.path=gxPath('office',a,p59Destination(a));return WHATIF_QA.interaction59();};
WHATIF_QA.guideDirection59=dir=>{const a=P58.guide;GX.panel=null;GX.chat=false;GX.chatModal=false;P58.guideHoldUntil=0;Object.assign(GX.player,{x:1250,y:730});Object.assign(a,{x:650,y:600,dir,path:[{x:650+(dir===1?-150:dir===2?150:0),y:600+(dir===3?-150:dir===0?120:0)}]});gxDraw(performance.now());return WHATIF_QA.interaction59();};

WHATIF_QA.qaAtlas59=()=>P55.normalized.get('qa_walk59')?.toDataURL('image/png')||null;
