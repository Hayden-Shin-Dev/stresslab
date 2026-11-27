'use strict';

// WHAT IF is the primary product; the quote monitor and holdings pages stay valid return targets.
const DEFAULT_TARGET = '/whatif-v6/';
const allowedTargets = new Set(['/whatif-v6/', '/whatif-v6', '/quote-monitor', '/holdings.html']);
const params = new URLSearchParams(location.search);
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');

function safeTarget(value) {
  try {
    const url = new URL(value || DEFAULT_TARGET, location.origin);
    return url.origin === location.origin && allowedTargets.has(url.pathname)
      ? url.pathname : DEFAULT_TARGET;
  } catch {
    return DEFAULT_TARGET;
  }
}

// The live region always carries the full sentence; the console only animates it visually.
let typingTimer = 0;
function setStatus(text) {
  document.getElementById('login-status').textContent = text;
  const typed = document.querySelector('.rm-typed');
  if (!typed) return;
  clearInterval(typingTimer);
  if (reduceMotion.matches) { typed.textContent = text; return; }
  typed.textContent = '';
  let i = 0;
  typingTimer = setInterval(() => {
    typed.textContent = text.slice(0, ++i);
    if (i >= text.length) clearInterval(typingTimer);
  }, 28);
}

async function startLogin() {
  const target = safeTarget(params.get('returnTo') || params.get('next'));
  document.getElementById('sign-in').href =
    '/.auth/login/google?post_login_redirect_uri=' + encodeURIComponent(target);
  setStatus('로그인 상태를 확인하는 중입니다.');
  try {
    const response = await fetch('/.auth/me', {cache: 'no-store', credentials: 'same-origin'});
    if (!response.ok) throw new Error('Authentication status unavailable');
    const {clientPrincipal} = await response.json();
    if (clientPrincipal) {
      location.replace(target);
      return;
    }
    setStatus('Google 계정으로 WHAT IF에 입장하세요.');
  } catch {
    setStatus('로그인 상태를 확인할 수 없습니다. 아래 버튼으로 로그인을 진행해 주세요.');
  }
}

// Pixel rain over the night city. The pointer steers the wind; a tap splashes.
function startRain() {
  const canvas = document.querySelector('.rm-rain');
  if (!canvas || reduceMotion.matches) return;
  const ctx = canvas.getContext('2d');
  const SCALE = 3;
  let w = 0, h = 0, wind = -0.6, targetWind = -0.6, drops = [], splashes = [], raf = 0;
  function resize() {
    w = canvas.width = Math.ceil(innerWidth / SCALE);
    h = canvas.height = Math.ceil(innerHeight / SCALE);
    const count = Math.min(140, Math.round((w * h) / 900));
    drops = Array.from({length: count}, () => ({x: Math.random() * w, y: Math.random() * h, v: 2 + Math.random() * 2, l: 2 + (Math.random() * 3 | 0)}));
  }
  function frame() {
    wind += (targetWind - wind) * 0.05;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = 'rgba(190,215,255,.55)';
    for (const d of drops) {
      d.y += d.v; d.x += wind;
      if (d.y > h) { d.y = -d.l; d.x = Math.random() * w; }
      if (d.x < 0) d.x += w; else if (d.x > w) d.x -= w;
      for (let i = 0; i < d.l; i++) ctx.fillRect(Math.round(d.x - wind * i * 0.5), Math.round(d.y - i), 1, 1);
    }
    ctx.fillStyle = 'rgba(242,195,91,.9)';
    splashes = splashes.filter((s) => (s.t += 1) < 14);
    for (const s of splashes) {
      for (let k = 0; k < 8; k++) {
        const a = (Math.PI * 2 * k) / 8;
        ctx.fillRect(Math.round(s.x + Math.cos(a) * s.t * 0.8), Math.round(s.y + Math.sin(a) * s.t * 0.5), 1, 1);
      }
    }
    raf = requestAnimationFrame(frame);
  }
  addEventListener('resize', resize);
  addEventListener('pointermove', (e) => {
    targetWind = ((e.clientX / innerWidth) - 0.5) * 3;
    const px = ((e.clientX / innerWidth) - 0.5) * -12, py = ((e.clientY / innerHeight) - 0.5) * -8;
    document.body.style.backgroundPosition = `calc(50% + ${px.toFixed(1)}px) calc(50% + ${py.toFixed(1)}px)`;
  }, {passive: true});
  addEventListener('pointerdown', (e) => {
    if (e.target.closest('a,button')) return;
    splashes.push({x: e.clientX / SCALE, y: e.clientY / SCALE, t: 0});
  }, {passive: true});
  document.addEventListener('visibilitychange', () => {
    cancelAnimationFrame(raf);
    if (!document.hidden) raf = requestAnimationFrame(frame);
  });
  resize();
  raf = requestAnimationFrame(frame);
}

startLogin();
startRain();
