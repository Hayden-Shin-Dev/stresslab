/* V4.9 keeps finance and meeting contracts; this layer owns entry and affordances. */
const P49={loading:false,hover:null,selected:null,authOpen:false,videoError:false};
const P49_GLOW='drop-shadow(0 0 2px #fffde4) drop-shadow(0 0 5px #ffe28b) drop-shadow(0 0 9px #e8a53d)';
function p49Glowing(id){return !!id&&(P49.hover===id||P49.selected===id);}
function p49Name(value){return Array.from(String(value??'').normalize('NFC').replace(/[\u0000-\u001f\u007f]/g,'').trim()).slice(0,5).join('');}
const p49Persist=persist;
persist=function(){S.profile.name=p49Name(S.profile.name)||'시간여행자';return p49Persist();};
const p49Profile=profilePage;
profilePage=function(){return p49Profile().replace('maxlength="24"','maxlength="5"');};
const p49Render=render,p49Action=gxAction,p49OnAction=onAction,p49Draw=gxDraw;
function p49Progress(video){
 const duration=video.duration,ratio=Number.isFinite(duration)&&duration>0?Math.min(1,video.currentTime/duration):0,percent=Math.floor(ratio*100);
 const bar=document.querySelector('.p49-progress');if(bar){bar.setAttribute('aria-valuenow',percent);bar.querySelector('i').style.width=ratio*100+'%';}
 const status=document.querySelector('.p49-progress-text');if(status)status.textContent=Number.isFinite(duration)?`${percent}% · ${Math.min(video.currentTime,duration).toFixed(1)} / ${duration.toFixed(1)}초`:'영상을 준비하고 있습니다';
}
function p49Finish(){if(!P49.loading)return;P49.loading=false;P49.videoError=false;GX.phase='game';P49.selected=null;gxSetRoom('office');}
function p49Loading(){
 if(document.querySelector('.p49-loading'))return;
 document.querySelector('#app').innerHTML=`<main class="p49-loading" aria-label="2008년으로 시간 이동"><div class="p49-video-wrap"><video id="p49-travel-video" playsinline preload="auto" poster="${GX_ASSETS.splash48}" aria-label="타임머신 이동 영상"></video><button class="p49-video-play" hidden>영상 재생</button><div class="p49-video-error" hidden role="alert"><p>영상을 재생하지 못했습니다.</p><button data-gx="p49-video-retry">다시 재생</button><button data-gx="p49-back-login">로그인으로</button></div></div><footer><strong>2008년 WHAT IF 사무실로 이동 중</strong><div class="p49-progress" role="progressbar" aria-label="시간 이동 영상 진행률" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i></i></div><span class="p49-progress-text" aria-live="off">영상을 준비하고 있습니다</span><button data-gx="p49-video-sound">${GX.sound.enabled?'영상 소리 끄기':'영상 소리 켜기'}</button></footer></main>`;
 const video=document.querySelector('#p49-travel-video'),play=document.querySelector('.p49-video-play');video.src=GX_MEDIA.travel;video.muted=!GX.sound.enabled;video.volume=GX.sound.master;gxAudio?.suspend().catch(()=>{});
 const update=()=>{if(!video.isConnected||!P49.loading)return;p49Progress(video);requestAnimationFrame(update);};requestAnimationFrame(update);
 const attempt=()=>{play.hidden=true;video.play().catch(()=>{if(video.isConnected&&!video.error)play.hidden=false;});};play.addEventListener('click',attempt);
 video.addEventListener('loadedmetadata',()=>p49Progress(video));video.addEventListener('timeupdate',()=>p49Progress(video));video.addEventListener('ended',()=>{p49Progress(video);p49Finish();});
 video.addEventListener('error',()=>{if(!P49.loading||!video.isConnected)return;P49.videoError=true;play.hidden=true;document.querySelector('.p49-video-error').hidden=false;});attempt();
}
function p49Start(){
 if(P49.loading)return;const input=document.querySelector('#gx-nickname');if(!p56ValidName(input?.value)){P55.loginError='닉네임은 1–5글자, 한글·영문·숫자로 입력해 주세요.';return render();}S.profile.name=p49Name(input?.value||M48.nick||S.profile.name)||'시간여행자';M48.nick=S.profile.name;S.authenticated=true;persist();gxSave();GX.keys.clear();GX.path=[];GX.soundOpen=false;GX.phase='travel';P49.loading=true;render();
}
gxAction=function(action,el){
 if(action==='enter')return p49Start();
 if(action==='p49-google'){P49.authOpen=true;return render();}
 if(action==='p49-google-close'){P49.authOpen=false;return render();}
 if(action==='p49-video-sound'){GX.sound.enabled=!GX.sound.enabled;gxSave();const v=document.querySelector('#p49-travel-video');if(v)v.muted=!GX.sound.enabled;el.textContent=GX.sound.enabled?'영상 소리 끄기':'영상 소리 켜기';return;}
 if(action==='p49-video-retry'){P49.videoError=false;document.querySelector('.p49-video-error').hidden=true;const v=document.querySelector('#p49-travel-video');v.load();v.play().catch(()=>document.querySelector('.p49-video-play').hidden=false);return;}
 if(action==='p49-back-login'){P49.loading=false;document.querySelector('#p49-travel-video')?.pause();GX.phase='login';return render();}
 if(action==='p49-persona'){P49.selected=el.dataset.persona;GX.keys.clear();GX.path=[];S.myroom.agent=el.dataset.persona;S.myroom.modal='agent';return render();}
 if(action==='m48-people'&&el.dataset.glow)P49.selected=el.dataset.glow;
 if(action==='ppukku-chat'){P49.selected='ppukku';if(GX.panel==='collab'){M48.view='computer';if(!S.collab.started)gxAction('m48-start',el);}}
 if(['chat-close','feature-close','logout','room'].includes(action))P49.selected=null;
 return p49Action(action,el);
};
onAction=function(action,el){if(action==='enter')return p49Start();if(action==='mr35-close')P49.selected=null;return p49OnAction(action,el);};
function p49SyncHits(){const stage=document.querySelector('.gx-stage');if(!stage)return;for(const a of GX.npcs){const b=stage.querySelector(`[data-gx="p49-persona"][data-persona="${a.id}"]`);if(b){b.style.left=a.x/1536*100+'%';b.style.top=a.y/864*100+'%';b.classList.toggle('p49-selected',p49Glowing(a.id));}}}
gxDraw=function(now){p49Draw(now);p49SyncHits();};
function p49AuthModal(){return `<div class="p49-auth-shade"><section role="dialog" aria-modal="true" aria-label="Google 로그인 설정"><h2>Google 로그인</h2><p>Google 계정 연결을 사용하려면 서비스의 OAuth 클라이언트 ID와 승인된 로그인 주소를 설정해 주세요.</p><button data-gx="p49-google-close">확인</button></section></div>`;}
render=function(){
 if(P49.loading){p49Loading();return;}
 S.profile.name=p49Name(S.profile.name)||'시간여행자';if(S.profileEditName!=null)S.profileEditName=p49Name(S.profileEditName);if(M48.nick!=null)M48.nick=p49Name(M48.nick);
 p49Render();
 if(GX.phase==='login'){
  const art=document.querySelector('.m48-art img');if(art)art.src=GX_ASSETS.login49;
  const card=document.querySelector('.m48-login-card');card.querySelectorAll('[data-gx="enter"]').forEach((b,i)=>{if(i)b.remove();else b.textContent='로그인';});card.querySelector('.m48-local')?.remove();
  const field=document.querySelector('#gx-nickname');field.maxLength=5;field.value=p49Name(field.value);field.setAttribute('aria-describedby','p49-name-help');field.previousSibling.textContent='사용자 이름';
  const help=document.createElement('small');help.id='p49-name-help';help.textContent='1–5글자 · 한글, 영문, 숫자만 사용';field.after(help);
  const google=document.createElement('button');google.type='button';google.className='p49-google';google.dataset.gx='p49-google';google.textContent='Google로 로그인';card.querySelector('[data-gx="enter"]').after(google);
  if(P49.authOpen){document.querySelector('#app').insertAdjacentHTML('beforeend',p49AuthModal());document.querySelector('[data-gx="p49-google-close"]').focus();}
 }
 if(GX.phase!=='game')return;
 const root=document.querySelector('.ui48');root?.classList.add('ui49');
 root?.querySelectorAll('.gx-rail [data-room]').forEach(b=>{const active=b.dataset.room===(GX.panel==='collab'?'meeting':GX.room);b.classList.toggle('p49-nav-active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');b.setAttribute('aria-pressed',String(active));});
 const stage=document.querySelector('.gx-stage');if(stage){for(const a of GX.npcs){const b=document.createElement('button');b.type='button';b.className='p49-persona-hit';b.dataset.gx='p49-persona';b.dataset.persona=a.id;b.dataset.glow=a.id;b.setAttribute('aria-label',a.name+' 프로필 보기');stage.append(b);}const pet=stage.querySelector('.p43-companion-hit');if(pet)pet.dataset.glow='ppukku';p49SyncHits();}
 if(GX.panel==='collab'&&M48.view==='room'){document.querySelectorAll('.m48-name').forEach((b,i)=>b.dataset.glow=['kim','yoon','shin','kang'][i]);document.querySelector('.m48-desk')?.setAttribute('aria-label','회의 컴퓨터 화면 확대');const b=document.createElement('button');b.type='button';b.className='p49-meeting-pet';b.dataset.gx='ppukku-chat';b.dataset.glow='ppukku';b.setAttribute('aria-label','뿌꾸 AI 챗봇 열기');document.querySelector('.m48-room-stage')?.append(b);}
};
document.addEventListener('input',e=>{if(['gx-nickname','profile-name'].includes(e.target.id)&&!e.isComposing){const v=p49Name(e.target.value);if(e.target.value!==v)e.target.value=v;if(e.target.id==='gx-nickname')M48.nick=v;else S.profileEditName=v;}},true);
document.addEventListener('compositionend',e=>{if(['gx-nickname','profile-name'].includes(e.target.id)){e.target.value=p49Name(e.target.value);if(e.target.id==='gx-nickname')M48.nick=e.target.value;else S.profileEditName=e.target.value;}},true);
document.addEventListener('pointerover',e=>{const hit=e.target.closest('[data-glow]');if(hit)P49.hover=hit.dataset.glow;},true);
document.addEventListener('pointerout',e=>{if(e.target.closest('[data-glow]')&&!e.relatedTarget?.closest('[data-glow]'))P49.hover=null;},true);
document.addEventListener('focusin',e=>{if(e.target.dataset.glow)P49.hover=e.target.dataset.glow;});
document.addEventListener('focusout',e=>{if(e.target.dataset.glow)P49.hover=null;});
window.addEventListener('pointerdown',e=>{const hit=e.target.closest('.p49-persona-hit');if(!hit||GX.panel||GX.soundOpen||S.modal||S.myroom.modal||GX.chatModal)return;e.preventDefault();e.stopImmediatePropagation();gxAction('p49-persona',hit);},true);
window.addEventListener('keydown',e=>{if(P49.loading){if(e.key==='Escape')e.preventDefault();e.stopImmediatePropagation();}else if(P49.authOpen){if(e.key==='Escape'){P49.authOpen=false;render();}if(e.key==='Tab'){e.preventDefault();document.querySelector('[data-gx="p49-google-close"]')?.focus();}e.stopImmediatePropagation();}},true);
window.WHATIF_QA.travel49=()=>({loading:P49.loading,phase:GX.phase,hover:P49.hover,selected:P49.selected,name:S.profile.name,video:document.querySelector('#p49-travel-video')?{currentTime:document.querySelector('#p49-travel-video').currentTime,duration:document.querySelector('#p49-travel-video').duration,paused:document.querySelector('#p49-travel-video').paused}:null});
