'use strict';

const allowedTargets = new Set(['/quote-monitor', '/holdings.html']);
const params = new URLSearchParams(location.search);

function safeTarget(value) {
  try {
    const url = new URL(value || '/quote-monitor', location.origin);
    return url.origin === location.origin && allowedTargets.has(url.pathname)
      ? url.pathname : '/quote-monitor';
  } catch {
    return '/quote-monitor';
  }
}

async function startLogin() {
  const target = safeTarget(params.get('returnTo') || params.get('next'));
  document.getElementById('sign-in').href =
    '/.auth/login/google?post_login_redirect_uri=' + encodeURIComponent(target);
  try {
    const response = await fetch('/.auth/me', {cache: 'no-store', credentials: 'same-origin'});
    if (!response.ok) throw new Error('Authentication status unavailable');
    const {clientPrincipal} = await response.json();
    if (clientPrincipal) {
      location.replace(target);
      return;
    }
    document.getElementById('login-status').textContent =
      'Google 계정으로 로그인하고 실시간 데이터 화면으로 이동하세요.';
  } catch {
    document.getElementById('login-status').textContent =
      '로그인 상태를 확인할 수 없습니다. 아래 버튼으로 로그인을 진행해 주세요.';
  }
}

startLogin();
