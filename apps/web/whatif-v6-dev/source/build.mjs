import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const inputs=fs.readdirSync(path.join(root,'assets')).filter(n=>n.endsWith('.png')&&!n.startsWith('._')&&n!=='.DS_Store').sort();
const font=fs.readFileSync(path.join(root,'assets/fonts/Pretendard-Regular.otf'));
const boldFont=fs.readFileSync(path.join(root,'assets/fonts/Pretendard-Bold.otf'));
const fontLicense=fs.readFileSync(path.join(root,'assets/fonts/Pretendard-LICENSE.txt'),'utf8');
const data={},external={},manifest=[];
for(const file of inputs){const bytes=fs.readFileSync(path.join(root,'assets',file)),id=file.slice(0,-4);data[id]='data:image/png;base64,'+bytes.toString('base64');external[id]='assets/'+file;manifest.push({id,file:'assets/'+file,bytes:bytes.length});}
const source=fs.readFileSync(path.join(root,'src/base-v3.9.html'),'utf8');
const scripts=['geometry.js','game.js','agent-contract.js','popup.js','chat-engine.js','v42.js','ppukku.js','myroom-v44.js','forecast-interval511.js','chart-period512-core.js','chart-v45.js','notebook-v45.js','newsprint.js','aged-newsprint.js','newspaper-fix.js','light-clipboard.js','apricot-v47.js','meeting-v48.js','travel-v49.js','archive-v50.js','stability-v51.js','sound-private-v52.js','preview-chat-v52.js','hud-v53.js','fullbleed-v54.js','personal-v55.js','wide-v56.js','service-v57.js','polish-v58.js','interaction-v59.js','paper-v510.js','chart-v511.js','chart-v512.js','live-v60.js','service-copy60.js','scenario-reference-v61.js'].map(f=>fs.readFileSync(path.join(root,'src',f),'utf8').replaceAll('V4.0','V4.2').replaceAll('V4.1','V4.2').replaceAll("'4.0.0'","'4.2.0'").replaceAll("'4.1.0'","'4.2.0'").replaceAll('V4.2','V4.3').replaceAll("'4.2.0'","'4.3.0'").replaceAll('V4.3','V4.4').replaceAll("'4.3.0'","'4.4.0'").replaceAll('V4.4','V4.5').replaceAll("'4.4.0'","'4.5.0'").replaceAll('V4.5','V4.5.1').replaceAll("'4.5.0'","'4.5.1'").replaceAll('V4.5.1','V4.5.2').replaceAll("'4.5.1'","'4.5.2'").replaceAll("V4.5.2","V4.5.3").replaceAll("'4.5.2'","'4.5.3'").replaceAll("V4.5.3","V4.6").replaceAll("'4.5.3'","'4.6.0'").replaceAll("Galmuri","Pretendard").replaceAll("V4.6","V4.7").replaceAll("'4.6.0'","'4.7.0'").replaceAll("V4.7","V4.8").replaceAll("'4.7.0'","'4.8.0'").replaceAll('V4.8','V4.9').replaceAll("'4.8.0'","'4.9.0'").replaceAll('V4.9','V5.5').replaceAll("'4.9.0'","'5.5.0'").replaceAll('V5.5','V5.5').replaceAll("'5.5.0'","'5.5.0'"));
for(let i=0;i<scripts.length;i++)scripts[i]=scripts[i].replaceAll('V5.4','V5.5').replaceAll("'5.4.0'","'5.5.0'").replaceAll('V5.3','V5.5').replaceAll("'5.3.0'","'5.5.0'").replaceAll('V5.2','V5.5').replaceAll("'5.2.0'","'5.5.0'").replaceAll('V5.1','V5.5').replaceAll("'5.1.0'","'5.5.0'").replaceAll('V5.0','V5.5').replaceAll("'5.0.0'","'5.5.0'");
for(let i=0;i<scripts.length;i++)scripts[i]=scripts[i].replaceAll('V5.5','V5.6').replaceAll("'5.5.0'","'5.6.0'");
for(let i=0;i<scripts.length;i++)scripts[i]=scripts[i].replaceAll('V5.6','V5.7').replaceAll("'5.6.0'","'5.7.0'");
for(let i=0;i<scripts.length;i++)scripts[i]=scripts[i].replaceAll('V5.7','V5.8').replaceAll("'5.7.0'","'5.8.0'");
for(let i=0;i<scripts.length;i++)scripts[i]=scripts[i].replaceAll('V5.8','V5.9').replaceAll("'5.8.0'","'5.9.0'");
for(let i=0;i<scripts.length;i++)scripts[i]=scripts[i].replaceAll('V5.9','V5.10').replaceAll("'5.9.0'","'6.0.0'");
for(let i=0;i<scripts.length;i++)scripts[i]=scripts[i].replaceAll('V5.10','V5.11').replaceAll("'5.10.0'","'6.0.0'").replaceAll('OHLC 바','OHLC');
for(let i=0;i<scripts.length;i++)scripts[i]=scripts[i].replaceAll('V5.11','V5.12').replaceAll("'5.11.0'","'6.0.0'");
for(let i=0;i<scripts.length;i++)scripts[i]=scripts[i].replaceAll('V5.12','V6.0').replaceAll("'5.12.0'","'6.0.0'");
const uiIcons=Object.fromEntries(fs.readdirSync(path.join(root,'assets/ui51')).filter(f=>f.endsWith('.svg')&&!f.startsWith('._')&&f!=='.DS_Store').map(f=>[f.slice(0,-4),fs.readFileSync(path.join(root,'assets/ui51',f),'utf8')]));
function make(assets,embedded){
 let html=source.replace('<head>','<head><meta name="whatif-prompt-version" content="1.6-r2">').replaceAll('let offset=0,span=65','let offset=0,span=110').replaceAll('offset=0;span=65','offset=0;span=110').replace("window.addEventListener('whatif-chart-view',render);","window.addEventListener('whatif-chart-view',()=>render());");
 html=html.replace('let go=','let go=');
 const anchor=html.lastIndexOf('\nS.researchRevision=1;');if(anchor<0)throw new Error('Missing injection anchor');
 html=html.slice(0,anchor)+'\nconst GX_CONTENT57='+JSON.stringify({faq:JSON.parse(fs.readFileSync(path.join(root,'content/faq57.json'),'utf8')),snapshot:JSON.parse(fs.readFileSync(path.join(root,'content/market-snapshot57.json'),'utf8'))})+';\nconst GX_UI_ICONS='+JSON.stringify(uiIcons)+';\nconst GX_SFX='+JSON.stringify(Object.fromEntries(['click','step'].map(k=>[k,embedded?'data:audio/wav;base64,'+fs.readFileSync(path.join(root,'assets',k==='click'?'pixel_select_sfx.wav':'pixel_footstep_light_loop.wav')).toString('base64'):'assets/'+(k==='click'?'pixel_select_sfx.wav':'pixel_footstep_light_loop.wav')])))+';\nconst GX_MEDIA='+JSON.stringify({travel:embedded?'data:video/mp4;base64,'+fs.readFileSync(path.join(root,'assets/time_travel49.mp4')).toString('base64'):'assets/time_travel49.mp4'})+';\nconst GX_ASSETS='+JSON.stringify(assets)+';\n'+scripts.join('\n')+'\n'+html.slice(anchor);
 html=html.replace('const go=','let go=');
 html=html.replace("render();document.querySelector('.simulation-workspace')?.scrollIntoView({behavior:'smooth',block:'start'});","render();");
 let css=fs.readFileSync(path.join(root,'src/game.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/popup.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/v42.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/ppukku.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/myroom-v44.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/notebook-v45.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/newsprint.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/aged-newsprint.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/newspaper-fix.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/light-clipboard.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/apricot-v47.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/meeting-v48.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/travel-v49.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/archive-v50.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/stability-v51.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/sound-private-v52.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/hud-v53.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/fullbleed-v54.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/personal-v55.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/wide-v56.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/service-v57.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/polish-v58.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/interaction-v59.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/paper-v510.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/chart-v511.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/chart-v512.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/live-v60.css'),'utf8')+'\n'+fs.readFileSync(path.join(root,'src/scenario-reference-v61.css'),'utf8');
 css=css.replace(/@font-face\{[^}]*font-family:Galmuri[^}]*\}/g,'');
 const regularURL=embedded?'data:font/otf;base64,'+font.toString('base64'):'assets/fonts/Pretendard-Regular.otf';
 const boldURL=embedded?'data:font/otf;base64,'+boldFont.toString('base64'):'assets/fonts/Pretendard-Bold.otf';
 css='@font-face{font-family:Pretendard;src:url("'+regularURL+'") format("opentype");font-weight:100 599;font-display:swap}@font-face{font-family:Pretendard;src:url("'+boldURL+'") format("opentype");font-weight:600 900;font-display:swap}\n'+css;
 css=':root{--p41-frame:url("'+assets.frame+'");--p41-button:url("'+assets.button_1+'");--p41-active:url("'+assets.button_2+'")}\n'+css;
 html=html.replace(/<title>[^<]*<\/title>/,'<title>WHAT IF : TIME INVESTOR — V6.0 LIVE FORECAST GAME</title>');
 html=html.replace('</head>','<style id="whatif-game-v4-4">'+css+'</style></head>');
 html=html.replaceAll("S.appVersion='3.9.0'","S.appVersion='6.0.0'").replaceAll("version:'V3.9-'","version:'V6.0-'").replaceAll("appVersion:'3.7.0'","appVersion:'6.0.0'");
 for(const [from,to]of Object.entries({'김진우':'영호','신강호':'영철','윤서연':'영숙','강유나':'옥순'}))html=html.replaceAll(from,to);
 html=html.replace("const storageKey='whatif-web-demo-v1';","const storageKey='whatif-web-demo-v4';");
 html=html.replace("localStorage.getItem(storageKey)||'{}'","localStorage.getItem(storageKey)||localStorage.getItem('whatif-web-demo-v1')||'{}'");
 html=html.replace(/<script>document.addEventListener\('DOMContentLoaded',function\(\)\{var f=document.createElement\('link'\);[\s\S]*?<\/script>/,'');
 html=html.replace('</head>','<script type="application/json" id="pretendard-license">'+JSON.stringify(fontLicense).replaceAll('<','\\u003c')+'</script></head>');
 html=html.replaceAll('OHLC 바','OHLC');
 html=html.replaceAll('함께 분석하기','회의 시작하기').replaceAll('함께분석','회의실').replaceAll('마이 룸','개인실').replaceAll('마이룸','개인실');
 let m,count=0;const pattern=/<script\b([^>]*)>([\s\S]*?)<\/script>/gi;
 while((m=pattern.exec(html))){if(/application\/json/.test(m[1])||!m[2].trim())continue;new vm.Script(m[2],{filename:'inline-'+(++count)+'.js'});}
 return {html,count};
}
const dev=make(external,false);
const outputDir=path.join(root,'..','dist','whatif-v6');
fs.mkdirSync(outputDir,{recursive:true});
function syncAssets(source,destination){
 fs.mkdirSync(destination,{recursive:true});
 for(const entry of fs.readdirSync(source,{withFileTypes:true})){
  if(entry.name.startsWith('._')||entry.name==='.DS_Store')continue;
  const from=path.join(source,entry.name),to=path.join(destination,entry.name);
  if(entry.isDirectory()){syncAssets(from,to);continue;}
  const a=fs.statSync(from),b=fs.existsSync(to)?fs.statSync(to):null;
  if(!b||a.size!==b.size||a.mtimeMs!==b.mtimeMs)fs.copyFileSync(from,to);
 }
}
syncAssets(path.join(root,'assets'),path.join(outputDir,'assets'));
fs.writeFileSync(path.join(outputDir,'index.html'),dev.html);
fs.writeFileSync(path.join(outputDir,'assets/manifest.json'),JSON.stringify(manifest,null,2));
const report={version:'6.0.0',assets:inputs.length,inlineScriptsParsed:dev.count,developmentBytes:Buffer.byteLength(dev.html),output:outputDir};
fs.writeFileSync(path.join(outputDir,'build.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));
