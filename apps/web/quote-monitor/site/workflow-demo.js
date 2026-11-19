(() => {
  'use strict';
  const API='/api', names={
    '005930':'삼성전자','000660':'SK하이닉스','373220':'LG에너지솔루션','207940':'삼성바이오로직스','005380':'현대차',
    '005935':'삼성전자우','000270':'기아','068270':'셀트리온','105560':'KB금융','012450':'한화에어로스페이스',
    '034020':'두산에너빌리티','055550':'신한지주','028260':'삼성물산','012330':'현대모비스','402340':'SK스퀘어',
    '032830':'삼성생명','086790':'하나금융지주','006400':'삼성SDI','009150':'삼성전기','034730':'SK'
  };
  const personas={macro:'거시경제 에이전트',market:'시장 에이전트',risk:'리스크 에이전트',portfolio:'포트폴리오 에이전트'};
  const sampleRows=[
    ['005930',194000,800805],['000660',1188000,2599829],['005380',253500,448221],['000270',147800,391220],['105560',98400,681004],['034020',43750,873019]
  ];
  const state={demo:new URLSearchParams(location.search).get('demo')==='1',quotes:new Map(),holdings:new Map(),supported:new Set(),selected:new Set(),news:[],selectedNews:new Set(),docs:new Map(),selectedDocs:new Set(),analysis:null,debateId:'',socket:null,quoteSocket:null,quoteRetry:null,debateRetry:null,debatePoll:null,quotePoll:null,newsLoaded:false,filterSupported:false,search:'',sampleTimer:null,seenEvents:new Set(),eventCursor:0,latestByDebate:new Map()};
  const $=id=>document.getElementById(id), won=value=>Number(value||0).toLocaleString('ko-KR'), safeText=value=>String(value??''), fmt=value=>{if(!value)return '미확인';const d=new Date(value);return Number.isNaN(d.getTime())?'미확인':d.toLocaleString('ko-KR',{timeZone:'Asia/Seoul',hour12:false})};
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  async function request(path,options={}){
    const response=await fetch(path.startsWith('/api')?path:API+path,{cache:'no-store',credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
    const type=response.headers.get('content-type')||'';
    if(response.redirected&&/login/i.test(new URL(response.url).pathname))throw Error('로그인이 필요합니다. Google 로그인 후 다시 시도하세요.');
    const body=type.includes('application/json')?await response.json():null;
    if(!response.ok)throw Error(typeof body?.detail==='string'?body.detail:body?.detail?.message||`API 요청 실패 (${response.status})`);
    if(!body)throw Error('API가 JSON 대신 HTML을 반환했습니다. 로그인/API 경로를 확인해 주세요.');
    return body;
  }
  function setChip(id,text,kind=''){const e=$(id);e.textContent=text;e.className=`chip ${kind}`.trim();}
  function addMessage(kind,label,text){const feed=$('chat-feed'),welcome=feed.querySelector('.welcome');if(welcome)welcome.remove();const box=document.createElement('div');box.className=`message ${kind}`;if(label){const title=document.createElement('span');title.className='speaker';title.textContent=label;box.append(title);}const content=document.createElement('span');content.textContent=text;box.append(content);feed.append(box);feed.scrollTop=feed.scrollHeight;}
  function addSystem(text){addMessage('system','',text);}

  function renderQuotes(){
    const root=$('quote-list');root.replaceChildren();
    const rows=[...state.quotes.values()].filter(q=>{
      const label=names[q.asset_id]||q.asset_name||q.asset_id||'';
      return (!state.search||`${label} ${q.asset_id}`.toLowerCase().includes(state.search.toLowerCase()))&&(!state.filterSupported||state.supported.has(q.asset_id));
    }).sort((a,b)=>Number(b.cumulative_volume||0)-Number(a.cumulative_volume||0));
    if(!rows.length){const empty=document.createElement('div');empty.className='empty';empty.textContent=state.demo?'샘플 종목이 없습니다.':'수신된 실제 시세가 없습니다. 연결 상태와 장 운영 시간을 확인하세요.';root.append(empty);}
    for(const q of rows){
      const id=q.asset_id,amount=state.holdings.get(id)?.amount_krw,selected=state.selected.has(id);
      const row=document.createElement('button');row.type='button';row.className=`quote-row ${selected?'selected':''}`;
      const pick=document.createElement('span');pick.className='pick';const box=document.createElement('input');box.type='checkbox';box.checked=selected;box.setAttribute('aria-label',`${names[id]||id} 선택`);pick.append(box);
      const asset=document.createElement('span');asset.className='asset';const label=document.createElement('strong');label.textContent=names[id]||q.asset_name||id;const code=document.createElement('small');code.textContent=`${id}${state.supported.size&&!state.supported.has(id)?' · 분석 미지원':''}${amount?` · 보유 ${won(amount)}원`:''}`;asset.append(label,code);
      const price=document.createElement('span');price.className='price';const current=document.createElement('strong');current.textContent=won(q.price);const volume=document.createElement('small');volume.textContent=`누적 거래량 ${won(q.cumulative_volume)}`;price.append(current,volume);
      const times=document.createElement('span');times.className='times';for(const [key,title,value] of [['event_time','체결',q.event_time],['received_at','수집',q.received_at],['browser_at','화면',q.browser_at]]){const line=document.createElement('span');line.innerHTML=`<b>${title}</b> ${escape(fmt(value))}`;times.append(line);}
      row.append(pick,asset,price,times);row.addEventListener('click',()=>openHolding(id));box.addEventListener('click',event=>event.stopPropagation());box.addEventListener('change',()=>{if(box.checked)openHolding(id);else{state.selected.delete(id);renderQuotes();}});root.append(row);
    }
    $('quote-count').textContent=`${rows.length}${state.demo?'개 예시 종목':'개 수신 종목'} · 선택 ${state.selected.size}개`;
    updateFlowControls();
  }
  function acceptQuotes(list,live){
    for(const q of list||[]){
      if(!q?.asset_id||!Number.isFinite(Number(q.price))||(!state.demo&&(q.is_mock!==false||!['quote_event','quote_latest'].includes(q.record_type))))continue;
      const previous=state.quotes.get(q.asset_id),stamp=x=>Date.parse(x?.event_time||x?.received_at||'')||0;
      if(previous&&stamp(q)<stamp(previous))continue;
      state.quotes.set(q.asset_id,{...q,browser_at:new Date().toISOString()});
    }
    if(live){$('quote-status').textContent='실시간 시세 수신 중';$('quote-dot').className='dot live';}
    renderQuotes();
  }
  async function quoteSnapshot(){
    try{const data=await request('/quotes/latest');acceptQuotes(data.quotes,false);if(!state.demo&&!state.quoteSocket){$('quote-status').textContent=state.quotes.size?'스냅샷 확인 · 스트림 연결 대기':'현재가 확인됨';$('quote-dot').className='dot';}}
    catch(error){if(!state.demo){$('quote-status').textContent=error.message;$('quote-dot').className='dot error';setChip('api-chip','실시간 API 오류','bad');}}
  }
  function closeQuoteSocket(){clearTimeout(state.quoteRetry);if(state.quoteSocket){state.quoteSocket.onclose=null;state.quoteSocket.close();state.quoteSocket=null;}}
  async function connectQuotes(){
    if(state.demo)return;closeQuoteSocket();$('quote-status').textContent='실시간 연결 중';
    try{const response=await fetch('/api/quotes/negotiate',{method:'POST',cache:'no-store',credentials:'same-origin'});if(!response.ok)throw Error(`시세 연결 실패 (${response.status})`);const token=await response.json();if(!token.url)throw Error('시세 연결 주소가 없습니다.');const socket=new WebSocket(token.url);state.quoteSocket=socket;
      socket.onopen=()=>{if(state.quoteSocket!==socket)return;$('quote-status').textContent='실시간 시세 연결됨';$('quote-dot').className='dot live';setChip('api-chip','시세 연결됨','ok');quoteSnapshot();};
      socket.onmessage=event=>{try{const message=JSON.parse(event.data);acceptQuotes(message.type==='quote_batch'?message.quotes:[message],true);}catch{$('quote-status').textContent='시세 메시지 해석 오류';}};
      socket.onerror=()=>{if(state.quoteSocket===socket){$('quote-status').textContent='실시간 연결 오류';$('quote-dot').className='dot error';socket.close();}};
      socket.onclose=()=>{if(state.quoteSocket!==socket||state.demo)return;state.quoteSocket=null;$('quote-status').textContent='재연결 중';$('quote-dot').className='dot';state.quoteRetry=setTimeout(connectQuotes,4000);};
    }catch(error){$('quote-status').textContent=error.message||'시세 API 연결 실패';$('quote-dot').className='dot error';state.quoteRetry=setTimeout(connectQuotes,6000);}
  }

  async function loadProfile(){
    try{const [support,profile]=await Promise.all([request('/stress/support'),request('/me/holdings')]);state.supported=new Set(support.supported_assets||[]);state.holdings.clear();for(const item of profile.holdings||[]){state.holdings.set(item.asset_id,item);state.selected.add(item.asset_id);}setChip('api-chip','로그인·보유종목 연결됨','ok');renderQuotes();}
    catch(error){setChip('api-chip',error.message||'로그인/API 확인 필요','bad');addSystem(`계정 API를 연결하지 못했습니다: ${error.message||error}. 데모 예시 모드로 화면 흐름을 볼 수 있습니다.`);}
  }
  function openHolding(assetId){
    if(state.supported.size&&!state.supported.has(assetId)){addSystem(`${names[assetId]||assetId}은 현재 스트레스 모델 지원 종목이 아닙니다.`);return;}
    const quote=state.quotes.get(assetId),saved=state.holdings.get(assetId);state.pendingAsset=assetId;
    $('holding-title').textContent=`${names[assetId]||assetId} 보유 금액`; $('holding-copy').textContent=`현재가 ${won(quote?.price)}원${quote?.event_time?` · 체결 ${fmt(quote.event_time)}`:''}. 평가 금액을 입력하세요.`;
    $('holding-amount').value=saved?.amount_krw||'';$('holding-message').textContent='';$('holding-dialog').showModal();
  }
  function closeHolding(){ $('holding-dialog').close(); }
  async function saveHolding(event){
    event.preventDefault();const id=state.pendingAsset,amount=Number($('holding-amount').value);if(!id||!(amount>0))return;
    const submit=$('holding-form').querySelector('[type=submit]');submit.disabled=true;$('holding-message').textContent='보유 종목 저장 중';
    try{
      if(state.demo){state.holdings.set(id,{asset_id:id,amount_krw:amount,shares:null});}
      else{const next=[...state.holdings.values()].filter(item=>item.asset_id!==id).map(item=>({asset_id:item.asset_id,amount_krw:Number(item.amount_krw),shares:item.shares||null}));next.push({asset_id:id,amount_krw:amount,shares:null});const saved=await request('/me/holdings',{method:'PUT',body:JSON.stringify({holdings:next})});state.holdings.clear();for(const item of saved.holdings||[])state.holdings.set(item.asset_id,item);}
      state.selected.add(id);renderQuotes();closeHolding();addSystem(`${names[id]||id} 보유 금액 ${won(amount)}원을 선택했습니다.`);
    }catch(error){$('holding-message').textContent=error.message||'저장하지 못했습니다.';}
    finally{submit.disabled=false;}
  }

  function setTab(tab){document.querySelectorAll('.tab').forEach(button=>{const active=button.dataset.tab===tab;button.classList.toggle('active',active);button.setAttribute('aria-selected',String(active));});document.querySelectorAll('.panel').forEach(panel=>panel.classList.toggle('active',panel.id===`panel-${tab}`));if(tab==='news')loadNews();}
  function safeHttps(value){try{const url=new URL(value);return url.protocol==='https:'?url.href:'';}catch{return '';}}
  function renderNews(){const root=$('news-list');root.replaceChildren();if(!state.news.length){const empty=document.createElement('div');empty.className='empty';empty.textContent=state.demo?'예시 뉴스가 없습니다.':'완료된 토론에서 수신한 뉴스 근거가 없습니다. 토론을 시작하면 여기서 선택할 수 있습니다.';root.append(empty);}
    for(const item of state.news){const card=document.createElement('label');card.className='source-card';const check=document.createElement('input');check.type='checkbox';check.checked=state.selectedNews.has(item.key);check.addEventListener('change',()=>{if(check.checked)state.selectedNews.add(item.key);else state.selectedNews.delete(item.key);updateBadges();});const main=document.createElement('span');main.className='source-main';const title=document.createElement('strong');title.textContent=`${item.asset_name||names[item.asset_id]||item.asset_id} · ${item.title||'뉴스 출처'}`;const sub=document.createElement('small');sub.textContent=`${item.debate_id||'토론 근거'} · ${item.asset_id||''} · ${item.source_id||''}`;main.append(title,sub);card.append(check,main);const safeUrl=safeHttps(item.url);if(safeUrl){const link=document.createElement('a');link.href=safeUrl;link.target='_blank';link.rel='noopener noreferrer';link.textContent='기사';link.addEventListener('click',e=>e.stopPropagation());card.append(link);}root.append(card);}
    $('news-badge').textContent=state.selectedNews.size?`(${state.selectedNews.size})`:'';updateFlowControls();
  }
  function addNewsFromEvidence(event){const payload=event.payload||{};for(const group of payload.web_news||[]){for(const citation of group.citations||[]){const key=`${event.debate_id}:${group.source_id}:${citation.url}`;if(state.news.some(item=>item.key===key))continue;state.news.unshift({key,debate_id:event.debate_id,source_id:group.source_id,asset_id:group.asset_id,asset_name:group.asset_name,title:citation.title,url:citation.url,search_query_urls:group.search_query_urls||[]});}}renderNews();}
  async function loadNews(){if(state.demo){renderNews();return;}if(state.newsLoaded){renderNews();return;}state.newsLoaded=true;
    try{const response=await request('/debates?limit=12');await Promise.all((response.debates||[]).map(async debate=>{try{const events=await request(`/debates/${encodeURIComponent(debate.debate_id)}/events?after_seq=0&limit=500`);for(const event of events.events||[])if(event.type==='debate.evidence_ready')addNewsFromEvidence(event);}catch{}}));renderNews();}
    catch(error){const root=$('news-list');root.innerHTML=`<div class="empty">뉴스 API를 불러오지 못했습니다: ${escape(error.message)}</div>`;}
  }

  function renderDocs(){const root=$('doc-list');root.replaceChildren();if(!state.docs.size){const empty=document.createElement('div');empty.className='empty';empty.textContent='텍스트 문서를 추가하면 여기서 에이전트에 전달할 파일을 선택할 수 있습니다.';root.append(empty);}for(const doc of state.docs.values()){const card=document.createElement('label');card.className='doc-card';const check=document.createElement('input');check.type='checkbox';check.checked=state.selectedDocs.has(doc.id);check.addEventListener('change',()=>{if(check.checked)state.selectedDocs.add(doc.id);else state.selectedDocs.delete(doc.id);updateBadges();});const main=document.createElement('span');main.className='source-main';const title=document.createElement('strong');title.textContent=doc.name;const details=document.createElement('small');details.textContent=`${doc.content.length.toLocaleString('ko-KR')}자 · 선택 시 후속 질문에 일부 내용 첨부`;main.append(title,details);card.append(check,main);const remove=document.createElement('button');remove.type='button';remove.textContent='제거';remove.className='soft-btn';remove.addEventListener('click',e=>{e.preventDefault();state.docs.delete(doc.id);state.selectedDocs.delete(doc.id);renderDocs();updateBadges();});card.append(remove);root.append(card);} $('docs-badge').textContent=state.selectedDocs.size?`(${state.selectedDocs.size})`:'';updateFlowControls();}
  async function addFiles(files){for(const file of files){if(file.size>300_000){$('doc-status').textContent=`${file.name}: 300KB 이하 텍스트 파일만 추가할 수 있습니다.`;continue;}if(!/\.(txt|md|csv)$/i.test(file.name)){$('doc-status').textContent=`${file.name}: TXT, MD, CSV만 읽을 수 있습니다.`;continue;}try{const content=await file.text(),id=`doc-${Date.now()}-${Math.random().toString(36).slice(2,7)}`;state.docs.set(id,{id,name:file.name,content});state.selectedDocs.add(id);$('doc-status').textContent=`${state.docs.size}개 문서가 이 화면에 임시 첨부됐습니다.`;}catch{$('doc-status').textContent=`${file.name} 파일을 읽지 못했습니다.`;}}renderDocs();}
  function updateBadges(){$('news-badge').textContent=state.selectedNews.size?`(${state.selectedNews.size})`:'';$('docs-badge').textContent=state.selectedDocs.size?`(${state.selectedDocs.size})`:'';updateFlowControls();}

  function money(value){return `${won(Math.round(Number(value||0)))}원`;}
  async function runStress(){
    const positions=[...state.selected].map(id=>({asset_id:id,value_krw:Number(state.holdings.get(id)?.amount_krw||0)})).filter(item=>item.value_krw>0&&(!state.supported.size||state.supported.has(item.asset_id)));
    if(!positions.length){addSystem('보유 금액을 입력한 스트레스 지원 종목을 먼저 선택하세요.');return;}
    $('run-stress').disabled=true;$('stress-result').textContent='스트레스 분석 계산 중';setChip('api-chip',state.demo?'데모 계산 중':'스트레스 API 계산 중');
    const shocks={fx_pct:Number($('shock-fx').value||0),us_rate_bp:Number($('shock-rate').value||0),wti_pct:Number($('shock-wti').value||0),vix_points:Number($('shock-vix').value||0)};
    try{
      if(state.demo){const total=positions.reduce((sum,p)=>sum+p.value_krw,0),delta=(shocks.fx_pct*.018+shocks.us_rate_bp*.0008+shocks.wti_pct*.006+shocks.vix_points*.004);state.analysis={analysis_id:`demo-${Date.now()}`,ai_handoff:{ready:true},portfolio_hypothetical_pnl_krw:Math.round(total*delta/100),portfolio_shock_incremental_pnl_krw:Math.round(total*delta/100),assets:positions.map(p=>({asset_id:p.asset_id,holding_krw:p.value_krw,scenario_return_pct:delta,hypothetical_pnl_krw:p.value_krw*delta/100})),demo:true};}
      else{state.analysis=await request('/stress/analyze',{method:'POST',body:JSON.stringify({positions,model:'catboost',shocks})});}
      const result=state.analysis;$('stress-result').textContent=`${result.demo?'예시 계산':'분석 완료'} · 보유 ${positions.length}종목 · 가상 손익 ${money(result.portfolio_hypothetical_pnl_krw)} · 무충격 대비 ${money(result.portfolio_shock_incremental_pnl_krw)}`;
      setChip('api-chip',result.demo?'데모 결과':'스트레스 분석 완료',result.demo?'':'ok');addMessage('agent','스트레스 분석',`${result.demo?'예시 계산입니다. 실제 ML 결과가 아닙니다.\n':''}총 보유 평가액 ${money(positions.reduce((s,p)=>s+p.value_krw,0))}\n시나리오 가상 손익 ${money(result.portfolio_hypothetical_pnl_krw)}\n무충격 대비 변화 ${money(result.portfolio_shock_incremental_pnl_krw)}${result.analysis_id?`\n분석 ID ${result.analysis_id}`:''}`);updateFlowControls();
    }catch(error){$('stress-result').textContent=`분석 실패: ${error.message}`;setChip('api-chip','스트레스 API 오류','bad');addSystem(`스트레스 분석 API 오류: ${error.message}`);}
    finally{$('run-stress').disabled=false;updateFlowControls();}
  }

  async function replayDebateEvents(){if(!state.debateId||state.demo)return;try{const response=await request(`/debates/${encodeURIComponent(state.debateId)}/events?after_seq=${state.eventCursor}&limit=500`);for(const event of response.events||[])handleDebateEvent(event);}catch(error){setChip('debate-chip',`이벤트 재생 오류: ${error.message}`,'bad');}}
  function connectDebateSocket(url){if(!url)return;closeDebateSocket();setChip('debate-chip','에이전트 연결 중');replayDebateEvents();state.debatePoll=setInterval(replayDebateEvents,5000);const socket=new WebSocket(url);state.socket=socket;socket.onopen=()=>{if(state.socket===socket)setChip('debate-chip','에이전트 연결됨','ok');};socket.onmessage=message=>{try{handleDebateEvent(JSON.parse(message.data));}catch{setChip('debate-chip','토론 이벤트 해석 오류','bad');}};socket.onerror=()=>{if(state.socket===socket)setChip('debate-chip','실시간 연결 오류','bad');};socket.onclose=()=>{if(state.socket!==socket||!state.debateId)return;state.socket=null;setChip('debate-chip','재연결 중');state.debateRetry=setTimeout(async()=>{try{const token=await request(`/debates/${encodeURIComponent(state.debateId)}/negotiate`);connectDebateSocket(token.url);}catch(error){setChip('debate-chip',error.message,'bad');}},3000);};}
  function closeDebateSocket(){clearTimeout(state.debateRetry);clearInterval(state.debatePoll);if(state.socket){state.socket.onclose=null;state.socket.close();state.socket=null;}}
  function handleDebateEvent(event){if(!event)return;if(Number.isFinite(Number(event.seq)))state.eventCursor=Math.max(state.eventCursor,Number(event.seq));const key=event.event_id||`${event.debate_id}:${event.seq}`;if(state.seenEvents.has(key))return;state.seenEvents.add(key);const p=event.payload||{};if(event.type==='debate.evidence_ready')addNewsFromEvidence(event);else if(event.type==='message.created'){if(p.silent)return;const text=p.display_text||p.summary_text||p.claims?.map(item=>item.statement).filter(Boolean).join('\n')||'에이전트 응답이 도착했습니다.';addMessage('agent',personas[p.role]||p.role||'에이전트',text);}else if(event.type==='message.failed')addMessage('system','에이전트 응답 실패',`${personas[p.role]||p.role||'에이전트'}: ${p.reason||'응답을 생성하지 못했습니다.'}`);else if(event.type==='debate.completed'){setChip('debate-chip','토론 완료','ok');addSystem('초기 에이전트 토론이 완료됐습니다. 아래에서 후속 질문을 보낼 수 있습니다.');}else if(event.type==='debate.failed'){setChip('debate-chip','토론 실패','bad');addSystem(`토론 실패: ${p.reason||'오류 원인 미확인'}`);}else if(event.type==='debate.accepted')setChip('debate-chip','토론 접수됨','ok');else if(event.type==='debate.round')addSystem(`${p.round||''}라운드 진행 중`);}
  async function startDebate(){if(!state.analysis){addSystem('스트레스 분석을 먼저 실행하세요.');return;}if(state.demo){state.debateId=`demo-debate-${Date.now()}`;setChip('debate-chip','데모 에이전트 연결됨','ok');updateFlowControls();addSystem('데모 대화가 시작됐습니다. 질문을 입력해 보세요.');setTimeout(()=>addMessage('agent','시장 에이전트','실시간 시장 자료와 스트레스 예시 결과를 바탕으로 답변하는 데모 상태입니다. 선택한 뉴스·문서 자료는 후속 질문에 포함됩니다.'),700);return;}
    $('start-debate').disabled=true;setChip('debate-chip','토론 시작 요청 중');try{const response=await request('/debates',{method:'POST',body:JSON.stringify({run_id:state.analysis.analysis_id})});state.debateId=response.debate_id;setChip('debate-chip','토론 접수됨','ok');addSystem(`토론 ${response.debate_id}을 시작했습니다. 실시간 에이전트 응답을 기다립니다.`);connectDebateSocket(response.pubsub?.url);updateFlowControls();}catch(error){setChip('debate-chip','토론 API 오류','bad');addSystem(`토론을 시작하지 못했습니다: ${error.message}`);}finally{$('start-debate').disabled=false;updateFlowControls();}}

  function contextForQuestion(question){let remaining=Math.max(0,1900-question.length-60),sections=[];const add=(title,text)=>{if(!text||remaining<=0)return;const content=String(text).slice(0,remaining);sections.push(`${title}\n${content}`);remaining-=content.length+title.length+4;};
    if($('use-market').checked){const selected=[...state.selected].map(id=>{const q=state.quotes.get(id),holding=state.holdings.get(id);return q?`${names[id]||id}(${id}) 현재가 ${won(q.price)}원, 보유 평가액 ${money(holding?.amount_krw)}, 체결 ${fmt(q.event_time)}`:''}).filter(Boolean);if(selected.length)add('선택 종목과 보유 금액',selected.join('\n'));const all=[...state.quotes.values()].sort((a,b)=>Number(b.cumulative_volume||0)-Number(a.cumulative_volume||0)).map(q=>`${names[q.asset_id]||q.asset_name||q.asset_id}(${q.asset_id}) ${won(q.price)}원 · 누적 거래량 ${won(q.cumulative_volume)}`).slice(0,15);if(all.length)add('최근 수신 전체 실시간 시세(거래량 상위 15)',all.join('\n'));}
    if($('use-stress').checked&&state.analysis){const shocks=`환율 ${$('shock-fx').value}%, 미국 금리 ${$('shock-rate').value}bp, WTI ${$('shock-wti').value}%, VIX ${$('shock-vix').value}pt`;add('선택한 스트레스 분석',`분석 ID ${state.analysis.analysis_id}; ${shocks}; 가상 손익 ${money(state.analysis.portfolio_hypothetical_pnl_krw)}; 무충격 대비 ${money(state.analysis.portfolio_shock_incremental_pnl_krw)}`);}
    if($('use-news').checked){const data=state.news.filter(item=>state.selectedNews.has(item.key)).map(item=>`${item.asset_name||item.asset_id}: ${item.title||'뉴스 출처'} (${safeHttps(item.url)||'출처 URL 없음'})`);if(data.length)add('사용자가 선택한 뉴스 출처',data.join('\n'));}
    if($('use-docs').checked){const data=[...state.selectedDocs].map(id=>state.docs.get(id)).filter(Boolean).map(doc=>`${doc.name}: ${doc.content.slice(0,450)}`);if(data.length)add('사용자가 선택한 문서 발췌',data.join('\n'));
    }
    return sections.length?`${question}\n\n[선택 자료]\n${sections.join('\n\n')}`:question;
  }
  async function sendQuestion(event){event.preventDefault();const question=$('question').value.trim();if(!question)return;if(!state.debateId){addSystem('먼저 스트레스 분석을 실행하고 AI 에이전트를 연결하세요.');return;}const roles=[...document.querySelectorAll('input[name=role]:checked')].map(input=>input.value);if(!roles.length){addSystem('답변할 에이전트를 하나 이상 선택하세요.');return;}const text=contextForQuestion(question);if(text.length>2000){addSystem('선택 자료가 많습니다. 질문이나 첨부 문서 발췌를 줄여 주세요.');return;}
    $('send-question').disabled=true;addMessage('user','나',question);$('question').value='';
    try{if(state.demo){addSystem(`선택 에이전트: ${roles.map(role=>personas[role]).join(', ')} · 첨부 자료 ${Math.max(0,(text.length-question.length))}자`);setTimeout(()=>{for(const role of roles)addMessage('agent',personas[role],`질문과 선택한 자료를 확인했습니다. ${state.selected.size?`${[...state.selected].map(id=>names[id]||id).join(', ')}의 보유 금액과 스트레스 예시 결과를 함께 살펴보겠습니다.`:'선택 종목이 없어 일반적인 관점으로 답합니다.'} 실제 연결 모드에서는 선택한 근거를 바탕으로 토론 에이전트가 답합니다.`);},650);}
      else{await request(`/debates/${encodeURIComponent(state.debateId)}/questions`,{method:'POST',body:JSON.stringify({text,target_roles:roles})});addSystem('질문을 토론 에이전트에 전달했습니다.');}}
    catch(error){addSystem(`질문을 보내지 못했습니다: ${error.message}`);}finally{$('send-question').disabled=false;updateFlowControls();}}

  function switchMode(){state.demo=!state.demo;state.quotes.clear();state.news=[];state.selectedNews.clear();state.newsLoaded=false;closeQuoteSocket();clearInterval(state.sampleTimer);if(state.demo){$('mode-toggle').textContent='실시간 API';$('mode-label').textContent='데모 예시 모드 · 샘플 데이터';$('quote-status').textContent='데모 예시 데이터';$('quote-dot').className='dot';state.supported=new Set(sampleRows.map(row=>row[0]));for(const [id,price,volume] of sampleRows)state.quotes.set(id,{asset_id:id,price,cumulative_volume:volume,record_type:'quote_latest',is_mock:true,event_time:new Date().toISOString(),received_at:new Date().toISOString(),browser_at:new Date().toISOString()});state.news=[{key:'demo-news-1',asset_id:'005930',asset_name:'삼성전자',title:'예시 뉴스 카드 · 실제 뉴스가 아닙니다',url:''}];renderNews();renderQuotes();setChip('api-chip','데모 예시 모드');}
    else{$('mode-toggle').textContent='데모 예시';$('mode-label').textContent='실시간 API 모드';state.holdings.clear();state.selected.clear();state.analysis=null;state.debateId='';state.supported.clear();renderQuotes();setChip('api-chip','API 연결 중');loadProfile();quoteSnapshot();connectQuotes();loadNews();}}

  function startDemoPriceTicks(){state.sampleTimer=setInterval(()=>{if(!state.demo)return;for(const [id,q] of state.quotes){const delta=(Math.random()-.48)*.0008;state.quotes.set(id,{...q,price:Math.max(100,Math.round(q.price*(1+delta))),event_time:new Date().toISOString(),received_at:new Date().toISOString(),browser_at:new Date().toISOString()});}renderQuotes();},3500);}
  function updateFlowControls(){const selected=[...state.selected].filter(id=>state.holdings.has(id)&&(!state.supported.size||state.supported.has(id)));$('run-stress').disabled=!selected.length||(!state.demo&&!state.supported.size);$('start-debate').disabled=!state.analysis||(!state.demo&&!state.analysis.ai_handoff?.ready);$('send-question').disabled=!state.debateId;}

  document.querySelectorAll('.tab').forEach(button=>button.addEventListener('click',()=>setTab(button.dataset.tab)));
  document.querySelectorAll('[data-prompt]').forEach(button=>button.addEventListener('click',()=>{$('question').value=button.dataset.prompt;$('question').focus();}));
  $('search').addEventListener('input',event=>{state.search=event.target.value;renderQuotes();});
  $('supported-only').addEventListener('click',event=>{state.filterSupported=!state.filterSupported;event.currentTarget.classList.toggle('active-filter',state.filterSupported);renderQuotes();});
  $('refresh-quotes').addEventListener('click',()=>{quoteSnapshot();if(!state.demo)connectQuotes();});
  $('mode-toggle').addEventListener('click',switchMode);
  $('doc-input').addEventListener('change',event=>addFiles([...event.target.files]));
  $('holding-form').addEventListener('submit',saveHolding);$('close-holding').addEventListener('click',closeHolding);$('cancel-holding').addEventListener('click',closeHolding);
  $('run-stress').addEventListener('click',runStress);$('start-debate').addEventListener('click',startDebate);$('composer').addEventListener('submit',sendQuestion);
  $('clear-chat').addEventListener('click',()=>{$('chat-feed').innerHTML='<div class="welcome">종목을 선택해 보유 금액을 입력한 뒤 스트레스 분석을 실행하세요.</div>';state.analysis=null;state.debateId='';state.eventCursor=0;state.seenEvents.clear();closeDebateSocket();setChip('debate-chip','토론 대기');updateFlowControls();});
  window.addEventListener('pagehide',()=>{closeQuoteSocket();closeDebateSocket();clearInterval(state.sampleTimer);clearInterval(state.quotePoll);});
  if(state.demo){$('mode-toggle').textContent='실시간 API';$('mode-label').textContent='데모 예시 모드 · 샘플 데이터';for(const [id,price,volume]of sampleRows)state.quotes.set(id,{asset_id:id,price,cumulative_volume:volume,record_type:'quote_latest',is_mock:true,event_time:new Date().toISOString(),received_at:new Date().toISOString(),browser_at:new Date().toISOString()});state.supported=new Set(sampleRows.map(row=>row[0]));state.news=[{key:'demo-news-1',asset_id:'005930',asset_name:'삼성전자',title:'예시 뉴스 카드 · 실제 뉴스가 아닙니다',url:''}];$('quote-status').textContent='데모 예시 데이터';renderQuotes();renderNews();startDemoPriceTicks();setChip('api-chip','데모 예시 모드');}
  else{loadProfile();quoteSnapshot();connectQuotes();loadNews();state.quotePoll=setInterval(quoteSnapshot,20000);}
  updateFlowControls();
})();
