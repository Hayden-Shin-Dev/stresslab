/* WHAT IF · retro-fx: interactive, functional pixel feedback.
   Every effect is a response to a user action or a real state change; nothing
   loops for decoration. State is read from the DOM only — this module never
   changes analysis input except through the same input events a user types. */
(function () {
  'use strict';
  if (window.__whatIfRetroFx) return;
  window.__whatIfRetroFx = true;

  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  const calm = () => reduce.matches;
  const SCOPE = '.ws-scenario-overlay,.handoff-floating,.handoff-popup,.handoff-taskbar,.handoff-archive';

  /* 1. Pixel burst on button press ------------------------------------ */
  addEventListener('pointerdown', (e) => {
    if (calm() || e.button !== 0) return;
    const btn = e.target.closest('button,[role=button],.fig-shared-agent-option,.handoff-stock-options label');
    if (!btn || btn.disabled || !btn.closest(SCOPE)) return;
    const colors = ['#f2c35b', '#fffbea', '#3d6e8e', '#c8902c'];
    for (let i = 0; i < 8; i++) {
      const p = document.createElement('i');
      p.className = 'rm-burst';
      p.style.left = e.clientX - 2 + 'px';
      p.style.top = e.clientY - 2 + 'px';
      p.style.background = colors[i % colors.length];
      document.body.append(p);
      const a = (Math.PI * 2 * i) / 8, d = 14 + (i % 2) * 8;
      const dx = Math.round((Math.cos(a) * d) / 2) * 2, dy = Math.round((Math.sin(a) * d) / 2) * 2;
      p.animate(
        [{ transform: 'translate(0,0)', opacity: 1 }, { transform: `translate(${dx}px,${dy}px)`, opacity: 0 }],
        { duration: 280, easing: 'steps(4,end)' }
      ).onfinish = () => p.remove();
    }
  }, { passive: true });

  /* 2. Drag-to-scrub on shock unit labels (bp / % / pt) --------------- */
  let tip = null;
  function showTip(x, y, text) {
    if (!tip) { tip = document.createElement('div'); tip.className = 'rm-scrub-tip'; tip.setAttribute('aria-hidden', 'true'); document.body.append(tip); }
    tip.style.left = x + 'px'; tip.style.top = y + 'px'; tip.textContent = text;
  }
  function hideTip() { tip?.remove(); tip = null; }
  function decimals(step) { const s = String(step); return s.includes('.') ? s.split('.')[1].length : 0; }

  addEventListener('pointerdown', (e) => {
    const unit = e.target.closest('.fig-shock-input b');
    if (!unit || e.button !== 0) return;
    const input = unit.parentElement.querySelector('input[type=number]');
    if (!input || input.disabled) return;
    e.preventDefault();
    const step = Number(input.step) || 1, places = decimals(step);
    const start = Number(input.value) || 0, x0 = e.clientX;
    unit.setPointerCapture(e.pointerId);
    let last = input.value;
    const move = (ev) => {
      const ticks = Math.round((ev.clientX - x0) / 6);
      const next = (start + ticks * step).toFixed(places);
      const r = unit.getBoundingClientRect();
      const sign = Number(next) > 0 ? '+' : '';
      showTip(r.left + r.width / 2, r.top, `${sign}${next} ${unit.textContent}`);
      if (next === last) return;
      last = next;
      input.value = next;
      input.dispatchEvent(new Event('input', { bubbles: true }));
    };
    const up = () => {
      unit.removeEventListener('pointermove', move);
      hideTip();
      if (String(start) !== last) input.dispatchEvent(new Event('change', { bubbles: true }));
    };
    unit.addEventListener('pointermove', move);
    unit.addEventListener('pointerup', up, { once: true });
    unit.addEventListener('pointercancel', up, { once: true });
    move(e);
  });
  // Describe the gesture once units render; keyboard users keep native arrow keys.
  function labelUnits(root) {
    for (const b of root.querySelectorAll('.fig-shock-input b:not([data-rm-scrub])')) {
      b.dataset.rmScrub = '1';
      b.title = '좌우로 드래그해 값 조절 · 입력칸에서 ↑↓ 키도 가능';
    }
  }

  /* 3. Windows-98 style "zoom rect" from a taskbar button to its window -- */
  const TARGETS = [
    [/시나리오/, '.fig-main-panel'],
    [/AI Agent|자료/, '[data-handoff-panel=agent],.ws-side-panel'],
    [/포트폴리오/, '[data-handoff-panel=portfolio]'],
    [/결과 분석/, '.handoff-result-panel'],
  ];
  function zoom(from, el) {
    if (calm() || !el) return;
    const to = el.getBoundingClientRect();
    if (!to.width || !to.height) return;
    const r = document.createElement('div');
    r.className = 'rm-zoom-rect';
    document.body.append(r);
    const box = (b) => ({ left: b.left + 'px', top: b.top + 'px', width: b.width + 'px', height: b.height + 'px' });
    r.animate([box(from), box(to)], { duration: 240, easing: 'steps(6,end)', fill: 'forwards' }).onfinish = () => r.remove();
  }
  addEventListener('click', (e) => {
    const btn = e.target.closest('.handoff-taskbar button');
    if (!btn) return;
    const from = btn.getBoundingClientRect();
    const hit = TARGETS.find(([re]) => re.test(btn.textContent));
    if (!hit) return;
    setTimeout(() => {
      const el = [...document.querySelectorAll(hit[1])].find((n) => n.offsetParent || n.getClientRects().length);
      zoom(from, el);
    }, 60);
  });

  /* 4. PLAY progress, result arrival toast ----------------------------- */
  let busy = false;
  function toast(text, isError) {
    document.querySelector('.rm-toast')?.remove();
    const t = document.createElement('div');
    t.className = 'rm-toast' + (isError ? ' is-error' : '');
    t.setAttribute('role', 'status');
    t.innerHTML = '<i aria-hidden="true"></i><span></span>';
    t.lastChild.textContent = text;
    document.body.append(t);
    setTimeout(() => t.remove(), 4200);
  }
  const kst = () => new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date());
  function syncBusy() {
    const status = document.querySelector('.ws-scenario-overlay .handoff-run-state [role=status]');
    const play = document.querySelector('.ws-scenario-overlay .fig-run-button');
    const text = status?.textContent || '';
    const now = /계산 중/.test(text);
    if (play) { play.classList.toggle('rm-busy', now); play.setAttribute('aria-busy', String(now)); }
    if (busy && !now) {
      if (/마지막 성공 결과/.test(text)) {
        toast(`새 결과 도착 · ${kst()} KST`);
        const chart = document.querySelector('.ws-scenario-overlay .fig-chart-panel');
        if (chart && !calm()) { chart.classList.remove('rm-arrive'); void chart.offsetWidth; chart.classList.add('rm-arrive'); }
      } else if (/실패|오류|다시 시도/.test(text)) {
        toast('계산 실패 · 이전 결과를 유지합니다', true);
      }
    }
    busy = now;
  }
  addEventListener('click', (e) => {
    const play = e.target.closest('.fig-run-button');
    if (!play || play.disabled) return;
    play.classList.add('rm-pressing');
    setTimeout(() => play.classList.remove('rm-pressing'), 140);
    // Some runs resolve between status repaints; treat the click as the start.
    busy = true;
    setTimeout(syncBusy, 30);
  });

  /* 5. Flash only the numeric cells whose value actually changed ------- */
  const seen = new Map();
  function cellKey(td) {
    const tr = td.closest('tr'), table = td.closest('table');
    if (!tr || !table) return null;
    const tableKey = table.className || table.closest('[class]')?.className || 't';
    const rowKey = tr.dataset.code || tr.dataset.assetId || tr.querySelector('th,td')?.textContent.trim() || tr.rowIndex;
    return tableKey + '|' + rowKey + '|' + td.cellIndex;
  }
  function scanCells(root) {
    for (const td of root.querySelectorAll('.ws-scenario-overlay td, .handoff-floating td, .fig-quote-row [class*=price]')) {
      const text = td.textContent.trim();
      if (!/\d/.test(text)) continue;
      const key = td.matches('td') ? cellKey(td) : 'q|' + (td.closest('[data-code]')?.dataset.code || '') + '|' + td.className;
      if (!key) continue;
      const prev = seen.get(key);
      seen.set(key, text);
      if (prev !== undefined && prev !== text && !calm()) {
        td.classList.remove('rm-flash'); void td.offsetWidth; td.classList.add('rm-flash');
      }
    }
  }

  /* 6. Taskbar tray clock --------------------------------------------- */
  function trayClock() {
    // A sibling, not a child: the status text must stay exactly what the app wrote.
    const bar = document.querySelector('.handoff-taskbar');
    if (!bar) return;
    let c = bar.querySelector(':scope>.rm-tray-clock');
    if (!c) { c = document.createElement('time'); c.className = 'rm-tray-clock'; c.setAttribute('aria-label', '현재 시각 KST'); bar.append(c); }
    const t = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date());
    if (c.textContent !== t) c.textContent = t;
  }
  setInterval(trayClock, 15000);

  /* 7. KRDS patterns layered on the existing workspace -----------------
     Every function below is idempotent: it only writes when the derived
     state differs from what is already in the DOM, so repaint observers
     never loop. None of them changes analysis input or request logic. */
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const statusText = () => $('.ws-scenario-overlay .fig-main-panel .handoff-run-state [role=status]')?.textContent || '';

  // 7a. The progress strip was removed from the scenario view.
  function steps() {
    $$('.ws-scenario-overlay .fig-main-panel > .rm-steps').forEach(el => el.remove());
  }

  // 7b. Focus moves into the analysis dialog when it opens (KRDS 모달 초점),
  //     and comes back to it when a repaint removes the focused node.
  let dialogOpen = false, focusInside = false;
  addEventListener('focusin', (e) => { focusInside = !!e.target.closest?.('.ws-scenario-overlay'); });
  function focusDialog() {
    // Only a rendered dialog counts as open (it can exist hidden in the DOM).
    const screen = $$('.ws-scenario-overlay .fig-scenario-screen[role=dialog]').find((n) => n.getClientRects().length && getComputedStyle(n).visibility !== 'hidden');
    const open = !!screen;
    const lost = document.activeElement === document.body && focusInside;
    if (open && (!dialogOpen || lost) && !screen.contains(document.activeElement)) {
      // Focus the dialog itself so the next Tab starts at Home, the first control.
      if (!screen.hasAttribute('tabindex')) screen.setAttribute('tabindex', '-1');
      screen.focus({ preventScroll: true });
    }
    dialogOpen = open;
  }

  // 7c. Shock fields (v1.4): the allowed range and unit live in an info icon
  //     next to each label; only a real error is printed under the field.
  //     Limits mirror the existing check in handoff-runtime.js run(); the
  //     request is still validated there, this only explains it in place.
  const LIMITS = { rate: [300, 'bp', 0], fx: [30, '%', 1], oil: [80, '%', 1], vix: [80, 'pt', 1] };
  const touched = new Set();
  let attempted = false;
  addEventListener('input', (e) => { const k = e.target?.dataset?.sim; if (k) touched.add(k); });
  function fieldHelp() {
    for (const input of $$('.ws-scenario-overlay .fig-main-panel input[data-sim]')) {
      const key = input.dataset.sim, lim = LIMITS[key];
      if (!lim) continue;
      const group = input.closest('.fig-shock-group');
      if (!group) continue;
      const range = `허용 범위 −${lim[0]} ~ +${lim[0]} ${lim[1]}`;
      const title = $(':scope > span:first-child', group);
      if (title && !$(':scope > .rm-lab', title)) {
        // Text and icon share one inline box so the icon follows the last word.
        title.id = 'rm-lab-' + key;
        const label = title.textContent.trim();
        const wrap = document.createElement('span');
        wrap.className = 'rm-lab';
        while (title.firstChild) wrap.append(title.firstChild);
        wrap.append(' ', infoButton(`${range} · 단위 ${lim[1]}. 오늘 대비 5거래일 누적 변화를 가정합니다.`, label + ' 도움말'));
        title.append(wrap);
      }
      let err = $(':scope > .rm-field-help', group);
      if (!err) {
        err = document.createElement('span');
        err.className = 'rm-field-help is-error';
        err.id = 'rm-help-' + key;
        group.append(err);
      }
      const raw = input.value.trim(), n = Number(raw);
      const bad = raw === '' ? '값을 입력해 주세요' : !Number.isFinite(n) ? '숫자로 입력해 주세요' : Math.abs(n) > lim[0] ? `${range}를 벗어났습니다` : '';
      const show = bad && (touched.has(key) || attempted);
      const text = show ? bad : '';
      if (err.textContent !== text) err.textContent = text;
      if (err.hidden !== !show) err.hidden = !show;
      if (title && input.getAttribute('aria-labelledby') !== title.id) input.setAttribute('aria-labelledby', title.id);
      const tipId = $('.rm-info', title || group)?.getAttribute('aria-describedby') || '';
      const desc = [tipId, show ? err.id : ''].filter(Boolean).join(' ');
      if (input.getAttribute('aria-describedby') !== desc) input.setAttribute('aria-describedby', desc);
      const inv = show ? 'true' : 'false';
      if (input.getAttribute('aria-invalid') !== inv) input.setAttribute('aria-invalid', inv);
    }
  }

  // 7d. After a refused PLAY, move focus to the place that needs fixing.
  addEventListener('click', (e) => {
    if (!e.target.closest('.fig-run-button')) return;
    attempted = true;
    setTimeout(() => {
      const panel = $('.ws-scenario-overlay .fig-main-panel');
      if (!panel) return;
      const msg = panel.textContent;
      if (/종목을 한 개 이상/.test(msg)) {
        // Open the collapsible target table first if the user had closed it.
        const toggle = $('.handoff-inputs .handoff-targets-toggle[aria-expanded=false]', panel);
        toggle?.click();
        const first = $('.handoff-inputs input[data-analysis-code]:not(:disabled)', panel);
        first?.scrollIntoView({ block: 'center' }); first?.focus({ preventScroll: true });
      } else if (/입력 범위를 확인/.test(msg)) {
        fieldHelp();
        const bad = $('input[data-sim][aria-invalid=true]', panel);
        bad?.scrollIntoView({ block: 'center' }); bad?.focus({ preventScroll: true });
      }
    }, 60);
  }, true);

  // 7e. Tables get a caption and header scope (KRDS 표 접근성).
  function tables() {
    for (const t of $$('.ws-scenario-overlay table, .handoff-floating table')) {
      if (!t.caption) {
        const title = t.closest('[class*=card],section,article')?.querySelector('h2,h3,header strong,strong')?.textContent.trim();
        const c = document.createElement('caption');
        c.className = 'rm-sr';
        c.textContent = (title ? title + ' · ' : '') + '수치 표';
        t.prepend(c);
      }
      for (const th of $$('thead th:not([scope])', t)) th.setAttribute('scope', 'col');
      for (const th of $$('tbody th:not([scope])', t)) th.setAttribute('scope', 'row');
    }
  }

  // 7f. Tabs point at the panel they control (KRDS 탭 aria-controls).
  function tabs() {
    const list = $('.ws-scenario-overlay .fig-live-market-tabs[role=tablist]');
    if (!list) return;
    const panel = list.parentElement && [...list.parentElement.children].find((n) => n !== list && n.matches('.fig-live-market-tablewrap,.fig-live-market-results,.fig-live-market-empty'));
    if (!panel) return;
    if (!panel.id) panel.id = 'rm-live-panel';
    if (panel.getAttribute('role') !== 'tabpanel') panel.setAttribute('role', 'tabpanel');
    $$('[role=tab]', list).forEach((tab, i) => {
      if (!tab.id) tab.id = 'rm-live-tab-' + i;
      if (tab.getAttribute('aria-controls') !== panel.id) tab.setAttribute('aria-controls', panel.id);
      if (tab.getAttribute('aria-selected') === 'true' && panel.getAttribute('aria-labelledby') !== tab.id) panel.setAttribute('aria-labelledby', tab.id);
    });
  }

  // 7g. Stock comparison box opens and closes vertically (KRDS 디스클로저).
  //     The chart repaints this box via innerHTML, so the open state lives here
  //     and is re-applied after every repaint. Closed by default; the selected
  //     count (n/4) and hint stay visible while closed.
  let compareOpen = false;
  try { compareOpen = sessionStorage.getItem('rm-compare-open') === '1'; } catch { /* storage unavailable */ }
  function compareBoxes() {
    $$('.ws-scenario-overlay .fig-stress-compare, .handoff-floating .fig-stress-compare').forEach((box, i) => {
      const opts = $(':scope > .fig-stress-compare-options', box);
      if (!opts) return;
      if (!opts.id) opts.id = 'rm-compare-options-' + i;
      let t = $(':scope > .rm-compare-toggle', box);
      if (!t) {
        t = document.createElement('button');
        t.type = 'button';
        t.className = 'rm-compare-toggle';
        const head = $(':scope > strong', box);
        head ? head.after(t) : box.prepend(t);
      }
      const label = compareOpen ? '종목 목록 접기 ▲' : '종목 목록 펼치기 ▼';
      if (t.textContent !== label) t.textContent = label;
      if (t.getAttribute('aria-expanded') !== String(compareOpen)) t.setAttribute('aria-expanded', String(compareOpen));
      if (t.getAttribute('aria-controls') !== opts.id) t.setAttribute('aria-controls', opts.id);
      box.classList.toggle('rm-collapsed', !compareOpen);
    });
  }
  addEventListener('click', (e) => {
    const t = e.target.closest('.rm-compare-toggle');
    if (!t) return;
    compareOpen = !compareOpen;
    try { sessionStorage.setItem('rm-compare-open', compareOpen ? '1' : '0'); } catch { /* storage unavailable */ }
    const box = t.closest('.fig-stress-compare');
    box?.classList.add('rm-animating');
    compareBoxes();
    setTimeout(() => box?.classList.remove('rm-animating'), 300);
  });

  /* 8. v1.4 · contextual help, grouping and state ------------------------ */

  // 8a. Info icon + tooltip (WCAG 2.2 SC 1.4.13). One floating tooltip lives
  //     on <body> so window and scroll boundaries never clip it. It opens on
  //     hover, keyboard focus or tap, stays while the pointer is on the icon or
  //     the tooltip itself, and closes on leave, blur, outside tap or Esc.
  //     Screen readers get the same text through aria-describedby.
  let tipSeq = 0;
  function infoButton(text, label) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'rm-info';
    b.dataset.tip = text;
    b.setAttribute('aria-label', label);
    b.textContent = 'i';
    return b;
  }
  function describeInfo(root = document) {
    for (const b of $$('.rm-info[data-tip]', root)) {
      let id = b.getAttribute('aria-describedby');
      let d = id && document.getElementById(id);
      if (!d) {
        id = 'rm-tipd-' + (++tipSeq);
        d = document.createElement('span');
        d.className = 'rm-sr';
        d.id = id;
        b.after(d);
        b.setAttribute('aria-describedby', id);
      }
      if (d.textContent !== b.dataset.tip) d.textContent = b.dataset.tip;
    }
  }
  let tipEl = null, tipFor = null, tipPinned = false, tipHide = 0;
  function tipNode() {
    if (!tipEl) {
      tipEl = document.createElement('div');
      tipEl.className = 'rm-tip';
      tipEl.setAttribute('aria-hidden', 'true'); // the trigger's aria-describedby carries the text
      tipEl.hidden = true;
      tipEl.addEventListener('pointerenter', () => clearTimeout(tipHide));
      tipEl.addEventListener('pointerleave', (e) => { if (!tipPinned && !(tipFor && tipFor.contains(e.relatedTarget))) hideTip(); });
      document.body.append(tipEl);
    }
    return tipEl;
  }
  function placeTip() {
    if (!tipFor || !tipEl || tipEl.hidden) return;
    if (!tipFor.isConnected || !tipFor.getClientRects().length) { hideTip(); return; }
    const r = tipFor.getBoundingClientRect(), t = tipEl.getBoundingClientRect(), m = 8;
    const below = r.bottom + 6 + t.height <= innerHeight - m;
    const top = below ? r.bottom + 6 : Math.max(m, r.top - 6 - t.height);
    const left = Math.min(Math.max(m, r.left + r.width / 2 - t.width / 2), innerWidth - t.width - m);
    tipEl.style.top = Math.round(top) + 'px';
    tipEl.style.left = Math.round(left) + 'px';
    tipEl.dataset.side = below ? 'below' : 'above';
  }
  function showTip(b, pinned = false) {
    clearTimeout(tipHide);
    const t = tipNode();
    if (tipFor && tipFor !== b) tipFor.removeAttribute('aria-expanded');
    tipFor = b; tipPinned = pinned;
    t.textContent = b.dataset.tip;
    t.hidden = false;
    b.setAttribute('aria-expanded', 'true');
    placeTip();
  }
  function hideTip() {
    clearTimeout(tipHide);
    if (tipEl) tipEl.hidden = true;
    tipFor?.removeAttribute('aria-expanded');
    tipFor = null; tipPinned = false;
  }
  // Leaving the icon toward the tooltip needs a short grace period; this is
  // not an auto-dismiss timer (the tooltip never closes while hovered).
  const softHide = () => { clearTimeout(tipHide); tipHide = setTimeout(() => { if (!tipPinned) hideTip(); }, 160); };
  addEventListener('pointerover', (e) => {
    const b = e.target.closest?.('.rm-info[data-tip]');
    if (b && e.pointerType === 'mouse' && tipFor !== b) showTip(b);
    else if (b && tipFor === b) clearTimeout(tipHide);
  });
  addEventListener('pointerout', (e) => {
    const b = e.target.closest?.('.rm-info[data-tip]');
    if (b && b === tipFor && !b.contains(e.relatedTarget) && !tipEl?.contains(e.relatedTarget)) softHide();
  });
  addEventListener('focusin', (e) => { const b = e.target.closest?.('.rm-info[data-tip]'); if (b) showTip(b); });
  addEventListener('focusout', (e) => { if (e.target === tipFor && !tipPinned) hideTip(); });
  addEventListener('click', (e) => {
    const b = e.target.closest?.('.rm-info[data-tip]');
    if (b) { e.preventDefault(); e.stopPropagation(); if (tipFor === b && tipPinned) hideTip(); else showTip(b, true); return; }
    if (tipFor && !tipEl?.contains(e.target)) hideTip();
  }, true);
  addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && tipFor && tipEl && !tipEl.hidden) { e.stopImmediatePropagation(); e.preventDefault(); hideTip(); }
  }, true);
  addEventListener('scroll', placeTip, true);
  addEventListener('resize', placeTip);

  // 8b. Disclosure state survives repaints (the panel is rebuilt via
  //     innerHTML). Keys are stable: per-answer evidence uses the message id.
  const openState = new Map();
  const detailsKey = (d) => d.matches('.ws-agent-dropdown') ? 'agents'
    : d.matches('.ws-applied') ? 'applied'
    : d.matches('.ws-used-evidence') ? 'ev:' + (d.dataset.msg || '')
    : d.matches('.handoff-agent-selection') ? 'agent-targets'
    : d.parentElement?.matches('.ws-context') ? 'analysis-info' : null;
  addEventListener('toggle', (e) => {
    const d = e.target;
    if (!(d instanceof HTMLDetailsElement)) return;
    const k = detailsKey(d);
    if (k) openState.set(k, d.open);
  }, true);
  function keepDetails() {
    for (const d of $$('.ws-side-panel details')) {
      const k = detailsKey(d);
      if (k && openState.has(k) && d.open !== openState.get(k)) d.open = openState.get(k);
    }
  }

  // 8c. Scenario groups get a small visible title and a group role so the
  //     settings → shocks → targets → run order reads as four units.
  const GROUPS = [
    ['.fig-model-row', '기본 분석 설정', 'rm-g-basic', ''],
    ['.scenario-shock-row > .fig-shock-panel', '충격 변수', 'rm-g-shock', '네 변수는 오늘 대비 5거래일 누적 변화 가정입니다. 단위 글자(bp · % · pt)를 좌우로 드래그해도 값을 조절할 수 있습니다.'],
  ];
  const groupOpen = new Map();
  function groups() {
    const panel = $('.ws-scenario-overlay .fig-main-panel');
    if (!panel) return;
    for (const [selector, label, id, tip] of GROUPS) {
      const group = panel.querySelector(':scope > ' + selector);
      if (!group || group.querySelector(':scope > .rm-group-title')) continue;
      const title = document.createElement('h3');
      title.className = 'rm-group-title';
      title.id = id;
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'rm-group-toggle';
      toggle.textContent = label;
      toggle.setAttribute('aria-label', label);
      toggle.setAttribute('aria-controls', id + '-body');
      group.id = id + '-body';
      group.classList.add('rm-flow-group');
      group.setAttribute('role', 'group');
      group.setAttribute('aria-labelledby', id);
      function show(open) {
        group.classList.toggle('rm-stage-collapsed', !open);
        toggle.setAttribute('aria-expanded', String(open));
      }
      show(groupOpen.get(id) ?? true);
      toggle.addEventListener('click', () => {
        const open = toggle.getAttribute('aria-expanded') !== 'true';
        groupOpen.set(id, open);
        show(open);
      });
      title.append(toggle);
      if (tip) title.append(infoButton(tip, label + ' 도움말'));
      group.prepend(title);
    }
  }

  // 8d. The run group shows the real current time (it used to be a fixed
  //     "06:21" placeholder labelled as simulation time).
  function runClock() {
    for (const c of $$('.ws-scenario-overlay .fig-clock')) {
      const t = new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date());
      if (c.textContent !== t) c.textContent = t;
      if (c.getAttribute('aria-label')) c.removeAttribute('aria-label');
      if (!c.dataset.rmClock) { c.dataset.rmClock = '1'; c.title = '현재 시각 (KST)'; }
    }
  }
  // The scenario no longer shows an unrelated wall clock beside the PLAY action.

  // 8e. The agent's linked analysis shows "미갱신" while the main window has
  //     unsent input changes; the linked conditions themselves stay as run.
  function linkStale() {
    const dirty = /입력 변경|미갱신/.test(statusText());
    for (const head of $$('.ws-zone-linked > .ws-zone-head')) {
      let chip = $(':scope > .ws-link-stale', head);
      if (dirty && !chip) {
        chip = document.createElement('span');
        chip.className = 'ws-link-stale';
        chip.innerHTML = '<b aria-hidden="true">!</b> 입력 변경 · 미갱신';
        const info = $(':scope > .rm-info', head);
        if (info) info.before(chip); else head.append(chip);
      } else if (!dirty && chip) chip.remove();
    }
  }

  /* Observe re-renders (the workspace repaints via innerHTML). ---------- */
  let queued = false;
  new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      labelUnits(document);
      syncBusy();
      scanCells(document);
      trayClock();
      steps();
      focusDialog();
      fieldHelp();
      groups();
      describeInfo();
      keepDetails();
      runClock();
      linkStale();
      placeTip();
      tables();
      tabs();
      compareBoxes();
    });
  }).observe(document.body, { subtree: true, childList: true, characterData: true });
})();
