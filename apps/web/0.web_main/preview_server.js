const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '../../..');
const types = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.mp4': 'video/mp4',
  '.svg': 'image/svg+xml',
};

http.createServer((request, response) => {
  let pathname;
  try {
    pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
  } catch {
    response.writeHead(400).end('Bad request');
    return;
  }

  let file = path.resolve(root, `.${pathname}`);
  if (!file.startsWith(`${root}${path.sep}`) && file !== root) {
    response.writeHead(403).end('Forbidden');
    return;
  }

  try {
    if (fs.statSync(file).isDirectory()) file = path.join(file, 'index.html');
  } catch {
    response.writeHead(404).end('Not found');
    return;
  }

  let stats;
  try {
    stats = fs.statSync(file);
  } catch {
    response.writeHead(404).end('Not found');
    return;
  }

  response.setHeader('Content-Type', types[path.extname(file).toLowerCase()] || 'application/octet-stream');
  response.setHeader('Accept-Ranges', 'bytes');
  const range = request.headers.range;
  if (range) {
    const match = /^bytes=(\d*)-(\d*)$/.exec(range);
    if (!match) {
      response.writeHead(416, { 'Content-Range': `bytes */${stats.size}` }).end();
      return;
    }
    const start = Number(match[1] || 0);
    const end = Math.min(Number(match[2] || stats.size - 1), stats.size - 1);
    if (start > end || start >= stats.size) {
      response.writeHead(416, { 'Content-Range': `bytes */${stats.size}` }).end();
      return;
    }
    response.writeHead(206, {
      'Content-Length': end - start + 1,
      'Content-Range': `bytes ${start}-${end}/${stats.size}`,
    });
    if (request.method === 'HEAD') response.end();
    else fs.createReadStream(file, { start, end }).pipe(response);
    return;
  }

  response.setHeader('Content-Length', stats.size);
  if (request.method === 'HEAD') {
    response.end();
    return;
  }
  fs.createReadStream(file)
    .on('error', () => response.writeHead(404).end('Not found'))
    .pipe(response);
}).listen(3000, '127.0.0.1', () => {
  console.log('WHAT IF intro: http://localhost:3000/apps/web/0.web_main/');
  console.log('Intro README: http://localhost:3000/apps/web/0.web_main/README.md');
});
