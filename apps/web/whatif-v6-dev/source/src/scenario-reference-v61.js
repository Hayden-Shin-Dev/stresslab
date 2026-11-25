/* Scenario workstation: the attached dashboard is the layout reference. Data and actions remain app-owned. */
const P61={tab:'market',page:0,filterOpen:false};
const P61_ASSET='assets/scenario-reference/';
const P61_PORTRAITS={kim:'agent-glasses-male.png',yoon:'agent-glasses-female.png',shin:'agent-silver.png',kang:'agent-ponytail.png'};
const p61PreviousScenario=scenario;
const p61PreviousChat=gxChatHTML;
gxChatHTML=function(){return GX.panel==='sim'?'':p61PreviousChat();};

function p61Clock(){return new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date());}
setInterval(()=>{const clock=document.getElementById('p61-clock');if(clock)clock.textContent=p61Clock();},15000);

function p61Settings(){
 const fields=[['rate','미국 10년 국채 금리 변화량','bp','1'],['fx','원/달러 환율 변화율','%','0.1'],['oil','WTI 유가 변화율','%','0.1'],['vix','시장불안충격 · VIX 변화량','pt','0.1']];
 return `<aside class="p61-settings" id="scenario-settings" aria-label="실행 설정"><div class="p61-field-row">${fields.map(([id,label,unit,step])=>`<label class="p61-field" for="inline-${id}"><span>${label}</span><span class="p61-input-wrap"><input id="inline-${id}" type="number" step="${step}" data-sim="${id}" ${id==='rate'?'data-unit="bp"':''} value="${E(id==='rate'?(S.sim.rate===''?'':Number(S.sim.rate)*100):S.sim[id])}"><small>${unit}</small></span></label>`).join('')}</div><p class="settings-feedback" role="status" aria-live="polite">${S.runError?E(S.runError):''}</p></aside>`;
}

function p61ChartControls(){return `<div class="p61-chart-controls"><label>차트 표현<select id="p61-chart-type"><option value="line" ${V45.type==='line'?'selected':''}>LINE</option><option value="candle" ${V45.type==='candle'?'selected':''}>CANDLE</option><option value="bar" ${V45.type==='bar'?'selected':''}>OHLC</option></select></label><label>차트 주기<select id="p61-chart-mode">${[['tick','틱'],['minute','1분'],['day','일'],['week','주'],['month','월'],['year','년']].map(([value,label])=>`<option value="${value}" ${S.chartMode===value?'selected':''}>${label}</option>`).join('')}</select></label><button data-action="chart-today" aria-label="오늘로 이동" title="오늘로 이동"><img class="p61-chart-reset-icon" src="${P61_ASSET}figma-46-987/refresh-chart.svg" alt=""></button><button data-action="chart-zoom" aria-label="차트 확대" title="차트 확대"><img class="p61-chart-zoom-icon" src="${P61_ASSET}figma-46-987/chart-zoom.svg" alt=""></button></div>`;}

