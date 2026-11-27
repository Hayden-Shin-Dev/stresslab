/*
 * WHAT IF · 시장국면 탭 내용
 *
 * 탭 틀(#market-regime-panel, .gx-market-regime-content)은 index.html이 그립니다.
 * 이 파일은 그 안의 내용만 채웁니다. 탭 크기와 다른 화면은 건드리지 않습니다.
 *
 * 데이터: GET /api/v1/market-regime/snapshot (contracts/market-regime/api-v1.md)
 * 화면 확인용 합성 샘플: 주소 끝에 ?mrx=sample 을 붙이면 sample/regime_snapshot.sample.json 을 읽고
 * "샘플(합성) 데이터" 표시를 띄웁니다. 운영 화면에서는 API만 씁니다.
 */
(function () {
  'use strict';

  var API_URL = '/api/v1/market-regime/snapshot';
  var SAMPLE_URL = './assets/market-regime/sample/regime_snapshot.sample.json';
  var REFRESH_MS = 5 * 60 * 1000;
  var ORDER = ['bull', 'sideways', 'bear'];
  var NAME = { bull: '상승장', sideways: '횡보장', bear: '폭락장' };
  var COLOR = { bull: '#1baf7a', sideways: '#6250d6', bear: '#eb6834' };
  var TABS = [['overview', '개요'], ['history', '국면 이력'], ['similar', '유사 시기'], ['model', '모델·데이터']];
  var RANGES = [[1, '1년'], [3, '3년'], [5, '5년'], ['all', '전체']];
  var NOTICE_FALLBACK = '과거 데이터 기반 시장 분석이며 투자 권유·종목 추천·수익 보장이 아닙니다.';

  var state = {
    tab: 'overview', range: 3, selected: 0,
    snap: null, status: 'idle', error: null, staleError: null,
    loadedAt: 0, scroll: {}, root: null, ro: null, lastWidth: 0
  };
  var useSample = /(?:^|[?&])mrx=sample(?:&|$)/.test(location.search);

  // ---------------------------------------------------------------- 표기 도우미
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function ok(v) { return v != null && isFinite(v); }
  function num(v, nd) {
    if (!ok(v)) return '—';
    return Number(v).toLocaleString('ko-KR', { minimumFractionDigits: nd, maximumFractionDigits: nd });
  }
  function signed(v, nd) { return ok(v) ? (v > 0 ? '+' : '') + num(v, nd) : '—'; }
  function prob(v, nd) { return ok(v) ? num(v * 100, nd == null ? 0 : nd) + '%' : '—'; }
  function day(s) { return s ? String(s).slice(0, 10).replace(/-/g, '.') : '—'; }
  function unitFmt(it) {
    var v = it.value, id = it.id || '', u = it.unit;
    if (!ok(v)) return '—';
    if (u === '%') return (/_ret_|_chg_|_dd_/.test(id) ? signed(v, 2) : num(v, 2)) + '%';
    if (u === 'bp') return signed(v, 0) + 'bp';
    if (u === 'corr') return num(v, 2);
    if (u === 'pt') return id === 'kospi_close' ? num(v, 2) : num(v, 2) + 'pt';
    return num(v, 2);
  }
  function dot(code) { return '<i class="mrx-dot" style="background:' + (COLOR[code] || '#8c8676') + '"></i>'; }
  function pill(code, name) { return '<span class="mrx-pill">' + dot(code) + esc(name || NAME[code] || code) + '</span>'; }
  function basisText(b) { return b === 'walk_forward' ? '실시간 판정' : b === 'mixed' ? '혼합' : b === 'initial_in_sample' ? '초기 학습 구간' : '—'; }
  function deck(title, body, extra) {
    return '<section class="mrx-deck' + (extra && extra.cls ? ' ' + extra.cls : '') + '">' +
      '<header class="mrx-deck-head"><h2 class="mrx-deck-title">' + esc(title) + '</h2>' + (extra && extra.tools ? '<div class="mrx-deck-tools">' + extra.tools + '</div>' : '') + '</header>' +
      '<div class="mrx-deck-body">' + body + '</div></section>';
  }
  function kv(rows) {
    return '<dl class="mrx-kv">' + rows.map(function (r) { return '<dt>' + esc(r[0]) + '</dt><dd>' + (r[2] ? r[1] : esc(r[1] == null || r[1] === '' ? '—' : r[1])) + '</dd>'; }).join('') + '</dl>';
  }
  function table(head, rows, opts) {
    opts = opts || {};
    return '<div class="mrx-table-wrap"><table class="mrx-table"' + (opts.label ? ' aria-label="' + esc(opts.label) + '"' : '') + '><thead><tr>' +
      head.map(function (h, i) { return '<th' + (opts.num && opts.num.indexOf(i) >= 0 ? ' class="mrx-num"' : '') + ' scope="col">' + esc(h) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + rows.join('') + '</tbody></table></div>';
  }
  function legend(withLine) {
    return '<div class="mrx-legend">' + (withLine ? '<span><i class="mrx-sw-line"></i>KOSPI</span>' : '') +
      ORDER.map(function (k) { return '<span><i class="mrx-sw" style="background:' + COLOR[k] + '"></i>' + NAME[k] + '</span>'; }).join('') +
      (withLine ? '<span><i class="mrx-sw mrx-sw-hatch"></i>초기 학습 구간(표본 내)</span>' : '') + '</div>';
  }

  // ---------------------------------------------------------------- 데이터
  function fetchJson(url) {
    var ctrl = typeof AbortController === 'function' ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, 15000) : null;
    return fetch(url, { credentials: 'same-origin', headers: { Accept: 'application/json' }, signal: ctrl ? ctrl.signal : undefined })
      .then(function (r) {
        if (timer) clearTimeout(timer);
        var type = r.headers.get('content-type') || '';
        if (!r.ok) { var e = new Error('HTTP ' + r.status); e.status = r.status; throw e; }
        if (type.indexOf('json') < 0) { var e2 = new Error('JSON 응답이 아님'); e2.status = 'not-json'; throw e2; }
        return r.json();
      }, function (err) { if (timer) clearTimeout(timer); err.status = err.name === 'AbortError' ? 'timeout' : 'network'; throw err; });
  }
  function validate(s) {
    if (!s || s.schema !== 'market_regime_snapshot' || s.schema_version !== 1) {
      var e = new Error('지원하지 않는 데이터 형식'); e.status = 'schema'; throw e;
    }
    if (!s.current || !Array.isArray(s.history)) { var e2 = new Error('필수 항목 누락'); e2.status = 'schema'; throw e2; }
    return s;
  }
  function load(force) {
    if (state.status === 'loading') return;
    if (!force && state.snap && Date.now() - state.loadedAt < REFRESH_MS) return;
    state.status = 'loading'; state.error = null; paint();
    fetchJson(useSample ? SAMPLE_URL : API_URL).then(validate).then(function (s) {
      state.snap = s; state.status = 'ready'; state.staleError = null; state.loadedAt = Date.now();
      if (state.selected >= ((s.similar && s.similar.neighbors) || []).length) state.selected = 0;
      paint();
    }).catch(function (e) {
      if (state.snap) { state.status = 'ready'; state.staleError = e; }
      else { state.status = 'error'; state.error = e; }
      paint();
    });
  }
  function errorText(e) {
    var st = e && e.status;
    if (st === 503) return ['시장 국면 데이터를 준비하고 있습니다.', '오늘 분석 결과가 아직 게시되지 않았습니다. 잠시 뒤 다시 불러와 주세요.'];
    if (st === 401 || st === 403) return ['로그인이 필요합니다.', '로그인한 뒤 다시 열어 주세요.'];
    if (st === 'schema') return ['데이터 형식을 확인할 수 없습니다.', '화면과 데이터 버전이 맞지 않습니다. 담당자에게 알려 주세요.'];
    if (st === 'timeout') return ['응답이 늦어지고 있습니다.', '잠시 뒤 다시 불러와 주세요.'];
    return ['시장 국면 데이터 연결을 준비하고 있습니다.', '연결이 끝나면 이 화면에 분석 결과가 표시됩니다.'];
  }

  // ---------------------------------------------------------------- 화면
  function panel() { return document.getElementById('market-regime-panel'); }
  function host() { var p = panel(); return p && p.querySelector('.gx-market-regime-content'); }

  function headHTML() {
    var s = state.snap;
    var meta = s ? '<span class="mrx-chip">기준일 ' + esc(day(s.as_of)) + '</span><span class="mrx-chip">' + esc((s.model && s.model.model_version) || '—') + '</span>' : '';
    return '<div class="mrx-titlebar">' +
      '<div class="mrx-titlebar-name"><img src="./assets/market-regime-icon.png" alt="" class="mrx-title-icon"><span>WHAT IF · 시장국면</span></div>' +
      '<div class="mrx-titlebar-tools">' + meta +
      '<button type="button" class="mrx-title-btn" data-mrx-action="reload" title="다시 불러오기" aria-label="다시 불러오기">↻</button>' +
      '<button type="button" class="mrx-title-btn" data-mrx-action="close" title="닫기" aria-label="시장국면 닫기">×</button></div></div>' +
      '<div class="mrx-tabs" role="tablist" aria-label="시장국면 보기">' + TABS.map(function (t) {
        var on = state.tab === t[0];
        return '<button type="button" role="tab" id="mrx-tab-' + t[0] + '" aria-controls="mrx-tabpanel" aria-selected="' + on + '" tabindex="' + (on ? 0 : -1) + '" data-mrx-tab="' + t[0] + '">' + t[1] + '</button>';
      }).join('') + '</div>';
  }
  function statusHTML() {
    var s = state.snap, out = '';
    if (s && s.data_mode === 'synthetic_fixture') out += '<p class="mrx-banner mrx-banner-sample" role="status"><strong>샘플(합성) 데이터</strong> 화면 확인용 합성 데이터입니다. 실제 시장 결과가 아닙니다.</p>';
    if (s && state.staleError) out += '<p class="mrx-banner" role="status">최신 데이터를 다시 불러오지 못해 ' + esc(day(s.as_of)) + ' 기준 데이터를 표시합니다.</p>';
    if (s && state.status === 'loading') out += '<p class="mrx-banner mrx-banner-quiet" role="status">최신 데이터를 확인하는 중입니다…</p>';
    return out;
  }
  function bodyHTML() {
    var s = state.snap;
    if (!s) {
      if (state.status === 'error') {
        var t = errorText(state.error);
        return deck('시장 국면', '<div class="mrx-empty"><p class="mrx-empty-title">' + esc(t[0]) + '</p><p>' + esc(t[1]) + '</p>' +
          '<p class="mrx-empty-code">' + esc(String((state.error && state.error.status) || '')) + '</p>' +
          '<button type="button" class="mrx-btn" data-mrx-action="reload">다시 불러오기</button></div>');
      }
      return deck('시장 국면', '<div class="mrx-empty" role="status"><p class="mrx-empty-title">시장 국면 데이터를 불러오는 중입니다…</p></div>');
    }
    var html = state.tab === 'history' ? historyTab(s) : state.tab === 'similar' ? similarTab(s) : state.tab === 'model' ? modelTab(s) : overviewTab(s);
    return html + '<p class="mrx-notice">' + esc(s.notice || NOTICE_FALLBACK) + '</p>';
  }

  function overviewTab(s) {
    var c = s.current || {}, p = c.probabilities || {};
    var cur = '<div class="mrx-kpi mrx-kpi-main"><span class="mrx-kpi-label">현재 국면</span>' +
      '<strong class="mrx-kpi-regime">' + dot(c.regime_code) + esc(c.regime_name || NAME[c.regime_code] || '—') + '</strong>' +
      '<span class="mrx-kpi-note">모델 확률 ' + prob(c.confidence) + (c.label_basis === 'initial_in_sample' ? ' · 초기 학습 구간' : '') + '</span>' +
      (c.pending_switch ? '<span class="mrx-pending">' + dot(c.pending_switch.to_code) + esc(c.pending_switch.to_name) + ' 전환 확인 중 (' + esc(c.pending_switch.consecutive_days) + '/' + esc(c.pending_switch.required_days) + '일)</span>' : '') + '</div>';
    var dur = '<div class="mrx-kpi"><span class="mrx-kpi-label">현재 국면 지속</span><strong class="mrx-kpi-value">' + num(c.days_in_regime, 0) + '<small>거래일</small></strong><span class="mrx-kpi-note">시작일 ' + day(c.regime_since) + '</span></div>';
    var chg = '<div class="mrx-kpi"><span class="mrx-kpi-label">최근 1년 국면 전환</span><strong class="mrx-kpi-value">' + num(c.changes_last_252d, 0) + '<small>회</small></strong><span class="mrx-kpi-note">최근 252거래일 기준</span></div>';
    var bars = '<div class="mrx-kpi mrx-kpi-probs"><span class="mrx-kpi-label">국면별 모델 확률</span>' + ORDER.map(function (k) {
      var v = p[k];
      return '<div class="mrx-pbar"><span class="mrx-pbar-name">' + dot(k) + NAME[k] + '</span><span class="mrx-pbar-track"><span class="mrx-pbar-fill" style="width:' + (ok(v) ? Math.max(0, Math.min(100, v * 100)).toFixed(1) : 0) + '%;background:' + COLOR[k] + '"></span></span><span class="mrx-pbar-val">' + prob(v) + '</span></div>';
    }).join('') + '</div>';
    var top = deck('현재 국면', '<div class="mrx-kpis">' + cur + dur + chg + bars + '</div>' +
      (c.pending_switch ? '<p class="mrx-cap">국면 전환은 새 국면 확률이 기준 이상인 날이 정해진 일수만큼 이어질 때 확정합니다. 확인 중에는 모델 확률이 낮게 보일 수 있습니다.</p>' : ''));

    var tools = '<div class="mrx-chips" role="group" aria-label="기간">' + RANGES.map(function (r) {
      return '<button type="button" class="mrx-chip-btn" aria-pressed="' + (state.range === r[0]) + '" data-mrx-range="' + r[0] + '">' + r[1] + '</button>';
    }).join('') + '</div>';
    var main = deck('KOSPI와 국면 구간', legend(true) + '<div class="mrx-chart" data-mrx-chart="index" style="height:300px"></div>', { tools: tools });

    var ind = (c.indicators || []).map(function (it) {
      var pc = it.percentile;
      return '<tr><td>' + esc(it.label) + '</td><td class="mrx-num">' + unitFmt(it) + '</td><td>' + (ok(pc) ?
        '<span class="mrx-pctl" title="과거 값의 ' + num(pc, 0) + '%가 현재 이하"><span class="mrx-pctl-track"><span class="mrx-pctl-mark" style="left:' + Math.max(0, Math.min(100, pc)) + '%"></span></span><span class="mrx-pctl-txt">' + num(pc, 0) + '</span></span>' : '—') + '</td></tr>';
    });
    var left = deck('현재 시장 지표', '<p class="mrx-cap">백분위: 과거 전체 기간에서 현재 값 이하였던 날의 비율입니다. 높을수록 과거 대비 큰 값입니다.</p>' +
      table(['지표', '현재', '과거 대비 백분위'], ind, { num: [1], label: '현재 시장 지표' }));
    var right = deck('국면별 확률 추이 (최근 120거래일)', legend(false) + '<div class="mrx-chart" data-mrx-chart="prob" style="height:260px"></div>' +
      '<p class="mrx-cap">그날까지의 자료만으로 계산한 모델 확률입니다.</p>');
    return top + main + '<div class="mrx-grid">' + left + right + '</div>';
  }

  function historyTab(s) {
    var tl = deck('국면 타임라인 (전체 기간)', legend(false) + '<div class="mrx-chart" data-mrx-chart="timeline" style="height:86px"></div>');
    var t = s.transitions || {}, f = t.daily_frequency || [], order = t.order || ORDER;
    var heat = '<div class="mrx-table-wrap"><table class="mrx-table mrx-heat" aria-label="과거 전이 빈도"><thead><tr><th scope="col">오늘 → 다음 거래일</th>' +
      order.map(function (k) { return '<th scope="col" class="mrx-num">' + pill(k) + '</th>'; }).join('') + '</tr></thead><tbody>' +
      order.map(function (a, i) {
        return '<tr><th scope="row">' + pill(a) + '</th>' + order.map(function (_, j) {
          var v = f[i] && f[i][j];
          var a2 = ok(v) ? Math.max(0.06, Math.min(1, v)) : 0;
          return '<td class="mrx-num" style="background:rgba(69,81,47,' + a2.toFixed(2) + ');color:' + (a2 > 0.55 ? '#fffdf4' : '#37382f') + '">' + (ok(v) ? num(v * 100, 1) + '%' : '—') + '</td>';
        }).join('') + '</tr>';
      }).join('') + '</tbody></table></div>';
    var hm = deck('과거 전이 빈도 (일 단위)', '<p class="mrx-cap">행 국면이던 날의 다음 거래일에 열 국면이었던 비율입니다. 앞으로의 확률이 아닙니다.</p>' + heat);
    var sm = deck('국면별 특성', '<p class="mrx-cap">과거 해당 국면이었던 날들의 KOSPI 일간 수익률로 계산한 관측치입니다.</p>' +
      table(['국면', '일수 비중', '구간 수', '평균 지속', '연환산 수익률', '연환산 변동성', '평균 VIX'], (s.summary || []).map(function (r) {
        return '<tr><td>' + pill(r.regime_code, r.regime_name) + '</td><td class="mrx-num">' + prob(r.day_share, 1) + '</td><td class="mrx-num">' + num(r.n_runs, 0) +
          '</td><td class="mrx-num">' + (ok(r.avg_run_days) ? num(r.avg_run_days, 0) + '일' : '—') + '</td><td class="mrx-num">' + (ok(r.ann_return_pct) ? signed(r.ann_return_pct, 2) + '%' : '—') +
          '</td><td class="mrx-num">' + (ok(r.ann_vol_pct) ? num(r.ann_vol_pct, 2) + '%' : '—') + '</td><td class="mrx-num">' + (ok(r.avg_vix) ? num(r.avg_vix, 2) + 'pt' : '—') + '</td></tr>';
      }), { num: [1, 2, 3, 4, 5, 6], label: '국면별 특성' }) +
      '<p class="mrx-cap">이 모델은 주로 변동성 수준으로 국면을 나눕니다. 그래서 폭락장의 연환산 수익률이 플러스로 나오는 기간이 있을 수 있습니다.</p>');
    var runs = (s.runs || []).slice().reverse().map(function (r) {
      return '<tr' + (r.is_current ? ' class="mrx-row-current"' : '') + '><td>' + pill(r.regime_code, r.regime_name) + (r.is_current ? ' <span class="mrx-tag">현재</span>' : '') + '</td><td>' + day(r.start) + '</td><td>' + day(r.end) +
        '</td><td class="mrx-num">' + num(r.days, 0) + '일</td><td class="mrx-num">' + (ok(r.kospi_change_pct) ? signed(r.kospi_change_pct, 2) + '%' : '—') + '</td><td>' + basisText(r.label_basis) + '</td></tr>';
    });
    var rl = deck('국면 구간 목록 (최근 순)', table(['국면', '시작', '종료', '지속', '구간 KOSPI 변화', '구분'], runs, { num: [3, 4], label: '국면 구간 목록' }) +
      '<p class="mrx-cap">구간 KOSPI 변화는 그 국면이 이어진 동안의 과거 실제 변화입니다. 다음 국면을 알려 주지 않습니다.</p>');
    return tl + '<div class="mrx-grid">' + hm + sm + '</div>' + rl;
  }

  function similarTab(s) {
    var sim = s.similar || {}, nbs = sim.neighbors || [];
    var rows = nbs.map(function (n, i) {
      var on = i === state.selected;
      return '<tr class="mrx-row-btn" tabindex="0" role="button" aria-pressed="' + on + '" data-mrx-select="' + i + '"><td class="mrx-num">' + esc(n.rank) + '</td><td>' + day(n.date) +
        '</td><td>' + pill(n.regime_code, n.regime_name) + '</td><td class="mrx-num">' + num(n.regime_run_days, 0) + '일</td><td class="mrx-num">' + num(n.distance, 2) + '</td></tr>';
    });
    var left = deck('현재와 비슷했던 과거 시기 (기준일 ' + day(sim.asof || s.as_of) + ')',
      '<p class="mrx-cap">행을 누르면 오른쪽에서 지표를 비교합니다. 거리가 작을수록 비슷합니다. 이후 수익률은 표시하지 않습니다.</p>' +
      table(['순위', '날짜', '당시 국면', '당시 국면 지속', '거리'], rows, { num: [0, 3, 4], label: '유사 시기 상위 목록' }) +
      (sim.method ? '<p class="mrx-cap">' + esc(sim.method) + '</p>' : ''));
    var nb = nbs[state.selected] || nbs[0];
    var right = deck('지표 비교 (표준화 값, σ)',
      '<div class="mrx-legend"><span><i class="mrx-sw mrx-sw-round" style="background:#37382f"></i>현재 ' + day(sim.asof || s.as_of) + '</span>' +
      '<span><i class="mrx-sw mrx-sw-round" style="background:#b0731f"></i>' + (nb ? '과거 ' + day(nb.date) : '—') + '</span></div>' +
      '<div class="mrx-chart" data-mrx-chart="dots"></div><p class="mrx-cap">0은 과거 전체 평균, ±1은 1표준편차입니다. ±3 밖의 값은 끝에 붙여 표시합니다.</p>');
    return '<div class="mrx-grid">' + left + right + '</div>';
  }

  function modelTab(s) {
    var v = s.validation || {}, md = s.model || {}, q = s.quality || {}, dv = s.data_version || {};
    var ev = deck('알려진 하락 구간 포착', '<p class="mrx-cap">분석자가 지정한 참고 구간입니다. 학습에는 쓰지 않습니다.</p>' +
      table(['구간', '기간', '폭락장 판정 비율', '평균 폭락장 확률'], (v.events || []).map(function (e) {
        return '<tr><td>' + esc(e.name) + '</td><td>' + day(e.start) + ' – ' + day(e.end) + '</td><td class="mrx-num">' + prob(e.bear_share, 1) + '</td><td class="mrx-num">' + prob(e.mean_p_bear, 1) + '</td></tr>';
      }), { num: [2, 3], label: '알려진 하락 구간 포착' }));
    var st = v.stability || {}, sil = v.silhouette || {}, knn = v.knn_regime_agreement || {};
    var mt = deck('검증 지표', kv([
      ['실시간 판정 시작', day(v.oos_start) + (ok(v.oos_days) ? ' (' + num(v.oos_days, 0) + '거래일)' : '')],
      ['연간 국면 전환', ok(st.label_switches_per_year) ? num(st.label_switches_per_year, 2) + '회' + (ok(st.raw_argmax_switches_per_year) ? ' (확인 규칙 적용 전 ' + num(st.raw_argmax_switches_per_year, 2) + '회)' : '') : '—'],
      ['실시간 vs 사후 추정 일치', prob(v.filtered_vs_smoothed_agreement, 1)],
      ['유사 시기 국면 일치율', ok(knn.mean) ? prob(knn.mean, 1) + (ok(knn.random_baseline) ? ' (무작위 기준 ' + prob(knn.random_baseline, 1) + ')' : '') : '—'],
      ['실루엣 점수 HMM / GMM', ok(sil.hmm) ? num(sil.hmm, 3) + ' / ' + num(sil.gmm, 3) : '—']
    ]) + (sil.note ? '<p class="mrx-cap">' + esc(sil.note) + '</p>' : ''));
    var mc = deck('모델', kv([
      ['방법', md.method], ['모델 버전', md.model_version], ['국면 수', md.n_states],
      ['입력 지표', (md.features || []).join(', ')], ['학습 기준일', day(md.trained_through)],
      ['재학습 주기', ok(md.refit_every_days) ? md.refit_every_days + '거래일' + (ok(md.n_refits) ? ' · 누적 ' + md.n_refits + '회' : '') : '—'],
      ['국면 확정 규칙', ok(md.label_threshold) ? '새 국면 확률 ' + prob(md.label_threshold) + ' 이상이 ' + (md.label_confirm_days || '—') + '일 연속일 때 전환' : '—']
    ]));
    var warn = (q.warnings || []).map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('');
    var dc = deck('데이터', kv([
      ['원천', (dv.gold_table || 'gold_stress_daily') + ' (' + (s.data_mode === 'synthetic_fixture' ? '합성 샘플' : 'Fabric Gold') + ')'],
      ['Gold 버전', dv.gold_snapshot_version || '—'],
      ['기간', day(q.first_date) + ' – ' + day(q.last_date) + (ok(q.dates_usable) ? ' (' + num(q.dates_usable, 0) + '일 사용)' : '')],
      ['종목 수', Array.isArray(q.assets) ? q.assets.length + '개' : '—'],
      ['제외한 날', ok(q.dates_excluded) ? num(q.dates_excluded, 0) + '일' : '—'],
      ['스냅샷 버전', s.snapshot_version || '—']
    ]) + (warn ? '<p class="mrx-cap mrx-warn-title">데이터 품질 경고</p><ul class="mrx-warn">' + warn + '</ul>' : ''));
    return '<div class="mrx-grid">' + ev + mt + '</div><div class="mrx-grid">' + mc + dc + '</div>';
  }

  // ---------------------------------------------------------------- 차트 (SVG)
  var SVGNS = 'http://www.w3.org/2000/svg';
  function sv(tag, attrs, parent) {
    var n = document.createElementNS(SVGNS, tag);
    for (var k in attrs) if (attrs[k] != null) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function niceTicks(lo, hi, n) {
    if (!(hi > lo)) return [lo];
    var span = hi - lo, step = Math.pow(10, Math.floor(Math.log10(span / n))), err = span / n / step;
    step *= err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1;
    var out = [];
    for (var v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }
  function segments(rows, key) {
    var out = [], s = 0;
    for (var i = 1; i <= rows.length; i++) if (i === rows.length || rows[i][key] !== rows[s][key]) { out.push({ from: s, to: i - 1, value: rows[s][key] }); s = i; }
    return out;
  }
  function timeTicks(rows, maxTicks) {
    var t = [], prev = null;
    rows.forEach(function (r, i) { var y = r.date.slice(0, 4); if (y !== prev) { if (prev !== null) t.push({ i: i, label: y }); prev = y; } });
    if (t.length < 2) {
      t = []; prev = null;
      rows.forEach(function (r, i) { var m = r.date.slice(0, 7); if (m !== prev) { if (prev !== null) t.push({ i: i, label: r.date.slice(2, 4) + '.' + r.date.slice(5, 7) }); prev = m; } });
    }
    var step = Math.max(1, Math.ceil(t.length / Math.max(1, maxTicks)));
    return t.filter(function (_, k) { return k % step === 0; });
  }
  function frame(box, h) {
    box.innerHTML = '';
    var w = Math.max(280, Math.floor(box.clientWidth));
    var svg = sv('svg', { width: w, height: h, viewBox: '0 0 ' + w + ' ' + h, class: 'mrx-svg', role: 'img' }, box);
    var tip = document.createElement('div'); tip.className = 'mrx-tip'; tip.hidden = true; box.appendChild(tip);
    return { svg: svg, w: w, h: h, tip: tip };
  }
  function showTip(f, html, x, y) {
    f.tip.innerHTML = html; f.tip.hidden = false;
    var tw = f.tip.offsetWidth, th = f.tip.offsetHeight;
    f.tip.style.left = Math.max(4, Math.min(f.w - tw - 4, x + 12)) + 'px';
    f.tip.style.top = Math.max(4, Math.min(f.h - th - 4, y - th - 8)) + 'px';
  }
  function tipRows(title, pairs) {
    return '<strong>' + esc(title) + '</strong>' + pairs.map(function (p) { return '<span>' + esc(p[0]) + ' <b>' + esc(p[1]) + '</b></span>'; }).join('');
  }
  function rangeRows(s) {
    var h = s.history || [];
    if (state.range === 'all') return h;
    var end = new Date(s.as_of + 'T00:00:00Z'); end.setUTCFullYear(end.getUTCFullYear() - state.range);
    var iso = end.toISOString().slice(0, 10);
    return h.filter(function (r) { return r.date >= iso; });
  }
  function indexChart(box, rows) {
    var f = frame(box, 300), m = { l: 64, r: 16, t: 12, b: 28 }, iw = f.w - m.l - m.r, ih = f.h - m.t - m.b, svg = f.svg;
    svg.setAttribute('aria-label', 'KOSPI 종가와 국면 구간');
    var vals = rows.map(function (r) { return r.kospi; }).filter(ok);
    if (!vals.length) { box.insertAdjacentHTML('afterbegin', '<p class="mrx-cap">표시할 이력이 없습니다.</p>'); return; }
    var lo = Math.min.apply(null, vals), hi = Math.max.apply(null, vals), pad = (hi - lo) * 0.06 || 1;
    var y0 = lo - pad, y1 = hi + pad, n = rows.length;
    var X = function (i) { return m.l + (n < 2 ? 0 : (i / (n - 1)) * iw); };
    var Y = function (v) { return m.t + ih - ((v - y0) / (y1 - y0)) * ih; };
    var defs = sv('defs', {}, svg);
    var pat = sv('pattern', { id: 'mrx-hatch', width: 6, height: 6, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, defs);
    sv('line', { x1: 0, y1: 0, x2: 0, y2: 6, stroke: '#5d5b4f', 'stroke-width': 1, 'stroke-opacity': 0.35 }, pat);
    var half = n > 1 ? iw / (n - 1) / 2 : 0;
    segments(rows, 'regime').forEach(function (sg) {
      sv('rect', { x: X(sg.from) - half, y: m.t, width: Math.max(1, X(sg.to) - X(sg.from) + 2 * half), height: ih, fill: COLOR[sg.value] || '#ccc', 'fill-opacity': 0.2 }, svg);
    });
    segments(rows, 'basis').forEach(function (sg) {
      if (sg.value === 'is') sv('rect', { x: X(sg.from) - half, y: m.t, width: Math.max(1, X(sg.to) - X(sg.from) + 2 * half), height: ih, fill: 'url(#mrx-hatch)' }, svg);
    });
    niceTicks(y0, y1, 5).forEach(function (t) {
      sv('line', { x1: m.l, x2: m.l + iw, y1: Y(t), y2: Y(t), class: 'mrx-grid-line' }, svg);
      var tx = sv('text', { x: m.l - 8, y: Y(t) + 4, 'text-anchor': 'end', class: 'mrx-axis' }, svg); tx.textContent = num(t, 0);
    });
    timeTicks(rows, Math.floor(iw / 80)).forEach(function (t) {
      sv('line', { x1: X(t.i), x2: X(t.i), y1: m.t + ih, y2: m.t + ih + 4, class: 'mrx-axis-tick' }, svg);
      var tx = sv('text', { x: X(t.i), y: f.h - 8, 'text-anchor': 'middle', class: 'mrx-axis' }, svg); tx.textContent = t.label;
    });
    var d = '', pen = false;
    rows.forEach(function (r, i) { if (ok(r.kospi)) { d += (pen ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(r.kospi).toFixed(1); pen = true; } else pen = false; });
    sv('path', { d: d, fill: 'none', stroke: '#37382f', 'stroke-width': 1.6, 'stroke-linejoin': 'round' }, svg);
    var cross = sv('line', { y1: m.t, y2: m.t + ih, class: 'mrx-cross', visibility: 'hidden' }, svg);
    var mk = sv('circle', { r: 4, fill: '#37382f', stroke: '#fffdf4', 'stroke-width': 1.5, visibility: 'hidden' }, svg);
    var hit = sv('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent' }, svg);
    hit.addEventListener('pointermove', function (ev) {
      var bb = svg.getBoundingClientRect(), x = ev.clientX - bb.left;
      var i = Math.max(0, Math.min(n - 1, Math.round((x - m.l) / Math.max(1, iw) * (n - 1)))), r = rows[i];
      cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('visibility', 'visible');
      if (ok(r.kospi)) { mk.setAttribute('cx', X(i)); mk.setAttribute('cy', Y(r.kospi)); mk.setAttribute('visibility', 'visible'); }
      showTip(f, tipRows(day(r.date), [['KOSPI', num(r.kospi, 2)], ['국면', NAME[r.regime] || '—'], ['판정', r.basis === 'is' ? '초기 학습 구간' : '실시간 판정']]), X(i), ev.clientY - bb.top);
    });
    hit.addEventListener('pointerleave', function () { f.tip.hidden = true; cross.setAttribute('visibility', 'hidden'); mk.setAttribute('visibility', 'hidden'); });
  }
  function probChart(box, rows) {
    var f = frame(box, 260), m = { l: 48, r: 12, t: 10, b: 28 }, iw = f.w - m.l - m.r, ih = f.h - m.t - m.b, svg = f.svg, n = rows.length;
    svg.setAttribute('aria-label', '최근 120거래일 국면별 확률');
    if (!n) return;
    var X = function (i) { return m.l + (n < 2 ? 0 : (i / (n - 1)) * iw); };
    var Y = function (v) { return m.t + ih - v * ih; };
    var cum = rows.map(function () { return 0; });
    ORDER.forEach(function (code) {
      var key = 'p_' + code, top = '', bottom = '';
      rows.forEach(function (r, i) { var v = ok(r[key]) ? r[key] : 0; top += (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(cum[i] + v).toFixed(1); });
      for (var i = n - 1; i >= 0; i--) bottom += 'L' + X(i).toFixed(1) + ' ' + Y(cum[i]).toFixed(1);
      sv('path', { d: top + bottom + 'Z', fill: COLOR[code], 'fill-opacity': 0.78 }, svg);
      rows.forEach(function (r, i) { cum[i] += ok(r[key]) ? r[key] : 0; });
    });
    [0, 0.5, 1].forEach(function (t) {
      sv('line', { x1: m.l, x2: m.l + iw, y1: Y(t), y2: Y(t), class: 'mrx-grid-line mrx-grid-over' }, svg);
      var tx = sv('text', { x: m.l - 8, y: Y(t) + 4, 'text-anchor': 'end', class: 'mrx-axis' }, svg); tx.textContent = (t * 100) + '%';
    });
    timeTicks(rows, Math.floor(iw / 70)).forEach(function (t) {
      var tx = sv('text', { x: X(t.i), y: f.h - 8, 'text-anchor': 'middle', class: 'mrx-axis' }, svg); tx.textContent = t.label;
    });
    var cross = sv('line', { y1: m.t, y2: m.t + ih, class: 'mrx-cross', visibility: 'hidden' }, svg);
    var hit = sv('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent' }, svg);
    hit.addEventListener('pointermove', function (ev) {
      var bb = svg.getBoundingClientRect(), x = ev.clientX - bb.left;
      var i = Math.max(0, Math.min(n - 1, Math.round((x - m.l) / Math.max(1, iw) * (n - 1)))), r = rows[i];
      cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('visibility', 'visible');
      showTip(f, tipRows(day(r.date), ORDER.map(function (k) { return [NAME[k], prob(r['p_' + k])]; })), X(i), ev.clientY - bb.top);
    });
    hit.addEventListener('pointerleave', function () { f.tip.hidden = true; cross.setAttribute('visibility', 'hidden'); });
  }
  function timelineChart(box, runs, history) {
    var f = frame(box, 86), m = { l: 8, r: 8, t: 8, b: 28 }, iw = f.w - m.l - m.r, ih = f.h - m.t - m.b, svg = f.svg, n = history.length;
    svg.setAttribute('aria-label', '전체 기간 국면 타임라인');
    if (!n) return;
    var idx = {}; history.forEach(function (r, i) { idx[r.date] = i; });
    var X = function (i) { return m.l + (i / Math.max(1, n - 1)) * iw; };
    runs.forEach(function (r) {
      var a = idx[r.start], b = idx[r.end];
      if (a == null || b == null) return;
      var x0 = X(a), w = Math.max(1.5, X(b) - x0 + iw / Math.max(1, n - 1));
      var rect = sv('rect', { x: x0, y: m.t, width: w, height: ih, fill: COLOR[r.regime_code] || '#ccc' }, svg);
      rect.addEventListener('pointermove', function (ev) {
        var bb = svg.getBoundingClientRect();
        showTip(f, tipRows(r.regime_name || NAME[r.regime_code], [['기간', day(r.start) + ' – ' + day(r.end)], ['지속', num(r.days, 0) + '일'], ['구분', basisText(r.label_basis)]]), ev.clientX - bb.left, ev.clientY - bb.top);
      });
      rect.addEventListener('pointerleave', function () { f.tip.hidden = true; });
    });
    timeTicks(history, Math.floor(iw / 70)).forEach(function (t) {
      var tx = sv('text', { x: X(t.i), y: f.h - 8, 'text-anchor': 'middle', class: 'mrx-axis' }, svg); tx.textContent = t.label;
    });
  }
  function dotChart(box, features, query, nb) {
    features = features || [];
    var rowH = 30, f = frame(box, features.length * rowH + 44), lab = Math.min(230, Math.floor(f.w * 0.38));
    var m = { l: lab, r: 18, t: 10, b: 30 }, iw = f.w - m.l - m.r, svg = f.svg, lim = 3;
    svg.setAttribute('aria-label', '현재와 선택한 과거 시기의 지표 비교');
    var X = function (z) { return m.l + ((Math.max(-lim, Math.min(lim, z)) + lim) / (2 * lim)) * iw; };
    [-3, -2, -1, 0, 1, 2, 3].forEach(function (t) {
      sv('line', { x1: X(t), x2: X(t), y1: m.t, y2: f.h - m.b, class: t === 0 ? 'mrx-grid-line mrx-grid-zero' : 'mrx-grid-line' }, svg);
      var tx = sv('text', { x: X(t), y: f.h - 10, 'text-anchor': 'middle', class: 'mrx-axis' }, svg); tx.textContent = (t > 0 ? '+' : '') + t + 'σ';
    });
    features.forEach(function (ft, k) {
      var y = m.t + k * rowH + rowH / 2, q = query ? query[ft.id] : null, v = nb && nb.z ? nb.z[ft.id] : null;
      var tx = sv('text', { x: m.l - 10, y: y + 4, 'text-anchor': 'end', class: 'mrx-axis mrx-axis-label' }, svg); tx.textContent = ft.label;
      if (ok(q) && ok(v)) sv('line', { x1: X(q), x2: X(v), y1: y, y2: y, stroke: '#8c8676', 'stroke-width': 2 }, svg);
      [[v, '#b0731f', nb ? '과거 ' + day(nb.date) : '과거'], [q, '#37382f', '현재']].forEach(function (pt) {
        if (!ok(pt[0])) return;
        var c = sv('circle', { cx: X(pt[0]), cy: y, r: 6, fill: pt[1], stroke: '#fffdf4', 'stroke-width': 1.5 }, svg);
        c.addEventListener('pointermove', function (ev) { var bb = svg.getBoundingClientRect(); showTip(f, tipRows(ft.label, [[pt[2], signed(pt[0], 2) + 'σ']]), ev.clientX - bb.left, ev.clientY - bb.top); });
        c.addEventListener('pointerleave', function () { f.tip.hidden = true; });
      });
    });
  }
  function drawCharts() {
    var root = state.root, s = state.snap;
    if (!root || !s || !root.isConnected) return;
    root.querySelectorAll('[data-mrx-chart]').forEach(function (box) {
      var kind = box.getAttribute('data-mrx-chart');
      if (kind === 'index') indexChart(box, rangeRows(s));
      else if (kind === 'prob') probChart(box, (s.history || []).slice(-120));
      else if (kind === 'timeline') timelineChart(box, s.runs || [], s.history || []);
      else if (kind === 'dots') { var sim = s.similar || {}; dotChart(box, sim.features, sim.query_z, (sim.neighbors || [])[state.selected]); }
    });
  }

  // ---------------------------------------------------------------- 그리기와 이벤트
  function railInset() {
    var p = panel(), rail = document.querySelector('.gx-rail');
    if (!p || !rail) return 0;
    var right = 0;
    rail.querySelectorAll('button').forEach(function (b) { if (b.getClientRects().length) right = Math.max(right, b.getBoundingClientRect().right); });
    return Math.max(0, Math.ceil(right + 12 - p.getBoundingClientRect().left));
  }
  function paint() {
    var root = state.root;
    if (!root || !root.isConnected) return;
    root.style.setProperty('--mrx-inset', railInset() + 'px');
    root.querySelector('.mrx-head').innerHTML = headHTML();
    root.querySelector('.mrx-status').innerHTML = statusHTML();
    var body = root.querySelector('.mrx-body');
    body.setAttribute('aria-labelledby', 'mrx-tab-' + state.tab);
    body.innerHTML = bodyHTML();
    drawCharts();
  }
  function setTab(t, focus) {
    var p = panel();
    if (p) state.scroll[state.tab] = p.scrollTop;
    state.tab = t; paint();
    if (p) p.scrollTop = 0;
    if (focus) { var b = state.root.querySelector('[data-mrx-tab="' + t + '"]'); if (b) b.focus(); }
  }
  function closePanel() {
    var b = document.querySelector('[data-gx=market-regime-shortcut]');
    if (b) b.click();
  }
  function onClick(e) {
    var t = e.target.closest('[data-mrx-tab],[data-mrx-range],[data-mrx-select],[data-mrx-action]');
    if (!t || !state.root.contains(t)) return;
    if (t.hasAttribute('data-mrx-tab')) setTab(t.getAttribute('data-mrx-tab'));
    else if (t.hasAttribute('data-mrx-range')) { var r = t.getAttribute('data-mrx-range'); state.range = r === 'all' ? 'all' : Number(r); paint(); }
    else if (t.hasAttribute('data-mrx-select')) { state.selected = Number(t.getAttribute('data-mrx-select')) || 0; paint(); var row = state.root.querySelector('[data-mrx-select="' + state.selected + '"]'); if (row) row.focus(); }
    else if (t.getAttribute('data-mrx-action') === 'reload') load(true);
    else if (t.getAttribute('data-mrx-action') === 'close') closePanel();
  }
  function onKey(e) {
    var tab = e.target.closest && e.target.closest('[data-mrx-tab]');
    if (tab && (e.key === 'ArrowRight' || e.key === 'ArrowLeft' || e.key === 'Home' || e.key === 'End')) {
      e.preventDefault();
      var keys = TABS.map(function (x) { return x[0]; }), i = keys.indexOf(state.tab);
      i = e.key === 'Home' ? 0 : e.key === 'End' ? keys.length - 1 : (i + (e.key === 'ArrowRight' ? 1 : -1) + keys.length) % keys.length;
      setTab(keys[i], true);
      return;
    }
    var row = e.target.closest && e.target.closest('[data-mrx-select]');
    if (row && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); row.click(); }
  }
  function mount(h) {
    if (state.ro) { state.ro.disconnect(); state.ro = null; }
    var root = document.createElement('div');
    root.className = 'mrx-root';
    root.innerHTML = '<div class="mrx-head"></div><div class="mrx-status"></div><div class="mrx-body" id="mrx-tabpanel" role="tabpanel"></div>';
    h.appendChild(root);
    state.root = root;
    root.addEventListener('click', onClick);
    root.addEventListener('keydown', onKey);
    var p = panel();
    if (p && !p.__mrxScroll) { p.__mrxScroll = true; p.addEventListener('scroll', function () { state.scroll[state.tab] = p.scrollTop; }, { passive: true }); }
    paint();
    if (p && state.scroll[state.tab]) p.scrollTop = state.scroll[state.tab];
    if (typeof ResizeObserver === 'function') {
      state.lastWidth = root.clientWidth;
      state.ro = new ResizeObserver(function () {
        var w = root.clientWidth;
        if (Math.abs(w - state.lastWidth) < 16) return;
        state.lastWidth = w;
        clearTimeout(state.rt);
        state.rt = setTimeout(function () { root.style.setProperty('--mrx-inset', railInset() + 'px'); drawCharts(); }, 120);
      });
      state.ro.observe(root);
    }
    load(false);
  }
  function ensure() {
    var h = host();
    if (!h) {
      if (state.root && !state.root.isConnected) { if (state.ro) state.ro.disconnect(); state.ro = null; state.root = null; }
      return;
    }
    if (state.root && state.root.isConnected && h.contains(state.root)) return;
    mount(h);
  }

  var queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(function () { queued = false; ensure(); });
  }
  function start() {
    new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
    window.addEventListener('resize', function () { if (state.root && state.root.isConnected) state.root.style.setProperty('--mrx-inset', railInset() + 'px'); });
    ensure();
  }
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
