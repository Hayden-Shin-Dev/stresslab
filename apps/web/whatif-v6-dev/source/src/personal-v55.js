/* V5.5: one interaction owner, normalized character assets, personal stationery. */
const P55={active:null,lastPanel:null,lock:false,marker:null,normalized:new Map(),slots:[],meetingMode:'day',meetingType:'line'};
const p55Image=gxImage;
function p55Normalize(im,cols,rows,outCols=cols){
 const src=document.createElement('canvas');src.width=im.naturalWidth;src.height=im.naturalHeight;const sc=src.getContext('2d',{willReadFrequently:true});sc.drawImage(im,0,0);
 const out=document.createElement('canvas');out.width=256*outCols;out.height=256*Math.ceil(cols*rows/outCols);const c=out.getContext('2d');c.imageSmoothingEnabled=false;
 for(let i=0;i<cols*rows;i++){const x=Math.floor(i%cols*src.width/cols),y=Math.floor(Math.floor(i/cols)*src.height/rows),w=Math.floor(src.width/cols),h=Math.floor(src.height/rows),data=sc.getImageData(x,y,w,h).data;let l=w,t=h,r=0,b=0;for(let yy=0;yy<h;yy++)for(let xx=0;xx<w;xx++)if(data[(yy*w+xx)*4+3]>190){l=Math.min(l,xx);r=Math.max(r,xx);t=Math.min(t,yy);b=Math.max(b,yy);}if(r<=l)continue;const scale=Math.min(196/(r-l+1),206/(b-t+1)),dw=(r-l+1)*scale,dh=(b-t+1)*scale;c.drawImage(src,x+l,y+t,r-l+1,b-t+1,(i%outCols)*256+128-dw/2,Math.floor(i/outCols)*256+232-dh,dw,dh);}
 out.complete=true;out.naturalWidth=out.width;out.naturalHeight=out.height;return out;
}
gxImage=function(id){const im=p55Image(id);if(!['sprite_youngcheol','idle_youngcheol','meeting_upper55'].includes(id))return im;if(!im.complete||!im.naturalWidth)return im;if(!P55.normalized.has(id))P55.normalized.set(id,p55Normalize(im,4,id==='sprite_youngcheol'?4:id==='idle_youngcheol'?2:1,id==='idle_youngcheol'?8:4));return P55.normalized.get(id);};
persona('shin').avatar=GX_ASSETS.portrait_2;
const p55ProfileText={kim:['거시 변수의 변화가 시장 전체에 미칠 영향을 먼저 짚는 분석가입니다.','금리·환율·유가와 VIX의 가정을 비교하고, 충격이 업종과 기업으로 전달되는 경로를 설명합니다.','시나리오 입력값, 분석 실행 결과, 공개된 거시 자료와 사용자가 공유한 문서를 확인합니다.'],shin:['손실 가능성과 분석의 한계를 먼저 확인하는 리스크 분석가입니다.','급락·변동성 확대·유사 국면을 점검하고, 낙관적인 결과에도 반대 근거와 손실 경로를 따져 봅니다.','종목별 분포, 시나리오 조건과 모델의 지원 범위를 확인합니다. 승인된 공동 표본이 없으면 위험 수치를 확정하지 않습니다.'],yoon:['분석 시점의 시장 상태와 거래 흐름을 먼저 구분하는 분석가입니다.','가격 움직임과 거래·업종 흐름을 비교하고, 새로운 뉴스가 기존 판단을 바꿀 만큼 중요한지 살펴봅니다.','시점이 확인된 시장 스냅샷과 선택한 뉴스를 확인합니다. 장중 데이터가 없으면 실시간 상황을 추정하지 않습니다.'],kang:['보유종목의 비중과 분산 상태를 먼저 점검하는 포트폴리오 분석가입니다.','특정 종목·업종에 위험이 몰리는지 확인하고, 자산이 함께 움직이는 상황에서 손실의 기여도를 살펴봅니다.','사용자가 등록한 보유내역과 확인 가능한 평가 기준을 봅니다. 공동 수익률 표본이 없으면 VaR·ES 계산을 보류합니다.']};
const p55AgentPanel=mr35AgentPanel;
mr35AgentPanel=function(){if(P52.teamList)return p55AgentPanel();const id=S.myroom.agent||'kim',p=persona(id),copy=p55ProfileText[id];return `<section class="v45-profile p55-profile"><header><small>WHAT IF · AI ANALYST</small><button class="v45-profile-close" data-action="mr35-close">x 닫기</button></header><img src="${p.avatar}" alt="${E(p.name)}"><h2>${E(p.name)}</h2><strong>${E(p.role)}</strong><p class="p55-lead">${copy[0]}</p><h3>어떤 관점으로 보나요?</h3><p>${copy[1]}</p><h3>무엇을 확인하나요?</h3><p>${copy[2]}</p><p class="v45-profile-note">제공된 자료와 가정 안에서 설명하며 미래 수익이나 시장 방향을 보장하지 않습니다.</p><button data-action="mr35-to-agent" data-persona="${id}">이 팀원과 대화</button></section>`;};
function p55Neutral(){P55.active=null;GX.panel=null;S.modal=null;S.myroom.modal='';P41.tab='none';P42.aiOpen=false;GX.keys.clear();GX.path=[];render();}
const p55GX=gxAction,p55Use=gxUse,p55Room=gxSetRoom;
gxSetRoom=function(room){P55.active=null;P55.marker=null;return p55Room(room);};
gxUse=function(h){if(P55.lock||GX.panel||S.modal||S.myroom.modal||GX.soundOpen)return;P55.lock=true;try{return p55Use(h);}finally{P55.lock=false;}};
gxAction=function(action,el){
 if(action==='enter'&&GX.phase==='login'){const value=document.querySelector('#gx-nickname')?.value?.trim();if(!p56ValidName(value)){P55.loginError='닉네임은 1–5글자, 한글·영문·숫자로 입력해 주세요.';return render();}P55.nickDraft=value;P55.loginError='';}
 if(['interact','p49-persona','ppukku-chat'].includes(action)&&(P55.lock||S.modal||S.myroom.modal||GX.soundOpen||(GX.panel&&GX.panel!=='collab')))return;
 if(action==='panel'&&el.closest('.p41-main-tabs')){const key=el.dataset.panel;if(key==='sim'&&P55.active==='agent'&&!GX.panel)return p55Neutral();P55.active={sim:'agent',minutes:'minutes',holdings:'holdings'}[key];}
 if(action==='feature-close'&&['minutes','holdings','account'].includes(GX.panel))P55.active=null;
 return p55GX(action,el);
};
const p55Chart=C.chartHTML;
C.chartHTML=function(options={}){return p55Chart(options.id==='meeting-simulation'?{...options,mode:P55.meetingMode,chartType:P55.meetingType}:options);};
const p55Action=onAction;
onAction=function(action,el){if(action==='p55-call-mode'){P55.meetingMode=el.dataset.value;return render();}if(action==='p55-call-type'){P55.meetingType=el.dataset.value;return render();}return p55Action(action,el);};
function p55CallControls(){return `<nav class="p55-call-controls" aria-label="공동 차트 보기">${[['minute','분봉'],['day','일봉'],['month','월봉']].map(([v,l])=>`<button data-action="p55-call-mode" data-value="${v}" aria-pressed="${P55.meetingMode===v}">${l}</button>`).join('')}<i></i>${[['line','선'],['candle','캔들'],['bar','OHLC 바']].map(([v,l])=>`<button data-action="p55-call-type" data-value="${v}" aria-pressed="${P55.meetingType===v}">${l}</button>`).join('')}</nav>`;}
const p55Attach=C.attach;
C.attach=function(svg,run,mode){return p55Attach(svg,run,svg.dataset.chart==='meeting-simulation'?P55.meetingMode:mode);};
const p55Draw=gxDraw;
gxDraw=function(now){p55Draw(now);if(!P55.marker||GX.panel||S.modal||S.myroom.modal)return;const m=P55.marker,age=now-m.at;if(age>2200){P55.marker=null;return;}const cv=document.querySelector('.gx-stage canvas');if(!cv)return;const c=cv.getContext('2d');c.save();c.translate(m.x,m.y);c.globalAlpha=Math.max(0,1-age/2200);c.strokeStyle='#fff4ba';c.lineWidth=3;c.beginPath();c.moveTo(0,-12);c.lineTo(22,0);c.lineTo(0,12);c.lineTo(-22,0);c.closePath();c.stroke();c.fillStyle='#efbd51';c.fillRect(-3,-3,6,6);c.strokeStyle='#b57029';c.strokeRect(-5,-5,10,10);c.restore();};
window.addEventListener('pointerdown',e=>{const cv=e.target.closest('.gx-stage canvas');if(!cv||GX.panel||S.modal||S.myroom.modal||GX.soundOpen||GX.chatModal)return;const r=cv.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*1536,y=(e.clientY-r.top)/r.height*864,target=gxNearest(GX.room,x,y);if(target)P55.marker={...target,at:performance.now()};},true);
function p55Slots(){const im=p55Image('menu_atlas55');if(!im.complete||!im.naturalWidth){if(!im._p55Bound){im._p55Bound=true;im.addEventListener('load',()=>render(),{once:true});}return;}if(!P55.slots.length)for(let i=0;i<6;i++){const cv=document.createElement('canvas');cv.width=220;cv.height=190;cv.getContext('2d').drawImage(im,(80+(i%3)*475)*im.naturalWidth/1536,(30+Math.floor(i/3)*410)*im.naturalHeight/1024,425*im.naturalWidth/1536,365*im.naturalHeight/1024,0,0,220,190);P55.slots.push(cv.toDataURL());}document.querySelectorAll('.p41-dock [data-tool]').forEach((b,i)=>{b.innerHTML=`<img class="p55-slot-art" src="${P55.slots[i]}" alt="${['AI 리포트','회의록','시뮬레이션','클라우드','메모','AI 팀원'][i]}">`;});}
const p55Render=render;
render=function(){p55Render();if(GX.phase==='login'){const field=document.querySelector('#gx-nickname');if(field){field.placeholder='최대 5글자 · 특수기호 사용 금지';field.value=P55.nickDraft||'';field.required=true;field.setAttribute('aria-required','true');field.setAttribute('aria-describedby','p49-name-help'+(P55.loginError?' p55-nick-error':''));const button=document.querySelector('.m48-login-card [data-gx=enter]');if(button)button.disabled=!p56ValidName(field.value);if(P55.loginError)field.insertAdjacentHTML('afterend','<small id="p55-nick-error" role="alert">'+E(P55.loginError)+'</small>');}}if(GX.phase!=='game')return;S.appVersion='5.5.0';const root=document.querySelector('.ui54');root?.classList.add('ui55');if(!root)return;
 if(P55.lastPanel&&['minutes','holdings'].includes(P55.lastPanel)&&!GX.panel)P55.active=null;P55.lastPanel=GX.panel;
 root.dataset.agentOpen=String(P55.active==='agent');root.querySelectorAll('.p41-main-tabs button').forEach(b=>{const key={sim:'agent',minutes:'minutes',holdings:'holdings'}[b.dataset.panel],active=P55.active===key;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});
 const modal=root.querySelector('.mr35-modal-card');if(modal){modal.dataset.p55Kind=S.myroom.modal;modal.classList.add('p55-stationery');const caption=modal.querySelector('.mr35-modal-top p');if(caption)caption.textContent=({report:'보유종목과 저장한 분석 기록을 연결한 나의 보고서입니다.',minutes:'날짜별 회의와 AI 팀원의 의견을 서류함에서 확인하세요.',cloud:'개인 문서와 이미지를 이 브라우저에 보관합니다.',memo:'글과 그림을 함께 저장하고 날짜별로 다시 확인하세요.'})[S.myroom.modal]||caption.textContent;}
 if(GX.room==='myroom'){p55Slots();const team=root.querySelector('[data-tool=agent]');if(team){team.style.position='relative';team.insertAdjacentHTML('beforeend','<span class="p55-mini-team">'+['kim','shin','yoon','kang'].map(id=>'<img src="'+persona(id).avatar+'" alt="">').join('')+'</span>');}}
 const work=root.querySelector('.call-simulator');if(work)work.insertAdjacentHTML('afterbegin',p55CallControls());
};
WHATIF_QA.personal55=()=>({active:P55.active,marker:P55.marker,normalized:[...P55.normalized.keys()],meetingMode:P55.meetingMode,meetingType:P55.meetingType,modal:S.myroom.modal,slots:P55.slots.length});

