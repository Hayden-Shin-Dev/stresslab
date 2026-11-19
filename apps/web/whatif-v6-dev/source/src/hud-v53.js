/* V5.3: game-native HUD built from existing controls, with unchanged workflows. */
const H53={icons:{
 home:'<path fill="#e3bb70" d="M2 10h3V7h3V4h8v3h3v3h3v3h-3v8H5v-8H2z"/><path fill="#386761" d="M10 13h4v8h-4z"/><path fill="#fff4ce" d="M8 9h3v3H8zm6 0h3v3h-3z"/>',
 meeting:'<path fill="#e3bb70" d="M3 12h18v7H3zM5 4h4v5H5zm10 0h4v5h-4zM5 21h4v2H5zm10 0h4v2h-4z"/><path fill="#fff4ce" d="M5 13h14v2H5z"/>',
 room:'<path fill="#e3bb70" d="M5 2h14v21H5z"/><path fill="#386761" d="M8 5h8v15H8z"/><path fill="#fff4ce" d="M13 12h2v2h-2z"/>',
 agent:'<path fill="#e3bb70" d="M11 1h2v4h6v3h3v11h-3v3H5v-3H2V8h3V5h6z"/><path fill="#183e3c" d="M5 9h14v8H5z"/><path fill="#a3e3c5" d="M7 11h3v3H7zm7 0h3v3h-3z"/>',
 minutes:'<path fill="#e3bb70" d="M5 2h14v21H5z"/><path fill="#fff4ce" d="M8 5h8v14H8z"/><path fill="#386761" d="M9 8h6v2H9zm0 4h6v2H9zm0 4h4v2H9z"/>',
 holdings:'<path fill="#e3bb70" d="M3 4h18v18H3z"/><path fill="#fff4ce" d="M6 7h12v11H6z"/><path fill="#386761" d="M7 13h3v4H7zm4-3h3v7h-3zm4-2h2v9h-2z"/>',
 scenario:'<path fill="#e3bb70" d="M3 3h2v16h17v2H3zM7 13h3v4H7zm5-5h3v9h-3zm5-4h3v13h-3z"/>',
 document:'<path fill="#e3bb70" d="M5 3h14v20H5z"/><path fill="#386761" d="M9 1h6v5H9z"/><path fill="#fff4ce" d="M8 9h8v2H8zm0 4h8v2H8zm0 4h5v2H8z"/>',
 news:'<path fill="#e3bb70" d="M2 5h20v16H2z"/><path fill="#386761" d="M5 8h7v6H5zm10 0h4v2h-4zm0 4h4v2h-4zM5 17h14v2H5z"/>',
 settings:'<path fill="#e3bb70" d="M9 2h6v3h4v4h3v6h-3v4h-4v3H9v-3H5v-4H2V9h3V5h4z"/><path fill="#386761" d="M8 8h8v8H8z"/><path fill="#fff4ce" d="M10 10h4v4h-4z"/>',
 account:'<path fill="#e3bb70" d="M8 2h8v9H8zM5 14h14v8H5z"/><path fill="#fff4ce" d="M10 4h4v4h-4z"/>',
 title:'<path fill="#e3bb70" d="M4 2h13v21H4zM17 10h5v4h-5z"/><path fill="#386761" d="M7 5h7v15H7z"/><path fill="#fff4ce" d="M11 12h2v2h-2z"/>',
 chat:'<path fill="#e3bb70" d="M2 3h20v15H11l-6 5v-5H2z"/><path fill="#386761" d="M6 8h3v3H6zm5 0h3v3h-3zm5 0h3v3h-3z"/>'}};
