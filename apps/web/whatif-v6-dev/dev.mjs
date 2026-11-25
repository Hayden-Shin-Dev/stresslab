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
const apiOriginInput=process.env.WHATIF_DEV_API_ORIGIN||'https://red-field-0b8ece310.1.azurestaticapps.net';
const apiOrigin=new URL(apiOriginInput).origin;
const apiRoutes=new Set(['/api/quotes/latest','/api/quotes/negotiate','/api/market-state/current','/api/market-state/stock-prices','/api/market-state/negotiate']);
const authRoutes=new Set(['/.auth/me','/.auth/login/google','/.auth/login/google/callback','/.auth/login/entra','/.auth/login/entra/callback','/.auth/complete','/.auth/logout']);
const clients=new Set();
let rebuilding=false;

const parsedApiOrigin=new URL(apiOrigin);
if(!['http:','https:'].includes(parsedApiOrigin.protocol)||parsedApiOrigin.username||parsedApiOrigin.password)throw new Error('WHATIF_DEV_API_ORIGIN must be an HTTP(S) origin without credentials.');

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
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://127.0.0.1:'+port);
  if(url.pathname==='/__dev/events'){
    res.writeHead(200,{'Content-Type':'text/event-stream','Cache-Control':'no-cache','Connection':'keep-alive'});
    res.write(': connected\n\n');clients.add(res);req.on('close',()=>clients.delete(res));return;
  }
  if(url.pathname.startsWith('/api/')||url.pathname.startsWith('/.auth/')){
    const isApi=apiRoutes.has(url.pathname),isAuth=authRoutes.has(url.pathname);
    if(apiOrigin&&(isApi||isAuth)){
      if(isAuth&&req.method!=='GET'){
        res.writeHead(405,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
        return res.end(JSON.stringify({error:'method_not_allowed'}));
      }
      if(isApi&&((url.pathname.endsWith('/negotiate')&&req.method!=='POST')||(!url.pathname.endsWith('/negotiate')&&req.method!=='GET'))){
        res.writeHead(405,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
        return res.end(JSON.stringify({error:'method_not_allowed'}));
      }
      const headers={accept:'application/json'};
      if(req.headers.cookie)headers.cookie=req.headers.cookie;
      if(req.headers.authorization)headers.authorization=req.headers.authorization;
      if(isAuth){headers['x-forwarded-host']=req.headers.host||`localhost:${port}`;headers['x-forwarded-proto']='http';}
      try{
        const upstream=await fetch(new URL(url.pathname+url.search,apiOrigin),{method:req.method,headers,cache:'no-store',redirect:'manual'});
        const location=upstream.headers.get('location');
        if(isAuth&&location){
          const localOrigin=`http://${req.headers.host||`localhost:${port}`}`;
          try{
            const redirect=new URL(location,apiOrigin);
            if(redirect.origin===apiOrigin){redirect.protocol=new URL(localOrigin).protocol;redirect.host=new URL(localOrigin).host;}
            const callback=redirect.searchParams.get('redirect_uri');
            if(callback){const callbackURL=new URL(callback);if(callbackURL.pathname.startsWith('/.auth/'))redirect.searchParams.set('redirect_uri',localOrigin+callbackURL.pathname+callbackURL.search);}
            headers.location=redirect.toString();
          }catch{headers.location=location.replace(apiOrigin,localOrigin);}
        }else if(location)headers.location=location;
        const setCookies=upstream.headers.getSetCookie?.()||[];
        if(setCookies.length)headers['set-cookie']=setCookies.map(cookie=>cookie.replace(/;\s*Domain=[^;]+/ig,''));
        if(upstream.status>=300&&upstream.status<400){
          if(isAuth){res.writeHead(upstream.status,{'Cache-Control':'no-store',...(headers.location?{Location:headers.location}:{}),...(setCookies.length?{'Set-Cookie':headers['set-cookie']}: {})});return res.end();}
          res.writeHead(401,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
          return res.end(JSON.stringify({error:'authenticated_development_api_login_required',message:'개발 API 로그인 후 다시 시도하세요.'}));
        }
        res.writeHead(upstream.status,{'Content-Type':upstream.headers.get('content-type')||'application/json; charset=utf-8','Cache-Control':'no-store',...(headers.location?{Location:headers.location}:{}),...(setCookies.length?{'Set-Cookie':headers['set-cookie']}: {})});
        return res.end(Buffer.from(await upstream.arrayBuffer()));
      }catch(error){
        res.writeHead(502,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
        return res.end(JSON.stringify({error:'development_api_unavailable',message:'개발 API 연결을 확인하세요.'}));
      }
    }
    if(url.pathname.startsWith('/.auth/'))return res.writeHead(404,{'Cache-Control':'no-store'}).end('Authentication route not found');
    res.writeHead(503,{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'});
    return res.end(JSON.stringify({error:'preview_backend_not_connected',message:'실제 시세 데이터는 WHATIF_DEV_API_ORIGIN에 지정한 인증된 개발 API에서 가져옵니다.'}));
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
