/* Presentation only. All existing news handlers, IDs and state remain unchanged. */
const newsprintRender=render;
render=function(){newsprintRender();if(GX.phase!=='game'||GX.panel!=='news')return;const panel=document.querySelector('.p41-feature');if(!panel)return;panel.classList.add('newsprint');const masthead=document.createElement('div');masthead.className='newsprint-masthead';masthead.setAttribute('aria-hidden','true');masthead.innerHTML='<span>WHAT IF</span> 경제신문<small>2008.10 · 서울지점 특별판 <i>게임 속 예시 기사</i></small>';panel.querySelector('.gx-window-body').prepend(masthead);};
