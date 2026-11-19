// Popup and list behavior refinements, preserving all existing actions and analysis state.
const p511Hotspots=gxHotspots;
gxHotspots=function(){return p511Hotspots().map(h=>h.id==='meeting'?{...h,name:'회의실'}:h);};
const P511_GEAR='<svg class="p511-device-gear" viewBox="0 0 32 32" role="img" aria-hidden="true"><path fill="#c88b43" stroke="#63472e" stroke-width="1.5" stroke-linejoin="round" d="m13 2 6 0 1 4 3 2 4-1 3 5-3 3v3l3 3-3 5-4-1-3 2-1 4h-6l-1-4-3-2-4 1-3-5 3-3v-3l-3-3 3-5 4 1 3-2z"/><circle cx="16" cy="16" r="7" fill="#fff1d7" stroke="#63472e" stroke-width="1.5"/><circle cx="16" cy="16" r="3" fill="#35675e"/></svg>';
const p511Render=render;
render=function(){
 p511Render();S.appVersion='5.11.0';
 const root=document.querySelector('.ui510');if(!root)return;root.classList.add('ui511');
 root.querySelectorAll('[data-action=p51-devices]').forEach(b=>{b.innerHTML=P511_GEAR;b.setAttribute('title','화상 장치 설정');b.setAttribute('aria-label','화상 장치 설정');});
 root.querySelectorAll('.mr35-modal-card .mr35-pill').forEach(b=>{if(/V\d+\.\d+/.test(b.textContent))b.classList.add('p511-version');});
 // A previous news-review adapter writes an inline foreground level; normalize the same layer for every primary popup.
 root.querySelectorAll('.v45-notebook-wrap').forEach(w=>w.style.zIndex='820');
};
const p511Action=gxAction;gxAction=function(action,el){const out=p511Action(action,el);document.querySelectorAll('.ui511 .v45-notebook-wrap').forEach(w=>w.style.zIndex='820');return out;};
WHATIF_QA.interval511={forecast:p511Forecast,chart:opts=>C.chartHTML(opts)};
