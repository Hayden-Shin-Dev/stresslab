/* Separate comparison thread. Configuration changes revoke unfinished generations
   before starting a new one; saved completed conversations are never rewritten. */
window.installWhatIfComparison=function(a){
 const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 let config={ids:[],baseline:''},generation=null,sequence=0,timer=null,status='비교 토론은 별도로 실행합니다.',completed=[],busy=false;
 const api=async(path,body,key)=>{const r=await fetch('/api'+path,{credentials:'same-origin',cache:'no-store',method:body?'POST':'GET',headers:{'Content-Type':'application/json',...(key?{'Idempotency-Key':key}:{})},signal:AbortSignal.timeout(20000),...(body?{body:JSON.stringify(body)}:{})});const x=await r.json().catch(()=>({}));if(!r.ok)throw Error(typeof x.detail==='string'?x.detail:'비교 토론 요청 실패 ('+r.status+')');return x;};
 function valid(){return config.ids.length>=2&&config.ids.length<=4&&config.ids.includes(config.baseline);}
 async function revoke(g){
   if(!g)return;
   g.invalid=true;clearTimeout(g.timer);
   const accepted=await g.accepted||await api('/debates',g.body,g.key); // Resolve uncertain acceptance with the SAME idempotency key.
   if(accepted?.debate_id){const x=await api('/debates/'+encodeURIComponent(accepted.debate_id)+'/cancel',{});return x.status;}
 }
 async function start(){
   if(busy||generation&&!generation.finished)return;
   if(!valid()){status='서로 다른 실행 2~4개와 기준 실행을 선택해 주세요.';a.repaint();return;}
   const roles=a.roles();if(!roles.length){status='Agent에서 비교에 참여할 역할을 선택해 주세요.';a.repaint();return;}
   busy=true;const frozen=structuredClone(config),g={id:++sequence,config:frozen,events:[],after:0,invalid:false};generation=g;status='비교 근거 준비 중';a.repaint();
   g.body={mode:'comparison',comparison_run_ids:frozen.ids,baseline_run_id:frozen.baseline,target_roles:roles,evidence_policy:'explicit_only'};g.key='comparison-'+crypto.randomUUID();
   g.accepted=api('/debates',g.body,g.key).catch(e=>{g.error=e;return null;});
   const accepted=await g.accepted;
   if(g.invalid)return;
   if(!accepted){busy=false;g.cancelRetry=true;status=g.error.message+' · 접수 여부가 불확실하므로 서버 취소 확인 후 다시 실행해 주세요.';a.repaint();return;}
   g.debate=accepted.debate_id;
   async function poll(){
     if(g.invalid||generation!==g)return;
     try{
       const x=await api('/debates/'+encodeURIComponent(g.debate)+'/events?after_seq='+g.after+'&limit=500');
       if(g.invalid||generation!==g)return;
       for(const e of x.events||[]){if(e.seq<=g.after)continue;g.events.push(e);g.after=e.seq;}
       const done=g.events.some(e=>e.type==='debate.completed'),failed=g.events.find(e=>e.type==='debate.failed');
       if(done||failed){g.finished=true;busy=false;status=done?'비교 토론 완료 · 이 답변은 당시 비교 대상과 기준에 고정됩니다.':'비교 토론 실패 · '+(failed.payload.reason||'응답을 확인해 주세요.');if(done)completed.push(g);a.repaint();return;}
       status='비교 토론 생성 중 · 대상이나 기준 변경 시 미완료 응답을 취소합니다.';g.failures=0;
     }catch(e){if(g.invalid)return;g.failures=(g.failures||0)+1;status=e.message+' · 저장된 이벤트 재조회 중';if(g.failures>=3){busy=false;status=e.message+' · 재연결을 눌러 저장된 이벤트부터 이어받으세요.';g.resume=poll;a.repaint();return;}}
     a.repaint();g.timer=setTimeout(poll,2000);
   }
   poll();
 }
 async function replace(){
   const old=generation;clearTimeout(timer);if(old)old.invalid=true;
   try{const outcome=await revoke(old);if(generation!==old)return;busy=false;generation=null;status=outcome==='completed'?'이전 요청은 완료되어 서버 이력에 보존됩니다.':'진행 중인 이전 요청과 미완료 응답을 서버에서 폐기했습니다.';a.repaint();
     if(valid()){status+=' 최신 설정으로 다시 분석합니다.';timer=setTimeout(start,450);}else{status+=' 비교 대상이 2개 미만이어서 재시작을 멈췄습니다.';a.repaint();}
   }catch(e){busy=false;status='이전 요청 취소 확인 실패 · '+e.message+' 새 요청은 시작하지 않았습니다.';if(old)old.cancelRetry=true;a.repaint();}
 }
 function configure(ids,baseline){const next={ids:[...ids],baseline};if(JSON.stringify(next)===JSON.stringify(config))return;config=next;
   if(generation&&!generation.finished){busy=true;clearTimeout(timer);if(generation)generation.invalid=true;timer=setTimeout(replace,350);}
   else if(completed.length){status='비교 설정 변경 · 완료된 답변은 이전 설정의 이력입니다. 새 비교 토론을 실행하세요.';}
 }
 function html(){const show=[...completed,...(generation&&!generation.invalid&&!completed.includes(generation)?[generation]:[])];return `<section class="handoff-comparison-chat"><h3>AI 실행 결과 비교</h3><p role="status">${esc(status)}</p><button data-comparison-start ${busy||generation&&!generation.finished?'disabled':''}>선택 실행으로 비교 토론</button>${busy||generation?.resume?'<button data-comparison-cancel>생성 취소</button>':''}${generation?.resume?'<button data-comparison-resume>응답 재연결</button>':''}${generation?.cancelRetry?'<button data-comparison-cancel>서버 취소 재시도</button>':''}${show.map(g=>`<article><strong>기준 ${esc(g.config.baseline)} · 실행 ${esc(g.config.ids.join(', '))}</strong>${g.events.filter(e=>e.type==='message.created'&&!e.payload.silent).map(e=>`<p><strong>${esc(({macro:'영호',market:'영숙',risk:'영철',portfolio:'옥순'})[e.payload.role]||e.payload.role)}</strong> ${esc(e.payload.display_text)}</p>`).join('')}</article>`).join('')}</section>`;}
 function click(el){if(el.hasAttribute('data-comparison-start')){start();return true;}if(el.hasAttribute('data-comparison-cancel')){clearTimeout(timer);const g=generation;if(g){g.invalid=true;revoke(g).then(outcome=>{if(generation!==g)return;busy=false;generation=null;status=outcome==='completed'?'요청이 이미 완료되어 서버 이력에 보존됩니다.':'생성 취소 완료 · 미완료 응답 삭제됨';a.repaint();}).catch(e=>{busy=false;g.cancelRetry=true;status='취소 확인 실패 · '+e.message;a.repaint();});}return true;}if(el.hasAttribute('data-comparison-resume')){busy=true;generation.resume();return true;}return false;}
 return {configure,html,click};
};
