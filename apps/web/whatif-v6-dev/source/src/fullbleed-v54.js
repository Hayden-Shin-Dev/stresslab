/* Shared cover camera keeps backgrounds, actors and hit targets in the same world space. */
const F54={meetingX:.54,drag:null,lastRoom:null,camera:null};
const f54Clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
function f54Cover(vw,vh,bw,bh,fx,fy,anchorY=.70,zoom=1){
 const scale=Math.max(vw/bw,vh/bh)*zoom,width=bw*scale,height=bh*scale;
 return {scale,width,height,x:f54Clamp(vw*.5-fx*scale,vw-width,0),y:f54Clamp(vh*anchorY-fy*scale,vh-height,0),vw,vh,bw,bh};
}
function f54Place(el,c){const key=[c.width,c.height,c.x,c.y].join('|');if(el._f54Position===key)return;el._f54Position=key;el.style.setProperty('--f54-scene-width',c.width+'px');el.style.setProperty('--f54-scene-height',c.height+'px');Object.assign(el.style,{width:c.width+'px',height:c.height+'px',left:c.x+'px',top:c.y+'px'});}
function f54Sync(){
 if(GX.phase!=='game')return;const world=document.querySelector('.ui54 .gx-world');if(!world)return;
 const vw=world.clientWidth,vh=world.clientHeight;
 if(GX.panel==='collab'&&M48.view==='room'){
  const stage=world.querySelector('.m48-room-stage');if(!stage)return;
  const c=f54Cover(vw,vh,1672,941,1672*F54.meetingX,941*.56,.56);f54Place(stage,c);F54.camera={...c,kind:'meeting'};
  const controls=document.querySelector('.f54-pan-controls');if(controls)controls.hidden=c.width<=vw+1;
  return;
 }
 const stage=world.querySelector('.gx-stage');if(!stage)return;
 const c=f54Cover(vw,vh,1536,864,GX.player.x,GX.player.y,.70,S.myroom.expanded?1.12:1);f54Place(stage,c);F54.camera={...c,kind:GX.room};
 // Off-screen scene targets remain available as directional HUD shortcuts.
 const nav=document.querySelector('.f54-waypoints');if(nav){
  const enabled=!GX.panel&&!S.modal&&!S.myroom.modal&&!GX.soundOpen&&!GX.chatModal;
  const off=enabled?gxHotspots().filter(h=>h.id!=='myroom'&&(()=>{const x=c.x+h.x*c.scale,y=c.y+h.y*c.scale;return x<90||x>vw-100||y<170||y>vh-130;})()):[];
  const key=off.map(h=>h.id).join('|');if(nav.dataset.key!==key){nav.dataset.key=key;nav.innerHTML=off.map(h=>gxButton('interact',`<span>${E(h.name)}</span><b aria-hidden="true">${c.x+h.x*c.scale<vw/2?'←':'→'}</b>`,'f54-waypoint',`data-hotspot="${h.id}"`)).join('');}nav.hidden=!off.length;
 }
}
const f54Render=render,f54Frame=gxFrame,f54GX=gxAction;
gxAction=function(action,el){
 
 if(action==='room'&&el.dataset.room==='meeting')F54.meetingX=.54;
 return f54GX(action,el);
};
render=function(){
 f54Render();if(GX.phase!=='game')return;const root=document.querySelector('.ui53');if(!root)return;root.classList.add('ui54');root.style.setProperty('--f54-meeting-image',`url("${GX_ASSETS.meeting_room48}")`);root.classList.remove('ap47-chat-docked');S.appVersion='5.4.0';
 const blocked=!!(GX.panel||S.modal||S.myroom.modal||GX.soundOpen);
 for(const node of root.querySelectorAll('.gx-stage>.p41-dock,.gx-stage>.p41-scene-controls')){root.append(node);node.inert=blocked;}
 const zoom=root.querySelector('[data-gx="expand-world"]');if(zoom)zoom.textContent=S.myroom.expanded?'기본 배율':'추가 확대';
 if(innerWidth<=650){const subs=root.querySelector('.p41-subtabs');if(subs){root.append(subs);subs.inert=blocked;}}
 if(GX.panel==='collab'&&M48.view==='room'){
  const tools=root.querySelector('.m48-room-tools');if(tools){tools.classList.add('f54-meeting-tools');}
 }else if(!GX.panel){const nav=document.createElement('nav');nav.className='f54-waypoints';nav.setAttribute('aria-label','화면 밖 상호작용 안내');root.append(nav);}
 f54Sync();
};
gxFrame=function(now){f54Frame(now);f54Sync();};
window.addEventListener('resize',()=>f54Sync());
WHATIF_QA.fullbleed54=()=>({camera:F54.camera?{...F54.camera}:null,meetingX:F54.meetingX,waypoints:[...document.querySelectorAll('.f54-waypoint')].map(b=>b.dataset.hotspot),player:{x:GX.player.x,y:GX.player.y},version:S.appVersion});
