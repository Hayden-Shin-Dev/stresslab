/* Shared navigation and real SWA authentication for the existing analysis UI. */
window.WhatIfService = (() => {
  'use strict';
  const routes = [
    ['/app', '대시보드', 'home', 'dashboard'],
    ['/app/market', '시장 현황', 'chart', 'agent', 'chat', 'realtime'],
    ['/app/scenarios', '시나리오 분석', 'agent', 'agent', 'chat', 'scenario'],
    ['/app/documents', '문서 분석', 'file', 'agent', 'chat', 'document'],
    ['/app/news', '뉴스 분석', 'news', 'agent', 'chat', 'news'],
    ['/app/collaboration', '함께 분석', 'users', 'agent', 'collab'],
    ['/app/my-room', '마이 룸', 'file', 'myroom'],
    ['/app/minutes', '회의록', 'calendar', 'agent', 'minutes'],
    ['/app/portfolio', '내 보유 종목', 'chart', 'portfolio'],
    ['/app/settings', '계정 설정', 'settings', 'account', 'settings'],
    ['/app/profile', '내 프로필', 'users', 'account', 'profile'],
  ];
  const returnPaths = new Set([...routes.map(route => route[0]), '/2_intro', '/quote-monitor']);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[ch]));
  const safeReturn = value => {
    try {
      const url = new URL(value || '/app', location.origin);
      return url.origin === location.origin && returnPaths.has(url.pathname.replace(/\/$/, ''))
        ? url.pathname.replace(/\/$/, '') + url.search : '/app';
    } catch { return '/app'; }
  };
  async function principal() {
    const response = await fetch('/.auth/me', {cache: 'no-store', credentials: 'same-origin'});
    if (!response.ok) throw new Error('로그인 상태를 확인하지 못했습니다.');
    return (await response.json()).clientPrincipal;
  }
  function loginPath(target) { return '/login?returnTo=' + encodeURIComponent(safeReturn(target)); }
  async function requireUser() {
    const app = document.getElementById('app');
    app.innerHTML = '<div class="service-loading" role="status">로그인 상태를 확인하는 중입니다…</div>';
    try {
      const user = await principal();
      if (user?.userId && user.userRoles?.includes('authenticated')) return user;
      location.replace(loginPath(location.pathname + location.search));
    } catch {
      app.innerHTML = `<section class="service-auth-error"><h1>로그인 상태를 확인하지 못했습니다</h1><p>연결 상태를 확인한 후 다시 시도해 주세요.</p><button type="button" onclick="location.reload()">다시 시도</button><a href="${loginPath(location.pathname)}">로그인으로 이동</a></section>`;
    }
    return null;
  }
  async function startLogin() {
    const currentPath = location.pathname.replace(/\/$/, '') || '/';
    const defaultTarget = returnPaths.has(currentPath) && currentPath !== '/app'
      ? currentPath + location.search : location.pathname.startsWith('/app') ? location.pathname + location.search : '/2_intro';
    const target = safeReturn(new URLSearchParams(location.search).get('returnTo') || defaultTarget);
    const link = document.getElementById('sign-in');
    link.href = '/.auth/login/google?post_login_redirect_uri=' + encodeURIComponent(target);
    try {
      if (await principal()) { location.replace(target); return; }
      document.getElementById('login-status').textContent = 'Google 계정으로 로그인하고 분석 공간으로 이동하세요.';
    } catch {
      document.getElementById('login-status').textContent = '로그인 상태를 확인할 수 없습니다. 아래 버튼으로 로그인을 진행해 주세요.';
    }
  }
  function create({state: S, render, persist, pause, initRoom, stopMedia, icon}) {
    let ready = false, active = '', applying = false, portfolioCleanup = null;
    const signature = () => [S.screen, S.tab, S.sub, S.accountTab].join(':');
    let lastSignature = '';
    const current = () => routes.find(r => r[0] === active);
    function header() {
      return `<header class="topbar service-topbar"><a class="brand" href="/2_intro" aria-label="WHAT IF 서비스 소개">WHAT IF<span class="service-brand-dot"></span></a><span class="service-header-title">${esc(current()?.[1] || '페이지를 찾을 수 없습니다')}</span><div class="header-right"><a class="service-profile" href="/app/profile" data-service-route>${esc(S.profile.name)}</a><a class="service-signout" href="/.auth/logout?post_logout_redirect_uri=%2F">로그아웃</a></div></header>`;
    }
    function rail() {
      return `<aside class="left-rail service-nav"><span class="service-nav-label">WORKSPACE</span><nav aria-label="공통 메뉴">${routes.filter(r => r[0] !== '/app/profile').map(([url, label, glyph]) => `<a href="${url}" data-service-route class="service-nav-link ${active === url ? 'active' : ''}" ${active === url ? 'aria-current="page"' : ''}>${icon(glyph)}<span>${label}</span></a>`).join('')}</nav><a class="service-back" href="/2_intro">← 서비스 소개</a></aside>`;
    }
    function apply(path, historyMode = 'push') {
      pause(); stopMedia();
      portfolioCleanup?.(); portfolioCleanup = null;
      const url = new URL(path, location.origin);
      active = url.pathname.replace(/\/$/, '') || '/app';
      const route = current();
      applying = true;
      S.modal = null; S.accountOpen = false; S.drawer = false; S.detailPage = false; S.detailRunId = null;
      S.keepChatDOMNext = false; S.homeLayout = 'single';
      S.screen = route?.[3] || 'missing';
      if (S.screen === 'agent') { S.tab = route[4]; if (route[5]) S.sub = route[5]; }
      if (S.screen === 'account') S.accountTab = route[4];
      if (S.screen === 'myroom') initRoom();
      lastSignature = signature();
      if (historyMode !== 'none') history[historyMode + 'State']({}, '', active + url.search);
      document.title = (route?.[1] || '페이지 없음') + ' | WHAT IF';
      applying = false;
      persist(); render();
      window.scrollTo(0, 0);
    }
    function sync() {
      if (applying || signature() === lastSignature) return;
      // Existing in-screen controls keep their behavior and gain shareable URLs.
      const next = S.screen === 'agent' && S.tab === 'holdings' ? '/app/portfolio' :
        routes.find(r => r[3] === S.screen && (S.screen === 'account' ? r[4] === S.accountTab :
          S.screen !== 'agent' || r[4] === S.tab && (!r[5] || r[5] === S.sub)))?.[0];
      if (next && next !== active) {
        active = next; history.pushState({}, '', next);
        document.title = current()[1] + ' | WHAT IF';
      }
      if (S.screen === 'agent' && S.tab === 'holdings') S.screen = 'portfolio';
      lastSignature = signature();
    }
    function dashboard() {
      const recent = [...S.runs].reverse().slice(0, 4);
      return `<section class="service-dashboard"><div class="service-welcome"><span class="service-eyebrow">MY WORKSPACE</span><h1>${esc(S.profile.name)}님, 무엇을 분석할까요?</h1><p>시장 현황을 확인하고, 조건을 바꿔 분석을 시작하세요.</p><a class="service-primary" href="/app/scenarios" data-service-route>시나리오 분석 시작 →</a></div><div class="service-cards">${[
        ['/app/market', '시장 현황', '시장 상태와 종목별 흐름을 확인하세요.'],
        ['/app/portfolio', '내 보유 종목', '내 자산을 등록하고 관리하세요.'],
        ['/app/collaboration', '함께 분석', '같은 자료와 조건으로 분석을 이어가세요.'],
        ['/app/my-room', '마이 룸', '분석 기록과 개인 자료를 살펴보세요.'],
      ].map(([url, title, text]) => `<a class="service-card" href="${url}" data-service-route><h2>${title}<span>↗</span></h2><p>${text}</p></a>`).join('')}</div><section class="service-recent"><div class="service-section-heading"><h2>최근 분석</h2><a href="/app/scenarios" data-service-route>분석 화면 열기 →</a></div><p class="service-note">이 브라우저에 저장된 실행 기록입니다.</p>${recent.length ? `<ul>${recent.map(run => `<li><a href="/app/scenarios" data-service-route>${esc(run.targetLabel || '시장 분석')}</a><span>${esc(new Date(run.at).toLocaleString('ko-KR', {timeZone:'Asia/Seoul'}))}</span></li>`).join('')}</ul>` : '<div class="service-empty">아직 실행한 분석이 없습니다. 시나리오 분석에서 첫 분석을 시작해 보세요.</div>'}</section></section>`;
    }
    function custom() {
      if (!['dashboard', 'portfolio', 'missing'].includes(S.screen)) return false;
      const content = S.screen === 'dashboard' ? dashboard() : S.screen === 'portfolio' ?
        `<section class="service-portfolio"><h1>내 보유 종목</h1><p>분석에 사용할 종목과 보유 금액을 등록하세요.</p><div id="portfolio-content" aria-live="polite">보유 종목을 불러오는 중입니다.</div></section>` :
        '<section class="service-empty"><h1>페이지를 찾을 수 없습니다</h1><p>주소를 확인하거나 대시보드로 이동해 주세요.</p><a class="service-primary" href="/app" data-service-route>대시보드로 이동</a></section>';
      document.getElementById('app').innerHTML = `<div class="app-root">${header()}<div class="workspace">${rail()}<main class="page service-custom">${content}</main></div></div>`;
      if (S.screen === 'portfolio') {
        portfolioCleanup?.();
        const host = document.getElementById('portfolio-content');
        import('/holdings.js').then(module => {
          if (host.isConnected) portfolioCleanup = module.mountHoldings(host, holdings => {
            S.holdings = holdings.map(h => ({code:h.asset_id, name:h.asset_id, mode:'amount', amount:h.amount_krw, basisDate:new Date().toISOString().slice(0,10)}));
            persist();
          });
        }).catch(() => { if (host.isConnected) host.textContent = '보유 종목 화면을 불러오지 못했습니다. 새로고침해 주세요.'; });
      }
      return true;
    }
    function action(name, element) {
      const destinations = {home:'/app', 'enter':'/app', 'main-collab':'/app/collaboration', 'mr35-enter':'/app/my-room',
        'tab-chat':'/app/scenarios', 'tab-minutes':'/app/minutes', 'v31-open-holdings':'/app/portfolio', 'v31-open-settings':'/app/settings'};
      if (name === 'signout') { pause(); stopMedia(); location.assign('/.auth/logout?post_logout_redirect_uri=%2F'); return true; }
      if (name === 'v31-account-page') {
        apply(element.dataset.tab === 'holdings' ? '/app/portfolio' : '/app/' + element.dataset.tab); return true;
      }
      if (destinations[name]) { apply(destinations[name]); return true; }
      return false;
    }
    document.addEventListener('click', event => {
      const link = event.target.closest('a[data-service-route]');
      if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault(); if (ready) apply(link.getAttribute('href'));
    });
    window.addEventListener('popstate', () => { if (ready) apply(location.pathname + location.search, 'none'); });
    function start(user) {
      // Browser-local prototype state must never grant authentication.
      S.authenticated = true;
      S.profile = {...S.profile, name: S.profile.email === user.userDetails && S.profile.name !== '체험 사용자' ? S.profile.name : user.userDetails || '사용자', email:user.userDetails || ''};
      ready = true;
      const path = location.pathname.startsWith('/app') ? location.pathname + location.search : '/app';
      apply(path, 'replace');
    }
    return {get ready() { return ready; }, header, rail, sync, custom, action, start};
  }
  return {create, startLogin, safeReturn, requireUser};
})();
