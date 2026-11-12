(() => {
  'use strict';
  const canvas = document.querySelector('#voxel-canvas');
  const intensity = document.querySelector('#shock-input');
  const value = document.querySelector('#shock-value');
  const pauseButton = document.querySelector('#pause-button');
  let scene;
  try { scene = new window.WhatIfVoxel(canvas, { intensity: 0.50 }); }
  catch (err) {
    console.error('WebGL2를 사용할 수 없어 인트로 모션을 정지합니다.', err);
    canvas.setAttribute('aria-hidden', 'false');
    canvas.setAttribute('aria-label', '이 브라우저에서는 WebGL2 인트로를 표시할 수 없습니다.');
    intensity.disabled=true;
    pauseButton.disabled=true;
    return;
  }
  intensity.addEventListener('input', () => {
    value.textContent=intensity.value;
    scene.setIntensity(Number(intensity.value)/100);
  });
  pauseButton.addEventListener('click', () => {
    scene.isPaused ? scene.play() : scene.pause();
    pauseButton.setAttribute('aria-pressed',String(scene.isPaused));
    pauseButton.textContent=scene.isPaused?'재생':'일시정지';
  });
  document.querySelector('#scenario-button').addEventListener('click', () => {
    const n=Math.round(20+Math.random()*80);
    intensity.value=String(n); value.textContent=String(n);
    scene.setScenario({rateBp:n*2,fxPct:n*.1,oilPct:n*.25,vixPt:n*.3});
    scene.play();
    pauseButton.textContent='일시정지';
    pauseButton.setAttribute('aria-pressed','false');
    window.scrollTo({top:0,behavior:'smooth'});
  });
  // Optional integration with other app components:
  // window.whatifVoxel.setScenario({rateBp:100,fxPct:5,oilPct:12,vixPt:20})
  window.whatifVoxel=scene;
})();