function p61MarketRows(){
 const query=P57.query.trim().toLocaleLowerCase(),all=(P57.market.rows||[]).filter(row=>!query||(row.name+' '+row.code+' '+(row.sector||'')).toLocaleLowerCase().includes(query));
 all.sort((a,b)=>P57.sort==='name'?a.name.localeCompare(b.name,'ko'):(b.volume??-1)-(a.volume??-1));
 const pages=Math.max(1,Math.ceil(all.length/10));P61.page=Math.min(P61.page,pages-1);
 const rows=all.slice(P61.page*10,P61.page*10+10),canWatch=P57.mode==='live'&&['connected','partial'].includes(P57.market.status);
 return `<div class="p61-market-head" aria-hidden="true"><span>선택</span><span>종목</span><span>${P57.tab==='indicators'?'장중 지표':'현재가'}</span><span>시각</span></div><div class="p61-market-list" role="list" aria-label="실시간 종목 목록">${rows.length?rows.map(row=>`<article class="p61-market-card ${row.code===p57Code()?'is-active':''}" role="listitem"><label class="p61-check"><input type="checkbox" id="p57-watch-${E(row.code)}" data-gx="p57-watch" data-code="${E(row.code)}" aria-label="${E(row.name)} 실시간 차트 표시" ${P57.watchCodes.includes(row.code)?'checked':''} ${canWatch?'':'disabled'}><span aria-hidden="true"></span></label><button class="p61-stock" data-gx="p57-pick" data-name="${E(row.name)}"><strong>${E(row.name)}</strong><small>${E(row.code)} · ${E(row.market||'KRX')}</small></button><div class="p61-price"><strong>${P57.tab==='indicators'?p57Pct(row.changePct):p57Money(row.price)}</strong><small>${P57.tab==='indicators'?`5분 ${p57Pct(row.fiveMinute)} · 30분 변동 ${p57Pct(row.volatility30)}`:`${p57Pct(row.changePct)} · 거래량 ${p57Money(row.volume)}`}</small></div><div class="p61-times"><span>체결 ${p57Time(row.tradeAt)}</span><span>수집 ${p57Time(row.collectedAt)}</span><span>수신 ${p57Time(row.receivedAt)}</span></div></article>`).join(''):`<div class="p61-market-empty" role="status"><strong>${query?'검색 결과가 없습니다.':P57.market.httpStatus===401||P57.market.httpStatus===403?'로그인 후 실시간 데이터가 표시됩니다.':'표시할 실시간 종목이 없습니다.'}</strong><span>${query?'검색어를 바꾸어 보세요.':P57.busy?'시세를 가져오는 중입니다.':P57.market.httpStatus===401||P57.market.httpStatus===403?'인증된 개발 API에 로그인되어 있는지 확인하세요.':P57.market.status==='unconfigured'?'시세 API 설정을 확인하세요.':'실제 시세 API 연결 상태를 확인하세요.'}</span>${P57.market.httpStatus===401||P57.market.httpStatus===403?'<button data-gx="p61-login">개발 API 로그인</button>':''}</div>`}</div><footer class="p61-list-footer"><span>${all.length?`${P61.page*10+1}–${Math.min((P61.page+1)*10,all.length)} / ${all.length}`:'0개 종목'} · ${E(p57Source())}</span><div><button data-gx="p61-prev" ${P61.page===0?'disabled':''} aria-label="이전 목록">‹</button><button data-gx="p61-next" ${P61.page>=pages-1?'disabled':''} aria-label="다음 목록">›</button></div></footer>`;
}

function p61NewsRows(){const query=P57.query.trim().toLocaleLowerCase(),items=(S.newsItems||[]).filter(n=>!query||(n.title+' '+n.summary).toLocaleLowerCase().includes(query));return `<div class="p61-aux-list">${items.length?items.map(n=>`<button data-gx="p61-open-news" data-id="${E(n.id)}"><span class="p61-aux-meta">${E(n.published||'')} · ${E(n.source||'')} · 예시 뉴스</span><strong>${E(n.title)}</strong><small>${E(n.summary||'')}</small></button>`).join(''):'<p>표시할 뉴스가 없습니다.</p>'}</div>`;}
function p61DocumentRows(){return `<div class="p61-aux-list"><div class="p61-document-card"><span class="p61-aux-meta">문서 분석</span><strong>${S.docReady?E(S.docName):'첨부한 문서가 없습니다.'}</strong><small>${S.docReady?'원문을 열어 분석 요청과 근거를 확인하세요.':'PDF, DOCX, TXT 문서를 문서 분석 화면에서 첨부할 수 있습니다.'}</small><button data-gx="p61-open-doc">문서 분석 열기 →</button></div></div>`;}

