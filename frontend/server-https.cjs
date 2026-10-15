// The production app has no HTTP listener; port 3000 only redirects safe navigation.
const https = require('node:https');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const next = require('next');

process.env.NODE_ENV = 'production';
const tlsDir = path.resolve(__dirname, '../backend/data/tls');
const hosts = new Set(JSON.parse(fs.readFileSync(path.join(tlsDir, 'hosts.json'), 'utf8')));
const app = next({ dev: false, dir: __dirname, hostname: 'localhost', port: 3443 });
const handle = app.getRequestHandler();

function validHost(req, port) {
  try {
    const raw = req.headers.host;
    if (!raw || /[\s/@\\?#]/.test(raw)) return null;
    const url = new URL('https://' + raw);
    const name = url.hostname.replace(/^\[|\]$/g, '').toLowerCase();
    return hosts.has(name) && (!url.port || url.port === String(port)) ? url.hostname : null;
  } catch { return null; }
}

function fail(res, status, text) {
  res.writeHead(status, { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store', 'Connection': 'close' });
  res.end(text);
}

async function main() {
  await app.prepare();
  const secure = https.createServer({
    key: fs.readFileSync(path.join(tlsDir, 'server-key.pem')),
    cert: fs.readFileSync(path.join(tlsDir, 'server.pem')),
    minVersion: 'TLSv1.2', maxHeaderSize: 16384,
  }, async (req, res) => {
    if (!validHost(req, 3443)) return fail(res, 403, '请使用启动窗口中的网站地址。');
    // Forwarded headers supplied by a remote caller must never become trusted proxy data.
    for (const name of Object.keys(req.headers)) {
      if (name === 'forwarded' || name.startsWith('x-forwarded-')) delete req.headers[name];
    }
    req.headers['x-forwarded-host'] = req.headers.host;
    req.headers['x-forwarded-proto'] = 'https';
    req.headers['x-forwarded-port'] = '3443';
    req.headers['x-forwarded-for'] = req.socket.remoteAddress;
    // HSTS upgrades HTTP on the same port; 3000 redirects to TLS on 3443, so it cannot be used here.
    res.setHeader('X-PastPaper-Transport', 'https');
    try { await handle(req, res); }
    catch (error) {
      console.error('HTTPS request failed:', error.message);
      if (!res.headersSent) fail(res, 500, '服务暂时无法完成操作。');
      else res.destroy();
    }
  });
  const redirect = http.createServer({ maxHeaderSize: 16384 }, (req, res) => {
    const host = validHost(req, 3000);
    if (!host) return fail(res, 403, '请使用启动窗口中的网站地址。');
    if (!['GET', 'HEAD'].includes(req.method) || req.url.startsWith('/api/')) {
      return fail(res, 426, '请使用 HTTPS 地址登录和操作：https://' + host + ':3443/');
    }
    // Ignore the supplied path: an HTTP request must not send data to an API or redirect off-site.
    res.writeHead(302, { Location: 'https://' + host + ':3443/', 'Cache-Control': 'no-store', Connection: 'close' });
    res.end();
  });
  for (const server of [secure, redirect]) {
    server.headersTimeout = 15000;
    server.requestTimeout = 120000;
    server.keepAliveTimeout = 5000;
    server.maxRequestsPerSocket = 200;
    server.on('error', error => { console.error(error.message); process.exit(1); });
  }
  secure.listen(3443, '0.0.0.0');
  redirect.listen(3000, '0.0.0.0');
  for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => {
    secure.close(); redirect.close();
    setTimeout(() => process.exit(0), 1000).unref();
  });
  console.log('PastPaper Studio HTTPS: https://localhost:3443/');
}
main().catch(error => { console.error(error.message); process.exit(1); });
