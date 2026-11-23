// Loopback preview with disposable Cloudflare bindings and a dummy local AI provider.
import {createServer} from 'node:http';
import {readFile} from 'node:fs/promises';
import {Readable} from 'node:stream';
import worker from '../deploy/cloudflare/worker.mjs';
import {bindings} from './share-fixture.mjs';
import '../frontend/scripts/prepare-device.mjs';

const port = Number(process.env.V3_PREVIEW_PORT || 39200);
if (!Number.isInteger(port) || port < 1024 || port > 65534) throw new Error('Invalid preview port.');
const origin = `http://127.0.0.1:${port}`;
const qa = process.env.V3_BROWSER_QA === '1';
const types = {html:'text/html',css:'text/css',mjs:'text/javascript',js:'text/javascript',txt:'text/plain',ttf:'font/ttf',pfb:'application/octet-stream'};
let droppedDeviceReads = 0, disconnected = false;
const {env} = bindings(async request => {
  const path = new URL(request.url).pathname.slice(1);
  try {
    let data = await readFile(new URL('../frontend/public/device/' + path, import.meta.url));
    if (qa && path === 'index.html') data = data.toString().replace('</head>', '<script type="module" src="/__qa/browser.mjs"></script></head>');
    const type = types[path.split('.').pop()] || 'text/plain';
    return new Response(request.method === 'HEAD' ? null : data, {headers:{'Content-Type': type}});
  } catch {return new Response(null,{status:404});}
});
createServer(async (request, reply) => {
  try {
    const path = new URL(request.url, origin).pathname;
    if (qa && request.method === 'GET' && ['/__qa/browser.mjs','/__qa/share-fixture.mjs'].includes(path)) {
      const source = path.endsWith('/browser.mjs') ? './browser-fixture.mjs' : './share-fixture.mjs';
      return reply.writeHead(200, {'Content-Type':'text/javascript', 'Cache-Control':'no-store'}).end(await readFile(new URL(source, import.meta.url)));
    }
    if (qa && request.method === 'POST' && request.headers.origin === origin && ['/__qa/disconnect','/__qa/reconnect'].includes(path)) {
      disconnected = path === '/__qa/disconnect';
      return reply.writeHead(200, {'Content-Type':'application/json'}).end(JSON.stringify({droppedDeviceReads}));
    }
    if (qa && disconnected && path.startsWith('/device/')) { droppedDeviceReads++; request.socket.destroy(); return; }
    const body = ['GET','HEAD'].includes(request.method) ? undefined : Readable.toWeb(request);
    const response = await worker.fetch(new Request(new URL(request.url, origin), {method:request.method, headers:request.headers, body, duplex:'half'}), env);
    reply.writeHead(response.status, Object.fromEntries(response.headers));
    if (response.body) Readable.fromWeb(response.body).pipe(reply);
    else reply.end();
  } catch { reply.writeHead(500).end(); }
}).listen(port, '127.0.0.1', () => console.log('Disposable device and sharing preview: ' + origin));

createServer(async (request, reply) => {
  reply.setHeader('Access-Control-Allow-Origin', origin);
  reply.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  reply.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  reply.setHeader('Content-Type', 'application/json');
  if (request.method === 'OPTIONS') return reply.writeHead(204).end();
  if (request.url === '/api/tags') return reply.end(JSON.stringify({models:[{name:'fixture-local'},{name:'should-not-show:cloud'}]}));
  if (request.url === '/v1/models') {
    if (request.headers.authorization !== 'Bearer fixture-runtime-token') return reply.writeHead(401).end('{}');
    return reply.end(JSON.stringify({data:[{id:'fixture-lm-studio'}]}));
  }
  if (request.url === '/api/generate' || request.url === '/v1/chat/completions') {
    for await (const _ of request) { /* Discard the synthetic request body. */ }
    return reply.end(JSON.stringify({response:'Mock local response',choices:[{message:{content:'Mock local response'}}]}));
  }
  return reply.writeHead(404).end('{}');
}).listen(port+1,'127.0.0.1');