function p61MarketHTML(){const tab=P61.tab;return `<div class="p61-data-frame"><nav class="p61-data-tabs" aria-label="자료 종류">${[['market','실시간 데이터'],['news','뉴스'],['documents','문서']].map(([id,label])=>`<button data-gx="p61-tab" data-tab="${id}" aria-current="${tab===id?'page':'false'}">${label}</button>`).join('')}</nav><div class="p61-data-body"><div class="p61-data-tools"><label class="p61-search"><span class="sr-only">목록 검색</span><img class="p61-search-icon" src="${P61_ASSET}figma-46-987/search.svg" alt=""><input id="p57-filter" type="search" placeholder="종목명·코드 검색" value="${E(P57.query)}"></label><button data-gx="p61-filter" aria-label="목록 정렬" title="목록 정렬" aria-expanded="${P61.filterOpen}"><img class="p61-filter-icon" src="${P61_ASSET}figma-46-987/filter.svg" alt=""></button>${tab==='market'?`<button data-gx="p61-login" aria-label="개발 API 계정" title="개발 API 로그인"><img class="p61-account-icon" src="${P61_ASSET}figma-46-987/person.svg" alt=""></button><button data-gx="p61-live-action" aria-label="실시간 데이터 요청" title="실시간 데이터 요청" ${P57.busy?'disabled':''}><img class="p61-live-action-icon" src="${P61_ASSET}figma-46-987/action-play.svg" alt=""></button><button data-gx="p57-refresh" aria-label="실시간 데이터 새로고침" title="새로고침" ${P57.busy?'disabled':''}><img class="p61-market-refresh-icon" src="${P61_ASSET}figma-46-987/refresh-market.svg" alt=""></button>`:''}</div>${P61.filterOpen&&tab==='market'?`<div class="p61-filter-row"><label>정렬<select id="p57-sort"><option value="volume" ${P57.sort==='volume'?'selected':''}>누적 거래량순</option><option value="name" ${P57.sort==='name'?'selected':''}>종목명순</option></select></label><label>보기<select id="p57-view"><option value="quotes" ${P57.tab==='quotes'?'selected':''}>종목 시세</option><option value="indicators" ${P57.tab==='indicators'?'selected':''}>장중 지표</option></select></label></div>`:''}<p class="p61-data-status" role="status">${tab==='market'?`${P57.market.httpStatus===401||P57.market.httpStatus===403?'인증 필요 · ':''}${E(p57Source())} · 마지막 수신 ${E(p57Time(P57.market.receivedAt,true))}`:tab==='news'?'화면 예시 뉴스 · 실제 수집 시세와 별개입니다.':'로컬에 첨부한 문서를 표시합니다.'}</p>${tab==='market'?p61MarketRows():tab==='news'?p61NewsRows():p61DocumentRows()}</div></div>`;}

const p61PreviousMarket=p57MarketHTML;
p57MarketHTML=function(){return document.querySelector('.p61-scenario')||GX.panel==='sim'&&!V45.compare?p61MarketHTML():p61PreviousMarket();};

function p61Chat(){const list=(S.chats.scenario||[]).filter(m=>m.kind!=='simulation'),questions=suggestedQuestions('scenario',list.some(m=>!m.me));return `<section class="p61-chat" aria-label="AI Agent 대화"><header><h2>AI Agent</h2><span role="status">${P41.bridge?'AI 연결됨':'AI 연결 확인 필요'} · 분석 결과에 관해 질문하세요</span><button class="p61-chat-close" data-gx="feature-close" aria-label="시나리오 분석 닫기"><img src="${P61_ASSET}figma-46-987/close.svg" alt=""></button></header><div class="p61-chat-main"><div class="p61-chat-thread" id="chat-scroll"><div class="p61-prompts">${questions.slice(0,3).map(q=>`<button data-action="quick" data-text="${E(q)}">${E(q)}</button>`).join('')}</div>${list.map(renderBubble).join('')}</div><aside class="p61-chat-side" role="group" aria-label="답변할 AI 선택">${D.personas.map(p=>`<label><input type="checkbox" data-role-choice="${p.id}" ${S.selectedRoles.includes(p.id)?'checked':''}><img class="p61-persona-avatar" src="${P61_ASSET}${P61_PORTRAITS[p.id]||'agent-wavy.png'}" alt=""><span>${E(p.name)}</span></label>`).join('')}</aside></div><div class="p61-chat-compose"><img class="p61-compose-avatar" src="${P61_ASSET}agent-wavy.png" alt=""><textarea data-chat-input="scenario" rows="2" placeholder="시나리오에 관해 질문하세요">${E(S.drafts.scenario||'')}</textarea><button data-action="send-chat" data-key="scenario" aria-label="질문 보내기"><img class="p61-send-icon" src="${P61_ASSET}figma-46-987/send-plane.svg" alt=""></button></div></section>`;}

