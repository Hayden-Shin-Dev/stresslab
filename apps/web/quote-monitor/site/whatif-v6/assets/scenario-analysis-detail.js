
(function () {
  "use strict";

  const esc = value => String(value ?? "").replace(/[&<>"']/g, char =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const number = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 2, signDisplay: "exceptZero" });
  const won = new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 });
  const date = new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeZone: "Asia/Seoul" });
  const percent = (value, suffix = "%") => Number.isFinite(value) ? number.format(value) + suffix : "—";
  const price = value => Number.isFinite(value) ? won.format(value) + "원" : "—";
  const fields = [
    { key: "shock_us10y_bp", label: "미국 10년 금리", unit: "bp", value: c => Number(c.rate) * 100 },
    { key: "shock_usdkrw_pct", label: "원/달러 환율", unit: "%", value: c => Number(c.fx) },
    { key: "shock_wti_pct", label: "WTI 유가", unit: "%", value: c => Number(c.oil) },
    { key: "shock_vix_pt", label: "VIX", unit: "pt", value: c => Number(c.vix) }
  ];
  const section = (title, content) => `<section class="detail-sheet"><h3>${esc(title)}</h3>${content}</section>`;
  const table = (headings, rows) => `<div class="detail-table"><table><thead><tr>${headings.map(label => `<th scope="col">${esc(label)}</th>`).join("")}</tr></thead><tbody>${rows.map(([first, ...cells]) => `<tr><th scope="row">${esc(first)}</th>${cells.map(cell => `<td>${esc(cell)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
  const cards = entries => `<dl class="detail-cards">${entries.map(([label,value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl>`;

  function comparison(asset) {
    const baseline = asset.baseline_model_return_pct, scenario = asset.scenario_return_pct;
    const interval = asset.model_interval_90_return_pct;
    const min = Math.min(-1, baseline, scenario, interval?.lower ?? 0);
    const max = Math.max(1, baseline, scenario, interval?.upper ?? 0);
    const padding = (max - min) * .13;
    const x = value => 155 + (value - min + padding) / (max - min + 2 * padding) * 534;
    const ticks = Array.from({ length: 5 }, (_, i) => min + (max - min) * i / 4);
    const plot = `<svg viewBox="0 0 725 148" class="detail-comparison-plot" role="img" aria-label="무충격 ${esc(percent(baseline))}, 입력 충격 ${esc(percent(scenario))}">
      <line x1="${x(0)}" x2="${x(0)}" y1="14" y2="113" class="detail-zero"/>
      <text x="12" y="39">무충격 중심값</text><text x="12" y="82">조건부 중심값</text>
      ${interval ? `<line x1="${x(interval.lower)}" x2="${x(interval.upper)}" y1="78" y2="78" class="detail-range"/>` : ""}
      <circle cx="${x(baseline)}" cy="35" r="6" class="detail-baseline"/><circle cx="${x(scenario)}" cy="78" r="6" class="detail-conditional"/>
      ${ticks.map(value => `<text x="${x(value)}" y="131" text-anchor="middle" class="detail-tick">${esc(percent(value))}</text>`).join("")}
    </svg>`;
    return `<h3 class="detail-heading">같은 시장 상태에서 입력 조건만 바꾸면?</h3>`
      + cards([["조건부 중심값", percent(scenario)], ["무충격 대비 차이", percent(scenario - baseline, "%p")], ["90% 구간 하단", percent(interval?.lower)]])
      + section("무충격과 사용자 조건 비교", plot + `<p>무충격 ${esc(percent(baseline))} · 입력 충격 ${esc(percent(scenario))}${interval ? ` · 90% 모델 구간 ${esc(percent(interval.lower))} ~ ${esc(percent(interval.upper))}` : ""}</p>`);
  }

  function casePlot(cases, asset, selection) {
    const returns = cases.map(row => row.actual_return_pct);
    const baseline = asset.baseline_model_return_pct, scenario = asset.scenario_return_pct;
    const min = Math.min(-1, baseline, scenario, ...returns), max = Math.max(1, baseline, scenario, ...returns);
    const padding = (max - min) * .16;
    const y = value => 188 - (value - min + padding) / (max - min + 2 * padding) * 158;
    const x = index => 80 + (index + .5) * 590 / cases.length;
    const grid = Array.from({ length: 5 }, (_, i) => min + (max - min) * i / 4);
    return `<svg viewBox="0 0 710 220" class="detail-case-plot" role="group" aria-label="과거 실제 수익률과 현재 조건 비교">
      ${grid.map(value => `<line x1="76" x2="676" y1="${y(value)}" y2="${y(value)}" class="detail-grid"/><text x="65" y="${y(value)+4}" text-anchor="end" class="detail-tick">${esc(percent(value))}</text>`).join("")}
      <line x1="76" x2="676" y1="${y(baseline)}" y2="${y(baseline)}" class="detail-baseline-line"/>
      <line x1="76" x2="676" y1="${y(scenario)}" y2="${y(scenario)}" class="detail-conditional-line"/>
      ${cases.map((row,index) => `<g role="button" tabindex="0" data-detail-case="${index}" data-case-point aria-pressed="${index===selection}" aria-label="사례 ${index+1} · ${esc(row.start)} · 실제 ${esc(percent(row.actual_return_pct))}">
        <title>${esc(row.start)} ~ ${esc(row.end)} · 실제 ${esc(percent(row.actual_return_pct))} · 현재 추정 대비 ${esc(percent(row.actual_return_pct-scenario,"%p"))}</title>
        <circle cx="${x(index)}" cy="${y(row.actual_return_pct)}" r="14" fill="transparent"/>
        <circle cx="${x(index)}" cy="${y(row.actual_return_pct)}" r="${index===selection?7:5}" class="detail-point"/>
        <text x="${x(index)}" y="211" text-anchor="middle">${index+1}</text>
      </g>`).join("")}
    </svg><p class="detail-chart-key"><span>● 과거 실제 수익률</span><span>┄ 무충격 중심값</span><span>┄ 현재 조건부 중심값</span></p>`;
  }

  function evidence(config, asset) {
    const { run, data, modelLabel, horizon, conditions, news } = config;
    const ctx = run?.stressResult?.model_context;
    const basis = asset && run?.priceSnapshot?.[asset.asset_id];
    const items = [
      ["분석 모델", modelLabel], ["분석 거래일", (data?.horizon || horizon) + "거래일"],
      ...(data?.basisDate ? [["모델 기준일", data.basisDate]] : []),
      ...fields.map(({ label, unit, value }) => [label, percent(value(conditions), unit)]),
      ...(run?.stressModel === WHATIF_CONDITIONAL_MODEL ? [["KOSPI 변화 가정","0%"]] : [])
    ];
    const stateRows = [
      ...(basis ? [[basis.adjusted ? "기준 수정종가" : "분석 당시 기준 시세", price(basis.price)]] : []),
      ...(ctx?.dataset_version ? [["데이터 기준", ctx.dataset_version]] : []),
      ...(ctx?.model_package_id ? [["모델 식별자", ctx.model_package_id]] : [])
    ];
    const contributions=asset?.shock_contributions_pp;
    const impact=contributions && Object.entries(contributions).filter(([, value]) => Number.isFinite(value));
    const sources=news?.sources?.filter(source => /^https:\/\//.test(source?.url || "")) || [];
    return `<h3 class="detail-heading">입력부터 결과까지 근거 확인</h3>
      <div class="detail-two">${section("사용한 입력과 시장 상태", table(["항목", "적용 값"], [...items,...stateRows]))}
      ${asset ? section("결과가 달라진 이유",
        table(["비교 항목","결과"], [
          ["무충격 중심값", percent(asset.baseline_model_return_pct)],
          ["조건부 중심값", percent(asset.scenario_return_pct)],
          ["무충격 대비", percent(asset.scenario_return_pct-asset.baseline_model_return_pct,"%p")],
          ...(impact?.length ? impact.map(([key,value])=>[fields.find(f=>f.key===key)?.label||key,percent(value,"%p")]) : [])
        ])+`<p>${impact?.length ? "변수별 기여는 모델 내 비교값입니다." : "변수별 영향의 크기는 이 결과만으로 구분할 수 없습니다."}</p>`) : ""}</div>
      ${news ? section("뉴스 반영 근거", `<p>${esc(news.summary)}</p><ul>${sources.map(source => `<li><a href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">${esc(source.title||"원문 보기")}</a></li>`).join("")}</ul>`) : ""}
      ${data ? '<button type="button" data-download-detail>분석 근거 JSON 저장</button>' : ""}`;
  }

  window.whatIfAnalysisDetail = function (config) {
    const { trigger, run, data, name, conditions, quotes, historicalCases } = config;
    const assets = data?.assets || [];
    const headings = ["상황 비교", "과거의 시장", "분석 근거"];
    const dialog = document.createElement("dialog");
    dialog.className = "fig-analysis-detail";
    dialog.setAttribute("aria-labelledby", "scenario-detail-title");
    dialog.innerHTML = `<header><div><h2 id="scenario-detail-title">분석 상세</h2>
      ${data ? `<p>${esc(config.modelLabel)} · ${data.horizon}거래일${data.basisDate?" · "+esc(data.basisDate):""}</p>` : ""}</div>
      <button type="button" data-detail-close>x 닫기</button></header>
      ${assets.length>1 ? `<label class="detail-asset-select">분석 종목 <select>${assets.map(row=>`<option value="${esc(row.asset_id)}">${esc(name(row.asset_id))}</option>`).join("")}</select></label>` : assets.length===1 ? `<p class="detail-asset-name">${esc(name(assets[0].asset_id))}</p>` : ""}
      <div class="fig-detail-tabs" role="tablist" aria-label="분석 상세 메뉴">${headings.map((label,i)=>`<button type="button" role="tab" id="scenario-detail-tab-${i}" aria-controls="scenario-detail-panel-${i}">${label}</button>`).join("")}</div>
      ${headings.map((_,i)=>`<section role="tabpanel" id="scenario-detail-panel-${i}" aria-labelledby="scenario-detail-tab-${i}" tabindex="0"></section>`).join("")}`;
    const tabs = [...dialog.querySelectorAll("[role=tab]")], panels = [...dialog.querySelectorAll("[role=tabpanel]")];
    const history = new Map();
    let tab = 0, asset = assets[0], selectedCase = 0, request;

    const similarityLink=config.openSimilarity?'<p><button type="button" data-detail-similarity>유사 시장 국면</button></p>':"";
    function renderHistory() {
      const panel = panels[1], code = asset?.asset_id;
      if (!code) { panel.innerHTML = "<p>시뮬레이션을 실행하면 관련 과거 자료를 확인할 수 있습니다.</p>"+similarityLink; return; }
      const record = history.get(code);
      const inline = Array.isArray(asset.historical_examples) ? asset.historical_examples : [];
      const cases = (record?.cases || inline).filter(row =>
        typeof row.start==="string" && typeof row.end==="string" && Number.isFinite(row.actual_return_pct));
      if (record?.loading) { panel.innerHTML = '<p role="status">과거 사례를 불러오고 있습니다.</p>'; return; }
      if (cases.length) {
        const row = cases[selectedCase];
        panel.innerHTML = `<h3 class="detail-heading">과거 구간과 현재 추정 비교</h3><div class="detail-history-layout">
          ${section("비교할 과거 구간", `<div class="detail-case-list">${cases.map((item,i)=>`<button type="button" data-detail-case="${i}" aria-pressed="${i===selectedCase}"><span>${i+1} · ${esc(item.start)}<small>~ ${esc(item.end)}</small></span><b>${esc(percent(item.actual_return_pct))}</b></button>`).join("")}</div>`)}
          ${section(`${data.horizon}거래일 종료 수익률 비교`,casePlot(cases,asset,selectedCase))}
        </div>${section("선택 구간의 조건 비교",
          cards([["과거 실제",percent(row.actual_return_pct)],["현재 조건부",percent(asset.scenario_return_pct)],["차이",percent(row.actual_return_pct-asset.scenario_return_pct,"%p")]])+
          (row.actual_shocks ? table(["충격 변수","현재 입력","당시 관측"], fields.map(({key,label,unit,value})=>[label,percent(value(conditions),unit),percent(row.actual_shocks[key],unit)])) : ""))}`;
        panel.insertAdjacentHTML("beforeend",similarityLink);
        return;
      }
      const historyRows = quotes[code] || [];
      const first = historyRows[0], last = historyRows.at(-1);
      panel.innerHTML = section("유사 시장 사례", record?.error
        ? '<p role="alert">과거 사례를 불러오지 못했습니다.</p><button type="button" data-detail-retry>다시 조회</button>'
        : "<p>이 실행 조건에서 확인할 수 있는 과거 사례가 없습니다.</p>")
        + (first && last ? section("실제 일별 종가", table(["관측 기간","최저 종가","최고 종가","마지막 종가"], [[
          date.format(new Date(first.at))+" ~ "+date.format(new Date(last.at)),
          price(Math.min(...historyRows.map(row=>row.price))), price(Math.max(...historyRows.map(row=>row.price))), price(last.price)
        ]])) : "");
      panel.insertAdjacentHTML("beforeend",similarityLink);
    }
    function loadCases() {
      const code = asset?.asset_id;
      if (!code || !historicalCases || history.has(code)) return;
      const controller=new AbortController();
      request?.abort();
      request=controller;
      history.set(code,{ loading:true });
      renderHistory();
      historicalCases(code, AbortSignal.any([controller.signal,AbortSignal.timeout(30000)])).then(cases=>{
        history.set(code,{ cases });
      }).catch(()=>{
        if (controller.signal.aborted) history.delete(code);
        else history.set(code,{ error:true });
      }).finally(()=>{
        if (dialog.open && asset?.asset_id===code) renderHistory();
      });
    }
    function paint() {
      panels[0].innerHTML=asset?comparison(asset):"<p>시뮬레이션을 실행하면 상황을 비교할 수 있습니다.</p>";
      panels[2].innerHTML=evidence(config,asset);
      renderHistory();
      if(tab===1)loadCases();
    }
    function show(index, focus = true) {
      tab=index;
      tabs.forEach((button,i)=>{
        button.setAttribute("aria-selected",String(index===i));
        button.tabIndex=index===i?0:-1;
        panels[i].hidden=index!==i;
      });
      if(index===1)loadCases();
      if(focus)tabs[index].focus({preventScroll:true});
    }
    tabs.forEach((button,i)=>{
      button.onclick=()=>show(i);
      button.onkeydown=event=>{
        const index={ArrowLeft:(i+2)%3,ArrowRight:(i+1)%3,Home:0,End:2}[event.key];
        if(index===undefined)return;
        event.preventDefault();show(index);
      };
    });
    dialog.querySelector("select")?.addEventListener("change",event=>{
      asset=assets.find(row=>row.asset_id===event.target.value);
      selectedCase=0;paint();
    });
    function chooseCase(event) {
      const button=event.target.closest("[data-detail-case]");
      if(!button)return;
      const focus=button.matches(":focus"), point=button.hasAttribute("data-case-point");
      selectedCase=Number(button.dataset.detailCase);
      const scroll=panels[1].scrollTop;
      renderHistory();
      panels[1].scrollTop=scroll;
      if(focus)panels[1].querySelector(`[data-detail-case="${selectedCase}"]${point?"[data-case-point]":":not([data-case-point])"}`)?.focus({preventScroll:true});
    }
    panels[1].onclick=event=>{
      if(event.target.closest("[data-detail-similarity]"))return config.openSimilarity();
      if(event.target.closest("[data-detail-retry]")){history.delete(asset.asset_id);loadCases();}
      else chooseCase(event);
    };
    panels[1].onkeydown=event=>{
      if(event.target.matches("[data-case-point]")&&["Enter"," "].includes(event.key)){
        event.preventDefault();chooseCase(event);
      }
    };
    panels[2].onclick=event=>{
      if(!event.target.closest("[data-download-detail]"))return;
      const content={model:data.model,horizon_trading_days:data.horizon,model_context:run.stressResult.model_context,
        conditions:fields.map(({key,unit,value})=>({key,unit,value:value(conditions)})),
        assets:data.assets,price_basis:run.priceSnapshot,news:config.news||null};
      const url=URL.createObjectURL(new Blob([JSON.stringify(content,null,2)],{type:"application/json"}));
      const link=document.createElement("a");
      link.href=url;link.download="whatif-analysis-detail.json";link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
    dialog.querySelector("[data-detail-close]").onclick=()=>dialog.close();
    dialog.addEventListener("close",()=>{
      request?.abort();dialog.remove();
      (trigger.isConnected?trigger:document.querySelector("[data-gx=p63-analysis-detail]"))?.focus({preventScroll:true});
    },{ once:true });
    paint();show(0,false);
    document.body.append(dialog);dialog.showModal();tabs[0].focus();
  };
})();
