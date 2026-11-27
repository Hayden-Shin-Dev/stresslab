// The conditional service uses separate horizon inputs and adjusted closes.
const WHATIF_CONDITIONAL_MODEL = 'huber_catboost_hybrid_conditional';
const WHATIF_STRESS_MODELS = ['catboost',WHATIF_CONDITIONAL_MODEL];
const WHATIF_STRESS_UNIVERSE = '000270 000660 005380 005930 005935 006400 009150 012330 012450 028260 032830 034020 034730 055550 068270 086790 105560 207940 373220 402340'.split(' ');
const WHATIF_STRESS_HORIZONS = [1,5,20];

/* The same selection drives the chart and the next stress test. */
window.installWhatIfHandoff = function (a) {
  const {state:s, mode, model, holdings, names, current, repaint, persist, commit, startAgents}=a;
  const selectionLimit=4;
  const normalizeModel=value=>WHATIF_STRESS_MODELS.includes(value)?value:'catboost';
  const normalizeSelections=values=>[...new Set((Array.isArray(values)?values:[]).filter(code=>WHATIF_STRESS_UNIVERSE.includes(code)))].slice(0,selectionLimit);
  a.setModel(normalizeModel(model()));
  const archive=window.installWhatIfArchive({...a,restore:r=>{const c=r.result.shocks;s.sim={...s.sim,horizon:r.result.horizon_trading_days||5,fx:c.fx_pct,rate:c.us_rate_bp/100,oil:c.wti_pct,vix:c.vix_points};a.setMode(r.context.analysis_type);a.setModel(normalizeModel(r.result.model));s.analysisSelections[r.context.analysis_type]=normalizeSelections(r.result.assets.map(x=>x.asset_id));persist();repaint();}});
  const selections=s.analysisSelections ||= {market:[],portfolio:[]};
  const settings=window.installWhatIfSettings({capture:()=>({schema:1,windows:a.windowLayout(),selections:structuredClone(selections),mode:mode(),model:model(),conditions:structuredClone(s.sim),chart:structuredClone(a.chart())}),restore:value=>{if(value.schema!==1)return;a.restoreWindows(value.windows);for(const type of ['market','portfolio'])if(Array.isArray(value.selections?.[type]))selections[type]=normalizeSelections(value.selections[type]);if(['market','portfolio'].includes(value.mode))a.setMode(value.mode);if(typeof value.model==='string')a.setModel(normalizeModel(value.model));if([1,5,20].includes(value.conditions?.horizon))s.sim.horizon=value.conditions.horizon;for(const k of ['fx','rate','oil','vix'])if(Number.isFinite(Number(value.conditions?.[k])))s.sim[k]=Number(value.conditions[k]);if(value.chart&&typeof value.chart==='object'){const v=value.chart;a.setChart({view:v.view==='assets'?'assets':'total',compareAssets:Array.isArray(v.compareAssets)?[...new Set(v.compareAssets.filter(c=>/^\d{6}$/.test(c)))].slice(0,4):[],hiddenAssets:Array.isArray(v.hiddenAssets)?v.hiddenAssets.filter(c=>/^\d{6}$/.test(c)):[],period:window.whatIfStressChart.periods.has(v.period)?v.period:'day',representation:['line','candle','ohlc'].includes(v.representation)?v.representation:'line',layoutColumns:[1,2,3,4].includes(v.layoutColumns)?v.layoutColumns:2,focusedAsset:/^\d{6}$/.test(v.focusedAsset||'')?v.focusedAsset:'',series:{baseline:v.series?.baseline!==false,scenario:v.series?.scenario!==false}});}persist();},repaint});
  for(const type of ['market','portfolio']) selections[type]=normalizeSelections(selections[type]);
  const capabilities=new Map(), supportPending=new Map(), supportErrors=new Set();
  const modelKey=()=>model()===WHATIF_CONDITIONAL_MODEL?WHATIF_CONDITIONAL_MODEL:'standard';
  const capability=()=>capabilities.get(modelKey());
  let pending=null,epoch=0,phase='';
  let pickerOpen=false,pickerQuery='',pickerScroll=0,pickerFocus=null,pickerCaret=null;
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const codes=()=>normalizeSelections(selections[mode()]).filter(code=>
    (!capability()||capability().assets.has(code))&&(mode()!=='portfolio'||holdings().some(x=>x.code===code)));
  const input=()=>({mode:mode(),model:model(),horizon:Number(s.sim.horizon)||5,includeNews:s.scenarioIncludeNews===true,codes:codes().sort(),conditions:{fx:Number(s.sim.fx),rate:Number(s.sim.rate),oil:Number(s.sim.oil),vix:Number(s.sim.vix)},holdings:mode()==='portfolio'?holdings().filter(x=>codes().includes(x.code)).map(x=>({code:x.code,quantity:x.quantity,amount:x.quantity==null?x.amount:null,avgPurchasePrice:x.avgPurchasePrice})).sort((a,b)=>a.code.localeCompare(b.code)):[]});
  const request=async(path,body,signal,headers={})=>{const r=await fetch('/api'+path,{cache:'no-store',method:body?'POST':'GET',credentials:'same-origin',headers:{'Content-Type':'application/json',...headers},...(body?{body:JSON.stringify(body)}:{}),signal});if(!r.ok)throw Object.assign(Error(r.status===401?'로그인 후 다시 시도해 주세요.':'요청을 완료하지 못했습니다. 다시 시도해 주세요.'),{status:r.status});return r.json();};
  async function fetchSupport(key){
    const conditional=key===WHATIF_CONDITIONAL_MODEL;
    supportErrors.delete(key);
    try{
      const r=await request(conditional?'/stress/scenario/support':'/stress/support',null,AbortSignal.timeout(15000));
      if(!Array.isArray(r.supported_assets)||(conditional&&r.model!==key))throw Error('올바른 지원 응답이 아닙니다.');
      const days=conditional?r.horizons:r.supported_horizon_trading_days;
      capabilities.set(key,{
        assets:new Set(r.supported_assets.filter(code=>WHATIF_STRESS_UNIVERSE.includes(code))),
        horizons:Array.isArray(days)?WHATIF_STRESS_HORIZONS.filter(day=>days.includes(day)):conditional?[]:[5],
        supportsNews:true
      });
    }catch{
      supportErrors.add(key);
    }finally{
      supportPending.delete(key);
      if(key===modelKey())repaint();
    }
    return capabilities.get(key);
  }
  function support(key=modelKey()){
    if(!supportPending.has(key))supportPending.set(key,fetchSupport(key));
    return supportPending.get(key);
  }
  const scenarioShocks=c=>({shock_usdkrw_pct:c.fx,shock_us10y_bp:c.rate*100,shock_wti_pct:c.oil,shock_vix_pt:c.vix});
  async function conditionalResult(snapshot,positions,signal){
    const c=snapshot.conditions;
    return request('/stress/scenario/analyze',{
      positions,analysis_type:snapshot.mode,model:snapshot.model,horizon_trading_days:snapshot.horizon,
      shocks:{fx_pct:c.fx,us_rate_bp:c.rate*100,wti_pct:c.oil,vix_points:c.vix}
    },signal);
  }
  async function historicalCases(run,code,signal){
    const result=run.stressResult;
    const model=result.model_context;
    const days=result.horizon_trading_days;
    const scenarios=result.conditional_scenarios;
    const data=await request('/stress/scenario/history',{asset_id:code,scenarios,horizon_days:days,snapshot_sha256:model.snapshot_sha256},signal);
    const fields=Object.keys(scenarioShocks(run.conditions));
    if(data.schema!=='conditional-history-response-v1'||data.asset_id!==code||data.horizon_days!==days||
       data.snapshot_sha256!==model.snapshot_sha256||data.model_package_id!==model.model_package_id||data.source_split!=='train'||
       !Array.isArray(data.cases)||data.cases.length>5||
       fields.some(k=>data.current_shocks?.[k]!==scenarios.find(row=>row.horizon_days===days)?.[k])||
       data.cases.some(row=>!Number.isFinite(row.actual_return_pct)||!Number.isFinite(Date.parse(row.start))||
        !Number.isFinite(Date.parse(row.end))||fields.some(k=>!Number.isFinite(row.actual_shocks?.[k]))))
      throw Error('이 실행과 일치하는 과거 사례를 가져오지 못했습니다.');
    return data.cases;
  }
  function beforeRender(){
    const picker=document.querySelector('.scenario-symbols');
    const active=document.activeElement;
    pickerFocus=null;
    if(!picker?.open)return;
    pickerScroll=picker.querySelector('.scenario-symbol-list').scrollTop;
    if(active?.type==='search'&&picker.contains(active))pickerCaret=[active.selectionStart,active.selectionEnd];
    else pickerCaret=null;
    if(picker.contains(active))pickerFocus=active.matches('summary')?'summary':active.matches('[type=search]')?'search':active.dataset.analysisCode||null;
  }
  function mount(){
    const root=document.querySelector('.ws-scenario-overlay .fig-main-panel');
    if(!root)return;
    const key=modelKey(), supportError=supportErrors.has(key), cap=capability();
    if(!cap&&!supportPending.has(key)&&!supportError)support();
    const portfolio=mode()==='portfolio';
    const list=(portfolio?[...new Set(holdings().map(x=>x.code))]:[...WHATIF_STRESS_UNIVERSE])
      .filter(code=>WHATIF_STRESS_UNIVERSE.includes(code))
      .sort((aCode,bCode)=>(names()[aCode]||aCode).localeCompare(names()[bCode]||bCode,'ko'));
    const selected=codes();
    const panel=document.createElement('details');
    panel.className='scenario-symbols';
    panel.open=pickerOpen;
    const caption=selected.length?selected.map(code=>names()[code]||code).join(', '):'종목 선택';
    const options=list.map(code=>{
      const checked=selected.includes(code);
      const owned=portfolio?holdings().filter(lot=>lot.code===code):[];
      const qty=owned.reduce((sum,lot)=>sum+Number(lot.quantity),0);
      const amount=owned.reduce((sum,lot)=>sum+(lot.quantity==null?Number(lot.amount):0),0);
      const position=qty>0?qty.toLocaleString('ko-KR')+'주':amount.toLocaleString('ko-KR')+'원';
      const available=!cap||cap.assets.has(code);
      return `<label data-symbol-option><input type="checkbox" data-analysis-code="${esc(code)}" ${checked?'checked':''} ${pending||!available||(!checked&&selected.length>=selectionLimit)?'disabled':''}><span>${esc(names()[code]||code)} <small>${esc(code)}</small></span>${cap&&!available?'<small>선택 모델 미지원</small>':portfolio?`<small>${position}</small>`:''}</label>`;
    }).join('');
    const empty=supportPending.has(key)?'종목을 불러오는 중입니다.':supportError?'종목을 불러오지 못했습니다.':portfolio?'선택할 보유 종목이 없습니다.':'선택할 종목이 없습니다.';
    panel.innerHTML=`<summary aria-label="분석 종목 선택"><span>${esc(caption)}</span></summary>
      <div class="scenario-symbol-menu"><input type="search" placeholder="종목명 또는 코드" aria-label="종목 검색" value="${esc(pickerQuery)}"><div class="scenario-symbol-list">${options||`<p>${empty}</p>`}</div>${supportError?'<button type="button" data-symbol-retry>다시 불러오기</button>':''}</div>`;
    root.querySelector('[data-scenario-symbol-slot]').append(panel);
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
      if(target===search&&pickerCaret)search.setSelectionRange(...pickerCaret);
    }
    panel.querySelector('summary').addEventListener('click',()=>{pickerOpen=!panel.open;});
    panel.addEventListener('toggle',()=>{if(panel.isConnected)pickerOpen=panel.open;});
    search.addEventListener('input',event=>{if(!event.isComposing){pickerQuery=search.value;filter();}});
    panel.querySelector('[data-symbol-retry]')?.addEventListener('click',()=>support(key));
    panel.addEventListener('change',event=>{
      const code=event.target.dataset.analysisCode;
      if(!code)return;
      const next=new Set(codes());
      if(!event.target.checked)next.delete(code);
      else if(next.size<selectionLimit)next.add(code);
      selections[mode()]=[...next];s.runError='';persist();settings.changed();repaint();
    });
    const toggle=root.querySelector('[data-scenario-news]');
    toggle.checked=s.scenarioIncludeNews===true;
    toggle.disabled=!!pending;

    for(const button of root.querySelectorAll('[data-shock-step]')){
      button.disabled=!!pending;
      button.addEventListener('click',()=>{
        const field=button.parentElement.querySelector('input');
        const step=Number(field.step), value=Number(field.value)||0;
        field.value=String(Math.min(Number(field.max),Math.max(Number(field.min),Number((value+Number(button.dataset.shockStep)*step).toFixed(2)))));
        field.dispatchEvent(new Event('input',{bubbles:true}));
      });
    }
    toggle.addEventListener('change',()=>{
      s.scenarioIncludeNews=toggle.checked;
      const active=current();
      if(active)active.showNewsOnChart=toggle.checked;
      persist();
      if(toggle.checked&&active?.stressResult)void run();
      else repaint();
    });
    const play=root.querySelector('.fig-run-button');
    const horizonStatus=root.querySelector('#fig-analysis-horizon-status');
    const horizon=Number(s.sim.horizon)||5;
    const message=supportError?'모델 지원 정보를 불러오지 못했습니다. PLAY를 누르면 다시 확인합니다.':
      cap&&!cap.horizons.includes(horizon)?`현재 모델의 계산 지원 기간: ${cap.horizons.map(days=>days+'거래일').join(', ')||'없음'}`:'';
    horizonStatus.hidden=!message;
    horizonStatus.textContent=message;
    play.disabled=!!pending||!selected.length||!WHATIF_STRESS_HORIZONS.includes(horizon);
    const status=root.querySelector('.scenario-run-status');
    const error=s.runError&&!s.runError.includes('분석 대상 종목을 한 개 이상 선택해 주세요.')?s.runError:'';
    status.hidden=!pending&&!error;
    status.innerHTML=pending?`<span role="status">${esc(phase)}</span><button type="button" data-analysis-cancel>취소</button>`:error?`<p role="alert">${esc(error)}</p>`:'';
    status.querySelector('[data-analysis-cancel]')?.addEventListener('click',()=>{const news=current()?.newsScenarios;if(news?.status==='pending')news.status='withheld';epoch++;pending?.abort();pending=null;persist();repaint();});
    if(window.whatIfWorkspaceStorage?.enabled)archive.mount(root);
  }
  document.addEventListener('keydown',event=>{
    const picker=document.querySelector('.scenario-symbols[open]');
    if(event.key!=='Escape'||!picker||event.isComposing)return;
    event.preventDefault();event.stopPropagation();pickerOpen=picker.open=false;
    picker.querySelector('summary').focus();
  },true);
  document.addEventListener('pointerdown',event=>{
    const picker=document.querySelector('.scenario-symbols[open]');
    if(picker&&!picker.contains(event.target))pickerOpen=picker.open=false;
  },true);

  async function run(){if(pending)return;const snapshot={...input(),at:new Date().toISOString()},selected=snapshot.codes;
    if(!selected.length||!WHATIF_STRESS_HORIZONS.includes(snapshot.horizon))return;
    const key=modelKey();
    const conditional=snapshot.model===WHATIF_CONDITIONAL_MODEL;
    const c=snapshot.conditions;if(['fx','rate','oil','vix'].some(k=>s.sim[k]===''||!Number.isFinite(c[k]))||Math.abs(c.fx)>30||Math.abs(c.rate)>3||Math.abs(c.oil)>80||Math.abs(c.vix)>80){s.runError='네 충격 변수의 입력 범위를 확인해 주세요.';repaint();return;}
    const controller=new AbortController(),ticket=++epoch;pending=controller;s.runError='';phase='시나리오를 계산하고 있습니다.';repaint();const timer=setTimeout(()=>controller.abort(),snapshot.includeNews?150000:45000);
    try{
      const cap=capabilities.get(key)||await support(key);
      if(ticket!==epoch)return;
      if(!cap)throw Error('분석 모델에 연결할 수 없습니다. 잠시 후 다시 실행해 주세요.');
      if(!cap.horizons.includes(snapshot.horizon)){
        throw Error(`${snapshot.horizon}거래일 결과는 현재 이 모델에서 제공하지 않습니다. 지원 기간: ${cap.horizons.map(days=>days+'거래일').join(', ')||'없음'}.`);
      }
      if(selected.some(code=>!cap.assets.has(code)))throw Error('이 모델이 지원하는 종목을 선택해 주세요.');
      const previous=current();
      const quotePayload=conditional&&snapshot.mode!=='portfolio'?{}:await request('/quotes/latest',null,controller.signal);
      const quotes=Object.fromEntries((quotePayload.quotes||[]).filter(q=>q.record_type==='quote_latest'&&q.is_mock===false&&Number(q.price)>0&&Number.isFinite(Date.parse(q.event_time))).map(q=>[q.asset_id,{price:Number(q.price),at:q.event_time,venue:q.venue,session:q.session}]));
      const lots=structuredClone(holdings()).filter(x=>selected.includes(x.code)).map(x=>({...x,price:quotes[x.code]?.price||null,priceAt:quotes[x.code]?.at||null}));
      const positions=selected.map(asset_id=>{
        if(snapshot.mode!=='portfolio')return {asset_id,value_krw:1000000};
        const owned=lots.filter(lot=>lot.code===asset_id);
        const value_krw=owned.reduce((sum,lot)=>sum+(lot.quantity==null?Number(lot.amount):Number(lot.quantity)*lot.price),0);
        if(!Number.isFinite(value_krw)||value_krw<=0||owned.some(lot=>lot.quantity!=null&&!lot.price)){
          throw Error(`${names()[asset_id]||asset_id}의 보유 금액이나 실제 시세를 확인할 수 없습니다.`);
        }
        return {asset_id,value_krw};
      });
      const payload={positions,analysis_type:snapshot.mode,model:snapshot.model,shocks:{fx_pct:c.fx,us_rate_bp:c.rate*100,wti_pct:c.oil,vix_points:c.vix}};
      if(snapshot.horizon!==5)payload.horizon_trading_days=snapshot.horizon;
      const result=conditional?await conditionalResult(snapshot,positions,controller.signal):await request('/stress/analyze',payload,controller.signal);
      if(ticket!==epoch)return;
      const valid=window.whatIfStressChart.derive(result);
      if(valid.error)throw Error(valid.error);
      if(result.horizon_trading_days!==snapshot.horizon||result.model!==snapshot.model||JSON.stringify(result.assets.map(x=>x.asset_id).sort())!==JSON.stringify(selected))throw Error('요청 조건과 반환 결과가 다릅니다. 다시 실행해 주세요.');
      if(previous?.stressResult&&!previous.archived&&previous.stressModel!==WHATIF_CONDITIONAL_MODEL)archive.archive(previous);
      const news=snapshot.includeNews?{status:'pending'}:null;
      const prices=conditional?Object.fromEntries(result.assets.map(row=>[row.asset_id,{
        price:row.adjusted_basis,at:result.model_context.as_of_trading_date+'T06:30:00Z',adjusted:true
      }])):Object.fromEntries(selected.filter(code=>quotes[code]).map(code=>[code,quotes[code]]));
      const run={id:result.analysis_id||crypto.randomUUID(),at:snapshot.at,version:'V6',appVersion:'6.0.0',targetKey:snapshot.mode==='portfolio'?'portfolio':'stocks',targetLabel:snapshot.mode==='portfolio'?'선택 보유 종목':'선택 종목',conditions:c,newsScenarios:news,showNewsOnChart:snapshot.includeNews,horizon:result.horizon_trading_days,stressMode:snapshot.mode,stressModel:snapshot.model,personaIds:[...s.selectedRoles],inputSnapshot:snapshot,priceSnapshot:structuredClone(prices),portfolioLots:lots,stressResult:structuredClone(result),source_kind:'api',azureAnalysisId:result.ai_handoff?.ready?result.analysis_id:null,azureStatus:'ready',azureScope:`선택 ${selected.length}종목 · ${snapshot.mode==='portfolio'?'개인 보유분':'독립 종목 계산'}`,autoSummary:true};
      commit(run);persist();
      if(news?.status==='pending'){
        const path='/stress/analyses/'+encodeURIComponent(result.analysis_id)+'/news-scenarios';
        phase='뉴스 영향을 검토하고 있습니다.';
        repaint();
        try{
          if(!result.recovery_receipt)throw Error('뉴스 분석에 필요한 결과 확인 정보를 받지 못했습니다. 다시 실행해 주세요.');
          const response=await request(path,{receipt:result.recovery_receipt,prices:Object.fromEntries(Object.entries(prices).map(([code,q])=>[code,q.price]))},controller.signal);
          run.newsMessage=response.message||'';
          if(ticket!==epoch)return;
          run.newsScenarios=window.whatIfStressChart.approvedNews(response,run)||{status:'withheld'};run.newsAdjustment={sources:response.selected_sources||[]};if(response.ai_handoff?.ready&&response.news_analysis_id)run.azureAnalysisId=response.news_analysis_id;
        }catch(error){
          if(ticket===epoch){run.newsScenarios={status:'withheld'};run.newsMessage=error.message||'뉴스 분석을 완료하지 못했습니다. 다시 실행해 주세요.';}
        }
      }
      if(result.archive_status?.persisted)archive.saveContext(run);
      else if(!conditional)run.archiveError=result.archive_status?.reason||'서버 보관소 저장을 확인할 수 없습니다.';
      if(run.azureAnalysisId&&s.selectedRoles.length)startAgents(run).catch(e=>{run.azureStatus='failed';run.azureError='계산 완료 · AI 연결 실패: '+e.message;persist();repaint();});
      else if(!run.azureAnalysisId){run.azureStatus='failed';run.azureError=conditional?'이 모델은 AI 토론에 결과를 전달할 수 없습니다.':'분석 근거를 불러오지 못했습니다.';}
      persist();
    }catch(e){if(ticket===epoch)s.runError=e.name==='AbortError'?'계산 시간이 초과됐습니다. 이전 결과를 유지했습니다. 다시 실행해 주세요.':e.message;}
    finally{clearTimeout(timer);if(ticket===epoch){pending=null;repaint();}}
  }
  function selectionText(text){
    const match=String(text||'').trim().match(/^(.+?)(?:을|를)?\s+(?:분석 대상에?\s*)?(추가|선택|제외|해제)(?:해줘|해 줘|해주세요|해 주세요)?[.!]?$/);
    if(!match)return false;
    const query=match[1].trim(), found=Object.entries(names()).filter(([code,name])=>query===code||query===name||query===name+'을'||query===name+'를');
    if(found.length!==1&&!text.includes('분석 대상'))return false;
    let message;
    if(found.length!==1)message='분석 대상 선택: 정확한 종목명 또는 6자리 코드를 입력해 주세요. 선택은 변경하지 않았습니다.';
    else{const code=found[0][0], available=mode()!=='portfolio'||holdings().some(x=>x.code===code);if(!available||!WHATIF_STRESS_UNIVERSE.includes(code)||(capability()&&!capability().assets.has(code)))message='현재 분석 유형에서 선택할 수 없는 종목입니다. 보유·모델 지원 상태를 확인해 주세요.';
    else{const list=new Set(codes());const adding=['추가','선택'].includes(match[2]);
      if(adding&&!list.has(code)&&list.size>=selectionLimit)message='종목은 최대 4개까지 선택할 수 있습니다.';
      else{adding?list.add(code):list.delete(code);selections[mode()]=[...list];message=found[0][1]+' '+match[2]+'했습니다.';}}}
    a.recordSelection(message);persist();settings.changed();repaint();return true;
  }
  return {mount,beforeRender,codes,run,historicalCases,selectionText,syncSettings:()=>settings.changed(),cancel:()=>{const news=current()?.newsScenarios;if(news?.status==='pending')news.status='withheld';epoch++;pending?.abort();pending=null;}};
};
