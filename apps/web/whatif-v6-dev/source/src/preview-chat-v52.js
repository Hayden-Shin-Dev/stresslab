/* Temporary opt-in UI preview. Remove this adapter and transport branch after Azure QA. */
P52.previewAI=false;
async function p52PreviewTransport(x,signal){
 await new Promise((resolve,reject)=>{if(signal.aborted)return reject(new DOMException('Cancelled','AbortError'));const abort=()=>{clearTimeout(timer);reject(new DOMException('Cancelled','AbortError'));},timer=setTimeout(()=>{signal.removeEventListener('abort',abort);resolve();},550);signal.addEventListener('abort',abort,{once:true});});
 const ctx=x.local_context||{},kind=x.participation_scope_id.split('/')[1],topic={scenario:ctx.run?.targetLabel||'시장 시나리오',document:ctx.document?.name||'선택 문서',news:'선택 뉴스'}[kind]||'선택 분석';
 const roles={macro:'금리·환율·유가의 입력 조건과 시장 전체의 흐름을 함께 확인하는 역할입니다.',intraday:'분석 시점과 시장 상태, 거래 흐름을 구분해 확인하는 역할입니다.',risk:'손실 가능성과 변동성, 분석에 필요한 근거의 한계를 확인하는 역할입니다.',portfolio:'보유 종목 비중과 분산, 포트폴리오 위험을 점검하는 역할입니다.'};
 const reply={schema_version:3,context_version:x.context_version,role:x.role,intent:'user_answer',response_status:'insufficient_data',emission:'speak',silence_reason:null,summary_text:'사전 체험 · 미리 작성된 안내 응답',display_text:`결론: [체험 응답 · 실제 AI 분석 아님]\n${topic}에 대한 질문을 받았습니다.\n${roles[x.role]}\n질문하신 내용은 실제 연결 후 해당 분석 자료를 바탕으로 검토하게 됩니다. 지금은 대화 전송·역할 선택·메뉴 연결을 확인하는 미리 작성된 응답입니다.`,tts_text:'',view_status:'deferred',claims:[],structured_source_ids:[],rag_source_ids:[],news_source_ids:[],uncertainty:{missing:[],limitations:[],next_checks:[]},questions_to_roles:[],ui_requests:[],follow_up:null,persona_data:Object.fromEntries(A41.personaKeys[x.role].map(k=>[k,[]]))};
 return {ok:true,json:async()=>({reply})};
}
const p52Bridge=p41Bridge,p52Connection=p51ConnectionHTML,p52PreviewSettings=gxSoundHTML,p52PreviewGX=gxAction,p52Question=p41Question;
p41Bridge=async function(force=false){if(P52.previewAI){P41.bridge=true;P41.bridgeStatus='preview';return true;}return p52Bridge(force);};
p51ConnectionHTML=function(){return P52.previewAI?`<div class="p52-preview-banner" role="status"><strong>AI 챗봇 사전 체험</strong><span>미리 작성된 응답 · Azure 미연결 · 개인 챗봇 전용</span>${gxButton('p52-preview-off','체험 종료')}</div>`:p52Connection();};
gxSoundHTML=function(){return p52PreviewSettings().replace('</div></section></div>',`<div class="p52-preview-settings"><h3>Azure 연결 전 사전 체험</h3><p>개인 AI 챗봇의 시나리오·문서·뉴스 흐름을 테스트합니다. 실제 분석·예측을 생성하지 않으며 외부 AI를 호출하지 않습니다. 새로고침하면 체험이 꺼집니다.</p>${gxButton(P52.previewAI?'p52-preview-off':'p52-preview-on',P52.previewAI?'AI 챗봇 체험 종료':'AI 챗봇 사전 체험 시작','',GX.phase!=='game'?'disabled':'')}</div></div></section></div>`);};
function p52SetPreview(on){
 if(P41.healthPromise||Object.keys(P41.pending).length||P41.submitting?.size)return gxToast('현재 요청이 끝난 뒤 체험 모드를 변경해 주세요.');
 P52.previewAI=on;P41.bridge=on;P41.bridgeStatus=on?'preview':'checking';P41.healthAt=0;GX.soundOpen=false;
 if(on){GX.panel=null;S.modal=null;S.myroom.modal='';P50.chatKey='scenario';GX.chat=true;GX.chatMin=false;}else p41Bridge(true).then(()=>render());
 render();
}
gxAction=function(action,el){if(action==='p52-preview-on')return p52SetPreview(true);if(action==='p52-preview-off')return p52SetPreview(false);return p52PreviewGX(action,el);};
p41Question=function(key,text,opts={}){if(P52.previewAI&&key==='collab')return notify('사전 체험은 개인 AI 챗봇에서 사용할 수 있습니다. 회의 AI는 Azure 연결이 필요합니다.');return p52Question(key,text,opts);};
const p52PreviewRender=render;
render=function(){p52PreviewRender();if(P52.previewAI){const head=document.querySelector('.gx-chat-grip .p41-state');if(head)head.textContent='사전 체험 중';}};
const p52QA=WHATIF_QA.sound52;
WHATIF_QA.sound52=()=>({...p52QA(),previewAI:P52.previewAI});

WHATIF_QA.preview52=()=>({replies:(S.chats.scenario||[]).filter(m=>m.contract).map(m=>({preview:!!m.preview,text:m.text})),history:P50.snapshots.scenario?p41History('scenario','personal/scenario',P50.snapshots.scenario.context.version):[]});

const p52Retry=p41Retry;
p41Retry=function(id){const job=P41.requests.get(id);if(job&&!!job.preview!==!!P52.previewAI)return notify('대화 모드가 변경되었습니다. 현재 모드에서 질문을 새로 보내 주세요.');return p52Retry(id);};
