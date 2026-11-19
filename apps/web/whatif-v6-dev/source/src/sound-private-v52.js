/* V5.2: supplied WAV effects, independent preferences, private-room tools. */
const P52={buffers:{},loading:null,foot:null,footGain:null,clicks:new Set(),lastClick:-Infinity,counts:{click:0,step:0},teamList:true,lastPosition:null};
GX.sound.click=Number.isFinite(GX.sound.click)?Math.max(0,Math.min(1,GX.sound.click)):.55;
GX.sound.step=Number.isFinite(GX.sound.step)?Math.max(0,Math.min(1,GX.sound.step)):.50;
function p52Load(){
 if(!gxAudio)return Promise.resolve();
 if(!P52.loading)P52.loading=Promise.all(['click','step'].map(async key=>{const r=await fetch(GX_SFX[key]);if(!r.ok)throw new Error('Sound load failed');P52.buffers[key]=await gxAudio.decodeAudioData(await r.arrayBuffer());})).catch(()=>{P52.loading=null;});
 return P52.loading;
}
function p52Audible(key){return !!(gxAudio&&GX.sound.enabled&&GX.sound.master>0&&GX.sound.effects>0&&GX.sound[key]>0&&!document.hidden);}
function p52Click(){
 const now=performance.now();if(now-P52.lastClick<35)return;P52.lastClick=now;
 gxAudioInit();if(!p52Audible('click'))return;
 p52Load().then(()=>{if(!p52Audible('click')||performance.now()-now>500||!P52.buffers.click)return;
  const source=gxAudio.createBufferSource(),gain=gxAudio.createGain();source.buffer=P52.buffers.click;gain.gain.value=GX.sound.click;source.connect(gain);gain.connect(gxFxBus);P52.clicks.add({source,gain});const item=[...P52.clicks].at(-1);P52.counts.click++;
  source.onended=()=>{P52.clicks.delete(item);source.disconnect();gain.disconnect();};source.start();
 });
}
function p52StopFoot(){if(!P52.foot)return;const source=P52.foot,gain=P52.footGain;P52.foot=null;P52.footGain=null;try{gain.gain.cancelScheduledValues(gxAudio.currentTime);gain.gain.setTargetAtTime(0,gxAudio.currentTime,.012);source.stop(gxAudio.currentTime+.055);}catch{}}
function p52Foot(walking){
 if(!walking||!p52Audible('step'))return p52StopFoot();
 if(!P52.buffers.step){p52Load();return;}
 if(!P52.foot){const source=gxAudio.createBufferSource(),gain=gxAudio.createGain();source.buffer=P52.buffers.step;source.loop=true;gain.gain.value=0;source.connect(gain);gain.connect(gxFxBus);P52.foot=source;P52.footGain=gain;P52.counts.step++;source.onended=()=>{source.disconnect();gain.disconnect();};source.start();}
 P52.foot.playbackRate.setTargetAtTime(GX.keys.has('shift')?1.35:1,gxAudio.currentTime,.04);
 P52.footGain.gain.setTargetAtTime(GX.sound.step,gxAudio.currentTime,.02);
}
// All button events pass window capture before older document handlers.
window.addEventListener('click',e=>{const b=e.target.closest('button,[role="button"],input[type="button"],input[type="submit"]');if(b&&!b.disabled&&b.getAttribute('aria-disabled')!=='true')p52Click();},true);
gxFx=function(kind='click'){if(kind==='click')p52Click();};
const p52Levels=gxAudioLevels;
gxAudioLevels=function(){p52Levels();if(!p52Audible('step'))p52StopFoot();for(const {gain}of P52.clicks)gain.gain.setTargetAtTime(GX.sound.click,gxAudio.currentTime,.02);};
const p52Frame=gxFrame;
gxFrame=function(now){p52Frame(now);const p=GX.player,previous=P52.lastPosition;P52.lastPosition={x:p.x,y:p.y};const moved=previous&&Math.hypot(p.x-previous.x,p.y-previous.y)>.02;
 p52Foot(performance.now()<(P52.previewUntil||0)||moved&&p.walking&&GX.phase==='game'&&!GX.panel&&!GX.soundOpen&&!S.modal&&!S.myroom.modal&&!GX.chatModal&&!S.myroom.paused);
};
document.addEventListener('visibilitychange',()=>{if(document.hidden)p52StopFoot();});
window.addEventListener('blur',()=>{GX.keys.clear();GX.path=[];p52StopFoot();});
window.addEventListener('pagehide',p52StopFoot);
gxSoundHTML=function(){const slider=(key,label)=>`<label class="p52-sound-row" for="gx-volume-${key}"><span>${label}</span><input id="gx-volume-${key}" type="range" min="0" max="100" value="${Math.round(GX.sound[key]*100)}" aria-label="${label}"><output id="gx-value-${key}">${Math.round(GX.sound[key]*100)}%</output></label>`;return `<div class="gx-layer"><section class="gx-window gx-settings" role="dialog" aria-modal="true" aria-label="사운드 설정"><header class="gx-window-head"><h2>사운드 설정</h2>${gxButton('sound-close','x 닫기')}</header><div class="gx-window-body"><label>사운드 ON / OFF<input id="gx-sound-enabled" type="checkbox" ${GX.sound.enabled?'checked':''}></label>${slider('master','전체 음량')}${slider('music','배경 음악')}${slider('effects','효과음 전체')}<h3>개별 효과음</h3>${slider('click','버튼 클릭음')}${slider('step','캐릭터 발걸음')}<div class="p52-sound-tests">${gxButton('p52-test-click','버튼음 미리 듣기')}${gxButton('p52-test-step','발걸음 미리 듣기')}</div><p class="gx-sound-meta">각 음량은 전체·효과음 음량과 함께 적용됩니다. 0%로 설정하면 해당 효과음만 꺼집니다. 설정은 이 브라우저에 저장됩니다.</p></div></section></div>`;};
document.addEventListener('input',e=>{if(!['gx-volume-click','gx-volume-step'].includes(e.target.id))return;const key=e.target.id.slice(10);GX.sound[key]=Number(e.target.value)/100;const out=document.querySelector('#gx-value-'+key);if(out)out.textContent=e.target.value+'%';gxAudioLevels();gxSave();});
const p52Action=gxAction,p52OnAction=onAction,p52AgentPanel=mr35AgentPanel;
gxAction=function(action,el){
 if(action==='tool'&&el.dataset.tool==='agent')P52.teamList=true;
 if(action==='p52-test-click')return;
 if(action==='p52-test-step'){gxAudioInit();return p52Load().then(()=>{P52.previewUntil=performance.now()+900;p52Foot(true);setTimeout(p52StopFoot,900);});}
 if(action==='sound-close'){P52.previewUntil=0;p52StopFoot();}
 return p52Action(action,el);
};
onAction=function(action,el){
 if(action==='mr35-open'&&el.dataset.panel==='agent')P52.teamList=true;
 if(action==='mr35-agent')P52.teamList=false;
 if(action==='p52-team-list'){P52.teamList=true;return render();}
 if(action==='p52-team-detail'){P52.teamList=false;S.myroom.agent=el.dataset.persona;return render();}
 return p52OnAction(action,el);
};
mr35AgentPanel=function(){if(!P52.teamList)return `<button class="p52-team-back" data-action="p52-team-list">← AI 팀원 목록</button>`+p52AgentPanel();return mr35Heading('AI 팀원','WHAT IF 시장분석팀 · 팀원을 선택해 역할을 확인하세요.')+`<div class="p52-team-list">${gxPeople.map(a=>{const p=persona(a.id);return `<button class="p52-team-card" data-action="p52-team-detail" data-persona="${a.id}"><img src="${p.avatar}" alt=""><span><strong>${E(a.name)}</strong><small>${E(a.role)}</small><em>프로필 보기 →</em></span></button>`;}).join('')}</div>`;};
const p52Render=render;
render=function(){P52.previewUntil=0;p52StopFoot();p52Render();document.querySelector('.p41-app')?.classList.add('ui52');if(GX.phase==='game')S.appVersion='5.2.0';};
window.WHATIF_QA.sound52=()=>({levels:{...GX.sound},counts:{...P52.counts},loaded:Object.keys(P52.buffers),durations:Object.fromEntries(Object.entries(P52.buffers).map(([k,b])=>[k,b.duration])),footPlaying:!!P52.foot,footRate:P52.foot?.playbackRate.value,teamList:P52.teamList});
