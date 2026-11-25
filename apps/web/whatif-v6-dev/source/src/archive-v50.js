/* Neutral navigation and immutable, per-analysis chat contexts. */
const P50={chatKey:'scenario',snapshots:{},pending:null,audio:{buffers:{},loading:false,lastClick:-Infinity,count:{click:0,step:0},foot:0}};
const P50_LABEL={scenario:'시나리오 분석',document:'문서 분석',news:'실시간 뉴스'};
const p50PanelKey=p=>({sim:'scenario',document:'document',news:'news'})[p];
function p50Capture(key){
 let context=p50BaseContext('personal/'+key),label='',at=new Date().toISOString(),id;
 if(key==='scenario'){const run=currentRun()||S.runs.at(-1);if(!run)return null;context.run=A41.copy(run);label=run.targetLabel+' · '+run.version;at=run.at;id=run.id;}
 if(key==='document'){if(!S.docReady||!S.docAnalyzed||!S.docContent?.trim())return null;context.run=null;label=S.docName;id=S.docName+'|'+S.docContent;context.document={name:S.docName,kind:S.docKind,text:S.docContent.slice(0,18000),extracted:true};}
 if(key==='news'){const a=activeNewsAnalysis();if(!a)return null;context.run=null;context.news=A41.copy(a.items);context.newsAnalysis={id:a.id,at:a.at,summary:a.summary};label='선택 뉴스 '+a.items.length+'건';at=a.at;id=a.id;}
 context.analysisLabel=label;context.analysisAt=at;return P50.snapshots[key]={id,label,at,context:A41.copy(context)};
}
function p50Snapshot(key){
 if(P50.snapshots[key])return P50.snapshots[key];
 if(key==='scenario'&&S.runs.length)return p50Capture(key);
 if(key==='news'&&activeNewsAnalysis())return p50Capture(key);
 if(key==='document'&&S.docAnalyzed)return p50Capture(key);
 return null;
}
const p50BaseContext=p41Context;
p41Context=function(scope=p41Scope()){const key=scope.split('/')[1];return scope.startsWith('personal/')&&P50.snapshots[key]?A41.copy(P50.snapshots[key].context):p50BaseContext(scope);};
p41Scope=function(){return GX.panel==='collab'&&S.collab.started?'collab/'+S.collab.room:'personal/'+P50.chatKey;};
p41ChatKey=function(){return p41Scope().startsWith('collab/')?'collab':P50.chatKey;};
const p50Question=p41Question;
function p50NeedAnalysis(key,text){
 P50.chatKey=key;P50.pending={key,text};S.drafts[key]=text;GX.chat=false;GX.chatMin=false;gxOpen(key==='scenario'?'sim':key);
}
p41Question=async function(key,text,opts={}){
 if(key==='collab')return p50Question(key,text,opts);
 if(!P50_LABEL[key])key=P50.chatKey;
 text=String(text||'').trim();if(!text)return [];
 const snapshot=opts.context?.run||opts.context?.document||opts.context?.news?.length?{context:opts.context}:p50Snapshot(key);
 if(!snapshot){p50NeedAnalysis(key,String(text||''));return [];}
 P50.chatKey=key;S.tab='chat';S.sub=key;
 const jobs=await p50Question(key,text,{...opts,context:A41.copy(snapshot.context)});return jobs;
};
sendChat=function(key,text=S.drafts[key]){return key==='collab'?sendCollab(text):p41Question(key,text);};
function p50Neutral(openChat=false){GX.panel=null;S.modal=null;S.myroom.modal='';S.drawer=false;S.detailPage=false;P41.tab='agent';P42.aiOpen=true;S.tab='chat';S.sub=P50.chatKey;GX.keys.clear();GX.path=[];if(openChat){GX.chat=true;GX.chatMin=false;}render();}
const p50Open=gxOpen,p50GX=gxAction,p50Action=onAction,p50Run=runSim,p50File=handleFile,p50News=createNewsAnalysis,p50Render=render;
gxOpen=function(panel){const key=p50PanelKey(panel);if(key){P50.chatKey=key;S.sub=key;S.tab='chat';GX.chat=false;GX.chatMin=false;}else if(panel!=='collab')S.tab='chat';return p50Open(panel);};
gxAction=function(action,el){
 if(action==='panel'&&el.dataset.panel==='sim'&&el.closest('.p41-main-tabs'))return p50Neutral();
 if(action==='feature-close'&&p50PanelKey(GX.panel))return p50Neutral();
 if(action==='p50-chat-tab'){P50.chatKey=el.dataset.key;S.sub=P50.chatKey;S.tab='chat';return render();}
 if(action==='p50-review'){const key=el.dataset.key||P50.chatKey;if(!p50Snapshot(key))return gxToast('먼저 '+P50_LABEL[key]+'을 실행해 주세요.');P50.chatKey=key;return p50Neutral(true);}
 if(action==='p50-continue-question'){const pending=P50.pending;if(!pending||!p50Snapshot(pending.key))return;P50.pending=null;p50Neutral(true);return p41Question(pending.key,pending.text);}
 if(action==='p50-open-analysis')return gxOpen(el.dataset.key==='scenario'?'sim':el.dataset.key);
 if(action==='chat-open'&&p50PanelKey(GX.panel)){P50.chatKey=p50PanelKey(GX.panel);return p50Neutral(true);}
 if(action==='room'&&el.dataset.room==='office'){const r=p50GX(action,el);S.tab='chat';P41.tab='agent';return r;}
 return p50GX(action,el);
};
onAction=function(action,el){
 if(action==='quick'){const key=el.closest('.gx-chat-window')?.dataset.p50Key||el.dataset.p50Key||(GX.panel==='collab'&&S.collab.started?'collab':P50.chatKey);return sendChat(key,el.dataset.text||'');}
 if(action==='send-chat'){const key=el.closest('.gx-chat-window')?.dataset.p50Key||el.dataset.key||P50.chatKey;return sendChat(key,S.drafts[key]);}
 if(['ai-agent','tab-chat'].includes(action))return p50Neutral();
 if(action==='analyze-doc'&&(!S.docReady||!S.docContent?.trim()))return gxToast('문서를 첨부하고 원문을 확인한 뒤 분석해 주세요.');
 const r=p50Action(action,el);
 if(action==='analyze-doc'&&S.docAnalyzed){p50Capture('document');render();}
 if(action==='clear-doc'){/* Existing reviewed snapshot remains available until explicit replacement. */}
 return r;
};
runSim=function(){const n=S.runs.length,r=p50Run();if(S.runs.length>n){p50Capture('scenario');P50.chatKey='scenario';render();}return r;};
createNewsAnalysis=function(){const id=S.newsAnalysisId,r=p50News();if(S.newsAnalysisId!==id){p50Capture('news');render();}return r;};
function p50ChatHeader(win,key){
 const current=p50Snapshot(key),nav=document.createElement('nav');nav.className='p50-chat-tabs';nav.setAttribute('aria-label','대화할 분석 종류');nav.innerHTML=Object.entries(P50_LABEL).map(([k,label])=>gxButton('p50-chat-tab',label,'',`data-key="${k}" aria-pressed="${key===k}"`)).join('');win.querySelector('.gx-chat-grip').after(nav);
 const status=document.createElement('div');status.className='p50-chat-context';status.innerHTML=current?`<strong>${E(current.label)}</strong><span>마지막 분석 결과 기준 · ${E(datetime(current.at))}</span>`:`<strong>${P50_LABEL[key]} 결과가 아직 없습니다</strong><span>분석을 실행하면 결과를 기준으로 의견을 나눌 수 있어요.</span>${gxButton('p50-open-analysis','분석하러 가기','',`data-key="${key}"`)}`;nav.after(status);
}
function p50DecorateMinutes(feature){
 feature.classList.add('ar50-feature','ar50-minutes');
 const layout=feature.querySelector('.minutes-v26-layout');if(!layout)return;
 const detail=feature.querySelector('#minute-detail-panel');feature.classList.toggle('ar50-detail',!!detail);
 const calendar=feature.querySelector('.minute-calendar');if(calendar)calendar.classList.add('ar50-calendar');
 const list=feature.querySelector('.minute-list-panel');if(list)list.classList.add('ar50-archive');
 if(detail){const close=detail.querySelector('[data-action="close-minute-detail"]');if(close){close.innerHTML=ico('chevron')+' 목록으로';close.setAttribute('aria-label','회의록 목록으로');}const scroll=detail.querySelector('.minute-detail-scroll');if(scroll){const main=document.createElement('div');main.className='ar50-report';for(const el of [...scroll.children])if(!el.classList.contains('minute-perspectives'))main.append(el);scroll.prepend(main);}}
}
function p50DecorateHoldings(feature){
 feature.classList.add('ar50-feature','ar50-holdings');const page=feature.querySelector('.holdings-page');if(!page)return;
 const book=document.createElement('div');book.className='ar50-book';const left=document.createElement('aside');left.className='ar50-book-left';const title=document.createElement('h2');title.textContent='자산 기록 요약';left.append(title);
 const stats=page.querySelector('.v31-stat-grid'),main=page.querySelector('.holdings-main'),bottom=page.querySelector('.holdings-bottom');if(stats)left.append(stats);if(bottom)left.append(bottom);book.append(left);if(main)book.append(main);page.querySelector('.page-title-row,.subhead')?.after(book);if(!book.isConnected)page.prepend(book);
}
render=function(){
 p50Render();if(GX.phase!=='game')return;S.appVersion='5.0.0';const root=document.querySelector('.ui49');if(!root)return;root.classList.add('ui50');
 root.style.setProperty('--ar50-calendar',`url("${GX_ASSETS.calendar50}")`);root.style.setProperty('--ar50-paper',`url("${GX_ASSETS.archive50}")`);root.style.setProperty('--ar50-book',`url("${GX_ASSETS.notebook50}")`);
 root.querySelectorAll('.gx-window-head .p41-state').forEach(e=>{if(/^작업\s*공간$/.test(e.textContent.trim()))e.remove();});
 root.querySelectorAll('.p41-subtabs button').forEach(b=>{const selected=b.dataset.panel===GX.panel;b.classList.toggle('active',selected);b.setAttribute('aria-pressed',String(selected));});
 if(!GX.panel&&P41.tab==='agent')root.querySelector('.p41-main-tabs [data-panel="sim"]')?.classList.add('active');
 const feature=root.querySelector('.p41-feature');if(feature&&p50PanelKey(GX.panel)){
  const key=p50PanelKey(GX.panel),button=document.createElement('button');button.type='button';button.dataset.gx='p50-review';button.dataset.key=key;button.className='gx-small p50-review';button.textContent='AI와 의견 나누기';feature.querySelector('.gx-window-head [data-gx="feature-close"]').before(button);
  if(P50.pending?.key===key){const note=document.createElement('div');note.className='p50-analysis-guide';note.setAttribute('role','status');const ready=p50Snapshot(key);note.innerHTML=ready?`<strong>분석을 완료했습니다.</strong><span>${E(P50.pending.text)}</span>${gxButton('p50-continue-question','이 질문으로 의견 나누기')}`:`<strong>먼저 ${P50_LABEL[key]}을 실행해 주세요.</strong><span>질문은 보관했습니다. 분석을 마치면 이어서 대화할 수 있어요.</span>`;feature.querySelector('.gx-window-body').prepend(note);}
 }
 const chat=root.querySelector('.gx-chat-window');if(chat&&!p41Scope().startsWith('collab/')){const key=P50.chatKey;chat.dataset.p50Key=key;p50ChatHeader(chat,key);chat.querySelectorAll('[data-action="quick"]').forEach(b=>b.dataset.p50Key=key);}
 if(feature&&GX.panel==='minutes')p50DecorateMinutes(feature);if(feature&&GX.panel==='holdings')p50DecorateHoldings(feature);
};
window.addEventListener('keydown',e=>{if(document.querySelector('dialog[data-stock-prices][open]'))return;if(e.key==='Escape'&&!document.querySelector('.p512-period-menu[open]')&&GX.phase==='game'&&p50PanelKey(GX.panel)&&!S.modal&&!S.myroom.modal&&!GX.soundOpen){e.preventDefault();e.stopImmediatePropagation();p50Neutral();}},true);
/* Original, asset-backed effects routed through existing sound preferences. */
function p50LoadAudio(){if(P50.audio.loading||!gxAudio)return;P50.audio.loading=true;for(const key of ['click','step'])fetch(GX_SFX[key]).then(r=>r.arrayBuffer()).then(a=>gxAudio.decodeAudioData(a)).then(buffer=>P50.audio.buffers[key]=buffer).catch(()=>{});}
const p50Fx=gxFx;
gxFx=function(kind='click'){
 if(!['click','step'].includes(kind))return p50Fx(kind);
 const now=performance.now();if(kind==='click'&&now-P50.audio.lastClick<35)return;if(kind==='click')P50.audio.lastClick=now;
 gxAudioInit();p50LoadAudio();if(!gxAudio||!GX.sound.enabled||!GX.sound.master||!GX.sound.effects||document.hidden)return;
 if(kind==='step'&&(GX.phase!=='game'||GX.panel||S.modal||S.myroom.modal||GX.chatModal||S.myroom.paused))return;
 P50.audio.count[kind]++;const buffer=P50.audio.buffers[kind];if(!buffer){gxTone(kind==='step'?125:850,kind==='step'?.07:.055,gxFxBus,'triangle',.06);return;}
 const source=gxAudio.createBufferSource(),gain=gxAudio.createGain();source.buffer=buffer;source.playbackRate.value=kind==='step'?(P50.audio.foot++%2?.96:1.04):1;gain.gain.value=kind==='step'?.55:.65;source.connect(gain);gain.connect(gxFxBus);source.start();source.onended=()=>{source.disconnect();gain.disconnect();};
};
window.WHATIF_QA.v50=()=>({chatKey:P50.chatKey,activeSub:p50PanelKey(GX.panel)||null,snapshots:Object.fromEntries(Object.entries(P50.snapshots).map(([k,s])=>[k,{id:s.id,label:s.label,at:s.at,context:A41.copy(s.context)}])),pending:P50.pending,audio:{count:{...P50.audio.count},loaded:Object.keys(P50.audio.buffers),state:gxAudio?.state}});