for(const id of ['sprite_youngcheol','idle_youngcheol','meeting_upper55']){const im=p55Image(id);if(im.complete&&im.naturalWidth)gxImage(id);else im.addEventListener('load',()=>gxImage(id),{once:true});}

window.addEventListener('input',e=>{if(e.target.id==='gx-nickname'){P55.nickDraft=e.target.value;const b=document.querySelector('.m48-login-card [data-gx=enter]');if(b)b.disabled=!p56ValidName(e.target.value);document.querySelector('#p55-nick-error')?.remove();}},true);

if(!S.authenticated&&['체험사용자','시간 여행자',''].includes(S.profile.name))S.profile.name='시간여행자';

p55Image('menu_atlas55');
window.addEventListener('click',e=>{const root=document.querySelector('.ui55');if(!root)return;const top=[...root.querySelectorAll('.modal-wrap .modal,.mr35-modal-card,.gx-settings')].filter(x=>x.getClientRects().length).at(-1)||[...root.querySelectorAll('.p41-feature')].find(x=>x.getClientRects().length);if(top&&!top.contains(e.target)&&!(e.target.closest('.gx-rail')&&!S.modal&&!S.myroom.modal&&!GX.soundOpen)&&!((p50PanelKey(GX.panel)||GX.panel==='collab')&&GX.chat&&!GX.chatMin&&!S.modal&&!S.myroom.modal&&!GX.soundOpen&&e.target.closest('.gx-chat-window'))){e.preventDefault();e.stopImmediatePropagation();}},true);
