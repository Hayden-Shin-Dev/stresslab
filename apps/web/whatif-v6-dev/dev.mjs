import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const root=path.dirname(fileURLToPath(import.meta.url));
const source=path.join(root,'source');
const dist=path.join(root,'dist');
const port=Number(process.env.PORT||4213);
const host=process.env.FIGMA?(process.env.FIGMA_DEV_SERVER_HOST||'0.0.0.0'):'127.0.0.1';
const clients=new Set();
let rebuilding=false;

function build(){
  if(rebuilding)return false;
  rebuilding=true;
  const result=spawnSync(process.execPath,[path.join(source,'build.mjs')],{cwd:root,encoding:'utf8',stdio:'pipe'});
  rebuilding=false;
  if(result.status!==0){console.error(result.stderr||result.stdout||'Build failed');return false;}
  console.log(result.stdout.trim());
  for(const response of clients)response.write('data: reload\n\n');
  return true;
}

if(!build())process.exit(1);

const mime={'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.json':'application/json; charset=utf-8','.png':'image/png','.svg':'image/svg+xml','.wav':'audio/wav','.mp4':'video/mp4','.otf':'font/otf','.woff2':'font/woff2','.ttf':'font/ttf'};
const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1:'+port);
  if(url.pathname==='/__dev/events'){
    res.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-cache','Connection':'keep-alive'});
    res.write(': connected\n\n');clients.add(res);req.on('close',()=>clients.delete(res));return;
  }
  if(url.pathname.startsWith('/api/')){
    res.writeHead(503,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
    return res.end(JSON.stringify({error:'preview_backend_not_connected',message:'로컬 화면 미리보기입니다. StressLab 개발 API 연결은 어댑터 작업 후 설정합니다.'}));
  }
  let pathname;
  try{pathname=decodeURIComponent(url.pathname);}catch{return res.writeHead(400).end();}
  if(pathname==='/'||pathname==='/whatif-v6'||pathname==='/whatif-v6/')pathname='/whatif-v6/index.html';
  const file=path.resolve(dist,'.'+pathname);
  if(!file.startsWith(dist+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile())return res.writeHead(404).end('Not found');
  const ext=path.extname(file);
  res.setHeader('Content-Type',mime[ext]||'application/octet-stream');
  res.setHeader('Cache-Control','no-store');
  if(ext==='.html'){
    const html=fs.readFileSync(file,'utf8').replace('</body>','<script>new EventSource("/__dev/events").onmessage=()=>location.reload()</script></body>');
    return res.end(html);
  }
  fs.createReadStream(file).pipe(res);
});

server.listen(port,host,()=>console.log(`WHAT IF V6 preview: http://${host}:${port}/whatif-v6/`));

const watcher=fs.watch(source,{recursive:true},(_event,filename)=>{
  if(!filename||! /\.(html|css|js|json|png|svg|wav|mp4|otf|woff2|ttf)$/i.test(String(filename)))return;
  clearTimeout(watcher.timer);
  watcher.timer=setTimeout(()=>build(),700);
});
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>{watcher.close();server.close(()=>process.exit(0));});