scenario=function(){if(V45.compare)return p61PreviousScenario();C.setTarget(targetKey());const run=currentRun();return `<section class="scenario-page p61-scenario"><img class="p61-brand-gear" src="${P61_ASSET}pixel-gear.png" alt="" aria-hidden="true"><button class="p61-home" data-gx="feature-close" aria-label="시나리오 분석 닫기" title="홈으로"><img class="p61-home-icon" src="${P61_ASSET}home.png" alt=""><span class="sr-only">홈으로</span></button><div class="p61-grid"><section class="p61-primary" aria-label="실행 설정과 시나리오 차트"><header class="p61-primary-header"><div class="p61-context"><label>분석 대상<select id="p61-analysis-type"><option value="index" ${S.analysisTab==='index'?'selected':''}>지수 분석</option><option value="stock" ${S.analysisTab==='stock'?'selected':''}>국내 주식 분석</option><option value="compare">종목 비교</option></select></label><label>분석 기간<select id="p61-horizon"><option value="1" ${S.sim.horizon===1?'selected':''}>분석 1거래일</option><option value="5" ${S.sim.horizon===5?'selected':''}>분석 5거래일</option></select></label>${S.analysisTab==='stock'?`<select id="p57-stock-select" class="p61-selected-stock" aria-label="분석 종목 선택">${ASSET_MASTER.map(a=>`<option value="${E(a.name)}" ${a.name===S.stock?'selected':''}>${E(a.name)} · ${E(a.code)}</option>`).join('')}</select>`:''}</div><time id="p61-clock" aria-label="현재 시각">${p61Clock()}</time></header><div class="p61-execution">${p61Settings()}<div class="p61-execution-actions"><button class="p61-play" data-action="run-sim" aria-label="시뮬레이션 실행"><img class="p61-play-bg" src="${P61_ASSET}rectangle52.svg" alt=""><span>PLAY</span><img class="p61-play-icon" src="${P61_ASSET}play.png" alt=""></button></div></div><section class="p61-chart" aria-label="시나리오 경로 차트"><div class="p61-chart-head"><div class="p61-chart-status"><strong>${E(targetLabel())}</strong><small>${run?'실행 '+E(p57Time(run.at,true)):'실행 전 · 조건을 설정하세요'}</small></div>${p61ChartControls()}</div><div class="p61-chart-body scenario-chart">${C.chartHTML({run,mode:S.chartMode,visible:S.chartVisible,id:'main'})}</div><div class="p61-chart-footer">${p57WatchHTML()}<button type="button" data-gx="p61-stock-prices">주가 추이</button><span>실선은 과거 경로, 분기선은 입력 조건을 적용한 계산 예시입니다.</span></div></section></section><section class="p57-data p61-data" aria-label="자료와 실시간 데이터">${p61MarketHTML()}</section><section class="p61-results" aria-label="분석 결과 공간"></section>${p61Chat()}</div></section>`;};

