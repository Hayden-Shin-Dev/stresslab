(function (global) {
  'use strict';
  const horizons = [1, 5, 20];
  const fields = [
    ['kospi_pct', '코스피 (%)'], ['shock_usdkrw_pct', '원/달러 (%)'],
    ['shock_us10y_bp', '미국 10년 금리 (bp)'], ['shock_wti_pct', 'WTI (%)'],
    ['shock_vix_pt', 'VIX (pt)'],
  ];
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const won = n => Number(n).toLocaleString('ko-KR', {maximumFractionDigits: 0}) + '원';
  const pct = n => Number(n).toLocaleString('ko-KR', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '%';
  let pending = null, result = null, resultKey = '', error = '', mountedKey = '';
  let history = null, historyPending = null, historyError = '';
  const shockLabels = fields.filter(([k])=>k!=='kospi_pct');

  function clearHistory() {
    historyPending?.abort(); historyPending=null; history=null; historyError='';
  }
  function historyHTML() {
    if (!history) return '<p>결과 행의 과거 비교를 누르면 같은 종목·기간의 학습 구간 실제 사례를 확인할 수 있습니다.</p>';
    if (historyPending) return '<p role="status">학습 구간에서 가까운 과거 충격을 찾는 중…</p>';
    if (historyError) return `<p role="alert">${esc(historyError)}</p>`;
    const data=history.data;
    if (!data?.cases?.length) return `<p>${esc(data?.unavailable_reason||'비교 가능한 과거 사례가 없습니다.')}</p>`;
    const item=data.cases[history.index], response=result.results.find(r=>r.asset_id===history.assetId);
    const prediction=response.predictions.find(p=>p.horizon_days===history.horizon);
    const delta=item.actual_return_pct-prediction.point_simple_return_pct;
    return `<h4>과거 유사 충격 구간 · ${esc(history.assetId)} · ${history.horizon}거래일</h4>
      <div class="conditional-history-options">${data.cases.map((c,i)=>`<button type="button" data-history-index="${i}" aria-pressed="${i===history.index}">${esc(c.start)} → ${esc(c.end)} · 실제 ${pct(c.actual_return_pct)}</button>`).join('')}</div>
      <h4>선택 구간의 조건 비교</h4><div class="conditional-history-comparison"><div class="conditional-history-summary"><strong>${esc(item.start)} → ${esc(item.end)}</strong><p>실제 수익률 ${pct(item.actual_return_pct)}</p><p>현재 조건부 추정 ${pct(prediction.point_simple_return_pct)}</p><p>차이 ${delta>=0?'+':''}${delta.toFixed(2)}%p</p></div>
      <div class="conditional-table-wrap"><table><thead><tr><th>비교 기준</th>${shockLabels.map(([,label])=>`<th>${esc(label)}</th>`).join('')}</tr></thead><tbody><tr><th>현재 입력</th>${shockLabels.map(([k])=>`<td>${Number(data.current_shocks[k]).toFixed(2)}</td>`).join('')}</tr><tr><th>당시 관측</th>${shockLabels.map(([k])=>`<td>${Number(item.actual_shocks[k]).toFixed(2)}</td>`).join('')}</tr></tbody></table>
      <p>과거 실제 수익률은 현재 추정값보다 ${Math.abs(delta).toFixed(2)}%p ${delta>=0?'높았습니다':'낮았습니다'}. 당시 조건은 현재 입력과 다르며 과거 수익률은 예측이 아닙니다.</p></div></div>
      <details><summary>검색 기준과 자료 범위</summary><p>현재 모델 학습 구간의 실제 관측만 사용합니다. 같은 종목·기간에서 6가지 시장 상태가 가까운 최대 100건을 찾고, 4가지 충격의 표준화 거리가 1 이하인 겹치지 않는 구간을 가까운 순서로 최대 5건 표시합니다.</p><p>거리는 확률이나 예측 신뢰도가 아닙니다. 코스피 가정은 이 4충격 거리 계산에 포함하지 않습니다.</p></details>`;
  }

  async function loadHistory(a,assetId,horizon) {
    if (!result || pending) return;
    const frozen=result, response=result.results.find(r=>r.asset_id===assetId);
    if (!response) return;
    historyPending?.abort();
    const controller=new AbortController();historyPending=controller;
    history={assetId,horizon,index:0,data:null};historyError='';a.repaint();
    const timer=setTimeout(()=>controller.abort(),30000);
    try {
      const data=await request('/history',{asset_id:assetId,scenarios:response.scenarios,
        horizon_days:horizon,snapshot_sha256:response.snapshot_sha256},controller.signal);
      if (controller.signal.aborted || result!==frozen || historyPending!==controller) return;
      if (data.asset_id!==assetId || data.horizon_days!==horizon
          || data.snapshot_sha256!==response.snapshot_sha256 || data.model_package_id!==response.model_package_id
          || data.source_split!=='train' || !Array.isArray(data.cases) || data.cases.length>5)
        throw Error('과거 비교 자료가 현재 예측의 종목·기간·모델과 다릅니다.');
      const scenario=response.scenarios.find(s=>s.horizon_days===horizon);
      if (shockLabels.some(([k])=>data.current_shocks?.[k]!==scenario[k])) throw Error('과거 검색의 충격 가정이 현재 입력과 다릅니다.');
      for (const c of data.cases) {
        if (![c.actual_return_pct,...shockLabels.map(([k])=>c.actual_shocks?.[k])].every(Number.isFinite))
          throw Error('과거 비교 관측값이 올바르지 않습니다.');
      }
      history.data=data;
    } catch(e) {
      if(historyPending===controller) historyError=e.name==='AbortError'?'과거 비교 조회가 취소되었거나 시간이 초과됐습니다.':e.message;
    } finally {
      clearTimeout(timer);if(historyPending===controller)historyPending=null;a.repaint();
    }
  }

  function scenarios(state) {
    state.conditionalScenarios ||= horizons.map(h => Object.fromEntries([
      ['horizon_days', h], ...fields.map(([k]) => [k, 0])
    ]));
    return state.conditionalScenarios;
  }
  function payload(ids, rows) {
    if (!ids.length || ids.length > 20 || new Set(ids).size !== ids.length || ids.some(id => !/^\d{6}$/.test(id)))
      throw Error('지원 종목을 1~20개 선택해 주세요.');
    if (rows.length !== 3 || [...rows].map(r=>r.horizon_days).sort((a,b)=>a-b).join(',') !== '1,5,20')
      throw Error('1·5·20거래일의 가정을 모두 입력해 주세요.');
    const values = rows.map(r => {
      const row = {horizon_days: r.horizon_days};
      for (const [k] of fields) {
        if (r[k] === '' || r[k] == null || !Number.isFinite(Number(r[k])))
          throw Error('다섯 가지 충격을 기간별로 모두 입력해 주세요.');
        row[k] = Number(r[k]);
      }
      if (['kospi_pct','shock_usdkrw_pct','shock_wti_pct'].some(k => row[k] <= -100))
        throw Error('코스피·환율·WTI 변화율은 -100%보다 커야 합니다.');
      return row;
    });
    return {asset_ids: [...ids].sort(), scenarios: values};
  }
  async function request(path, body, signal) {
    const response = await fetch('/api/stress/scenario' + path, {
      method: body ? 'POST' : 'GET', credentials: 'same-origin', cache: 'no-store',
      headers: {'Content-Type': 'application/json'}, signal,
      ...(body ? {body: JSON.stringify(body)} : {}),
    });
    if (response.redirected || response.status === 401) throw Error('로그인이 필요합니다.');
    if (!response.ok) {
      let detail;
      try { detail = (await response.json()).detail; } catch {}
      throw Error(typeof detail === 'string' ? detail : `조건부 분석 요청 실패 (${response.status})`);
    }
    return response.json();
  }
  function validate(response, body) {
    if (response.model !== 'huber_catboost_hybrid_conditional' || !Array.isArray(response.results)
        || response.results.length !== body.asset_ids.length) throw Error('모델 응답 형식이 다릅니다.');
    const ids = response.results.map(r=>r.asset_id).sort();
    if (JSON.stringify(ids) !== JSON.stringify(body.asset_ids)) throw Error('응답 종목이 요청과 다릅니다.');
    let signature;
    for (const r of response.results) {
      const sig = JSON.stringify([r.snapshot_sha256, r.model_package_id, r.dataset_version, r.as_of_trading_date]);
      if (signature && signature !== sig) throw Error('종목 간 스냅샷이 다릅니다. 다시 실행하세요.');
      signature = sig;
      if (!Array.isArray(r.scenarios) || r.scenarios.length !== 3 || body.scenarios.some(expected => {
        const actual = r.scenarios.find(s=>s.horizon_days===expected.horizon_days);
        return !actual || fields.some(([k])=>actual[k]!==expected[k]);
      })) throw Error('응답 가정이 요청과 다릅니다.');
      if (!Array.isArray(r.predictions) || r.predictions.length !== 3
          || r.predictions.map(p=>p.horizon_days).sort((a,b)=>a-b).join(',') !== '1,5,20') throw Error('세 기간 결과가 모두 필요합니다.');
      for (const p of r.predictions) {
        if (p.asset_id !== r.asset_id || ['base_close','predicted_close','point_simple_return_pct',
          'lower_80_close','upper_80_close','lower_90_close','upper_90_close'].some(k=>!Number.isFinite(p[k])))
          throw Error('결과에 올바르지 않은 숫자가 있습니다.');
      }
    }
    return response;
  }
  function cancel() { pending?.abort(); pending = null; clearHistory(); }
  async function run(a) {
    if (pending) return;
    let body;
    try { body = payload(a.ids, scenarios(a.state)); }
    catch (e) { error = e.message; a.repaint(); return; }
    const key = JSON.stringify(body), controller = new AbortController();
    clearHistory();pending = controller; error = ''; result = null; a.repaint();
    const timer = setTimeout(()=>controller.abort(), 40000);
    try {
      const response = validate(await request('', body, controller.signal), body);
      if (!controller.signal.aborted && pending === controller && mountedKey === key) {
        result = response; resultKey = key;
      }
    } catch (e) { if (pending === controller) error = e.name === 'AbortError' ? '요청이 취소되었거나 시간이 초과됐습니다.' : e.message; }
    finally { clearTimeout(timer); if (pending === controller) pending = null; a.repaint(); }
  }
  function mount(a) {
    const {root, state, ids, names, repaint, persist} = a;
    if (!root) return;
    if (!a.active) { cancel(); mountedKey = ''; return; }
    let key;
    try { key = JSON.stringify(payload(ids, scenarios(state))); } catch { key = ''; }
    if (key !== mountedKey) { cancel(); result = null; error = ''; mountedKey = key; }
    root.querySelectorAll(':scope > .fig-shock-panel, :scope > .fig-chart-panel').forEach(el=>el.hidden=true);
    const period = root.querySelector('#fig-period-select');
    if (period) { period.innerHTML='<option>1·5·20거래일 함께 계산</option>'; period.disabled=true; }
    root.querySelector('.conditional-v4-panel')?.remove();
    const panel = document.createElement('section'); panel.className='conditional-v4-panel';
    panel.setAttribute('aria-label','Huber + CatBoost 조건부 분석');
    const rows = scenarios(state);
    panel.innerHTML = `<h3>기간별 시장 충격 가정</h3><p>각 기간 전체의 누적 변화입니다. 0은 변화 없음입니다. 기간별 가정을 자동 환산하지 않습니다.</p>
      <div class="conditional-table-wrap"><table><thead><tr><th>기간</th>${fields.map(([,label])=>`<th>${label}</th>`).join('')}</tr></thead>
      <tbody>${rows.map((r,i)=>`<tr><th>${r.horizon_days}거래일</th>${fields.map(([k,label])=>`<td><input type="number" step="any" data-conditional-row="${i}" data-conditional-field="${k}" value="${esc(r[k])}" aria-label="${r.horizon_days}거래일 ${label}" ${pending?'disabled':''}></td>`).join('')}</tr>`).join('')}</tbody></table></div>
      <p>선택 종목 ${ids.length}개 · 수정종가 기준 · 연구용 시나리오 분석</p>
      <p role="status">${pending?'계산 중…':error?esc(error):result&&resultKey===key?'계산 완료':'가정과 종목을 확인한 뒤 PLAY를 누르세요.'}</p>
      ${pending?'<button type="button" data-conditional-cancel>계산 취소</button>':''}
      <div class="conditional-v4-result"></div>
      <p>이 결과는 기존 5일 분석의 차트·포트폴리오 손익·AI 토론·보관소에 자동으로 섞이지 않습니다.</p>`;
    const anchor=root.querySelector(':scope > .fig-model-row');
    if(anchor)anchor.after(panel);else root.prepend(panel);
    panel.querySelectorAll('[data-conditional-field]').forEach(input=>input.addEventListener('change',()=>{
      rows[Number(input.dataset.conditionalRow)][input.dataset.conditionalField]=input.value;
      result=null; error=''; persist(); repaint();
    }));
    panel.querySelector('[data-conditional-cancel]')?.addEventListener('click',()=>{cancel();error='계산을 취소했습니다.';repaint();});
    const play=root.querySelector('.fig-run-button'); if(play)play.disabled=!!pending;
    if(result && resultKey===key) {
      const first=result.results[0], target=panel.querySelector('.conditional-v4-result');
      target.innerHTML=`<p>데이터 기준일 ${esc(first.as_of_trading_date)} · ${esc(first.model_package_id)}</p>
        <div class="conditional-table-wrap"><table><thead><tr><th>종목</th><th>기간</th><th>기준 수정종가</th><th>예측 수정종가</th><th>수익률</th><th>80% 구간</th><th>90% 구간</th><th>과거 사례</th></tr></thead><tbody>${result.results.flatMap(r=>[...r.predictions].sort((a,b)=>a.horizon_days-b.horizon_days).map(p=>`<tr><th>${esc(names[r.asset_id]||r.asset_id)} (${esc(r.asset_id)})</th><td>${p.horizon_days}거래일</td><td>${won(p.base_close)}</td><td>${won(p.predicted_close)}</td><td>${pct(p.point_simple_return_pct)}</td><td>${won(p.lower_80_close)} ~ ${won(p.upper_80_close)}</td><td>${won(p.lower_90_close)} ~ ${won(p.upper_90_close)}</td><td><button type="button" data-history-asset="${esc(r.asset_id)}" data-history-horizon="${p.horizon_days}">과거 비교</button></td></tr>`)).join('')}</tbody></table></div>
        <p>입력한 가정 아래의 조건부 추정입니다. 예측구간의 실제 포함률을 보장하지 않습니다.</p>
        <section class="conditional-history" aria-label="선택 구간의 조건 비교">${historyHTML()}</section>`;
      target.querySelectorAll('[data-history-asset]').forEach(button=>button.addEventListener('click',()=>loadHistory(a,button.dataset.historyAsset,Number(button.dataset.historyHorizon))));
      target.querySelectorAll('[data-history-index]').forEach(button=>button.addEventListener('click',()=>{history.index=Number(button.dataset.historyIndex);repaint();}));
    }
  }
  const api={mount,run,cancel,payload,validate};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  else global.whatIfConditional=api;
})(typeof window==='undefined'?globalThis:window);