function h53Icon(key){return `<svg class="h53-icon" viewBox="0 0 24 24" aria-hidden="true" shape-rendering="crispEdges">${H53.icons[key]||H53.icons.agent}</svg>`;}
function h53Button(b,key,label){if(!b)return;b.innerHTML=h53Icon(key)+`<span>${label}</span>`;b.classList.add('h53-button');b.title=label;b.setAttribute('aria-label',label);}
function h53HUD(root){
 const header=root.querySelector('.gx-header'),rail=root.querySelector('.gx-rail'),tabs=root.querySelector('.gx-tabs');
 if(!header||!rail||!tabs)return;
 const utilities=document.createElement('nav');utilities.className='h53-utilities';utilities.setAttribute('aria-label','게임 설정과 내 정보');
 for(const [action,key,label]of [['sound-open','settings','설정'],['account','account','내 정보'],['logout','title','타이틀']]){const b=header.querySelector(`[data-gx="${action}"]`);if(b){h53Button(b,key,label);utilities.append(b);}}
 const chatButton=header.querySelector('[data-gx="chat-open"]');if(chatButton)chatButton.remove();
 header.innerHTML=`<img class="h53-player" src="${GX_ASSETS[GX.playerKind==='female'?'portrait_female':'portrait_host']}" alt=""><div class="h53-identity"><strong>${E(S.profile.name||'시간여행자')}</strong><small>WHAT IF · 시장분석팀</small><span>2008.10 <b>· ${GX.panel==='collab'?'회의실':GX.room==='myroom'?'개인실':'서울 사무실'}</b></span></div><span class="h53-emblem" aria-hidden="true">W</span>`;
 header.setAttribute('aria-label','플레이어 상태');root.append(utilities);
 for(const [room,key,label]of [['office','home','홈'],['meeting','meeting','회의실'],['myroom','room','개인실']])h53Button(rail.querySelector(`[data-room="${room}"]`),key,label);
 rail.setAttribute('aria-label','공간 이동 HUD');
 for(const [panel,key,label]of [['sim','agent','AI Agent'],['minutes','minutes','회의록'],['holdings','holdings','내 보유종목']])h53Button(tabs.querySelector(`.p41-main-tabs [data-panel="${panel}"]`),key,label);
 for(const [panel,key,label]of [['sim','scenario','시나리오 분석'],['document','document','문서 분석'],['news','news','실시간 뉴스']])h53Button(tabs.querySelector(`.p41-subtabs [data-panel="${panel}"]`),key,label);
 tabs.setAttribute('aria-label','분석 도구 HUD');
 const fab=root.querySelector('.gx-chat-fab');if(fab){fab.innerHTML=`<img src="${GX_ASSETS.ppukku_portrait}" alt="">`;fab.setAttribute('aria-label','뿌꾸 AI 챗봇 열기');fab.title='뿌꾸 AI 챗봇 열기';}
 const footer=root.querySelector('.gx-footer');if(footer)footer.innerHTML='<span><kbd>WASD</kbd> 이동 <kbd>Shift</kbd> 달리기 <kbd>E</kbd> 상호작용</span><span>WHAT IF / TIME INVESTOR · V5.3</span>';
 // Preserve modal navigation policy after moving utility buttons out of the header.
 utilities.inert=!!(GX.panel||S.modal||S.myroom.modal||GX.soundOpen);
}
const h53Render=render,h53Loading=p49Loading,h53ChatLayout=ap47ChatLayout;
const P53={focusEditor:false};
const h53GX=gxAction;
gxAction=function(action,el){if(action==='p49-persona')P52.teamList=false;return h53GX(action,el);};
const h53Action=onAction;
onAction=function(action,el){if(['v31-holding-add','v31-holding-edit'].includes(action))P53.focusEditor=true;return h53Action(action,el);};
ap47ChatLayout=function(){h53ChatLayout();if(!document.querySelector('.ui53')||P42.manualChat)return;const chat=document.querySelector('.gx-chat-window');if(!chat)return;const width=Math.min(420,innerWidth-28),height=Math.max(240,innerHeight-128);GX.window={x:innerWidth-width-16,y:108,w:width,h:height};Object.assign(chat.style,{left:GX.window.x+'px',top:'108px',width:width+'px',height:height+'px'});};
p49Loading=function(){h53Loading();const page=document.querySelector('.p49-loading');if(!page||page.querySelector('.h53-loading-bg'))return;const bg=document.createElement('img');bg.className='h53-loading-bg';bg.src=GX_ASSETS.login49;bg.alt='';page.prepend(bg);const footer=page.querySelector('footer');footer?.insertAdjacentHTML('afterbegin','<small class="h53-loading-label">TIME TRANSFER / 2008</small>');};
render=function(){const oldBody=GX.panel==='holdings'?document.querySelector('.p41-feature[data-h53-panel=holdings]>.gx-window-body'):null,scrollTop=oldBody?.scrollTop;h53Render();if(GX.phase!=='game')return;const root=document.querySelector('.p41-app');if(!root)return;root.classList.add('ui53');root.style.setProperty('--h53-world-image',`url("${GX_ASSETS[gxBackground()]}")`);S.appVersion='5.3.0';h53HUD(root);root.dataset.agentOpen=String(P41.tab==='agent');
 root.querySelectorAll('.p41-feature').forEach(el=>{el.dataset.h53Panel=GX.panel;el.querySelector('.gx-window-body')?.setAttribute('tabindex','0');});
 const editor=root.querySelector('.holding-editor');if(editor){editor.setAttribute('aria-label',S.holdingDraft?.edit?'보유종목 수정':'보유종목 등록');editor.querySelector('[data-action="v31-holding-cancel"]')?.replaceChildren(document.createTextNode('x 닫기'));}
 if(editor&&scrollTop!=null)root.querySelector('.p41-feature>.gx-window-body').scrollTop=scrollTop;
 if(editor&&P53.focusEditor){P53.focusEditor=false;requestAnimationFrame(()=>{if(!editor.isConnected)return;editor.scrollIntoView({block:'start'});editor.querySelector('#holding-search')?.focus({preventScroll:true});});}
 ap47ChatLayout();
};
WHATIF_QA.hud53=()=>({version:S.appVersion,room:GX.room,panel:GX.panel,hasDraft:!!S.holdingDraft,holdings:S.holdings.map(h=>({name:h.name,code:h.code,quantity:h.quantity,amount:h.amount})),icons:Object.keys(H53.icons)});