const p61PreviousGX=gxAction;
gxAction=function(action,el){
 if(action==='p61-login')return location.assign('/.auth/login/google?post_login_redirect_uri='+encodeURIComponent(location.pathname+location.search));
 if(action==='p61-stock-prices')return p61OpenStockPrices();
 if(action==='p61-live-action')return p57Poll();
 if(action==='p61-tab'){P61.tab=el.dataset.tab;P61.page=0;P57.query='';return p57PaintData();}
 if(action==='p61-prev'){P61.page=Math.max(0,P61.page-1);return p57PaintData();}
 if(action==='p61-next'){P61.page++;return p57PaintData();}
 if(action==='p61-filter'){P61.filterOpen=!P61.filterOpen;return p57PaintData();}
 if(action==='p61-open-news'){S.sub='news';S.newsSelected=el.dataset.id;S.newsDetailOpen=true;return gxOpen('news');}
 if(action==='p61-open-doc'){S.sub='document';return gxOpen('document');}
 return p61PreviousGX(action,el);
};
document.addEventListener('change',event=>{
 if(event.target.id==='p61-analysis-type'){const value=event.target.value;if(value==='compare'){V45.compare=true;render();}else gxAction(value==='index'?'market-index':'market-stock',event.target);}
 if(event.target.id==='p61-horizon'){S.sim.horizon=Number(event.target.value);persist();render();}
 if(event.target.id==='p61-chart-type'){V45.type=event.target.value;render();}
 if(event.target.id==='p61-chart-mode'){const value=event.target.value;onAction('p512-period',{dataset:{scope:'main',value,minutes:'1'}});}
});
const p61PreviousWidth=p57ScenarioWidth;
p57ScenarioWidth=function(){if(GX.panel!=='sim'||V45.compare)return p61PreviousWidth();const vw=document.documentElement.clientWidth||innerWidth;return Math.max(420,Math.round(vw<=980?vw-126:(vw-110)*.64-70));};
const p61PreviousRender=render;
render=function(){p61PreviousRender();if(GX.panel!=='sim'||V45.compare)return;const feature=document.querySelector('.p41-feature.p57-machine');feature?.classList.remove('light-surface');for(const [name,value] of Object.entries({left:'0px',top:'0px',transform:'none','transform-origin':'top left',width:'2734px',height:'1635px','max-width':'none','max-height':'none'}))feature?.style.setProperty(name,value,'important');feature?.querySelector('.gx-window-body')?.style.setProperty('padding','0','important');if(P57.mode==='live'&&P57.market.status==='connecting'&&!P57.busy)queueMicrotask(()=>{if(GX.panel==='sim'&&!P57.busy)p57Poll();});};


