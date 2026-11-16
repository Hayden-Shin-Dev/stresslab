/*
================================================================================
  Modules:
    1. Live ticker         — infinite CSS scroll with hover-pause
    2. Trusted-by logos    — infinite CSS scroll
    3. Nav scroll behavior — translateY snap on scroll past ticker
    4. Mobile menu         — body-scroll-lock + landscape-safe layout
    5. Stats counter       — IntersectionObserver count-up + bar fill
    6. Sticky stack        — scroll-driven feature switcher with right-panel swap
    7. Pricing toggle      — monthly / annual with dual price display
    8. FAQ                 — independent accordion + expand/collapse all
    9. Testimonials        — auto-scroll carousel with play/pause
   10. Period switcher     — dashboard time range toggle (7D/1M/3M/1Y)
   11. Silk reveals        — IntersectionObserver scroll-triggered animations
   12. Phone 3D tilt       — window-wide mouse tracking with lerp easing
================================================================================
*/

const tickerData=[{sym:'USD/KRW',price:'환율 충격',chg:'시나리오 변수',up:true},{sym:'미국 10년물',price:'금리 충격',chg:'시나리오 변수',up:true},{sym:'WTI',price:'유가 충격',chg:'시나리오 변수',up:true},{sym:'VIX',price:'변동성 충격',chg:'시나리오 변수',up:true},{sym:'KOSPI',price:'시장 분석',chg:'분석 대상',up:true},{sym:'개별 종목',price:'종목 분석',chg:'분석 대상',up:true}];
const track=document.getElementById('tickerTrack');
[...tickerData,...tickerData].forEach(t=>{
  const el=document.createElement('div');
  el.className='ticker-item';
  el.innerHTML=`<span class="ticker-sym">${t.sym}</span><span class="ticker-price">${t.price}</span><span class="${t.up?'ticker-up':'ticker-dn'}">${t.chg}</span>`;
  track.appendChild(el);
});

const logos=['시장 시나리오','환율 충격','금리 변화','유가 변동','VIX 변화','AI 분석가','문서 분석','뉴스 분석','종목 분석','보유자산','공동 분석','분석 근거'];
const lt=document.getElementById('logosTrack');
[...logos,...logos].forEach(l=>{
  const el=document.createElement('div');
  el.className='logo-item';
  el.textContent=l;
  lt.appendChild(el);
});

const nav=document.getElementById('mainNav');
const ticker=document.querySelector('.ticker');
window.addEventListener('scroll',()=>{
  nav.classList.toggle('scrolled',window.scrollY>10);
});
window.addEventListener('load',()=>{
  document.querySelectorAll('.hero-content,.hero-visual').forEach((el,i)=>{
    setTimeout(()=>el.classList.add('visible'),i*150+100);
  });
});

const hamburger=document.getElementById('hamburger');
const mobileMenu=document.getElementById('mobileMenu');
let scrollY=0;
hamburger.addEventListener('click',()=>{
  const open=mobileMenu.classList.contains('open');
  if(open){
    mobileMenu.classList.remove('open');
    hamburger.classList.remove('open');
    hamburger.setAttribute('aria-expanded','false');
    document.body.style.position='';
    document.body.style.top='';
    window.scrollTo({top:scrollY,behavior:'instant'});
  } else {
    scrollY=window.scrollY;
    document.body.style.position='fixed';
    document.body.style.top=`-${scrollY}px`;
    mobileMenu.classList.add('open');
    hamburger.classList.add('open');
    hamburger.setAttribute('aria-expanded','true');
  }
});
mobileMenu.querySelectorAll('a').forEach(a=>{
  a.addEventListener('click',()=>{
    mobileMenu.classList.remove('open');
    hamburger.classList.remove('open');
    hamburger.setAttribute('aria-expanded','false');
    document.body.style.position='';
    document.body.style.top='';
    window.scrollTo({top:scrollY,behavior:'instant'});
  });
});


