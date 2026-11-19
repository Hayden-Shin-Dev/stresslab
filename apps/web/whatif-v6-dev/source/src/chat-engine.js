/* Request execution is server-only. Contexts and histories are frozen per analysis. */
function p51ContextVersion(key,ctx){const s=JSON.stringify([key,ctx.run?.id,ctx.document?.name,ctx.document?.text,ctx.newsAnalysis?.id,ctx.news,ctx.analysisAt,ctx.shared?.at]);let h=2166136261;for(let i=0;i<s.length;i++)h=Math.imul(h^s.charCodeAt(i),16777619);return 'analysis-'+key+'-'+(h>>>0).toString(16);}
function p41History(key,scope,version){return (S.chats[key]||[]).filter(m=>!!m.preview===!!P52.previewAI&&m.participation_scope_id===scope&&m.contextVersion===version&&(m.me||m.contract||m.moderator)).slice(-6).map(m=>({participation_scope_id:scope,role:m.me?'user':m.moderator?'moderator':A41.roles[m.persona],text:m.text,message_id:m.messageId||m.questionId}));}
async function p41Execute(job){
 if(P41.pending[job.id]||job.epoch!==(P41.epoch||0))return;
 const list=S.chats[job.key]||(S.chats[job.key]=[]),controller=new AbortController();job.controller=controller;job.done=false;job.cancelled=false;job.errorCode=null;P41.pending[job.id]={scope:job.scope};
 const stamp={persona:job.persona,jobId:job.id,questionId:job.questionId,participation_scope_id:job.scope,contextKey:job.contextKey,contextVersion:job.input.context_version,preview:!!job.preview};
 const set=m=>{if(job.epoch!==(P41.epoch||0))return;const at=list.findIndex(v=>v.jobId===job.id);if(at<0)list.push(m);else list[at]=m;};
 if(!job.automated)set({...stamp,kind:'p41-pending'});render();let timedOut=false;
 const timer=setTimeout(()=>{timedOut=true;controller.abort();},50000);
 try{
  if(!job.preview&&!/^https?:$/.test(location.protocol))throw new Error('server_required');
  const response=job.preview?await p52PreviewTransport(job.input,controller.signal):await fetch('/api/agent/respond',{method:'POST',headers:{'Content-Type':'application/json','X-Whatif-Token':window.WHATIF_BRIDGE_TOKEN||''},body:JSON.stringify({request_id:job.id,input:job.input}),signal:controller.signal});
  const body=await response.json().catch(()=>({}));if(!response.ok)throw new Error(response.status===403?'session_expired':body.error||'reply_unavailable');
  if(controller.signal.aborted||job.epoch!==(P41.epoch||0))throw new DOMException('Aborted','AbortError');
  let validationInput=job.input;if(body.validation)validationInput={...job.input,D_sources:body.validation.D_sources||[],N_sources:body.validation.N_sources||[],S_sources:body.validation.S_sources||[],role_payload:body.validation.portfolio_payload||job.input.role_payload};
  const errors=A41.validateOutput(body.reply,validationInput);if(errors.length)throw new Error('invalid_output');
  job.reply=body.reply;job.emission=body.reply.emission;
  if(body.reply.emission==='silent'){const at=list.findIndex(m=>m.jobId===job.id);if(at>=0)list.splice(at,1);job.done=true;return;}
  set({...stamp,text:body.reply.display_text,summary:body.reply.summary_text,time:clock(),messageId:'answer-'+job.questionId+'-'+job.input.role,questionText:job.input.user_message,runId:job.input.local_context?.run?.id||null,note:'AI 답변'+(job.input.local_context?.analysisLabel?' · '+job.input.local_context.analysisLabel:''),contract:body.reply});job.done=true;if(job.key==='collab')S.collab.speaker=job.persona;
  if(P41.debate?.waiting===job.id){P41.debate.waiting=null;P41.debate.turn++;S.collab.turn=P41.debate.turn;if(P41.debate.turn>=P41.debate.agents.length*2){S.collab.phase='done';p41SaveDiscussion(P41.debate);}}
 }catch(error){
  const code=timedOut?'timeout':controller.signal.aborted?'cancelled':error.message;job.errorCode=code;
  const messages={cancelled:'답변 요청을 중지했습니다.',timeout:'응답 시간이 초과되었습니다. 다시 시도해 주세요.',azure_unconfigured:'AI 연결을 확인한 뒤 다시 시도해 주세요.',session_expired:'연결 정보가 만료되었습니다. 페이지를 새로고침한 뒤 다시 시도해 주세요.',invalid_output:'응답 형식을 확인하지 못했습니다. 이 AI만 다시 시도해 주세요.',server_required:'AI에 연결한 뒤 다시 시도해 주세요.'};
  if(code==='azure_unconfigured'){P41.bridge=false;P41.bridgeStatus='unconfigured';P41.healthAt=0;}
  if(!job.automated)set({...stamp,kind:'p41-error',questionText:job.input.user_message,text:messages[code]||'AI 응답을 받지 못했습니다. 연결 상태를 확인하고 다시 시도해 주세요.',time:clock()});
 }finally{clearTimeout(timer);delete P41.pending[job.id];if(job.epoch===(P41.epoch||0)){persist();render();}}
}
async function p41Question(key,text,opts={}){
 text=String(text||'').trim();if(!text)return [];
 if(!['scenario','document','news','collab'].includes(key))return [];
 if(text.length>12000){notify('질문은 12,000자 이내로 입력해 주세요.');return [];}
 const collab=key==='collab';if(collab&&!S.collab.started){notify('회의를 먼저 시작해 주세요.');return [];}
 const scope=collab?'collab/'+S.collab.room:'personal/'+key,mentioned=D.personas.filter(p=>text.includes('@'+p.name)).map(p=>p.id),allRequested=/모두.{0,8}(답|의견|설명)|(전체|네\s*명).{0,8}(답|의견)/.test(text);
 if(collab&&mentioned.some(id=>!S.collab.agents.includes(id))){notify('질문할 AI를 먼저 회의에 추가해 주세요.');return [];}
 const ids=[...new Set(opts.ids||(mentioned.length?mentioned:collab?[...S.collab.agents]:allRequested?Object.keys(A41.roles):[...S.selectedRoles]))].filter(id=>A41.roles[id]);
 if(!ids.length){notify('답변할 AI를 한 명 이상 선택해 주세요.');return [];}
 P41.submitting??=new Set();if(P41.submitting.has(scope)||Object.values(P41.pending).some(p=>p.scope===scope)){notify('현재 답변을 마친 뒤 질문해 주세요.');return [];}
 const context=A41.copy(opts.context||p41Context(scope)),epoch=P41.epoch||0;context.version=p51ContextVersion(key,context);P41.submitting.add(scope);
 try{
  if(!await p41Bridge()){S.drafts[key]=text;if(collab&&opts.questionId)p51Api('/api/meetings/question-failed',{room:S.collab.room,question_id:opts.questionId}).catch(()=>{});notify(P41.bridgeStatus==='file'?'앱 서버에서 열어 AI 연결을 설정해 주세요.':'AI 연결을 확인해 주세요. 입력한 질문은 보관했습니다.');return [];}
  if(epoch!==(P41.epoch||0))return [];
  const qid=opts.questionId||'q-'+crypto.randomUUID();if(collab&&!await p51PrepareQuestion(qid,text,ids,!!opts.automated))return [];
  if(collab)context.meeting_context=P51.meeting;
  const history=p41History(key,scope,context.version),contextKey=collab?collabContext():null;
  S.chats[key]??=[];if(!opts.automated)S.chats[key].push({me:true,preview:!!P52.previewAI,text,time:clock(),questionId:qid,messageId:qid,participation_scope_id:scope,runId:context.run?.id||null,contextKey,contextVersion:context.version});S.drafts[key]='';
  const jobs=ids.map(persona=>{const input=A41.makeInput({id:persona,scope,question:text,context,history,questionId:qid,phase:opts.phase||'USER_ANSWER',reference:opts.reference,triggerType:opts.automated?'automatic':'user_request',addressedRoles:ids.map(id=>A41.roles[id])});const job={preview:!!P52.previewAI,id:qid+'-'+persona,key,scope,persona,input,questionId:qid,contextKey,epoch,automated:!!opts.automated};P41.requests.set(job.id,job);return job;});
  await Promise.allSettled(jobs.map(job=>job.promise=p41Execute(job)));if(collab&&!opts.automated&&epoch===(P41.epoch||0)){P41.submitting.delete(scope);if(jobs.every(j=>j.errorCode==='cancelled'))await p51Api('/api/meetings/question-failed',{room:S.collab.room,question_id:qid}).catch(()=>{});else await p51Moderate(qid);}return jobs;
 }finally{P41.submitting.delete(scope);if(epoch===(P41.epoch||0)&&GX.phase==='game')render();}
}
async function p41Retry(id){const job=P41.requests.get(id);P41.retrying??=new Set();if(!job||P41.pending[id]||P41.retrying.has(id)||job.epoch!==(P41.epoch||0))return;if(job.scope.startsWith('collab/')&&(!S.collab.started||!S.collab.agents.includes(job.persona)))return notify('해당 AI를 회의에 다시 추가해 주세요.');P41.retrying.add(id);render();try{if(!await p41Bridge(true))return notify('AI 연결 설정을 확인해 주세요.');if(job.epoch!==(P41.epoch||0))return;return await p41Execute(job);}finally{P41.retrying.delete(id);render();}}
sendChat=function(key,text=S.drafts[key]){return key==='collab'?sendCollab(text):p41Question(key,text);};
sendCollab=function(text){text=String(text||'').trim();if(!text||!S.collab.started)return;if(S.collab.phase==='running'&&S.collab.interrupt==='queue'){S.collab.queue.push(text);S.drafts.collab='';persist();render();return;}pauseDiscussion();return p41Question('collab',text);};
answerCollab=function(text){return p41Question('collab',text);};
simulatePersona=function(question,id,key){return {kind:'p41-connection-required',persona:id,text:'AI 연결 후 분석을 요청해 주세요.',time:clock()};};
discussionReply=function(id){return simulatePersona('',id,'collab');};
const p41CallRun=runCallSimulation;
runCallSimulation=function(){const d=callUI.draft;if(+d.horizon!==5||+d.rate>58){callUI.runError='5거래일과 확인된 금리 지원 범위 안에서 실행해 주세요. 이전 결과는 유지됩니다.';return render();}const n=S.runs.length,r=p41CallRun();if(S.runs.length>n){p41Event('simulation','공동 시뮬레이션 실행',{runId:S.runs.at(-1).id});persist();render();}return r;};

