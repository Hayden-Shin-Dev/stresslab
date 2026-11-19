const mr44Render=render;
gxBackground=function(){return GX.room==='myroom'?(GX.playerKind==='female'?'myroom_female':'myroom'):'office';};
render=function(){mr44Render();if(GX.phase!=='game')return;const root=document.querySelector('.p42-app');root?.classList.add('p44-app');root?.setAttribute('data-player-kind',GX.playerKind);if(GX.room==='myroom'){const dock=document.querySelector('.p41-dock'),stage=document.querySelector('.gx-stage');if(dock&&stage){stage.appendChild(dock);dock.setAttribute('aria-label','개인실 퀵슬롯');dock.querySelectorAll('[data-tool]').forEach(button=>{const icon=button.querySelector('img');if(icon)icon.src=GX_ASSETS['menu_'+button.dataset.tool];button.title=button.innerText.trim();});}}};
window.WHATIF_QA.roomBackground=()=>gxBackground();