function switchPeriod(btn,period){
  document.querySelectorAll('.dp-period-btn').forEach(b=>b.classList.remove('active'));
  btn.classList.add('active');
  const configs={
    '7d':{val:'$284,920',change:'조건부 분석 예시 · 7일'},
    '1m':{val:'$284,920',change:'조건부 분석 예시 · 1개월'},
    '3m':{val:'$284,920',change:'조건부 분석 예시 · 3개월'},
    '1y':{val:'$284,920',change:'조건부 분석 예시 · 1년'},
  };
  const c=configs[period];
  document.getElementById('dpChartVal').textContent=c.val;
  document.getElementById('dpChartChange').textContent=c.change;
}

const sparkBars=[60,75,50,90,65,85,70,95];
document.getElementById('sparkline').innerHTML=sparkBars.map(h=>`<div class="pm-spark-bar" style="height:${h}%"></div>`).join('');

const stickyCards=document.querySelectorAll('.sticky-card');
const panelViews=document.querySelectorAll('.panel-view');
const panelLabel=document.getElementById('panelLabel');
const panelLabels=['시나리오','AI 분석가','종목 분석','분석 기준'];
stickyCards.forEach((card,i)=>{
  card.addEventListener('click',()=>{
    stickyCards.forEach(c=>c.classList.remove('active'));
    panelViews.forEach(p=>p.classList.remove('active'));
    card.classList.add('active');
    document.getElementById('panel-'+i).classList.add('active');
    panelLabel.textContent=panelLabels[i];
  });
});

const observer=new IntersectionObserver((entries)=>{
  entries.forEach(e=>{
    if(e.isIntersecting){
      stickyCards.forEach((card,i)=>{
        const rect=card.getBoundingClientRect();
        const viewH=window.innerHeight;
        if(rect.top<viewH*0.6&&rect.bottom>viewH*0.3){
          stickyCards.forEach(c=>c.classList.remove('active'));
          panelViews.forEach(p=>p.classList.remove('active'));
          card.classList.add('active');
          document.getElementById('panel-'+i).classList.add('active');
          panelLabel.textContent=panelLabels[i];
        }
      });
    }
  });
},{threshold:0.3});
stickyCards.forEach(c=>observer.observe(c));

const statNums=document.querySelectorAll('.stat-num[data-target]');
const statsObs=new IntersectionObserver((entries)=>{
  entries.forEach(e=>{
    if(e.isIntersecting){
      const el=e.target;
      const target=parseFloat(el.dataset.target);
      const suffix=el.dataset.suffix||'';
      const decimal=parseInt(el.dataset.decimal)||0;
      const prefix=el.dataset.prefix||'';
      let start=0,duration=1800,startTime=null;
      function animate(ts){
        if(!startTime)startTime=ts;
        const progress=Math.min((ts-startTime)/duration,1);
        const ease=1-Math.pow(1-progress,3);
        const val=start+(target-start)*ease;
        el.textContent=prefix+(decimal?val.toFixed(decimal):Math.round(val))+suffix;
        if(progress<1)requestAnimationFrame(animate);
      }
      requestAnimationFrame(animate);
      const bar=el.closest('.stat-block').querySelector('.stat-bar');
      if(bar){setTimeout(()=>{bar.style.width=bar.dataset.width;},200);}
      statsObs.unobserve(el);
    }
  });
},{threshold:0.5});
statNums.forEach(el=>statsObs.observe(el));

let isAnnual=false;
function togglePricing(){
  isAnnual=!isAnnual;
  document.getElementById('pricingToggle').classList.toggle('on',isAnnual);
  document.querySelectorAll('.price-num').forEach(el=>{
    el.textContent=isAnnual?el.dataset.annual:el.dataset.monthly;
  });
  document.querySelectorAll('.period-label').forEach(el=>{
    el.textContent=isAnnual?'개별 종목':'시장';
  });
  document.querySelectorAll('.price-alt-monthly').forEach(el=>{
    el.style.display=isAnnual?'none':'inline';
  });
  document.querySelectorAll('.price-alt-annual').forEach(el=>{
    el.style.display=isAnnual?'inline':'none';
  });
}

