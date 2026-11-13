/* Preview the same files and URL rules that are deployed to Static Web Apps.
 * Real authentication and API access require Azure; no local login bypass exists.
 */
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {execFileSync} = require('node:child_process');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'whatif-preview-'));
execFileSync('python3', [path.join(__dirname, '../quote-monitor/deploy.py'), '--build-only', root], {stdio:'inherit'});
const config = JSON.parse(fs.readFileSync(path.join(root, 'staticwebapp.config.json'), 'utf8'));
const types = {'.css':'text/css; charset=utf-8', '.html':'text/html; charset=utf-8', '.js':'text/javascript; charset=utf-8', '.json':'application/json', '.mp4':'video/mp4', '.svg':'image/svg+xml', '.png':'image/png', '.webp':'image/webp'};
const server = http.createServer((request, response) => {
  let pathname;
  try { pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname); }
  catch { response.writeHead(400).end('Bad request'); return; }
  if (pathname === '/.auth/me') {
    response.writeHead(200, {'Content-Type':'application/json', 'Cache-Control':'no-store'}).end(JSON.stringify({clientPrincipal:null})); return;
  }
  if (pathname.startsWith('/.auth/') || pathname.startsWith('/api/')) {
    response.writeHead(503, {'Content-Type':'application/json'}).end(JSON.stringify({detail:'실제 인증과 API는 Azure 배포 환경에서 사용할 수 있습니다.'})); return;
  }
  const rule = config.routes.find(r => r.route.endsWith('*') ? pathname.startsWith(r.route.slice(0, -1)) : pathname === r.route);
  if (rule?.redirect) { response.writeHead(rule.statusCode || 302, {Location:rule.redirect}).end(); return; }
  const file = path.resolve(root, '.' + (rule?.rewrite || pathname));
  if (!file.startsWith(root + path.sep)) { response.writeHead(403).end('Forbidden'); return; }
  let stats;
  try { stats = fs.statSync(file); if (!stats.isFile()) throw new Error('not a file'); }
  catch { response.writeHead(404).end('Not found'); return; }
  response.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
  response.setHeader('Accept-Ranges', 'bytes');
  if (request.headers.range) {
    const match = /^bytes=(\d*)-(\d*)$/.exec(request.headers.range);
    if (!match || (!match[1] && !match[2])) { response.writeHead(416, {'Content-Range':`bytes */${stats.size}`}).end(); return; }
    const start = match[1] ? Number(match[1]) : Math.max(0, stats.size - Number(match[2]));
    const end = match[1] && match[2] ? Math.min(Number(match[2]), stats.size - 1) : stats.size - 1;
    if (start > end || start >= stats.size) { response.writeHead(416, {'Content-Range':`bytes */${stats.size}`}).end(); return; }
    response.writeHead(206, {'Content-Length':end - start + 1, 'Content-Range':`bytes ${start}-${end}/${stats.size}`});
    if (request.method === 'HEAD') response.end(); else fs.createReadStream(file, {start, end}).pipe(response);
    return;
  }
  response.setHeader('Content-Length', stats.size);
  if (request.method === 'HEAD') response.end(); else fs.createReadStream(file).pipe(response);
});
server.listen(Number(process.env.PORT || 3000), '127.0.0.1', () => console.log('WHAT IF: http://localhost:' + server.address().port));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => server.close(() => { fs.rmSync(root, {recursive:true, force:true}); process.exit(0); }));
