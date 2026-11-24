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
    const status = document.querySelector('.ws-scenario-overlay .handoff-inputs [role=status]');
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
    });
  }).observe(document.body, { subtree: true, childList: true, characterData: true });
})();