const faqs=[
{q:'WHAT IF에서는 어떤 분석을 할 수 있나요?',a:'환율·미국 10년물 금리·WTI·VIX 충격을 설정하는 시나리오 분석, 문서·뉴스 분석, 종목·보유자산 분석, 사람과 AI가 참여하는 함께 분석을 제공합니다. 이용 가능 범위는 연결된 데이터와 서비스 상태에 따라 달라집니다.'},
{q:'시나리오 분석 결과는 미래를 예측하나요?',a:'아닙니다. 결과는 설정한 충격과 기준 시점의 자료를 바탕으로 한 조건부 분석입니다. 미래 경로나 발생 확률을 보장하지 않으며, 화면에서 연구 모델과 데이터의 한계를 확인해야 합니다.'},
{q:'어떤 충격 변수를 설정할 수 있나요?',a:'원/달러 환율 변화율, 미국 10년물 금리 변화량, WTI 유가 변화율, VIX 지수 변화량을 설정합니다. 입력 단위와 지원 범위를 확인하고 분석을 실행할 수 있습니다.'},
{q:'AI 분석가들은 어떻게 답하나요?',a:'네 명의 AI 분석가가 서로 다른 역할과 관점으로 의견을 제시합니다. 각 의견은 참고 자료와 함께 검토하고, 분석의 전제와 한계를 확인할 수 있습니다.'},
{q:'문서나 뉴스를 분석에 활용할 수 있나요?',a:'문서를 업로드하거나 분석할 뉴스를 선택해 대화와 시나리오의 맥락으로 활용할 수 있습니다. 원문과 인용은 접근 권한 및 이용 가능한 자료 범위 안에서 제공됩니다.'},
{q:'내 보유종목을 분석할 수 있나요?',a:'보유종목을 직접 등록하고 시장·개별 종목·개인 구성의 영향을 살펴볼 수 있습니다. 현재가나 연구 자료가 확인되지 않는 항목은 미평가 또는 미지원 상태로 구분합니다.'},
{q:'다른 사람과 함께 분석할 수 있나요?',a:'함께 분석에서 공동 시나리오와 공유 자료를 같은 맥락으로 검토하고 AI 팀원을 추가하거나 제외할 수 있습니다. 원격 영상·음성 연결 등 일부 기능은 운영 연결 상태에 따라 제공 여부가 달라집니다.'}
];
const faqList=document.getElementById('faqList');
faqs.forEach((f,i)=>{
  const item=document.createElement('div');
  item.className='faq-item';
  item.innerHTML=`<div class="faq-q"><span class="faq-q-text">${f.q}</span><svg class="faq-chevron" viewBox="0 0 24 24"><polyline points="6,9 12,15 18,9"/></svg></div><div class="faq-a">${f.a}</div>`;
  item.querySelector('.faq-q').addEventListener('click',()=>{
    item.classList.toggle('open');
  });
  faqList.appendChild(item);
});

let allExpanded=false;
function toggleAllFaq(){
  allExpanded=!allExpanded;
  document.querySelectorAll('.faq-item').forEach(el=>{
    allExpanded?el.classList.add('open'):el.classList.remove('open');
  });
  document.getElementById('faqToggleLabel').textContent=allExpanded?'모두 접기':'모두 펼치기';
  const icon=document.getElementById('faqToggleIcon');
  icon.innerHTML=allExpanded
    ?'<line x1="5" y1="12" x2="19" y2="12"/>'
    :'<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>';
}

const testimonials=[
{q:'환율과 금리 충격을 함께 설정해 여러 시장 시나리오를 비교하고 분석의 전제를 확인합니다.',name:'시장 충격 시나리오',role:'분석 예시',init:'01'},
{q:'네 명의 분석가가 같은 질문을 다른 관점에서 검토해 근거와 놓친 쟁점을 비교합니다.',name:'AI 분석가 토론',role:'분석 예시',init:'02'},
{q:'시장 자료와 연구 모델을 구분해 결과의 가정과 적용 범위를 함께 확인합니다.',name:'시장 분석 패널',role:'분석 예시',init:'03'},
{q:'문서와 뉴스를 같은 맥락에서 살펴보고 공동 분석 공간에서 논점을 이어갑니다.',name:'공동 분석 공간',role:'분석 예시',init:'04'}
];
const tt=document.getElementById('testiTrack');
[...testimonials,...testimonials].forEach(t=>{
  const el=document.createElement('div');
  el.className='testi-card';
  el.innerHTML=`<div class="testi-stars">${[...Array(5)].map(()=>'<svg viewBox="0 0 24 24"><polygon points="12,2 15.09,8.26 22,9.27 17,14.14 18.18,21.02 12,17.77 5.82,21.02 7,14.14 2,9.27 8.91,8.26"/></svg>').join('')}</div><p class="testi-quote">"${t.q}"</p><div class="testi-author"><div class="testi-avatar">${t.init}</div><div><div class="testi-name">${t.name}</div><div class="testi-role">${t.role}</div></div></div>`;
  tt.appendChild(el);
});

