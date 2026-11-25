/* The same selection drives the chart and the next stress test. */
window.installWhatIfHandoff = function (a) {
  const {state:s, mode, model, holdings, names, current, repaint, persist, commit, startAgents}=a;
  const archive=window.installWhatIfArchive({...a,restore:r=>{const c=r.result.shocks;s.sim={...s.sim,horizon:r.result.horizon_trading_days||5,fx:c.fx_pct,rate:c.us_rate_bp/100,oil:c.wti_pct,vix:c.vix_points};a.setMode(r.context.analysis_type);a.setModel(r.result.model);s.analysisSelections[r.context.analysis_type]=r.result.assets.map(x=>x.asset_id);persist();repaint();}});
  const selections=s.analysisSelections ||= {market:[],portfolio:[]};
  const settings=window.installWhatIfSettings({capture:()=>({schema:1,windows:a.windowLayout(),selections:structuredClone(selections),mode:mode(),model:model(),conditions:structuredClone(s.sim),chart:structuredClone(a.chart())}),restore:value=>{if(value.schema!==1)return;a.restoreWindows(value.windows);for(const type of ['market','portfolio'])if(Array.isArray(value.selections?.[type]))selections[type]=[...new Set(value.selections[type].filter(c=>/^\d{6}$/.test(c)))];if(['market','portfolio'].includes(value.mode))a.setMode(value.mode);if(['ridge','catboost'].includes(value.model))a.setModel(value.model);if([1,5,20].includes(value.conditions?.horizon))s.sim.horizon=value.conditions.horizon;for(const k of ['fx','rate','oil','vix'])if(Number.isFinite(Number(value.conditions?.[k])))s.sim[k]=Number(value.conditions[k]);if(value.chart&&typeof value.chart==='object'){const v=value.chart;a.setChart({view:v.view==='assets'?'assets':'total',compareAssets:Array.isArray(v.compareAssets)?[...new Set(v.compareAssets.filter(c=>/^\d{6}$/.test(c)))].slice(0,4):[],hiddenAssets:Array.isArray(v.hiddenAssets)?v.hiddenAssets.filter(c=>/^\d{6}$/.test(c)):[],period:window.whatIfStressChart.periods.has(v.period)?v.period:'day',representation:['line','candle','ohlc'].includes(v.representation)?v.representation:'line',layoutColumns:[1,2,3,4].includes(v.layoutColumns)?v.layoutColumns:2,focusedAsset:/^\d{6}$/.test(v.focusedAsset||'')?v.focusedAsset:'',series:{baseline:v.series?.baseline!==false,scenario:v.series?.scenario!==false}});}persist();},repaint});
  const selectionLimit=4;
  for(const type of ['market','portfolio']) selections[type]=(selections[type]||[]).slice(0,selectionLimit);
  let supported=null, horizons=[5], supportsNews=false, supportError='',supportPending=false,pending=null,epoch=0,phase='';
  let pickerOpen=false,pickerQuery='',pickerScroll=0,pickerFocus=null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const codes=()=>[...new Set(selections[mode()]||[])].filter(code=>(!supported||supported.has(code))&&(mode()!=='portfolio'||holdings().some(x=>x.code===code))).slice(0,selectionLimit);
  const input=()=>({mode:mode(),model:model(),horizon:Number(s.sim.horizon)||5,includeNews:s.scenarioIncludeNews===true,codes:codes().sort(),conditions:{fx:Number(s.sim.fx),rate:Number(s.sim.rate),oil:Number(s.sim.oil),vix:Number(s.sim.vix)},holdings:mode()==='portfolio'?holdings().filter(x=>codes().includes(x.code)).map(x=>({code:x.code,quantity:x.quantity,avgPurchasePrice:x.avgPurchasePrice})).sort((a,b)=>a.code.localeCompare(b.code)):[]});
  const request=async(path,body,signal,headers={})=>{const r=await fetch('/api'+path,{cache:'no-store',method:body?'POST':'GET',credentials:'same-origin',headers:{'Content-Type':'application/json',...headers},...(body?{body:JSON.stringify(body)}:{}),signal});if(!r.ok)throw Object.assign(Error(r.status===401?'로그인 후 다시 시도해 주세요.':'요청을 완료하지 못했습니다. 다시 시도해 주세요.'),{status:r.status});return r.json();};
  async function support(){if(supportPending)return;supportPending=true;supportError='';try{const r=await request('/stress/support',null,AbortSignal.timeout(15000));if(!Array.isArray(r.supported_assets))throw Error('모델 지원 종목 응답을 확인할 수 없습니다.');supported=new Set(r.supported_assets);horizons=Array.isArray(r.supported_horizon_trading_days)?[1,5,20].filter(days=>r.supported_horizon_trading_days.includes(days)):[5];supportsNews=r.news_scenarios_version==='V1.6-r8';}catch(e){supportError=e.message;}finally{supportPending=false;repaint();}}
  function beforeRender(){
    const picker=document.querySelector('.scenario-symbols');
    const active=document.activeElement;
    pickerFocus=null;
    if(!picker?.open)return;
    pickerScroll=picker.querySelector('.scenario-symbol-list').scrollTop;
    if(picker.contains(active))pickerFocus=active.matches('summary')?'summary':active.matches('[type=search]')?'search':active.dataset.analysisCode||null;
  }
  function mount(){
    const root=document.querySelector('.ws-scenario-overlay .fig-main-panel');
    if(!root)return;
    if(!supported&&!supportPending&&!supportError)support();
    const portfolio=mode()==='portfolio';
    const list=(portfolio?[...new Set(holdings().map(x=>x.code))]:[...(supported||[])])
      .filter(code=>!supported||supported.has(code))
      .sort((aCode,bCode)=>(names()[aCode]||aCode).localeCompare(names()[bCode]||bCode,'ko'));
    const selected=codes();
    const panel=document.createElement('details');
    panel.className='scenario-symbols';
    panel.open=pickerOpen;
    const caption=selected.length?selected.map(code=>names()[code]||code).join(', '):'종목 선택';
    const options=list.map(code=>{
      const checked=selected.includes(code);
      const qty=portfolio?holdings().filter(lot=>lot.code===code).reduce((sum,lot)=>sum+Number(lot.quantity),0):0;
      return `<label data-symbol-option><input type="checkbox" data-analysis-code="${esc(code)}" ${checked?'checked':''} ${pending||!supported||(!checked&&selected.length>=selectionLimit)?'disabled':''}><span>${esc(names()[code]||code)} <small>${esc(code)}</small></span>${portfolio?`<small>${qty.toLocaleString('ko-KR')}주</small>`:''}</label>`;
    }).join('');
    const empty=supportPending?'종목을 불러오는 중입니다.':supportError?'종목을 불러오지 못했습니다.':portfolio?'선택할 보유 종목이 없습니다.':'선택할 종목이 없습니다.';
    panel.innerHTML=`<summary><strong>종목</strong><span>${esc(caption)}</span></summary>
      <div class="scenario-symbol-menu"><input type="search" placeholder="종목명 또는 코드" aria-label="종목 검색" value="${esc(pickerQuery)}"><div class="scenario-symbol-list">${options||`<p>${empty}</p>`}</div>${supportError?'<button type="button" data-symbol-retry>다시 불러오기</button>':''}</div>`;
    root.querySelector(':scope > .fig-model-row').after(panel);
    const search=panel.querySelector('input[type=search]');
    const filter=()=>{
      const query=pickerQuery.trim().toLocaleLowerCase('ko-KR');
      for(const label of panel.querySelectorAll('[data-symbol-option]'))
        label.hidden=!label.textContent.toLocaleLowerCase('ko-KR').includes(query);
    };
    filter();
    if(pickerOpen){
      panel.querySelector('.scenario-symbol-list').scrollTop=pickerScroll;
      const target=pickerFocus==='summary'?panel.querySelector('summary'):pickerFocus==='search'?search:
        [...panel.querySelectorAll('[data-analysis-code]')].find(el=>el.dataset.analysisCode===pickerFocus);
      target?.focus({preventScroll:true});
    }
    panel.querySelector('summary').addEventListener('click',()=>{pickerOpen=!panel.open;});
    panel.addEventListener('toggle',()=>{if(panel.isConnected)pickerOpen=panel.open;});
    search.addEventListener('input',()=>{pickerQuery=search.value;filter();});
    panel.querySelector('[data-symbol-retry]')?.addEventListener('click',support);
    panel.addEventListener('change',event=>{
      const code=event.target.dataset.analysisCode;
      if(!code)return;
      const next=new Set(codes());
      if(!event.target.checked)next.delete(code);
      else if(next.size<selectionLimit)next.add(code);
      selections[mode()]=[...next];persist();settings.changed();repaint();
    });
    const toggle=root.querySelector('[data-scenario-news]');
    toggle.checked=s.scenarioIncludeNews===true;
    toggle.disabled=!!pending;
    toggle.addEventListener('change',()=>{s.scenarioIncludeNews=toggle.checked;persist();});
    const play=root.querySelector('.fig-run-button');
    const horizonStatus=root.querySelector('#fig-analysis-horizon-status');
    const horizonAvailable=horizons.includes(input().horizon);
    horizonStatus.textContent=supported&&!horizonAvailable?`현재 계산 가능한 기간은 ${horizons.map(days=>days+'거래일').join(', ')}입니다.`:'';
    play.disabled=!!pending||!supported||!selected.length||!horizonAvailable;
    const status=root.querySelector('.scenario-run-status');
    const error=s.runError&&!s.runError.includes('분석 대상 종목을 한 개 이상 선택해 주세요.')?s.runError:'';
    status.hidden=!pending&&!error;
    status.innerHTML=pending?`<span role="status">${esc(phase)}</span><button type="button" data-analysis-cancel>취소</button>`:error?`<p role="alert">${esc(error)}</p>`:'';
    status.querySelector('[data-analysis-cancel]')?.addEventListener('click',()=>{const news=current()?.newsScenarios;if(news?.status==='pending')news.status='withheld';epoch++;pending?.abort();pending=null;persist();repaint();});
    if(window.whatIfWorkspaceStorage?.enabled)archive.mount(root);
  }
  document.addEventListener('keydown',event=>{
    const picker=document.querySelector('.scenario-symbols[open]');
    if(event.key!=='Escape'||!picker)return;
    event.preventDefault();event.stopPropagation();pickerOpen=picker.open=false;
    picker.querySelector('summary').focus();
  },true);
  document.addEventListener('pointerdown',event=>{
    const picker=document.querySelector('.scenario-symbols[open]');
    if(picker&&!picker.contains(event.target))pickerOpen=picker.open=false;
  },true);

  async function run(){if(pending)return;const snapshot={...input(),at:new Date().toISOString()},selected=snapshot.codes;
    if(!selected.length)return;
    if(!supported||!horizons.includes(snapshot.horizon)||selected.some(code=>!supported.has(code)))return;
    const c=snapshot.conditions;if(['fx','rate','oil','vix'].some(k=>s.sim[k]===''||!Number.isFinite(c[k]))||Math.abs(c.fx)>30||Math.abs(c.rate)>3||Math.abs(c.oil)>80||Math.abs(c.vix)>80){s.runError='네 충격 변수의 입력 범위를 확인해 주세요.';repaint();return;}
    const controller=new AbortController(),ticket=++epoch;pending=controller;s.runError='';phase='시나리오를 계산하고 있습니다.';repaint();const timer=setTimeout(()=>controller.abort(),snapshot.includeNews?150000:45000);
    try{
      const previous=current();
      const quotePayload=await request('/quotes/latest',null,controller.signal);
      const quotes=Object.fromEntries((quotePayload.quotes||[]).filter(q=>q.record_type==='quote_latest'&&q.is_mock===false&&Number(q.price)>0&&Number.isFinite(Date.parse(q.event_time))).map(q=>[q.asset_id,{price:Number(q.price),at:q.event_time,venue:q.venue,session:q.session}]));
      const lots=structuredClone(holdings()).filter(x=>selected.includes(x.code)).map(x=>({...x,price:quotes[x.code]?.price||null,priceAt:quotes[x.code]?.at||null}));
      const positions=selected.map(asset_id=>{let value_krw=1000000;if(snapshot.mode==='portfolio'){const owned=lots.filter(x=>x.code===asset_id);if(!owned.length||!quotes[asset_id])throw Error(`${names()[asset_id]||asset_id} 보유 수량 또는 실제 시세가 없습니다.`);value_krw=owned.reduce((sum,x)=>sum+Number(x.quantity)*quotes[asset_id].price,0);}return {asset_id,value_krw};});
      const payload={positions,analysis_type:snapshot.mode,model:snapshot.model,shocks:{fx_pct:c.fx,us_rate_bp:c.rate*100,wti_pct:c.oil,vix_points:c.vix}};
      if(snapshot.horizon!==5)payload.horizon_trading_days=snapshot.horizon;
      const result=await request('/stress/analyze',payload,controller.signal);
      if(ticket!==epoch)return;
      const valid=window.whatIfStressChart.derive(result);
      if(valid.error)throw Error(valid.error);
      if(result.horizon_trading_days!==snapshot.horizon||result.model!==snapshot.model||JSON.stringify(result.assets.map(x=>x.asset_id).sort())!==JSON.stringify(selected))throw Error('요청 조건과 반환 결과가 다릅니다. 다시 실행해 주세요.');
      if(previous?.stressResult&&!previous.archived)archive.archive(previous);
      const news=snapshot.includeNews?{status:supportsNews&&result.analysis_id?'pending':'withheld'}:null;
      const run={id:result.analysis_id||crypto.randomUUID(),at:snapshot.at,version:'V6',appVersion:'6.0.0',targetKey:snapshot.mode==='portfolio'?'portfolio':'stocks',targetLabel:snapshot.mode==='portfolio'?'선택 보유 종목':'선택 종목',conditions:c,newsScenarios:news,horizon:result.horizon_trading_days,stressMode:snapshot.mode,stressModel:snapshot.model,personaIds:[...s.selectedRoles],inputSnapshot:snapshot,priceSnapshot:structuredClone(Object.fromEntries(selected.filter(code=>quotes[code]).map(code=>[code,quotes[code]]))),portfolioLots:lots,stressResult:structuredClone(result),source_kind:'api',azureAnalysisId:result.ai_handoff?.ready?result.analysis_id:null,azureStatus:'ready',azureScope:`선택 ${selected.length}종목 · ${snapshot.mode==='portfolio'?'개인 보유분':'독립 종목 계산'}`,autoSummary:true};
      commit(run);persist();
      if(news?.status==='pending'){
        const path='/stress/analyses/'+encodeURIComponent(result.analysis_id)+'/news-scenarios';
        phase='뉴스 영향을 검토하고 있습니다.';
        repaint();
        try{
          const response=await request(path,{},controller.signal);
          if(ticket!==epoch)return;
          run.newsScenarios=window.whatIfStressChart.approvedNews(response,run)||{status:'withheld'};
        }catch{
          if(ticket===epoch)run.newsScenarios={status:'withheld'};
        }
      }
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
    else{const list=new Set(codes());const adding=['추가','선택'].includes(match[2]);
      if(adding&&!list.has(code)&&list.size>=selectionLimit)message='종목은 최대 4개까지 선택할 수 있습니다.';
      else{adding?list.add(code):list.delete(code);selections[mode()]=[...list];message=found[0][1]+' '+match[2]+'했습니다.';}}}
    a.recordSelection(message);persist();settings.changed();repaint();return true;
  }
  return {mount,beforeRender,codes,run,selectionText,syncSettings:()=>settings.changed(),cancel:()=>{const news=current()?.newsScenarios;if(news?.status==='pending')news.status='withheld';epoch++;pending?.abort();pending=null;}};
};
