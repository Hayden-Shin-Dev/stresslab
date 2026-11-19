/* V4.7: selected apricot-journal art direction; financial workflows stay intact. */
const AP47={paper:{document:'auto',news:'landscape'},pdfDirection:'portrait',fileSeq:0};
const ap47Render=render,ap47File=handleFile;
const ap47Action=onAction;
onAction=function(action,el){if(action==='clear-doc'){AP47.fileSeq++;AP47.pdfDirection='portrait';}return ap47Action(action,el);};
const ap47Chart=C.chartHTML;
C.chartHTML=function(options){return ap47Chart(options).replaceAll('#f8f9ec','#fffaf0').replaceAll('#cfdbc6','#ded4bf').replaceAll('#415d50','#665a4d').replaceAll('#3f7456','#285653');};

function ap47Direction(panel){
 const mode=AP47.paper[panel];
 return mode==='auto'?(panel==='document'?AP47.pdfDirection:'landscape'):mode;
}
function ap47FitPaper(feature=document.querySelector('.paper47')){
 if(!feature||!['document','news'].includes(GX.panel))return;
 const dir=ap47Direction(GX.panel),portrait=dir==='portrait',gap=innerWidth<650?12:40;
 const availableW=Math.max(240,innerWidth-gap),availableH=Math.max(240,innerHeight-gap);
 const ratio=portrait?.80:1.60;
 const height=innerWidth<650?availableH:Math.min(availableH,portrait?1100:920,availableW/ratio),width=innerWidth<650?availableW:Math.min(availableW,height*ratio);
 feature.classList.toggle('paper47-portrait',portrait);feature.classList.toggle('paper47-landscape',!portrait);
 feature.style.setProperty('--paper47-width',Math.round(width)+'px');feature.style.setProperty('--paper47-height',Math.round(height)+'px');
 feature.style.setProperty('--paper47-inset',Math.max(18,Math.round(width*.05))+'px');
 feature.style.setProperty('--paper47-view-height',Math.max(260,Math.round(height)-340)+'px');
 feature.querySelectorAll('[data-paper47]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.paper47===AP47.paper[GX.panel])));
 const status=feature.querySelector('.paper47-status');if(status)status.textContent=(portrait?'세로 문서':'가로 슬라이드')+' 맞춤';
}
function ap47Paper(feature){
 if(!feature||!['document','news'].includes(GX.panel))return;
 feature.classList.add('paper47');
 const bar=document.createElement('nav');bar.className='paper47-toolbar';bar.setAttribute('aria-label','팝업 문서 방향');
 bar.innerHTML='<div class="paper47-modes" role="group" aria-label="보기 비율">'+[['auto','자동 맞춤'],['portrait','세로 문서'],['landscape','가로 슬라이드']].map(([key,label])=>'<button type="button" data-paper47="'+key+'" aria-pressed="false">'+label+'</button>').join('')+'</div><span class="paper47-status" role="status"></span>';
 feature.querySelector('.gx-window-head').after(bar);ap47FitPaper(feature);
 bar.addEventListener('click',e=>{const button=e.target.closest('[data-paper47]');if(!button)return;AP47.paper[GX.panel]=button.dataset.paper47;gxFx('click');ap47FitPaper(feature);});
}

handleFile=async function(file){
 const seq=++AP47.fileSeq;await ap47File(file);
 if(!file||seq!==AP47.fileSeq||!S.docReady||S.docName!==file.name)return;
 AP47.pdfDirection='portrait';
 if(S.docKind==='pdf'&&window.PDFLib?.PDFDocument){
  try{
   const pdf=await PDFLib.PDFDocument.load(await file.arrayBuffer(),{updateMetadata:false});
   if(seq!==AP47.fileSeq||!S.docReady||S.docName!==file.name)return;
   const page=pdf.getPages()[0];if(page){let {width,height}=page.getSize();const angle=((page.getRotation().angle%360)+360)%360;if(angle===90||angle===270)[width,height]=[height,width];AP47.pdfDirection=width>height?'landscape':'portrait';}
  }catch{/* Unreadable/encrypted PDFs keep the document default; manual modes remain available. */}
 }
 if(seq===AP47.fileSeq&&GX.panel==='document')ap47FitPaper();
};

function ap47ChatLayout(){
 const root=document.querySelector('.ui47'),chat=root?.querySelector('.gx-chat-window');if(!root)return;
 const docked=!!chat&&!P42.manualChat&&innerWidth>=1180&&!GX.panel&&!S.modal&&!S.myroom.modal&&!GX.soundOpen;
 root.classList.toggle('ap47-chat-docked',docked);root.style.setProperty('--ap47-chat-space','432px');
 if(!chat)return;
 const world=root.querySelector('.gx-world').getBoundingClientRect();
 if(!P42.manualChat){const width=Math.min(420,innerWidth-88),height=Math.min(innerHeight-world.top-12,Math.max(300,world.height));GX.window={x:innerWidth-width-12,y:world.top,w:width,h:height};Object.assign(chat.style,{left:GX.window.x+'px',top:GX.window.y+'px',width:width+'px',height:height+'px'});}
 else{GX.window=gxClampWindow(GX.window,innerWidth,innerHeight);Object.assign(chat.style,{left:GX.window.x+'px',top:GX.window.y+'px',width:GX.window.w+'px',height:GX.window.h+'px'});}
}
render=function(){
 ap47Render();
 if(GX.phase!=='game'){document.querySelector('.gx-launch')?.classList.add('ap47-launch');return;}
 S.appVersion='4.7.0';const root=document.querySelector('.ui46');if(!root)return;root.classList.add('ui47');
 const agent=P41.tab==='agent'&&GX.room==='office';root.setAttribute('data-agent-open',String(agent));
 root.querySelector('.p41-main-tabs [data-panel="sim"]')?.classList.toggle('active',agent);
 const feature=root.querySelector('.p41-feature');if(feature)ap47Paper(feature);
 const grip=root.querySelector('.gx-chat-grip'),title=grip?.querySelector('strong');
 if(title){const subtitle=document.createElement('small');subtitle.className='ap47-chat-subtitle';subtitle.textContent='무엇을 함께 살펴볼까요?';title.appendChild(subtitle);}
 const chat=root.querySelector('.gx-chat-window');if(chat)chat.setAttribute('aria-label','뿌꾸 AI 챗봇');
 root.querySelectorAll('.gx-rail button').forEach(button=>{const label=button.querySelector('span');if(label&&button.dataset.room==='myroom')label.textContent='마이룸';});
 ap47ChatLayout();
 if(chat?.querySelector('.chat-welcome')){const scroll=chat.querySelector('.chat-messages');if(scroll)scroll.scrollTop=0;}
};
window.addEventListener('resize',()=>{if(GX.phase==='game'){ap47FitPaper();ap47ChatLayout();}});
window.WHATIF_QA.paper47=()=>({mode:AP47.paper[GX.panel],direction:ap47Direction(GX.panel),pdfDirection:AP47.pdfDirection});