// Decode only word/document.xml, bounded before decompression. No embedded macros or links execute.
async function p41DocxText(file){
 const bytes=new Uint8Array(await file.arrayBuffer()),view=new DataView(bytes.buffer);let end=-1;
 for(let i=bytes.length-22;i>=Math.max(0,bytes.length-65558);i--){if(view.getUint32(i,true)===0x06054b50){end=i;break;}}
 if(end<0)throw new Error('invalid_docx');let ptr=view.getUint32(end+16,true),count=view.getUint16(end+10,true);
 for(let i=0;i<count;i++){
  if(view.getUint32(ptr,true)!==0x02014b50)throw new Error('invalid_zip');const method=view.getUint16(ptr+10,true),compressed=view.getUint32(ptr+20,true),size=view.getUint32(ptr+24,true),n=view.getUint16(ptr+28,true),extra=view.getUint16(ptr+30,true),comment=view.getUint16(ptr+32,true),local=view.getUint32(ptr+42,true),name=new TextDecoder().decode(bytes.slice(ptr+46,ptr+46+n));
  if(name==='word/document.xml'){
   if(size>8*1024*1024||compressed>10*1024*1024||local+30>bytes.length)throw new Error('docx_size');const start=local+30+view.getUint16(local+26,true)+view.getUint16(local+28,true);if(start+compressed>bytes.length)throw new Error('docx_bounds');
   let xml;if(method===0)xml=new TextDecoder().decode(bytes.slice(start,start+compressed));else if(method===8){const stream=new Blob([bytes.slice(start,start+compressed)]).stream().pipeThrough(new DecompressionStream('deflate-raw'));const reader=stream.getReader(),chunks=[];let total=0;while(true){const {done,value}=await reader.read();if(done)break;total+=value.length;if(total>8*1024*1024){await reader.cancel();throw new Error('expansion_size');}chunks.push(value);}const all=new Uint8Array(total);let offset=0;for(const c of chunks){all.set(c,offset);offset+=c.length;}xml=new TextDecoder().decode(all);}else throw new Error('zip_method');
   const doc=new DOMParser().parseFromString(xml,'application/xml');if(doc.querySelector('parsererror'))throw new Error('xml');return [...doc.getElementsByTagNameNS('*','p')].map(p=>[...p.getElementsByTagNameNS('*','t')].map(n=>n.textContent).join('')).join('\n');
  }ptr+=46+n+extra+comment;
 }throw new Error('docx_content');
}
const p41File=handleFile,p41DocSection=docSection;
handleFile=async function(file){await p41File(file);if(!S.docReady||S.docName!==file.name)return;
 if(/\.docx$/i.test(file.name)){try{S.docContent=(await p41DocxText(file)).slice(0,150000);}catch{S.docContent='';notify('문서 원문을 읽지 못했습니다. TXT로 다시 첨부하거나 원문을 확인해 주세요.');}}
 if(/\.pdf$/i.test(file.name)&&P41.backend){try{const data=await new Promise(resolve=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.readAsDataURL(file);});const r=await fetch('/api/documents/extract',{method:'POST',headers:{'Content-Type':'application/json','X-Whatif-Token':window.WHATIF_BRIDGE_TOKEN||''},body:JSON.stringify({name:file.name,data})});if(r.ok){const body=await r.json();S.docContent=body.text;P41.documentPages=body.pages;}}catch{S.docContent='';}}
 p41Event('document','문서 첨부: '+file.name,{extracted:!!S.docContent});render();
};
docSection=function(){let html=p41DocSection();if(S.docKind==='docx'&&S.docContent)html=html.replace('DOCX 미리보기는 서버 연동 또는 별도 문서 뷰어가 필요합니다. 파일명만 읽었으며 문서 내용은 추출하지 않았습니다.',E(S.docContent.slice(0,25000)));if(S.docContent&&S.docKind!=='txt')html=html.replace('분석 요청 (시연)','분석 요청');return html;};
mr36MemoSave=async function(){
 if(P41.memoBusy)return;P41.memoBusy=true;let oldBlob=null,blobChanged=false,id='';const before=A41.copy(MR36.notes);
 try{
  const title=(document.querySelector('#mr36-note-title')?.value.trim()||'제목 없는 메모').slice(0,90),body=document.querySelector('#mr36-note-body')?.value||'',date=document.querySelector('#mr36-note-date')?.value||mr36LocalDay(),cv=document.querySelector('#mr36-note-canvas'),old=MR36.notes.find(n=>n.id===MR36.editingId);id=old?.id||'note_'+crypto.randomUUID();
  if(date>mr36LocalDay())return notify('오늘 이후 날짜는 저장할 수 없습니다.');let hasDrawing=!!old?.hasDrawing;
  if(cv&&cv.dataset.dirty==='1'){oldBlob=await mr35GetFile('note_drawing_'+id);if(cv.dataset.blank==='1'){await mr35DeleteFile('note_drawing_'+id);hasDrawing=false;}else{const blob=await new Promise(r=>cv.toBlob(r,'image/png'));if(!blob)throw new Error('drawing');await mr35PutFile('note_drawing_'+id,blob);hasDrawing=true;}blobChanged=true;}
  const at=new Date().toISOString(),item={id,title,body,date,hasDrawing,createdAt:old?.createdAt||at,updatedAt:at};MR36.notes=[item,...MR36.notes.filter(n=>n.id!==id)].slice(0,250);
  if(!mr36SaveIndex())throw new Error('index');MR36.memoView='list';MR36.editingId='';P41.memoDraft=null;p41Event('memo','메모 저장: '+title,{title,body:body.slice(0,3000),date});notify('메모와 그림을 저장했습니다.');render();
 }catch{MR36.notes=before;if(blobChanged)try{if(oldBlob)await mr35PutFile('note_drawing_'+id,oldBlob);else await mr35DeleteFile('note_drawing_'+id);}catch{}notify('메모를 저장하지 못했습니다. 입력한 내용은 유지됩니다.');}
 finally{P41.memoBusy=false;}
};
mr35Upload=async function(files){let done=0,fail=0;for(const file of [...files]){if(file.size>15*1024*1024){fail++;continue;}const id='file_'+crypto.randomUUID();try{await mr35PutFile(id,file);const before=MR35.files;const next=[{id,name:file.name,size:file.size,type:file.type,at:new Date().toISOString()},...before];if(!mr35Save('files',next)){await mr35DeleteFile(id);throw new Error('metadata');}MR35.files=next;done++;}catch{fail++;}}if(done)p41Event('cloud','로컬 파일 '+done+'개 추가');render();notify('파일 '+done+'개 저장'+(fail?', '+fail+'개 실패 또는 용량 초과':'')+' · 이 브라우저에 보관');};
const p41Go=go;
go=function(screen,...args){if(screen==='myroom')return gxSetRoom('myroom');if(screen==='holdings'){GX.panel='holdings';P41.tab='holdings';}if(screen==='minutes'){GX.panel='minutes';P41.tab='minutes';}if(screen==='chat'){GX.panel=['document','news'].includes(args[0])?args[0]:'sim';P41.tab='agent';}if(screen==='collab')GX.panel='collab';if(screen==='account')GX.panel='account';P41.resetScroll=true;return p41Go(screen,...args);};
// Bounded discussion: initial roles, then referenced cross-review, with no recursive role calls.
nextDiscussion=async function(auto=false){
 const c=S.collab;if(!c.started||!c.shared||!c.agents.length||P41.debateBusy)return;
 if(!P41.debate||P41.debate.scope!==collabContext()||P41.debate.agents.join(',')!==c.agents.join(',')){P41.debate={id:crypto.randomUUID(),scope:collabContext(),agents:[...c.agents],context:A41.copy(p41Context('collab/'+c.room)),turn:0,jobs:[],at:new Date().toISOString()};}
 const d=P41.debate,n=d.agents.length;if(d.turn>=n*2){c.phase='done';persist();render();return;}
 P41.debateBusy=true;try{
  if(c.queue.length){const text=c.queue.shift();await p41Question('collab',text);}
  else{const i=d.turn%n,id=d.agents[i],prior=[...S.chats.collab].reverse().find(m=>m.messageId&&m.contract&&m.contextKey===collabContext()),cross=d.turn>=n;
   if(cross&&!prior?.contract?.claims?.length){d.turn=n*2;c.turn=d.turn;}else{const jobs=await p41Question('collab',cross?'앞선 발언의 근거와 한계를 현재 관점에서 검토해 주세요.':'공유한 자료를 현재 관점에서 검토해 주세요.',{ids:[id],context:d.context,phase:cross&&prior?'CHALLENGE':'INITIAL',reference:cross?prior?.messageId:null,automated:true});if(!jobs?.length){c.phase='paused';return;}d.jobs.push(...jobs.map(j=>j.id));const failed=jobs.find(j=>!j.done);if(failed){d.waiting=failed.id;c.phase='paused';}else{d.turn++;c.turn=d.turn;}}}
  if(d.turn>=n*2){c.phase='done';c.speaker=null;p41SaveDiscussion(d);}persist();render();
 }finally{P41.debateBusy=false;}
 if(auto&&c.phase==='running')scheduleDiscussion();
};
function p41SaveDiscussion(d){if(d.saved)return;const turns=S.chats.collab.filter(m=>d.jobs.includes(m.jobId)&&m.contract).map(m=>({persona:m.persona,text:m.text,at:new Date().toISOString(),stage:P41.requests.get(m.jobId)?.input.phase==='INITIAL'?'독립분석':'교차 검토',messageId:m.messageId,evidence:'현재 회의에 공유된 자료'}));if(!turns.length)return;S.meetings.unshift({id:'meeting-'+d.id,at:d.at,title:'함께 분석 회의',status:'저장된 AI 회의록',type:'공동 회의',scope:'collab',participationScope:d.scope,runId:d.context.run?.id||null,summary:'실제 저장된 '+turns.length+'개 발언을 확인할 수 있습니다.',disagreements:'추가 확인이 필요한 근거와 한계는 각 발언에 기록되어 있습니다.',turns});d.saved=true;persist();}
const p41Shared=setShared;
setShared=function(value){P41.debate=null;for(const job of P41.requests.values())if(job.scope.startsWith('collab/')&&!job.done)job.controller?.abort();const r=p41Shared(value);p41Event('shared','회의 공유 자료 변경: '+value.title);return r;};
window.WHATIF_QA.ask=(text,key='scenario')=>sendChat(key,text);
async function p41AnalyzeRun(id){const run=S.runs.find(r=>r.id===id);if(!run)return notify('분석할 실행을 먼저 선택해 주세요.');const ids=executionRoles(run);if(!ids.length)return notify('이 실행에 선택된 AI가 없습니다.');GX.chat=true;GX.chatMin=false;const context=p41Context('personal/scenario');context.run=A41.copy(run);const jobs=await p41Question('scenario','이 실행의 조건과 결과를 현재 관점에서 설명해 주세요.',{ids,context});if(jobs?.length&&jobs.every(j=>j.done)){run.personaAnalysisAt=new Date().toISOString();persist();render();}}
