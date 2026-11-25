/* One state/request owner per page. Detached windows are views, never app copies.
   No localStorage/BroadcastChannel bus can leak one task's data into another. */
window.installWhatIfWindows=function(a){
  const task=crypto.randomUUID(), panels=new Map();
  let layout={},resultRequested=false,z=10010,note='',moving=null,resizing=null,splitting=null,pendingRender=false,painting=false;
  const agentSize={width:434,height:796};
  const clamp=(n,min,max)=>Math.max(min,Math.min(Number(n)||min,Math.max(min,max)));
  function box(v={}){
    const margin=innerWidth<=800?16:24,maxWidth=Math.max(1,innerWidth-2*margin),maxHeight=Math.max(1,innerHeight-(document.querySelector('.handoff-taskbar')?.offsetHeight||64)-2*margin);
    const width=clamp(v.width||520,Math.min(300,maxWidth),maxWidth),height=clamp(v.height||720,Math.min(250,maxHeight),maxHeight);
    return {x:clamp(v.x,margin,innerWidth-width-margin),y:clamp(v.y,margin,maxHeight+margin-height),width,height};
  }
  const titles={agent:'뿌꾸 AI Agent',result:'결과 분석',portfolio:'나의 포트폴리오'};
  const icons={
    '이동 창':'<path d="M12 3v18M3 12h18M9 6l3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3M18 9l3 3-3 3"/>',
    '기본 위치':'<path d="M4 10a8 8 0 1 1 1 8M4 4v6h6"/>',
    '왼쪽 도킹':'<path d="M4 3v18M20 12H8m5-5-5 5 5 5"/>',
    '오른쪽 도킹':'<path d="M20 3v18M4 12h12m-5-5 5 5-5 5"/>',
    '별도 창':'<path d="M14 3h7v7M21 3 10 14M10 5H4v15h15v-6"/>',
    '최소화':'<path d="M4 18h16"/>'
  };
  const ensure=id=>{if(!panels.has(id))panels.set(id,{id,node:null,placeholder:null,shell:null,popup:null,observer:null});return panels.get(id);};
  function save(){a.changed?.();}
  function applyBox(id,value){const b=box(value),p=ensure(id);layout[id]={...layout[id],...b};if(p.shell)Object.assign(p.shell.style,{left:b.x+'px',top:b.y+'px',width:b.width+'px',height:b.height+'px'});return b;}
  function finishGesture(){if(!moving&&!resizing&&!splitting)return;const split=splitting;moving=null;resizing=null;splitting=null;save();if(pendingRender){pendingRender=false;a.repaint();}else if(split&&ensure('agent').popup)syncPopup(ensure('agent'));}
  function dock(id,where=id==='portfolio'?'default':'right'){
    const p=ensure(id),popup=p.popup;p.popup=null;if(popup&&!popup.closed)popup.close();
    layout[id]={...layout[id],mode:'dock',where,automaticFloat:false};note='메인 작업 영역으로 복귀했습니다.';save();if(id==='portfolio'&&!document.querySelector('.ws-scenario-overlay .fig-scenario-screen'))a.openAnalysis();else a.repaint();
  }
  function float(id){const p=ensure(id),rect=p.node?.getBoundingClientRect();layout[id]={...layout[id],...box(layout[id]?.width?layout[id]:{x:rect?.x||24,y:Math.min(rect?.y||24,80),width:id==='agent'?agentSize.width:id==='portfolio'?Math.min(1000,rect?.width||900):520,height:id==='agent'?agentSize.height:id==='portfolio'?480:720}),mode:'float',automaticFloat:false};a.keepAgent();save();a.repaint();}
  function setDockSize(node, width, height) {
    const screen=node.closest('.ws-scenario-overlay .fig-scenario-screen');
    if(!screen)return;
    const maxWidth=Math.min(screen.clientWidth-32,Math.max(agentSize.width,screen.clientWidth-390));
    const nextWidth=clamp(width,Math.min(300,maxWidth),maxWidth);
    const nextHeight=clamp(height,320,1080);
    layout.agent={mode:'dock',where:'right',...layout.agent,dockWidth:nextWidth,dockHeight:nextHeight};
    screen.style.setProperty('--scenario-agent-width',nextWidth+'px');
    node.style.setProperty('--scenario-agent-height',nextHeight+'px');
  }
  function resizeEdges(node, target, floating) {
    for(const edge of ['n','e','s','w','ne','se','sw','nw']){
      const handle=document.createElement('div');
      handle.className='agent-resize-edge';
      handle.dataset.edge=edge;
      handle.setAttribute('aria-hidden','true');
      handle.onpointerdown=event=>{
        if(event.button!==0)return;
        const rect=target.getBoundingClientRect();
        resizing={handle,rect,x:event.clientX,y:event.clientY};
        handle.setPointerCapture(event.pointerId);
        if(floating)target.style.zIndex=++z;
        event.preventDefault();
      };
      handle.onpointermove=event=>{
        if(resizing?.handle!==handle)return;
        const {rect,x,y}=resizing;
        const dx=event.clientX-x,dy=event.clientY-y;
        const west=edge.includes('w'),north=edge.includes('n');
        const width=rect.width+(west?-dx:edge.includes('e')?dx:0);
        const height=rect.height+(north?-dy:edge.includes('s')?dy:0);
        if(!floating){setDockSize(node,width,height);return;}
        const margin=innerWidth<=800?16:24;
        const maxRight=innerWidth-margin;
        const maxBottom=innerHeight-(document.querySelector('.handoff-taskbar')?.offsetHeight||64)-margin;
        const right=west?rect.right:maxRight,bottom=north?rect.bottom:maxBottom;
        const left=west?margin:rect.left,top=north?margin:rect.top;
        const w=clamp(width,Math.min(300,right-left),right-left);
        const h=clamp(height,Math.min(250,bottom-top),bottom-top);
        applyBox('agent',{x:west?rect.right-w:rect.left,y:north?rect.bottom-h:rect.top,width:w,height:h});
      };
      handle.onpointerup=handle.onpointercancel=handle.onlostpointercapture=finishGesture;
      target.append(handle);
    }
  }
  function controls(id){const bar=document.createElement('header');bar.className='handoff-window-bar';
    const title=document.createElement('strong');title.textContent=titles[id];title.tabIndex=0;title.setAttribute('role','button');title.title='이동 창에서 드래그 또는 방향키로 이동 · Shift+방향키로 크기 조절';title.setAttribute('aria-label',titles[id]+' 창 조절: Enter로 이동 창 열기, 방향키 이동, Shift와 방향키로 크기 조절');bar.append(title);
    const actions=document.createElement('div');actions.className='handoff-window-actions';actions.setAttribute('role','group');actions.setAttribute('aria-label',titles[id]+' 창 관리');bar.append(actions);
    for(const [label,action] of [['이동 창',()=>float(id)],['기본 위치',()=>{delete layout[id];dock(id);}],['왼쪽 도킹',()=>dock(id,'left')],['오른쪽 도킹',()=>dock(id,'right')],['별도 창',()=>detach(id)],['최소화',()=>{layout[id]={...layout[id],resumeMode:layout[id]?.mode==='float'?'float':'dock',mode:'minimized'};save();a.repaint();}]]){
      const b=document.createElement('button');b.type='button';b.className='handoff-window-icon';b.setAttribute('aria-label',label);b.title=label;b.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'+icons[label]+'</svg>';b.onclick=action;actions.append(b);
    }
    title.onpointerdown=e=>{if(e.button!==0||layout[id]?.mode!=='float')return;const p=ensure(id);p.shell.style.zIndex=++z;moving={id,x:e.clientX,y:e.clientY,x0:layout[id].x,y0:layout[id].y};title.setPointerCapture(e.pointerId);e.preventDefault();};
    title.onpointermove=e=>{if(moving?.id===id)applyBox(id,{...layout[id],x:moving.x0+(e.clientX-moving.x),y:moving.y0+(e.clientY-moving.y)});};
    title.onpointerup=title.onpointercancel=title.onlostpointercapture=finishGesture;
    title.onkeydown=e=>{
      if(e.key==='Enter'||e.key===' '){e.preventDefault();if(layout[id]?.mode!=='float')float(id);return;}
      const axis={ArrowLeft:['x','width',-1],ArrowRight:['x','width',1],ArrowUp:['y','height',-1],ArrowDown:['y','height',1]}[e.key];
      if(!axis||layout[id]?.mode!=='float')return;e.preventDefault();const key=axis[e.shiftKey?1:0];applyBox(id,{...layout[id],[key]:layout[id][key]+axis[2]*(e.altKey?40:10)});save();
    };
    return bar;
  }
  function splitMetrics(node){
    const resources=node.querySelector(':scope > .ws-resource-region'),chat=node.querySelector(':scope > .fig-chat-panel');
    if(!resources||!chat)return null;
    const style=node.ownerDocument.defaultView.getComputedStyle(node);
    const other=[...node.children].filter(el=>el!==resources&&el!==chat).reduce((sum,el)=>{const css=node.ownerDocument.defaultView.getComputedStyle(el);return sum+el.getBoundingClientRect().height+parseFloat(css.marginTop||0)+parseFloat(css.marginBottom||0);},0);
    const minChat=Math.max(192,(chat.querySelector('.fig-chat-compose')?.offsetHeight||80)+(chat.querySelector('.fig-chat-status')?.offsetHeight||28)+64);
    // Sources keep at least 80px (scroll cue shows more) so the composer fits the
    // sticky panel with the 100/50px PC margins at a 900px-tall viewport.
    const minSources=80;
    const available=Math.max(minChat+minSources,node.clientHeight-other-parseFloat(style.paddingTop||0)-parseFloat(style.paddingBottom||0));
    return {resources,chat,available,minChat,maxChat:available-minSources};
  }
  function applyChatSplit(node,requested=layout.agent?.chatHeight){
    const m=splitMetrics(node);if(!m)return;
    const picker=m.resources.querySelector('.fig-shared-agent-picker'),pickerEnd=picker?picker.getBoundingClientRect().bottom-m.resources.getBoundingClientRect().top+m.resources.scrollTop+8:0;const preferred=Number.isFinite(requested)?requested:m.available-Math.max(Math.min(m.resources.scrollHeight,m.available*.30),Math.min(pickerEnd,m.available*.34));
    const chatHeight=clamp(preferred,m.minChat,m.maxChat),resourceHeight=m.available-chatHeight;
    node.style.setProperty('--handoff-resource-height',resourceHeight+'px');node.style.setProperty('--handoff-chat-height',chatHeight+'px');
    const handle=node.querySelector('.handoff-chat-separator');if(handle){handle.setAttribute('aria-valuemin',String(Math.round(m.minChat)));handle.setAttribute('aria-valuemax',String(Math.round(m.maxChat)));handle.setAttribute('aria-valuenow',String(Math.round(chatHeight)));handle.setAttribute('aria-valuetext','대화 '+Math.round(chatHeight)+'픽셀, 자료 '+Math.round(resourceHeight)+'픽셀');}
    return {...m,chatHeight};
  }
  function changeChatHeight(node,height){
    const m=applyChatSplit(node,height);if(!m)return;
    layout.agent={mode:'dock',where:'right',...layout.agent,chatHeight:m.chatHeight};
    const source=ensure('agent').node;if(source&&source!==node)applyChatSplit(source,m.chatHeight);
  }
  function installChatSplit(node){
    const resources=node?.querySelector(':scope > .ws-resource-region'),chat=node?.querySelector(':scope > .fig-chat-panel');if(!resources||!chat)return;
    node.dataset.chatSplit='true';resources.id='handoff-agent-resources';chat.id='handoff-agent-chat';
    let handle=node.querySelector(':scope > .handoff-chat-separator');
    if(!handle){handle=node.ownerDocument.createElement('div');handle.className='handoff-chat-separator';handle.tabIndex=0;handle.setAttribute('role','separator');handle.setAttribute('aria-orientation','horizontal');handle.setAttribute('aria-label','자료와 대화 높이 조절');handle.setAttribute('aria-controls','handoff-agent-resources handoff-agent-chat');handle.title='위아래로 드래그 · 위/아래 방향키로 대화 높이 조절 · Enter로 초기화';handle.innerHTML='<span aria-hidden="true"></span>';resources.after(handle);}
    handle.onpointerdown=e=>{if(e.button!==0)return;const m=applyChatSplit(node);if(!m)return;splitting={node,y:e.clientY,height:m.chatHeight};handle.setPointerCapture(e.pointerId);e.preventDefault();};
    handle.onpointermove=e=>{if(splitting?.node===node)changeChatHeight(node,splitting.height+splitting.y-e.clientY);};
    handle.onpointerup=handle.onpointercancel=handle.onlostpointercapture=finishGesture;
    handle.onkeydown=e=>{if(!['ArrowUp','ArrowDown','Home','End','Enter'].includes(e.key))return;e.preventDefault();const m=applyChatSplit(node);if(!m)return;if(e.key==='Enter'){if(layout.agent)delete layout.agent.chatHeight;applyChatSplit(node);if(ensure('agent').node!==node)applyChatSplit(ensure('agent').node);}else changeChatHeight(node,e.key==='Home'?m.minChat:e.key==='End'?m.maxChat:m.chatHeight+(e.key==='ArrowUp'?1:-1)*(e.shiftKey?32:8));save();};
    applyChatSplit(node);
    return handle;
  }
  function installAgentTabs(node, notify=true){
    const bar=node?.querySelector(':scope > .ws-agent-tabs');if(!bar||bar.dataset.bound==='true')return;
    bar.dataset.bound='true';
    const activate=key=>{for(const tab of bar.querySelectorAll('[data-agent-view]')){const active=tab.dataset.agentView===key;tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;const panel=node.querySelector('#'+tab.getAttribute('aria-controls'));if(panel)panel.hidden=!active;}};
    bar.addEventListener('click',event=>{const tab=event.target.closest('[data-agent-view]');if(tab){activate(tab.dataset.agentView);if(notify)a.selectAgentView?.(tab.dataset.agentView);}});
    bar.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;const tabs=[...bar.querySelectorAll('[data-agent-view]')],index=tabs.indexOf(event.target.closest('[data-agent-view]'));if(index<0)return;event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?tabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;tabs[next].focus();activate(tabs[next].dataset.agentView);if(notify)a.selectAgentView?.(tabs[next].dataset.agentView);});
    activate(bar.querySelector('[aria-selected=true]')?.dataset.agentView||'agent');
  }
  function detach(id){
    const p=ensure(id);if(p.popup&&!p.popup.closed){p.popup.focus();return;}
    const pop=window.open(new URL('workspace-view.html',location.href).href,'whatif-'+task+'-'+id,'popup,width=650,height=850');
    if(!pop){note='새 창이 차단되어 내부 이동 창으로 열었습니다. 브라우저에서 팝업 허용 후 다시 분리할 수 있습니다.';float(id);return;}
    p.popup=pop;layout[id]={...layout[id],mode:'popup'};a.keepAgent();
    const setup=()=>{const d=pop.document;if(!d.body||d.URL==='about:blank'||d.body.dataset.ready)return;d.body.dataset.ready='true';d.body.replaceChildren();d.title=titles[id]+' · WHAT IF';d.documentElement.lang='ko';
    const base=d.createElement('base');base.href=location.href;d.head.append(base);
    const viewport=d.createElement('meta');viewport.name='viewport';viewport.content='width=device-width,initial-scale=1';d.head.append(viewport);
    for(const name of ['scenario-window.css','scenario-workspace.css','handoff-base.css','handoff-windows.css','handoff-common.css','scenario-layout.css']){const link=d.createElement('link');link.rel='stylesheet';link.href=new URL('assets/'+name,location.href).href;d.head.append(link);}
    d.body.className='handoff-popup';const bar=d.createElement('header');bar.className='handoff-popup-bar';
    const back=d.createElement('button');back.type='button';back.textContent='메인 창으로 복귀';back.onclick=()=>dock(id);
    const status=d.createElement('span');status.textContent='같은 작업에 연결됨 · 요청은 메인 창에서 한 번만 실행';bar.append(back,status);d.body.append(bar);
    const view=d.createElement('main');view.className='handoff-popup-content';d.body.append(view);
    for(const type of ['click','input','change','keydown','toggle'])view.addEventListener(type,event=>{
      if(event.target.closest?.('.handoff-chat-separator'))return;
      const el=event.target.closest?.('[data-window-bridge]');if(!el)return;
      const target=p.node?.querySelector('[data-window-bridge="'+el.dataset.windowBridge+'"]');
      if(!target?.isConnected||!a.authenticated()){event.preventDefault();return;}
      if(type==='click'){
        if(el.closest('a[href]'))return;
        if(el.matches('input,textarea,select'))return;
        event.preventDefault();target.click();
        if(document.querySelector('dialog[open],.fig-doc-modal,.fig-asset-modal-layer'))window.focus();
      }else if(type==='toggle'){if(el.tagName==='DETAILS'){target.open=el.open;target.dispatchEvent(new Event('toggle'));}}
      else if(type==='keydown'){if(!['Enter','Escape'].includes(event.key))return;const e=new KeyboardEvent('keydown',{key:event.key,shiftKey:event.shiftKey,bubbles:true,cancelable:true});target.dispatchEvent(e);if(e.defaultPrevented)event.preventDefault();}
      else{if('value' in target)target.value=el.value;if('checked' in target)target.checked=el.checked;target.dispatchEvent(new Event(type,{bubbles:true}));}
    },true);
    pop.addEventListener('resize',()=>{if(id==='agent'&&view.firstElementChild)applyChatSplit(view.firstElementChild);});
    pop.addEventListener('blur',finishGesture);
    // Closing a view re-docks; it never terminates a computation or duplicates it.
    pop.addEventListener('pagehide',()=>{if(p.popup===pop){p.popup=null;layout[id]={...layout[id],mode:'dock',where:id==='portfolio'?'default':'right'};save();setTimeout(a.repaint,0);}});
    save();a.repaint();};
    pop.addEventListener('load',setup,{once:true});
    const wait=setInterval(()=>{if(pop.closed){clearInterval(wait);return;}try{if(pop.document.URL!=='about:blank'&&pop.document.readyState==='complete'){clearInterval(wait);setup();}}catch{clearInterval(wait);}},100);
  }
  function syncPopup(p){
    if(!p.popup||p.popup.closed||!p.node||splitting)return;
    const d=p.popup.document,view=d.querySelector('main');if(!view)return;
    const focused=d.activeElement,key=focused?.dataset.windowSlot,tag=focused?.tagName,caret=focused?.selectionStart;
    const rootScroll={top:view.firstElementChild?.scrollTop||0,left:view.firstElementChild?.scrollLeft||0};
    const scrolls=[...view.querySelectorAll('[data-window-slot]')].filter(x=>x.scrollTop||x.scrollLeft).map(x=>[x.dataset.windowSlot,x.scrollTop,x.scrollLeft]);
    // Old mirrored controls cannot address a newly rendered unrelated control.
    const revision=crypto.randomUUID();
    p.node.querySelectorAll('*').forEach((x,i)=>{x.dataset.windowSlot=String(i);x.dataset.windowBridge=revision+'-'+i;});
    const copy=p.node.cloneNode(true);copy.classList.remove('handoff-hidden-view');copy.querySelectorAll('.handoff-window-bar').forEach(x=>x.remove());
    for(const field of p.node.querySelectorAll('input,select,textarea')){const twin=copy.querySelector('[data-window-bridge="'+field.dataset.windowBridge+'"]');if(twin){twin.value=field.value;twin.checked=field.checked;}}
    view.replaceChildren(copy);
    if(p.id==='agent'){const tabs=copy.querySelector('.ws-agent-tabs');if(tabs)delete tabs.dataset.bound;installAgentTabs(copy,false);}
    copy.scrollTop=rootScroll.top;copy.scrollLeft=rootScroll.left;
    for(const [id,top,left] of scrolls){const el=view.querySelector('[data-window-slot="'+id+'"]');if(el){el.scrollTop=top;el.scrollLeft=left;}}
    const next=key&&view.querySelector('[data-window-slot="'+key+'"]');if(next&&next.tagName===tag){next.focus({preventScroll:true});if(caret!=null&&next.setSelectionRange)try{next.setSelectionRange(caret,caret);}catch{}}
  }
  function beforeRender(){
    // Live data can refresh while a pointer owns the title/resize handle. Keep
    // that DOM alive until release, then paint the latest shared application state.
    if(moving||resizing||splitting){pendingRender=true;return false;}
    painting=true;
    for(const p of panels.values()){
      p.observer?.disconnect();p.resize?.disconnect();p.splitResize?.disconnect();p.popupSplitResize?.disconnect();
      if(p.id==='portfolio'&&p.node){const table=p.node.querySelector('[data-live-scroll]');p.scroll={top:p.node.scrollTop,tableTop:table?.scrollTop||0,tableLeft:table?.scrollLeft||0};}
      if(p.node&&p.placeholder?.isConnected)p.placeholder.replaceWith(p.node);
      if(p.id==='result'&&p.node?.parentElement===document.body)p.node.remove();
      p.node?.querySelectorAll(':scope > .agent-resize-edge').forEach(handle=>handle.remove());
      p.node?.classList.remove('handoff-hidden-view');p.node?.querySelector('.handoff-window-bar')?.remove();
      p.shell?.remove();p.shell=null;p.placeholder=null;
    }
    document.querySelector('.handoff-taskbar')?.remove();document.querySelector('.handoff-analysis-actions')?.remove();
    return true;
  }
  function mount(){
    const screen=document.querySelector('.ws-scenario-overlay .fig-scenario-screen');
    const agent=document.querySelector('.ws-side-panel');
    const globalHost=agent?.closest('.ws-global-host');
    const result=resultRequested?a.resultPanel():null;
    const portfolio=screen?.querySelector('.fig-live-state-panel')||((layout.portfolio&&layout.portfolio.mode!=='dock')?a.portfolioPanel?.():null);
    if(result&&screen)screen.append(result);
    for(const [id,node] of [['agent',agent],['result',result],['portfolio',portfolio]]){
      const p=ensure(id);p.node=node;if(!node)continue;
      let l=layout[id]||{mode:'dock',where:id==='portfolio'?'default':'right'};
      if(screen&&l.automaticFloat)l=layout[id]={...l,mode:'dock',automaticFloat:false};
      if(id==='agent'&&globalHost&&l.mode!=='dock')globalHost.style.setProperty('display','none','important');
      // Minimizing the main analysis preserves its result task. Dock it back when
      // the analysis returns; do not rewrite the user's saved docking choice.
      if(id==='result'&&!screen&&l.mode==='dock')l=layout[id]={...l,...box(l),mode:'float',automaticFloat:true};
      if(l.mode==='popup'&&(!p.popup||p.popup.closed)){l=layout[id]={...l,...box(l),mode:'float'};note='별도 창은 클릭해서 다시 열어 주세요. 저장된 배치는 내부 창으로 복원했습니다.';}
      node.prepend(controls(id));node.dataset.handoffPanel=id;
      if(l.mode==='dock'){
        node.dataset.dock=l.where||'right';
        if(id==='agent'&&screen){
          if(l.dockWidth||l.dockHeight)setDockSize(node,l.dockWidth||agentSize.width,l.dockHeight||agentSize.height);
          resizeEdges(node,node,false);
        }
      }
      else{
        if(id==='result'&&!node.isConnected)document.body.append(node);
        p.placeholder=document.createElement('section');p.placeholder.className='handoff-window-placeholder';p.placeholder.dataset.windowPanel=id;p.placeholder.textContent=titles[id]+(l.mode==='minimized'?' 최소화됨':' · 별도 작업창에서 사용 중');
        const returnButton=document.createElement('button');returnButton.textContent='여기로 복귀';returnButton.onclick=()=>dock(id);p.placeholder.append(returnButton);node.replaceWith(p.placeholder);
        const shell=document.createElement('section');shell.className='handoff-floating fig-scenario-screen';shell.dataset.windowPanel=id;shell.setAttribute('aria-label',titles[id]+' 작업창');shell.append(node);document.body.append(shell);p.shell=shell;
        if(l.mode==='float'){
          layout[id]=l;applyBox(id,l);shell.style.zIndex=++z;
          if(id==='agent')resizeEdges(node,shell,true);
          else {
          shell.addEventListener('pointerdown',e=>{shell.style.zIndex=++z;const rect=shell.getBoundingClientRect();if(e.button===0&&e.clientX>=rect.right-24&&e.clientY>=rect.bottom-24)resizing=id;});
          let first=true;p.resize=new ResizeObserver(()=>{if(first){first=false;return;}if(p.shell===shell&&shell.isConnected&&!painting){const b=box({...layout[id],width:shell.offsetWidth,height:shell.offsetHeight});if(b.width!==layout[id].width||b.height!==layout[id].height||b.x!==layout[id].x||b.y!==layout[id].y){applyBox(id,b);save();}}});p.resize.observe(shell);
          }
        }else{shell.classList.add('handoff-hidden-view');}
      }
      if(id==='agent')installAgentTabs(node);
      if(l.mode==='popup')syncPopup(p);
      let scheduled=false;p.observer=new MutationObserver(records=>{if(painting||scheduled||records.every(r=>r.attributeName==='data-window-bridge'))return;scheduled=true;setTimeout(()=>{scheduled=false;if(p.popup&&!p.popup.closed){p.observer.disconnect();syncPopup(p);p.observer.observe(node,{subtree:true,childList:true,characterData:true});}},80);});p.observer.observe(node,{subtree:true,childList:true,characterData:true});
      if(id==='portfolio'&&p.scroll){node.scrollTop=p.scroll.top;const table=node.querySelector('[data-live-scroll]');if(table){table.scrollTop=p.scroll.tableTop;table.scrollLeft=p.scroll.tableLeft;}}
    }
    if(screen){const actions=document.createElement('nav');actions.className='handoff-analysis-actions';actions.setAttribute('aria-label','분석창 관리');
      for(const [text,fn] of [['분석 최소화',a.minimize],['분석 종료 · 엔진 연결 해제',()=>{resultRequested=false;delete layout.result;note='';a.closeAnalysis();}]]){const b=document.createElement('button');b.type='button';b.textContent=text;b.onclick=()=>{note='';fn();};actions.append(b);}{const home=screen.querySelector(':scope > .fig-home');if(home)home.after(actions);else screen.prepend(actions);}
    }
    if(a.active()){
      const bar=document.createElement('nav');bar.className='handoff-taskbar';bar.setAttribute('aria-label','열린 작업');
      for(const [label,fn] of [['시나리오 분석',a.openAnalysis],['뿌꾸 AI Agent',()=>{a.keepAgent();dock('agent');}],['나의 포트폴리오',()=>{const p=ensure('portfolio');if(p.popup&&!p.popup.closed){p.popup.focus();return;}if(layout.portfolio?.mode==='float'||layout.portfolio?.resumeMode==='float'||!screen)float('portfolio');else dock('portfolio');}],['결과 분석',()=>{resultRequested=true;if(!a.resultPanel()){note='실행된 분석 결과가 없습니다.';return a.repaint();}if(screen)dock('result');else float('result');}]]){const b=document.createElement('button');b.type='button';b.textContent=label;b.onclick=fn;bar.append(b);}
      const status=document.createElement('span');status.setAttribute('role','status');status.textContent=note||a.status();bar.append(status);document.body.append(bar);
    }
    painting=false;
    // The taskbar may wrap after a narrow viewport change; keep every title and
    // resize corner inside the remaining work area after its real height is known.
    for(const [id,l] of Object.entries(layout))if(l.mode==='float')applyBox(id,l);
  }
  addEventListener('pointerup',finishGesture);addEventListener('pointercancel',finishGesture);addEventListener('blur',finishGesture);
  addEventListener('resize',()=>{for(const [id,l] of Object.entries(layout))if(l.mode==='float')applyBox(id,l);});
  addEventListener('pagehide',()=>{for(const p of panels.values())if(p.popup&&!p.popup.closed){const view=p.popup.document.querySelector('main');view?.replaceChildren();const text=p.popup.document.createElement('p');text.textContent='메인 작업이 닫혔습니다. 이 창에서는 더 이상 요청하지 않습니다. 메인 페이지에서 다시 열어 주세요.';view?.append(text);}});
  return {beforeRender,mount,capture:()=>structuredClone(layout),restore:value=>{if(!value||typeof value!=='object')return;for(const id of ['agent','result','portfolio']){const v=value[id];if(v&&['dock','float','popup','minimized'].includes(v.mode))layout[id]={...box(id==='agent'?{...agentSize,...v}:v),mode:v.mode,where:['left','right'].includes(v.where)?v.where:id==='portfolio'?'default':'right',resumeMode:v.resumeMode==='float'?'float':'dock',...(id==='agent'&&Number.isFinite(v.dockWidth)&&Number.isFinite(v.dockHeight)?{dockWidth:v.dockWidth,dockHeight:v.dockHeight}:{})};}},closeViews:()=>{resultRequested=false;moving=null;resizing=null;splitting=null;pendingRender=false;for(const p of panels.values()){p.observer?.disconnect();p.resize?.disconnect();p.splitResize?.disconnect();p.popupSplitResize?.disconnect();const pop=p.popup;p.popup=null;pop?.close();p.shell?.remove();}layout={};}};
};
