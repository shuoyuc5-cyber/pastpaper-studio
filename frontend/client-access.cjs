const path = require('node:path');

async function gateDeviceRequest(req, res, requireSession = false) {
  let requested;
  try {
    const pathname = /^https?:\/\//i.test(req.url) ? new URL(req.url).pathname : req.url.split('?')[0];
    requested = path.posix.normalize(decodeURIComponent(pathname).replace(/\\/g,'/')).toLowerCase();
  } catch {
    res.writeHead(400, {'Cache-Control':'no-store'}).end();
    return true;
  }
  if (requested !== '/device' && !requested.startsWith('/device/')) return false;
  const host = new URL('http://' + req.headers.host).hostname;
  const remote = req.socket.remoteAddress?.replace(/^::ffff:/,'');
  if (!requireSession && ['localhost','127.0.0.1','[::1]'].includes(host) && ['127.0.0.1','::1'].includes(remote)) return false;

  let authorized = false;
  if (req.headers.cookie) {
    try {
      const port = Number(process.env.PASTPAPER_BACKEND_PORT || 8000);
      const response = await fetch(`http://127.0.0.1:${port}/api/auth/device-access`, {
        headers: {
          cookie: req.headers.cookie,
          'x-forwarded-host': req.headers.host,
          'x-forwarded-proto': req.headers['x-forwarded-proto'],
          'x-forwarded-for': req.headers['x-forwarded-for'],
        },
        signal: AbortSignal.timeout(2500), redirect: 'error',
      });
      authorized = response.status === 204;
    } catch {}
  }
  res.setHeader('Cache-Control', 'private, no-store');
  if (authorized) return false;
  if (['/device','/device/','/device/index.html'].includes(requested)) res.writeHead(302, {Location:'/'}).end();
  else res.writeHead(401, {'Content-Type':'text/plain; charset=utf-8','X-Content-Type-Options':'nosniff'}).end('请先登录。');
  return true;
}

module.exports = gateDeviceRequest;
