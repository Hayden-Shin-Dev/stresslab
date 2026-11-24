/* Handoff execution controller: input selection is independent of chart display.
   Local preferences are never presented as account/server synchronization. */
window.installWhatIfHandoff = function (a) {
  const {state:s, mode, model, holdings, names, current, repaint, persist, commit, startAgents}=a;
  const archive=window.installWhatIfArchive({...a,restore:r=>{const c=r.result.shocks;s.sim={...s.sim,fx:c.fx_pct,rate:c.us_rate_bp/100,oil:c.wti_pct,vix:c.vix_points};a.setMode(r.context.analysis_type);a.setModel(r.result.model);s.analysisSelections[r.context.analysis_type]=r.result.assets.map(x=>x.asset_id);persist();repaint();}});
  const selections=s.analysisSelections ||= {market:[],portfolio:[]};
  const settings=window.installWhatIfSettings({capture:()=>({schema:1,windows:a.windowLayout(),selections:structuredClone(selections),mode:mode(),model:model(),conditions:structuredClone(s.sim),chart:structuredClone(a.chart())}),restore:value=>{if(value.schema!==1)return;a.restoreWindows(value.windows);for(const type of ['market','portfolio'])if(Array.isArray(value.selections?.[type]))selections[type]=[...new Set(value.selections[type].filter(c=>/^\d{6}$/.test(c)))];if(['market','portfolio'].includes(value.mode))a.setMode(value.mode);if(['ridge','catboost'].includes(value.model))a.setModel(value.model);for(const k of ['fx','rate','oil','vix'])if(Number.isFinite(Number(value.conditions?.[k])))s.sim[k]=Number(value.conditions[k]);if(value.chart&&typeof value.chart==='object'){const v=value.chart;a.setChart({view:v.view==='assets'?'assets':'total',compareAssets:Array.isArray(v.compareAssets)?[...new Set(v.compareAssets.filter(c=>/^\d{6}$/.test(c)))].slice(0,4):[],hiddenAssets:Array.isArray(v.hiddenAssets)?v.hiddenAssets.filter(c=>/^\d{6}$/.test(c)):[],layoutColumns:[1,2,3,4].includes(v.layoutColumns)?v.layoutColumns:2,focusedAsset:/^\d{6}$/.test(v.focusedAsset||'')?v.focusedAsset:'',series:{baseline:v.series?.baseline!==false,scenario:v.series?.scenario!==false}});}persist();},repaint});
  let targetsOpen=true,supported=null, supportError='', supportPending=false, pending=null, epoch=0;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const codes=()=>[...new Set(selections[mode()]||[])];
  const input=()=>({mode:mode(),model:model(),codes:codes().sort(),conditions:{fx:Number(s.sim.fx),rate:Number(s.sim.rate),oil:Number(s.sim.oil),vix:Number(s.sim.vix)},holdings:mode()==='portfolio'?holdings().filter(x=>codes().includes(x.code)).map(x=>({code:x.code,quantity:x.quantity,avgPurchasePrice:x.avgPurchasePrice})).sort((a,b)=>a.code.localeCompare(b.code)):[]});
  const request=async(path,body,signal)=>{const r=await fetch('/api'+path,{method:body?'POST':'GET',credentials:'same-origin',headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{}),signal});if(!r.ok)throw Error(r.status===401?'로그인이 필요합니다. 입력은 유지됩니다.':`요청 실패 (${r.status}). 다시 시도해 주세요.`);return r.json();};
  async function support(){if(supportPending)return;supportPending=true;supportError='';try{const r=await request('/stress/support',null,AbortSignal.timeout(15000));if(!Array.isArray(r.supported_assets))throw Error('모델 지원 종목 응답을 확인할 수 없습니다.');supported=new Set(r.supported_assets);}catch(e){supportError=e.message;}finally{supportPending=false;repaint();}}
  function mount(){const root=document.querySelector('.fig-main-panel')||document.querySelector('.ws-resource-region');if(!root)return;if(!supported&&!supportPending&&!supportError)support();root.querySelector('.handoff-inputs')?.remove();
    const list=mode()==='portfolio'?[...new Set(holdings().map(x=>x.code))]:[...(supported||[])];
    const selected=codes(),research=!!a.research?.()&&!root.matches('.fig-main-panel'),old=research?null:current(),dirty=old?.inputSnapshot&&JSON.stringify(old.inputSnapshot)!==JSON.stringify(input());
    const panel=document.createElement('section');panel.className='handoff-inputs';panel.setAttribute('aria-label','스트레스테스트 분석 대상');
    const portfolioMode=mode()==='portfolio',qty=code=>holdings().filter(x=>x.code===code).reduce((n,x)=>n+(Number(x.quantity)||0),0);
    const targetRows=list.map(code=>{const on=selected.includes(code),ok=!!supported?.has(code);return `<tr class="${on?'is-selected':''}${supported&&!ok?' is-unsupported':''}"><th scope="row"><label><input type="checkbox" data-analysis-code="${esc(code)}" ${on?'checked':''} ${pending||!ok?'disabled':''}>${esc(names()[code]||code)}</label></th><td>${esc(code)}</td><td>${supported?(ok?'지원':'모델 미지원'):'확인 중'}</td>${portfolioMode?`<td>${qty(code).toLocaleString('ko-KR')}주</td>`:''}</tr>`;}).join('');
    const targetTable=targetRows?`<table class="handoff-targets"><caption class="rm-sr">${research?'리서치 선택':'분석 대상'} 종목 · 체크한 종목만 계산</caption><thead><tr><th scope="col">종목</th><th scope="col">코드</th><th scope="col">모델</th>${portfolioMode?'<th scope="col">보유 수량</th>':''}</tr></thead><tbody>${targetRows}</tbody></table>`:`<p>${esc(supportError|| (supportPending?'지원 종목 확인 중…':portfolioMode?'서버에 저장된 보유 종목을 추가해 주세요.':'지원 종목이 없습니다.'))}</p>`;
    panel.innerHTML=`<header><button type="button" class="handoff-targets-toggle" aria-expanded="${targetsOpen}" aria-controls="handoff-targets-body"><strong>${research?'리서치 선택':'분석 대상'} ${selected.length}종목</strong><span>${targetsOpen?'접기 ▲':'펼치기 ▼'}</span></button><button type="button" class="rm-info" data-tip="체크한 종목만 계산합니다. 차트의 종목 비교 목록(최대 4개)과는 별도로 관리됩니다." aria-label="분석 대상 도움말">i</button></header><div class="handoff-stock-options" id="handoff-targets-body"${targetsOpen?'':' hidden'}>${targetTable}</div>`;
    (()=>{const after=root.querySelector(':scope > .fig-shock-panel')||root.querySelector(':scope > .fig-model-row');if(after)after.after(panel);else root.prepend(panel);})();
    // Run/status group: PLAY, the run state line and the current time read as one
    // unit (v1.4 grouping). render() rebuilds the panel, so this runs on fresh DOM.
    let runGroup=root.querySelector(':scope > .handoff-run-group');
    if(!runGroup){runGroup=document.createElement('section');runGroup.className='handoff-run-group';runGroup.setAttribute('aria-label','실행 · 상태');panel.after(runGroup);}
    const play=root.querySelector(':scope > .fig-run-button');if(play)runGroup.prepend(play);
    runGroup.querySelector(':scope > .handoff-run-state')?.remove();
    const runState=document.createElement('div');runState.className='handoff-run-state';runState.innerHTML=`<div role="status">${pending?'모델 계산 중 · 이전 성공 결과를 표시합니다.':research?'독립 리서치 선택 · 자동 스트레스 계산 없음':dirty?'입력 변경 · 결과 미갱신 · PLAY로 재실행해 주세요.':old?.stressResult?'마지막 성공 결과 표시 중':'분석할 종목과 조건을 선택한 뒤 PLAY를 누르세요.'}</div>${pending?'<button type="button" data-analysis-cancel>계산 요청 취소</button>':''}${supportError?'<button type="button" data-analysis-support-retry>지원 종목 다시 조회</button>':''}${s.runError?`<p role="alert">${esc(s.runError)}</p>`:''}`;
    runGroup.append(runState);
    const clock=root.querySelector('.fig-model-row .fig-clock');if(clock)runGroup.append(clock);
    if(root.matches('.fig-main-panel'))archive.mount(panel);settings.mount(panel);
    document.querySelectorAll('.handoff-agent-selection').forEach(el=>el.remove());
    const context=document.querySelector('.ws-target-slot')||document.querySelector('.ws-context');
    if(context&&root.matches('.fig-main-panel')){const agent=document.createElement('details');agent.className='handoff-agent-selection';agent.innerHTML='<summary>분석 대상 선택 · '+(mode()==='portfolio'?'보유 종목':'독립 종목')+'</summary>'+(()=>{const copy=panel.querySelector('.handoff-stock-options').cloneNode(true);copy.removeAttribute('id');copy.hidden=false;return copy.outerHTML;})()+'<p>선택 변경은 아직 계산·응답에 반영되지 않습니다.</p>';context.append(agent);}
    document.querySelectorAll('[data-analysis-code]').forEach(el=>el.addEventListener('change',()=>{const set=new Set(codes());el.checked?set.add(el.dataset.analysisCode):set.delete(el.dataset.analysisCode);selections[mode()]=[...set];persist();repaint();}));
    runGroup.querySelector('[data-analysis-support-retry]')?.addEventListener('click',support);
    panel.querySelector('.handoff-targets-toggle')?.addEventListener('click',e=>{targetsOpen=!targetsOpen;const t=e.currentTarget,body=panel.querySelector('#handoff-targets-body');t.setAttribute('aria-expanded',String(targetsOpen));t.querySelector('span').textContent=targetsOpen?'접기 ▲':'펼치기 ▼';if(body){body.hidden=!targetsOpen;body.classList.toggle('rm-opening',targetsOpen);}});
    runGroup.querySelector('[data-analysis-cancel]')?.addEventListener('click',()=>{epoch++;pending?.abort();pending=null;s.runError='계산 요청을 취소했습니다. 이전 결과는 유지됩니다.';repaint();});
  }
  async function run(){if(pending)return;const snapshot=input(),selected=snapshot.codes;
    if(!selected.length){s.runError='분석 대상 종목을 한 개 이상 선택해 주세요.';repaint();return;}
    if(!supported||selected.some(x=>!supported.has(x))){s.runError='미지원 종목을 확인하고 지원 종목 조회를 다시 시도해 주세요.';repaint();return;}
    const c=snapshot.conditions;if(['fx','rate','oil','vix'].some(k=>s.sim[k]===''||!Number.isFinite(c[k]))||Math.abs(c.fx)>30||Math.abs(c.rate)>3||Math.abs(c.oil)>80||Math.abs(c.vix)>80){s.runError='네 충격 변수의 입력 범위를 확인해 주세요.';repaint();return;}
    const controller=new AbortController(),ticket=++epoch;pending=controller;s.runError='';repaint();const timer=setTimeout(()=>controller.abort(),45000);
    try{
      const previous=current();if(previous?.stressResult&&!previous.archived)archive.archive(previous);
      const quotePayload=await request('/quotes/latest',null,controller.signal);
      const quotes=Object.fromEntries((quotePayload.quotes||[]).filter(q=>q.record_type==='quote_latest'&&q.is_mock===false&&Number(q.price)>0&&Number.isFinite(Date.parse(q.event_time))).map(q=>[q.asset_id,{price:Number(q.price),at:q.event_time,venue:q.venue,session:q.session}]));
      const lots=structuredClone(holdings()).filter(x=>selected.includes(x.code)).map(x=>({...x,price:quotes[x.code]?.price||null,priceAt:quotes[x.code]?.at||null}));
      const positions=selected.map(asset_id=>{let value_krw=1000000;if(snapshot.mode==='portfolio'){const owned=lots.filter(x=>x.code===asset_id);if(!owned.length||!quotes[asset_id])throw Error(`${names()[asset_id]||asset_id} 보유 수량 또는 실제 시세가 없습니다.`);value_krw=owned.reduce((sum,x)=>sum+Number(x.quantity)*quotes[asset_id].price,0);}return {asset_id,value_krw};});
      const result=await request('/stress/analyze',{positions,analysis_type:snapshot.mode,model:snapshot.model,shocks:{fx_pct:c.fx,us_rate_bp:c.rate*100,wti_pct:c.oil,vix_points:c.vix}},controller.signal);
      if(ticket!==epoch)return;const valid=window.whatIfStressChart.derive(result);if(valid.error)throw Error(valid.error);
      if(result.model!==snapshot.model||JSON.stringify(result.assets.map(x=>x.asset_id).sort())!==JSON.stringify(selected))throw Error('요청 종목·모델과 반환 결과가 달라 이전 결과를 유지했습니다.');
      const run={id:result.analysis_id||crypto.randomUUID(),at:new Date().toISOString(),version:'V6',appVersion:'6.0.0',targetKey:snapshot.mode==='portfolio'?'portfolio':'stocks',targetLabel:snapshot.mode==='portfolio'?'선택 보유 종목':'선택 종목',conditions:c,horizon:result.horizon_trading_days,stressMode:snapshot.mode,stressModel:snapshot.model,personaIds:[...s.selectedRoles],inputSnapshot:snapshot,priceSnapshot:structuredClone(Object.fromEntries(selected.filter(code=>quotes[code]).map(code=>[code,quotes[code]]))),portfolioLots:lots,stressResult:structuredClone(result),source_kind:'api',azureAnalysisId:result.ai_handoff?.ready?result.analysis_id:null,azureStatus:'ready',azureScope:`선택 ${selected.length}종목 · ${snapshot.mode==='portfolio'?'개인 보유분':'독립 종목 계산 · API 명목 금액'}`,autoSummary:true};
      commit(run);persist();
      if(result.archive_status?.persisted)archive.saveContext(run);
      else run.archiveError=result.archive_status?.reason||'서버 보관소 저장을 확인할 수 없습니다.';
      if(run.azureAnalysisId&&s.selectedRoles.length)startAgents(run).catch(e=>{run.azureStatus='failed';run.azureError='계산 완료 · AI 연결 실패: '+e.message;persist();repaint();});
      else if(!run.azureAnalysisId){run.azureStatus='failed';run.azureError='계산 완료 · 서버 근거 저장을 확인할 수 없어 AI 연결은 보류됐습니다.';}
      persist();
    }catch(e){if(ticket===epoch)s.runError=e.name==='AbortError'?'계산 시간이 초과됐습니다. 이전 결과를 유지했습니다. 다시 실행해 주세요.':e.message;}
    finally{clearTimeout(timer);if(ticket===epoch){pending=null;repaint();}}
  }
  function selectionText(text){
    const match=String(text||'').trim().match(/^(.+?)(?:을|를)?\s+(?:분석 대상에?\s*)?(추가|선택|제외|해제)(?:해줘|해 줘|해주세요|해 주세요)?[.!]?$/);
    if(!match)return false;
    const query=match[1].trim(), found=Object.entries(names()).filter(([code,name])=>query===code||query===name||query===name+'을'||query===name+'를');
    let message;
    if(found.length!==1)message='분석 대상 선택: 정확한 종목명 또는 6자리 코드를 입력해 주세요. 선택은 변경하지 않았습니다.';
    else{const code=found[0][0], available=mode()==='portfolio'?holdings().some(x=>x.code===code):supported?.has(code);if(!available||!supported?.has(code))message='현재 분석 유형에서 선택할 수 없는 종목입니다. 보유·모델 지원 상태를 확인해 주세요.';
    else{const list=new Set(codes());['추가','선택'].includes(match[2])?list.add(code):list.delete(code);selections[mode()]=[...list];message=found[0][1]+' 분석 대상 '+match[2]+' · 입력 변경 / 결과·응답 미갱신. PLAY를 눌러 재실행해 주세요.';}}
    a.recordSelection(message);persist();repaint();return true;
  }
  return {mount,run,selectionText,syncSettings:()=>settings.changed(),cancel:()=>{epoch++;pending?.abort();pending=null;}};
};
