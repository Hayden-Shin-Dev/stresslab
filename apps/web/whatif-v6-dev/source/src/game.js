/* Incremental V4.0 adapter. Original finance, files, minutes and discussion code remains in scope. */
const GX_PREF='whatif-game-v4-prefs';
const gxStored=(()=>{try{return JSON.parse(localStorage.getItem(GX_PREF)||'{}')}catch{return {}}})();
const gxDemoSession=!!gxStored.demoSession||!!S.authenticated;
const GX={phase:gxDemoSession?'game':'splash',demoSession:gxDemoSession,room:'office',panel:null,chat:false,chatMin:false,playerKind:gxStored.playerKind==='female'?'female':'male',
  player:{x:752,y:816,dir:0,walking:false},path:[],keys:new Set(),npcs:[],roomPositions:{},sheet:'male',soundOpen:false,
  sound:{enabled:true,master:.38,music:.60,effects:.7,...gxStored.sound},window:gxStored.window||null,toast:'',last:0,nextWander:0};
const gxImages=new Map();
function gxImage(id){if(!gxImages.has(id)){const im=new Image();im.src=GX_ASSETS[id]||'';gxImages.set(id,im);}return gxImages.get(id);}
function gxSave(){try{localStorage.setItem(GX_PREF,JSON.stringify({sound:GX.sound,window:GX.window,playerKind:GX.playerKind,demoSession:!!GX.demoSession}));}catch{}}
const gxNames={office:'WHAT IF 본사',lab:'AI Agent 분석실',meeting:'함께 분석 · 회의실',myroom:'마이 룸 · 개인 자료실',lounge:'휴게실'};
const gxPeople=[{id:'kim',key:'youngho',name:'영호',role:'거시경제'},{id:'shin',key:'youngcheol',name:'영철',role:'리스크'},{id:'yoon',key:'youngsook',name:'영숙',role:'장중 시장상태'},{id:'kang',key:'oksoon',name:'옥순',role:'포트폴리오'}];
for(const p of gxPeople){
  const base=persona(p.id);base.name=p.name;base.role=p.role;
  base.avatar='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="76 18 104 112"><image width="1024" height="1024" href="${GX_ASSETS['sprite_'+p.key]}"/></svg>`);
  MR35.roleNames[p.id]=p.name;MR35.roleTitles[p.id]=p.role;
}
if(GX.demoSession){S.authenticated=true;GX.npcs=gxPeople.map((p,i)=>({...p,x:500+(i%2)*480,y:590+Math.floor(i/2)*180,dir:0,path:[],walking:false}));}
let gxAudio=null,gxMaster=null,gxMusicBus=null,gxFxBus=null,gxMusicTimer=null,gxMusicStep=0;
function gxAudioInit(){
  if(!GX.sound.enabled)return;
  try{if(!gxAudio){gxAudio=new(window.AudioContext||window.webkitAudioContext)();gxMaster=gxAudio.createGain();gxMusicBus=gxAudio.createGain();gxFxBus=gxAudio.createGain();gxMusicBus.connect(gxMaster);gxFxBus.connect(gxMaster);gxMaster.connect(gxAudio.destination);}gxAudio.resume().catch(()=>{});gxAudioLevels();if(!gxMusicTimer)gxMusicTimer=setInterval(gxMusicTick,410);}catch{GX.sound.enabled=false;}
}
function gxAudioLevels(){if(!gxMaster)return;const t=gxAudio.currentTime;gxMaster.gain.setTargetAtTime(GX.sound.enabled?GX.sound.master:0,t,.06);gxMusicBus.gain.setTargetAtTime(GX.sound.music,t,.06);gxFxBus.gain.setTargetAtTime(GX.sound.effects,t,.03);}
function gxTone(freq,duration,bus,type='triangle',level=.12){
  if(!gxAudio||!GX.sound.enabled||document.hidden)return;
  const t=gxAudio.currentTime,o=gxAudio.createOscillator(),g=gxAudio.createGain();o.type=type;o.frequency.value=freq;
  g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(level,t+.012);g.gain.exponentialRampToValueAtTime(.0001,t+duration);o.connect(g);g.connect(bus);o.start(t);o.stop(t+duration+.03);o.onended=()=>{o.disconnect();g.disconnect();};
}
function gxMusicTick(){
  if(!GX.sound.enabled||document.hidden||!gxAudio||gxAudio.state!=='running')return;
  const seq=[60,64,67,71,69,67,64,62,57,60,64,67,65,64,60,59];const n=seq[gxMusicStep%seq.length];
  gxTone(440*2**((n-69)/12),.65,gxMusicBus,'triangle',.07);
  if(gxMusicStep%4===0)gxTone(440*2**((n-24-69)/12),1.1,gxMusicBus,'sine',.1);gxMusicStep++;
}
function gxFx(kind='click'){gxAudioInit();if(!gxFxBus)return;const notes={click:660,door:392,success:880,step:140};gxTone(notes[kind]||660,kind==='success'?.24:.085,gxFxBus,kind==='step'?'triangle':'square',kind==='step'?.025:.045);}
function gxToast(s){GX.toast=s;clearTimeout(GX.toastTimer);render();GX.toastTimer=setTimeout(()=>{GX.toast='';document.querySelector('.gx-toast')?.remove()},3200);}
function gxButton(action,text,cl='gx-small',extra=''){return `<button type="button" class="${cl}" data-gx="${action}" ${extra}>${text}</button>`;}
function gxSetRoom(room){
  if(!(room in gxNames))room='office';GX.roomPositions[GX.room]={x:GX.player.x,y:GX.player.y};
  GX.room=room;const spawn=(room==='office'||room==='lab')?{x:752,y:816}:{x:752,y:928};
  Object.assign(GX.player,GX.roomPositions[room]||spawn,{walking:false,dir:3});GX.path=[];GX.keys.clear();GX.panel=null;GX.chat=false;GX.soundOpen=false;
  S.modal=null;S.drawer=false;S.myroom.modal='';S.screen=room==='myroom'?'myroom':'agent';S.tab=room==='meeting'?'collab':'chat';S.sub='scenario';
  const compact=room==='office'||room==='lab';GX.npcs=gxPeople.map((p,i)=>({...p,x:compact?500+(i%2)*480:360+i*285,y:compact?590+Math.floor(i/2)*180:912,dir:0,path:[],walking:false}));
  GX.nextWander=performance.now()+5000;gxFx('door');render();document.querySelector('.gx-stage')?.focus({preventScroll:true});
}
function gxHotspots(){
  if(GX.room==='office')return [
    {id:'lab',x:1010,y:430,stand:[990,530],name:'분석실',kind:'room',room:'lab'},
    {id:'meeting',x:1110,y:395,stand:[1070,500],name:'회의실',kind:'room',room:'meeting'},
    {id:'myroom',x:1110,y:575,stand:[1070,590],name:'개인 자료실',kind:'room',room:'myroom'},
    {id:'lounge',x:1110,y:790,stand:[1050,800],name:'휴게실',kind:'room',room:'lounge'},
    {id:'sim',x:765,y:445,stand:[765,550],name:'차트 시뮬레이터',kind:'sim'}];
  if(GX.room==='lab')return [
    {id:'sim',x:840,y:445,stand:[840,540],name:'차트 확대 · 실행 설정',kind:'sim'},
    {id:'meeting',x:1130,y:405,stand:[1070,500],name:'회의실',kind:'room',room:'meeting'},
    {id:'doc',x:405,y:570,stand:[440,600],name:'문서 분석',kind:'document'},
    {id:'news',x:1070,y:650,stand:[1020,675],name:'실시간 뉴스',kind:'news'},
    {id:'lounge',x:1130,y:795,stand:[1060,800],name:'휴게실',kind:'room',room:'lounge'},
    {id:'back',x:760,y:920,stand:[760,850],name:'본사로',kind:'room',room:'office'}];
  const common=[{id:'back',x:300,y:850,stand:[305,900],name:'본사로',kind:'room',room:'office'}];
  if(GX.room==='meeting')return [{id:'collab',x:800,y:820,stand:[800,900],name:'함께 분석 시작',kind:'collab'},{id:'minutes',x:1190,y:820,stand:[1190,900],name:'회의록',kind:'minutes'},...common];
  if(GX.room==='myroom')return [{id:'memo',x:800,y:810,stand:[800,900],name:'메모 · 개인 자료',kind:'tool',tool:'memo'},...common];
  return [{id:'rest',x:900,y:825,stand:[900,900],name:'잠깐 쉬기',kind:'rest'},...common];
}
function gxNear(h){return Math.hypot(GX.player.x-h.stand[0],GX.player.y-h.stand[1])<120;}
function gxUse(h){
  if(!h)return;if(!gxNear(h)){GX.path=gxPath(GX.room,GX.player,{x:h.stand[0],y:h.stand[1]});gxToast(h.name+' 쪽으로 이동합니다. 가까워지면 E 또는 상호작용 버튼을 선택하세요.');return;}
  gxFx('click');GX.keys.clear();GX.path=[];
  if(h.kind==='room')return gxSetRoom(h.room);
  if(h.kind==='rest')return gxToast('2008년의 커피 한 잔. 잠시 시장에서 눈을 떼어 보세요.');
  if(h.kind==='tool'){S.myroom.modal=h.tool;return render();}
  gxOpen(h.kind);
}
function gxOpen(panel){GX.panel=panel;GX.keys.clear();GX.path=[];S.modal=null;S.drawer=false;
  if(panel==='sim'){S.screen='agent';S.tab='chat';S.sub='scenario';C.setTarget(targetKey());}
  if(panel==='document'||panel==='news'){S.sub=panel;S.tab='chat';GX.chat=true;GX.chatMin=false;S.chatCollapsed=false;}
  if(panel==='minutes'){S.tab='minutes';S.screen='agent';}
  if(panel==='collab'){S.tab='collab';S.screen='agent';}
  render();
}
function gxChartHTML(){
  const pts=Array.from({length:46},(_,i)=>[45+i*15,177-Math.sin(i*.43)*19-i*.9+Math.cos(i*.9)*10]);
  return `<svg viewBox="0 0 760 220" role="img" aria-label="2008년 코스피 가상 차트, 예시 데이터"><rect width="760" height="220" fill="#101c30"/>${[50,90,130,170].map(y=>`<path d="M40 ${y}H730" stroke="#26394c"/>`).join('')}<text x="18" y="27" fill="#cde0ac" font-size="17">WHAT IF · KOSPI</text><text x="485" y="27" fill="#aebfd0" font-size="13">2008.10.31 · 가상 차트 / 예시 데이터</text><polyline points="${pts.map(p=>p.join(',')).join(' ')}" fill="none" stroke="#b6f500" stroke-width="3"/>${pts.filter((p,i)=>i%2===0).map(([x,y],i)=>`<rect x="${x-3}" y="${y+4}" width="5" height="${10+(i%4)*4}" fill="${i%3?'#df805b':'#4f9ec3'}" opacity=".7"/>`).join('')}<text x="45" y="212" fill="#8fa6bc" font-size="12">10.20</text><text x="668" y="212" fill="#8fa6bc" font-size="12">10.31</text></svg>`;
}
function gxBackground(){return GX.room==='lab'?'lab':GX.room==='meeting'?'meeting':GX.room==='myroom'?'myroom':GX.room==='lounge'?'lounge':'office';}
function gxSoundHTML(){return `<div class="gx-layer"><section class="gx-window gx-settings" role="dialog" aria-modal="true" aria-label="사운드 설정"><header class="gx-window-head"><h2>사운드 · 게임 설정</h2>${gxButton('sound-close','닫기')}</header><div class="gx-window-body"><label>사운드 ON / OFF<input id="gx-sound-enabled" type="checkbox" ${GX.sound.enabled?'checked':''}></label>${[['master','전체 음량'],['music','배경 음악'],['effects','효과음']].map(([key,label])=>`<label>${label}<input id="gx-volume-${key}" type="range" min="0" max="100" value="${Math.round(GX.sound[key]*100)}" aria-label="${label}"><output id="gx-value-${key}">${Math.round(GX.sound[key]*100)}%</output></label>`).join('')}${gxButton('sound-test','효과음 미리 듣기')}<p class="gx-sound-meta">오리지널 칩튠과 이동·선택·문 이동 효과음입니다. 첫 클릭 이후 재생되며 다른 탭으로 이동하면 일시 정지합니다. 설정은 이 브라우저에 저장됩니다.</p></div></section></div>`;}
function gxSheetHTML(){const keys=['male','female','youngho','youngcheol','youngsook','oksoon'];return `<div class="gx-sheet-nav">${keys.map((key,i)=>gxButton('sheet-select', ['남자 주인공','여자 주인공','영호','영철','영숙','옥순'][i],'gx-small',`data-key="${key}"`)).join('')}</div><img class="gx-gallery" src="${GX_ASSETS['sheet_'+GX.sheet]}" alt="캐릭터 시트"><p>실제 이동에는 동일 인물의 4방향 스프라이트 시트를 사용합니다.</p>`;}
function gxFeatureHTML(){
  if(!GX.panel)return '';let content='',title='';
  if(GX.panel==='sim'){title='차트 확대 · 시뮬레이션 실행 설정';content=`<div class="gx-sim-grid"><section>${marketTargetSelector()}${chartPanel({zoom:true})}${runSummary()}</section>${inlineSettings()}</div>${S.runError?`<p class="gx-error" role="alert">${E(S.runError)}</p>`:''}`;}
  else if(GX.panel==='document'){title='문서 자료실';content=docSection();}
  else if(GX.panel==='news'){title='뉴스 관측실';content=newsSection();}
  else if(GX.panel==='minutes'){title='회의 기록 보관실';content=meetingSection();}
  else if(GX.panel==='collab'){title='함께 분석 · 공동 회의';content=collabSection();}
  else if(GX.panel==='sheets'){title='WHAT IF 캐릭터 도감';content=gxSheetHTML();}
  else if(GX.panel==='account'){title='나의 프로필 · 보유 종목';content=accountPage();}
  return `<div class="gx-layer" data-gx-backdrop><section class="gx-window" role="dialog" aria-modal="true" aria-label="${title}"><header class="gx-window-head"><h2>${title}</h2><span class="gx-badge">2008 게임 공간 · 분석은 원본 시연 자료</span>${gxButton('feature-close','방으로 돌아가기 ×')}</header><div class="gx-window-body">${content}</div></section></div>`;
}
function gxChatHTML(){
  if(!GX.chat||GX.chatMin)return gxButton('chat-open','▣ AI 대화 열기','gx-small gx-chat-fab');
  const r=gxClampWindow(GX.window||{x:innerWidth-510,y:Math.min(190,innerHeight-610),w:480,h:580},innerWidth,innerHeight);GX.window=r;
  return `<section class="gx-chat-window" style="left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px" aria-label="이동 및 크기 조절 가능한 AI 대화창"><div class="gx-chat-grip"><strong>⠿ AI Agent · 대화 흐름</strong><span class="gx-drag-help">드래그 이동 / 우하단 크기</span><button data-gx="chat-reset" aria-label="대화창 위치 초기화">↺</button><button data-gx="chat-min" aria-label="대화창 최소화">−</button><button data-gx="chat-close" aria-label="대화창 닫기">×</button></div><nav class="gx-flow" aria-label="대화 단계">${gxButton('flow-conditions','① 조건 확인','')}${gxButton('flow-run','② 시뮬레이션','')}${gxButton('flow-evidence','③ 근거 확인','')}${gxButton('flow-question','④ 후속 질문','')}</nav>${chatPanel(['scenario','document','news'].includes(S.sub)?S.sub:'scenario')}</section>`;
}
const gxOldRender=render;
render=function(){
  const active=document.activeElement,focusKey=active?.dataset?.chatInput,sel=focusKey?active.selectionStart:null;
  S.appVersion='4.0.0';S.chatCollapsed=false;
  const app=document.querySelector('#app');if(!app)return;
  if(GX.phase!=='game'){
    app.innerHTML=`<div class="gx-launch"><img src="${GX_ASSETS[GX.phase==='splash'?'splash':'login']}" alt="${GX.phase==='splash'?'WHAT IF 시간여행 게임 스플래시':'2008년 WHAT IF 금융 사무실 로그인'}">${GX.phase==='splash'?`<div class="gx-splash-overlay">${gxButton('continue','PRESS ANY KEY · 시작하기','gx-start')}</div>`:`<div class="gx-login-cover"><small>WHAT IF : TIME INVESTOR · V4.0</small><h1>2008년으로</h1><p>미래를 기억하는 당신의 두 번째 투자 일지.<br>WHAT IF 회사의 문을 열어 보세요.</p><label>체험 닉네임<input id="gx-nickname" value="${E(S.profile?.name||'시간 여행자')}" maxlength="24"></label><div class="gx-character-select">${gxButton('player-male','남자 주인공','gx-small '+(GX.playerKind==='male'?'selected':''))}${gxButton('player-female','여자 주인공','gx-small '+(GX.playerKind==='female'?'selected':''))}</div>${gxButton('enter','로그인 · 체험 시작','gx-primary')}${gxButton('enter','게스트로 시작')}<p>로컬 체험 모드 · 실제 계정 인증 미연결<br>개인 정보나 입력값을 외부로 보내지 않습니다.</p>${gxButton('back-splash','← 타이틀로')}</div>`}<div class="gx-launch-sound">${gxButton('sound-open','♫ 사운드 설정')}</div><span class="gx-launch-note">2008 금융 시간여행 RPG · 이미지와 차트 수치는 예시</span>${GX.soundOpen?gxSoundHTML():''}</div>`;return;
  }
  const hs=gxHotspots();
  app.innerHTML=`<div class="gx-app"><header class="gx-header"><span class="gx-brand">WHAT IF</span><span class="gx-version">TIME INVESTOR · V4.0</span><span class="gx-time">2008.10.31 · ${gxNames[GX.room]}</span><span class="gx-spacer"></span>${gxButton('sheets','▧ 캐릭터 도감')}${gxButton('chat-open','▣ AI 대화')}${gxButton('sound-open',GX.sound.enabled?'♫ 사운드 ON':'♫ 사운드 OFF')}${gxButton('account','내 정보')}${gxButton('logout','타이틀')}</header><aside class="gx-rail" aria-label="전역 메뉴">${[['office','⌂','홈'],['meeting','♟','함께 분석'],['myroom','▣','마이 룸']].map(([key,icon,label])=>gxButton('room',`<b>${icon}</b><span>${label}</span>`,'',`data-room="${key}" aria-label="${label}" ${GX.room===key?'aria-current="page"':''}`)).join('')}${gxButton('sound-open','<b>⚙</b><span>설정</span>','gx-rail-bottom')}</aside><nav class="gx-tabs" aria-label="상위 게임 메뉴">${[['lab','분석실'],['meeting','회의실'],['myroom','개인 자료실'],['lounge','휴게실']].map(([key,label])=>gxButton('room',label,GX.room===key?'active':'',`data-room="${key}"`)).join('')}${gxButton('panel','문서 분석','', 'data-panel="document"')}${gxButton('panel','실시간 뉴스','', 'data-panel="news"')}${gxButton('panel','회의록','', 'data-panel="minutes"')}<small>WHAT IF 회사 · 2008년 사무실</small></nav><main class="gx-world"><div class="gx-stage" tabindex="0" aria-label="${gxNames[GX.room]}, 방향키 또는 WASD로 이동"><canvas width="1536" height="1024" aria-label="이동 가능한 2008년 사무실"></canvas><div class="gx-company">WHAT IF <small>금융 시나리오 연구소 · EST. 2008</small></div>${GX.room==='lab'?`<div class="gx-mapchart">${gxChartHTML()}</div>`:''}${hs.map(h=>gxButton('interact',h.name,'gx-hotspot '+(gxNear(h)?'ready':''),`data-hotspot="${h.id}" style="left:${h.x/15.36}%;top:${h.y/10.24}%" aria-label="${h.name} 상호작용"`)).join('')}${GX.room==='myroom'?`<div style="position:absolute;right:1%;top:14%;display:grid;gap:5px">${[['report','AI 리포트'],['minutes','회의록'],['sim','시뮬레이션'],['cloud','클라우드'],['memo','메모'],['agent','AI 팀원']].map(([id,label])=>gxButton('tool',label,'gx-small',`data-tool="${id}"`)).join('')}</div>`:''}</div></main><footer class="gx-footer"><span>WASD / 방향키 이동 · 바닥 클릭으로 걷기 · E 상호작용 · Esc 닫기</span><span id="gx-near-label">기계와 문 가까이 다가가 보세요.</span><span>로컬 데모 · 가상 시세 / 실제 주문 없음</span></footer>${gxFeatureHTML()}${gxChatHTML()}${modal()}${S.myroom.modal?mr35Modal():''}${GX.soundOpen?gxSoundHTML():''}${GX.toast?`<div class="gx-toast" role="status">${E(GX.toast)}</div>`:''}</div>`;
  document.querySelectorAll('svg[data-chart]').forEach(svg=>C.attach(svg,currentRun(),S.chartMode));attachHistoryInteractions();syncNewsSelection();syncPersonaPicker();
  if(GX.panel==='collab')mountCallMedia();if(S.myroom.modal==='memo'){mr36CanvasSetup();mr36RenderThumbs();}
  const zone=document.querySelector('#upload-zone');if(zone){zone.addEventListener('dragover',e=>e.preventDefault());zone.addEventListener('drop',e=>{e.preventDefault();const f=e.dataTransfer?.files[0];if(f)handleFile(f);});}
  const msg=document.querySelector('#chat-scroll');if(msg)msg.scrollTop=msg.scrollHeight;
  if(focusKey){const input=document.querySelector(`[data-chat-input="${focusKey}"]`);input?.focus({preventScroll:true});if(sel!==null)input?.setSelectionRange(sel,sel);}
  gxBindWindow();gxDraw(performance.now());
};
function gxBindWindow(){
  const win=document.querySelector('.gx-chat-window');if(!win)return;
  win.querySelector('.gx-chat-grip').addEventListener('pointerdown',e=>{if(e.target.closest('button'))return;const b=win.getBoundingClientRect(),dx=e.clientX-b.x,dy=e.clientY-b.y;const grip=e.currentTarget;grip.setPointerCapture(e.pointerId);
    const move=ev=>{const r=gxClampWindow({x:ev.clientX-dx,y:ev.clientY-dy,w:win.offsetWidth,h:win.offsetHeight},innerWidth,innerHeight);win.style.left=r.x+'px';win.style.top=r.y+'px';GX.window=r;};
    const up=()=>{grip.removeEventListener('pointermove',move);grip.removeEventListener('pointerup',up);grip.removeEventListener('pointercancel',up);gxSave();};grip.addEventListener('pointermove',move);grip.addEventListener('pointerup',up);grip.addEventListener('pointercancel',up);
  });
  if(window.ResizeObserver){const ro=new ResizeObserver(()=>{if(!win.isConnected){ro.disconnect();return;}const b=win.getBoundingClientRect();GX.window={x:b.x,y:b.y,w:b.width,h:b.height};});ro.observe(win);win.addEventListener('pointerup',gxSave);}
}
function gxDraw(now){
  if(GX.phase!=='game')return;const cv=document.querySelector('.gx-stage canvas');if(!cv)return;const c=cv.getContext('2d');c.imageSmoothingEnabled=false;
  const bg=gxImage(gxBackground());if(bg.complete&&bg.naturalWidth)c.drawImage(bg,0,0,1536,1024);else{c.fillStyle='#182a3e';c.fillRect(0,0,1536,1024);}
  if(GX.room==='office'||GX.room==='lab'){const im=gxImage('simulator');if(im.complete&&im.naturalWidth){const x=GX.room==='lab'?840:765;c.drawImage(im,x-94,300,188,188);}}
  const actors=[...GX.npcs,{...GX.player,key:GX.playerKind,name:'나',isPlayer:true}].sort((a,b)=>a.y-b.y);
  for(const a of actors){const im=gxImage('sprite_'+a.key);if(!im.complete||!im.naturalWidth)continue;const fr=a.walking?Math.floor(now/150)%4:0,sz=a.isPlayer?150:140;
    c.fillStyle='#07131c44';c.beginPath();c.ellipse(a.x,a.y+2,24,7,0,0,7);c.fill();c.drawImage(im,fr*256,a.dir*256,256,256,a.x-sz/2,a.y-sz*.90625,sz,sz);
    c.font='bold 14px Malgun Gothic';c.textAlign='center';const label=a.name;const w=c.measureText(label).width+18;c.fillStyle=a.isPlayer?'#b6f500':'#172b40e8';c.fillRect(a.x-w/2,a.y+13,w,25);c.fillStyle=a.isPlayer?'#172b40':'#e9edd7';c.fillText(label,a.x,a.y+31);
  }
}
function gxStepActor(a,dt){const t=a.path?.[0];a.walking=!!t;if(!t)return;const dx=t.x-a.x,dy=t.y-a.y,d=Math.hypot(dx,dy),step=Math.min(d,dt*(a===GX.player?210:70));if(d<2){a.path.shift();return;}a.x+=dx/d*step;a.y+=dy/d*step;a.dir=Math.abs(dx)>Math.abs(dy)?(dx<0?1:2):(dy<0?3:0);}
let gxLastStepSound=0;
function gxFrame(now){
  requestAnimationFrame(gxFrame);const dt=Math.min((now-(GX.last||now))/1000,.05);GX.last=now;
  if(GX.phase!=='game'||document.hidden)return;
  const blocked=GX.chatModal||GX.panel||GX.soundOpen||S.modal||S.myroom.modal||document.activeElement?.matches('input,textarea,select,[contenteditable="true"]');
  if(!blocked){
    let dx=0,dy=0;for(const k of GX.keys){if(k==='a'||k==='arrowleft')dx--;if(k==='d'||k==='arrowright')dx++;if(k==='w'||k==='arrowup')dy--;if(k==='s'||k==='arrowdown')dy++;}
    if(dx||dy){GX.path=[];const len=Math.hypot(dx,dy),nx=GX.player.x+dx/len*210*dt,ny=GX.player.y+dy/len*210*dt;if(gxWalkable(GX.room,nx,GX.player.y))GX.player.x=nx;if(gxWalkable(GX.room,GX.player.x,ny))GX.player.y=ny;GX.player.walking=true;GX.player.dir=Math.abs(dx)>Math.abs(dy)?(dx<0?1:2):(dy<0?3:0);}
    else{GX.player.path=GX.path;gxStepActor(GX.player,dt);}
    if(GX.player.walking&&now-gxLastStepSound>(GX.keys.has('shift')?190:320)){gxFx('step');gxLastStepSound=now;}
    if(now>GX.nextWander&&!S.preferences.reducedMotion){GX.npcs.forEach((a,i)=>{const t=gxNearest(GX.room,430+((now/15+i*170)%620),GX.room==='office'||GX.room==='lab'?540+(i%2)*230:920);a.path=gxPath(GX.room,a,t);});GX.nextWander=now+14000;}
    if(!S.preferences.reducedMotion)GX.npcs.forEach(a=>gxStepActor(a,dt));
  }else GX.player.walking=false;
  for(const h of gxHotspots()){const b=document.querySelector(`[data-hotspot="${h.id}"]`);b?.classList.toggle('ready',gxNear(h));}
  const near=gxHotspots().find(gxNear),label=document.querySelector('#gx-near-label');if(label)label.textContent=near?'[E] '+near.name:'바닥 클릭으로 이동할 수 있습니다.';
  gxDraw(now);
}
function gxAction(action,el){
  if(action!=='sound-open'&&action!=='sound-close')gxFx();
  if(action==='continue'){GX.phase='login';gxAudioInit();return render();}
  if(action==='back-splash'){GX.phase='splash';return render();}
  if(action==='enter'){const name=document.querySelector('#gx-nickname')?.value.trim();if(name)S.profile.name=name.slice(0,24);S.authenticated=true;GX.demoSession=true;GX.phase='game';gxSave();persist();return gxSetRoom('office');}
  if(action==='player-male'||action==='player-female'){GX.playerKind=action.slice(7);gxSave();return render();}
  if(action==='room')return gxSetRoom(el.dataset.room);
  if(action==='interact')return gxUse(gxHotspots().find(h=>h.id===el.dataset.hotspot));
  if(action==='panel'){const p=el.dataset.panel;if(p==='document'||p==='news')gxSetRoom('lab');else if(p==='minutes')gxSetRoom('meeting');return gxOpen(p);}
  if(action==='feature-close'){GX.panel=null;S.modal=null;S.drawer=false;return render();}
  if(action==='sound-open'){GX.soundOpen=true;GX.keys.clear();return render();}
  if(action==='sound-close'){GX.soundOpen=false;gxSave();return render();}
  if(action==='sound-test')return gxFx('success');
  if(action==='chat-open'){GX.chat=true;GX.chatMin=false;S.chatCollapsed=false;return render();}
  if(action==='chat-min'){GX.chatMin=true;return render();}
  if(action==='chat-close'){GX.chat=false;return render();}
  if(action==='chat-reset'){GX.window=null;return render();}
  if(action==='sheets'){GX.panel='sheets';return render();}
  if(action==='sheet-select'){GX.sheet=el.dataset.key;return render();}
  if(action==='account'){GX.panel='account';S.accountTab='profile';return render();}
  if(action==='tool'){S.myroom.modal=el.dataset.tool;GX.keys.clear();return render();}
  if(action==='logout'){pauseDiscussion();GX.demoSession=false;S.authenticated=false;gxSave();persist();GX.phase='splash';GX.panel=null;GX.chat=false;GX.keys.clear();return render();}
  if(action==='flow-conditions'||action==='flow-run')return gxOpen('sim');
  if(action==='flow-evidence'){if(currentRun()){S.detailTab='evidence';S.modal='detail';return render();}return gxToast('시뮬레이션을 먼저 실행하면 해당 실행의 근거를 확인할 수 있습니다.');}
  if(action==='flow-question'){document.querySelector('[data-chat-input]')?.focus();return;}
}
const gxPriorAction=onAction;
onAction=function(action,el){
  if(action==='enter'){GX.phase='game';S.authenticated=true;GX.demoSession=true;gxSave();return gxSetRoom('office');}
  if(action==='home')return gxSetRoom('office');
  if(action==='main-collab')return gxSetRoom('meeting');
  if(action==='mr35-enter')return gxSetRoom('myroom');
  if(action==='ai-agent'||action==='sub-scenario'){gxSetRoom('lab');return;}
  if(action==='tab-chat'){gxSetRoom('lab');return;}
  if(action==='tab-minutes'||action==='open-minute'){GX.panel='minutes';}
  if(action==='sub-document'){GX.panel='document';GX.chat=true;}
  if(action==='sub-news'){GX.panel='news';GX.chat=true;}
  if(action==='run-sim'){const count=S.runs.length;GX.panel='sim';const result=gxPriorAction(action,el);if(S.runs.length>count){gxFx('success');GX.chat=true;render();}return result;}
  if(action==='logout'){GX.demoSession=false;S.authenticated=false;gxSave();persist();GX.phase='splash';GX.panel=null;GX.chat=false;}
  return gxPriorAction(action,el);
};
document.addEventListener('click',e=>{const b=e.target.closest('[data-gx]');if(b){e.preventDefault();e.stopImmediatePropagation();gxAction(b.dataset.gx,b);}},true);
document.addEventListener('pointerdown',e=>{
  const cv=e.target.closest('.gx-stage canvas');if(!cv||GX.chatModal||GX.panel||GX.soundOpen||S.modal||S.myroom.modal)return;const r=cv.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*1536,y=(e.clientY-r.top)/r.height*1024;
  const npc=GX.npcs.find(a=>Math.hypot(a.x-x,a.y-50-y)<65);if(npc){S.myroom.agent=npc.id;S.myroom.modal='agent';GX.keys.clear();render();return;}
  GX.path=gxPath(GX.room,GX.player,{x,y});cv.parentElement.focus({preventScroll:true});
});
document.addEventListener('keydown',e=>{
  if(document.querySelector('dialog[data-stock-prices][open]'))return;
  if(GX.phase==='splash'&&!GX.soundOpen&&!['Tab','Shift','Control','Alt','Meta'].includes(e.key)){e.preventDefault();e.stopImmediatePropagation();return gxAction('continue',e.target);}
  if(GX.phase==='login'){if(e.key==='Enter'&&!GX.soundOpen){e.preventDefault();gxAction('enter',e.target);}return;}
  if(GX.phase!=='game')return;if(e.target.closest('.p43-companion-hit')&&['Enter',' '].includes(e.key))return;const k=e.key.toLowerCase();
  if(k==='escape'){
    e.preventDefault();e.stopImmediatePropagation();if(GX.soundOpen)GX.soundOpen=false;else if(S.myroom.modal)S.myroom.modal='';else if(S.modal)S.modal=null;else if(GX.panel)GX.panel=null;else if(GX.chat)GX.chat=false;GX.keys.clear();return render();
  }
  if(e.target.matches('input,textarea,select,[contenteditable="true"]')||GX.chatModal||GX.panel||GX.soundOpen||S.modal||S.myroom.modal)return;
  if(['w','a','s','d','arrowup','arrowleft','arrowdown','arrowright'].includes(k)){e.preventDefault();GX.keys.add(k);}
  if((k==='e'||k==='enter')&&!e.repeat){e.preventDefault();const h=gxHotspots().find(gxNear);if(h)gxUse(h);else gxToast('먼저 기계나 문 가까이 다가가 주세요.');}
},true);
document.addEventListener('keyup',e=>GX.keys.delete(e.key.toLowerCase()));
window.addEventListener('blur',()=>{GX.keys.clear();gxSave();});
window.addEventListener('resize',()=>{if(GX.window)GX.window=gxClampWindow(GX.window,innerWidth,innerHeight);if(GX.phase==='game')render();});
document.addEventListener('input',e=>{if(e.target.id?.startsWith('gx-volume-')){const k=e.target.id.slice(10);if(['master','music','effects'].includes(k)){GX.sound[k]=Math.min(1,Math.max(0,Number(e.target.value)/100));document.querySelector('#gx-value-'+k).textContent=e.target.value+'%';gxAudioLevels();gxSave();}}});
document.addEventListener('change',e=>{if(e.target.id==='gx-sound-enabled'){GX.sound.enabled=e.target.checked;if(GX.sound.enabled)gxAudioInit();gxAudioLevels();gxSave();}});
document.addEventListener('visibilitychange',()=>{GX.keys.clear();if(document.hidden)gxAudio?.suspend().catch(()=>{});else if(GX.sound.enabled&&gxAudio)gxAudio.resume().catch(()=>{});});
window.addEventListener('pagehide',()=>{gxSave();if(gxMusicTimer)clearInterval(gxMusicTimer);gxAudio?.close().catch(()=>{});});
requestAnimationFrame(gxFrame);