document.querySelectorAll('a[href^="#"]').forEach(a=>{
  a.addEventListener('click',e=>{
    const href=a.getAttribute('href');
    if(href==='#')return;
    e.preventDefault();
    const target=document.querySelector(href);
    if(target)target.scrollIntoView({behavior:'smooth'});
  });
});

const revealObs=new IntersectionObserver((entries)=>{
  entries.forEach(e=>{
    if(e.isIntersecting){
      e.target.classList.add('visible');
      revealObs.unobserve(e.target);
    }
  });
},{threshold:0.12});
document.querySelectorAll('.silk-reveal,.silk-reveal-left,.silk-reveal-right').forEach((el,i)=>{
  el.style.animationDelay=(i%4)*0.08+'s';
  revealObs.observe(el);
});

const statBlocks=document.querySelectorAll('.stat-block');
statBlocks.forEach((el,i)=>{
  el.style.opacity='0';
  el.style.transform='translateY(20px)';
  el.style.transition=`opacity .8s var(--silk) ${i*0.1}s, transform .8s var(--silk) ${i*0.1}s, border-color .6s var(--silk), box-shadow .6s var(--silk)`;
});
const statObs2=new IntersectionObserver((entries)=>{
  entries.forEach(e=>{
    if(e.isIntersecting){
      e.target.style.opacity='1';
      e.target.style.transform='translateY(0)';
      statObs2.unobserve(e.target);
    }
  });
},{threshold:0.2});
statBlocks.forEach(el=>statObs2.observe(el));

const sectionHeaders=document.querySelectorAll('.section-title,.section-tag,.section-sub');
sectionHeaders.forEach(el=>{
  el.style.opacity='0';
  el.style.transform='translateY(16px)';
  el.style.transition='opacity .8s var(--silk), transform .8s var(--silk)';
});
const headerObs=new IntersectionObserver((entries)=>{
  entries.forEach(e=>{
    if(e.isIntersecting){
      e.target.style.opacity='1';
      e.target.style.transform='translateY(0)';
      headerObs.unobserve(e.target);
    }
  });
},{threshold:0.3});
sectionHeaders.forEach(el=>headerObs.observe(el));

const phoneFrame=document.getElementById('phoneFrame');
if(phoneFrame){
  let targetX=0,targetY=0,currentX=0,currentY=0,rafId=null,running=false;
  const MAX_TILT=16;
  function animate(){
    currentX+=(targetX-currentX)*.06;
    currentY+=(targetY-currentY)*.06;
    phoneFrame.style.transform=`rotateX(${currentY}deg) rotateY(${currentX}deg) translateZ(0)`;
    if(Math.abs(targetX-currentX)>.02||Math.abs(targetY-currentY)>.02){
      rafId=requestAnimationFrame(animate);
    } else {
      rafId=null;
      running=false;
    }
  }
  function kick(){
    if(!rafId){running=true;rafId=requestAnimationFrame(animate);}
  }
  window.addEventListener('mousemove',e=>{
    const x=e.clientX/window.innerWidth-.5;
    const y=e.clientY/window.innerHeight-.5;
    targetX=x*MAX_TILT*4;
    targetY=-y*MAX_TILT*2;
    kick();
  });
  window.addEventListener('mouseleave',()=>{
    targetX=0;targetY=0;
    kick();
  });
}
