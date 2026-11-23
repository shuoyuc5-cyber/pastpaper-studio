const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const gateDeviceRequest = require('./client-access.cjs');
process.env.NODE_ENV = 'production';
const next = require('next');
const runtime = process.env.PASTPAPER_RUNTIME_DIR || path.resolve(__dirname, '../work/runtime');
const hosts = new Set(JSON.parse(fs.readFileSync(path.join(runtime, 'lan-hosts.json'), 'utf8')));
const lan = process.env.PASTPAPER_HOST_LAN === '1';
const port = Number(process.env.PASTPAPER_WEB_PORT || 3000);
const app = next({dev:false,dir:__dirname,hostname:'localhost',port});
const handle = app.getRequestHandler();
app.prepare().then(() => {
  const server = http.createServer({maxHeaderSize:16384}, async (req,res) => {
    let allowed=false;
    try {
      const host=req.headers.host;
      if(host && !/[\s/@\\?#]/.test(host)) {
        const parsed=new URL('http://'+host);
        allowed=hosts.has(parsed.hostname.replace(/^\[|\]$/g,'').toLowerCase()) && (!parsed.port || parsed.port===String(port));
      }
    } catch {}
    if(!allowed){res.writeHead(403,{'Content-Type':'text/plain; charset=utf-8'});return res.end('请使用启动窗口中的局域网网址。');}
    for(const name of Object.keys(req.headers))if(name==='forwarded'||name.startsWith('x-forwarded-'))delete req.headers[name];
    req.headers['x-forwarded-host']=req.headers.host;
    req.headers['x-forwarded-proto']='http';
    req.headers['x-forwarded-port']=String(port);
    req.headers['x-forwarded-for']=req.socket.remoteAddress;
    res.setHeader('X-PastPaper-Transport',lan?'lan-http':'local-http');
    res.setHeader('X-PastPaper-Release',process.env.PASTPAPER_RELEASE || 'v3');
    if (req.url.split('?')[0] === '/') res.setHeader('Cache-Control','private, no-store');
    try {
      if (!(await gateDeviceRequest(req,res))) await handle(req,res);
    } catch(error){console.error(error.message);if(!res.headersSent){res.writeHead(500);res.end('服务暂时无法完成操作');}else res.destroy();}
  });
  server.headersTimeout=15000;server.requestTimeout=120000;server.keepAliveTimeout=5000;server.maxRequestsPerSocket=200;
  server.on('error',error=>{console.error(error.message);process.exit(1);});
  server.listen(port,lan?'0.0.0.0':'127.0.0.1');
  for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>{server.close();setTimeout(()=>process.exit(0),1000).unref();});
}).catch(error=>{console.error(error.message);process.exit(1);});