function p61OpenStockPrices() {
 const codes = "000270 000660 005380 005930 005935 006400 009150 012330 012450 028260 032830 034020 034730 055550 068270 086790 105560 207940 373220 402340".split(" ");
 const selected = [...new Set([...(P57.watchCodes || []), p57Code()])].filter(code => codes.includes(code));
 const dialog = document.createElement("dialog");
 dialog.setAttribute("aria-label", "주가 추이");
 dialog.dataset.stockPrices = "";
 dialog.style.cssText = "width:min(900px,90vw);color:#192223;background:#fff;padding:24px;border:1px solid #b9c9c9;border-radius:12px";
 dialog.innerHTML = `<form method="dialog"><button aria-label="닫기" style="float:right">닫기</button></form>
  <h2>주가 추이</h2><label>기간 <select><option value="minute">1분봉</option><option value="tick">개별 틱</option><option value="3y">최근 3년</option></select></label>
  <fieldset style="display:flex;gap:8px;flex-wrap:wrap;margin:12px 0"><legend>종목</legend>${codes.map(code => {
   const asset = ASSET_MASTER.find(a => a.code === code);
   return `<label><input type="checkbox" value="${code}" ${selected.includes(code) ? "checked" : ""}>${E(asset?.name || code)}</label>`;
  }).join("")}</fieldset>
  <p role="status"></p><canvas width="850" height="300" style="width:100%" aria-label="선택 종목 주가 변화율"></canvas><ul></ul>`;
 document.body.append(dialog);
 const status = dialog.querySelector('[role="status"]'), canvas = dialog.querySelector("canvas");
 const legend = dialog.querySelector("ul"), period = dialog.querySelector("select");
 const timezone = new Intl.DateTimeFormat("ko-KR", {timeZone:"Asia/Seoul", dateStyle:"short", timeStyle:"medium"});
 let pending;
 const refresh = async () => {
  pending?.abort();
  const request = new AbortController();
  pending = request;
  const assets = [...dialog.querySelectorAll("input:checked")].map(input => input.value);
  if (!assets.length) {
   status.textContent = "종목을 선택하세요.";
   canvas.hidden = true;
   legend.replaceChildren();
   return;
  }
  try {
   const params = new URLSearchParams({ assets: assets.join(","), period: period.value });
   const response = await fetch("/api/market-state/stock-prices?" + params, { signal: request.signal, cache:"no-store" });
   if (!response.ok) throw new Error(String(response.status));
   const {series} = await response.json();
   if (request.signal.aborted) return;
   const lines = assets.map((code, index) => ({
    code, color: `hsl(${index * 137.5} 68% 36%)`,
    points: (series[code] || []).filter(p => p.price > 0 && Number.isFinite(Date.parse(p.at)))
   }));
   const data = lines.flatMap(({points}) => points.map(p => [Date.parse(p.at), (p.price / points[0].price - 1) * 100]));
   canvas.hidden = !data.length;
   const resolution = period.value === "tick" ? "개별 틱 (종목당 최근 최대 500건)"
    : period.value === "minute" ? "1분봉 종가" : "일별 마지막 체결가";
   status.textContent = data.length ? resolution + " · " + data.length.toLocaleString("ko-KR")
    + "개 관측 · 첫 가격 대비 변화율 · 한국 시간" : "선택한 기간에 저장된 데이터가 없습니다.";
   const ctx = canvas.getContext("2d");
   ctx.clearRect(0, 0, canvas.width, canvas.height);
   if (data.length) {
    const times = data.map(p => p[0]), values = data.map(p => p[1]);
    const from = Math.min(...times), to = Math.max(...times);
    const low = Math.min(0, ...values), high = Math.max(0, ...values);
    const x = t => 66 + (t - from) / (to - from || 1) * 770;
    const y = v => high === low ? 138 : 252 - (v - low) / (high - low) * 229;
    ctx.fillStyle = "#283737";
    ctx.font = "13px sans-serif";
    ctx.fillText(high.toFixed(2) + "%", 3, 24);
    ctx.fillText(low.toFixed(2) + "%", 3, 253);
    ctx.fillText(timezone.format(from), 66, 283);
    const end = timezone.format(to);
    ctx.fillText(end, Math.max(66, 836 - ctx.measureText(end).width), 283);
    for (const {color, points} of lines) {
     if (!points.length) continue;
     ctx.strokeStyle = ctx.fillStyle = color;
     ctx.lineWidth = 2;
     ctx.beginPath();
     points.forEach((p, i) => {
      const px = x(Date.parse(p.at)), py = y((p.price / points[0].price - 1) * 100);
      if (i) ctx.lineTo(px, py);
      else ctx.moveTo(px, py);
     });
     ctx.stroke();
     if (points.length === 1) ctx.fillRect(x(Date.parse(points[0].at)) - 2, y(0) - 2, 4, 4);
    }
   }
   legend.replaceChildren(...lines.map(({code, color, points}) => {
    const li = document.createElement("li"), last = points.at(-1);
    li.style.color = color;
    li.textContent = (ASSET_MASTER.find(a => a.code === code)?.name || code) + (last
     ? ` · ${last.price.toLocaleString("ko-KR")}원 · ${timezone.format(Date.parse(last.at))} · 시작 ${timezone.format(Date.parse(points[0].at))}`
     : " · 데이터 없음");
    return li;
   }));
  } catch (error) {
   if (request.signal.aborted) return;
   status.textContent = "주가 이력을 가져올 수 없습니다.";
   canvas.hidden = true;
   legend.replaceChildren();
  }
 };
 dialog.addEventListener("change", refresh);
 const timer = setInterval(() => { if (period.value !== "3y" && !document.hidden) refresh(); }, 15000);
 dialog.addEventListener("close", () => { clearInterval(timer); pending?.abort(); dialog.remove(); }, {once:true});
 dialog.showModal();
 refresh();
}
