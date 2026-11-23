const MAX_PDF = 10 * 1024 * 1024;
const ID = '[0-9a-f]{64}';
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const headers = {
  'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
};
const csp = "default-src 'none'; script-src 'self'; style-src 'self'; img-src blob:; connect-src 'self' http://127.0.0.1:*; worker-src 'self'; base-uri 'none'; form-action 'none'; object-src 'none'; frame-ancestors 'none'";
const assets = new Set(['index.html','studio.css','studio.mjs','locale.mjs','vault.mjs','providers.mjs','text-search.mjs','sw.js','pdf-engine/pdf.min.mjs','pdf-engine/pdf.worker.min.mjs','pdf-engine/LICENSE.txt'].map(name => '/device/' + name));
const fontAsset = /^\/device\/pdf-engine\/standard-fonts\/(?:Foxit[A-Za-z]+\.pfb|LiberationSans-[A-Za-z]+\.ttf|LICENSE_(?:FOXIT|LIBERATION))$/;
const json = (value, status = 200, more) => Response.json(value, {status, headers: {...headers, ...more}});
const error = (detail, status) => json({error: detail}, status);
const hash = bytes => crypto.subtle.digest('SHA-256', bytes).then(value => new Uint8Array(value));
const hex = bytes => Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
const enabledKey = value => typeof value === 'string' && /^[\x21-\x7e]{24,160}$/.test(value);

async function authorized(request, key) {
  const raw = request.headers.get('Authorization') || '';
  if (!enabledKey(key) || !raw.startsWith('Bearer ') || !enabledKey(raw.slice(7))) return false;
  const [actual, expected] = await Promise.all([hash(encoder.encode(raw.slice(7))), hash(encoder.encode(key))]);
  let unequal = 0;
  for (let i = 0; i < expected.length; i++) unequal |= actual[i] ^ expected[i];
  return unequal === 0;
}

async function readPdf(request) {
  const length = request.headers.get('Content-Length');
  if (!request.body || (length !== null && (!/^\d+$/.test(length) || Number(length) > MAX_PDF))) return null;
  const reader = request.body.getReader(), chunks = [];
  let size = 0;
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_PDF) { await reader.cancel(); return null; }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const pdf = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { pdf.set(chunk, offset); offset += chunk.byteLength; }
  return pdf;
}

const item = object => ({id: object.key.split('/')[1], title: object.customMetadata?.title || 'PDF', size: object.size, published: object.key.startsWith('public/')});
function pdfResponse(object, downloadName) {
  if (!object) return error('该题目不存在或已下架。', 404);
  return new Response(object.body, {headers: {...headers, 'Content-Type': 'application/pdf', 'Content-Length': String(object.size), 'Content-Disposition': `attachment; filename="${downloadName}.pdf"`, 'Content-Security-Policy': "default-src 'none'; sandbox"}});
}

async function handle(request, env) {
  const url = new URL(request.url), path = url.pathname, method = request.method;
  const read = method === 'GET' || method === 'HEAD';
  if (url.protocol !== 'https:' && !['127.0.0.1','localhost','[::1]'].includes(url.hostname)) return error('此服务需要 HTTPS。', 426);
  if (read && path === '/') return new Response(null, {status: 302, headers: {...headers, Location: '/device/index.html'}});
  if (read && (assets.has(path) || fontAsset.test(path))) {
    const asset = await env.ASSETS.fetch(new Request(new URL(path.slice('/device'.length), url), request));
    const response = new Response(asset.body, asset);
    for (const [name, value] of Object.entries(headers)) response.headers.set(name, value);
    response.headers.set('Content-Security-Policy', csp);
    return response;
  }
  if (!path.startsWith('/share/')) return error('没有这个页面。', 404);
  if (!env.SHARED_PAPERS || !env.SHARE_LIMIT) return error('共享题库未配置。', 503);
  const readOnly = env.STUDIO_READ_ONLY === '1';
  if (readOnly && (!read || path === '/share/review' || path.startsWith('/share/review/')))
    return error('没有这个操作。', 404);
  const canSubmit = !readOnly && enabledKey(env.SUBMISSION_CODE) && enabledKey(env.MODERATION_KEY) && env.SUBMISSION_CODE !== env.MODERATION_KEY;
  if (path === '/share/config' && method === 'GET') return json({submissions: canSubmit});
  if (!read && request.headers.get('Origin') !== url.origin) return error('请从本站页面发起操作。', 403);
  const peer = request.headers.get('CF-Connecting-IP') || 'unknown';
  const access = await env.SHARE_LIMIT.limit({key: `${read ? 'read' : 'write'}:${peer}`});
  if (!access.success) return json({error: '操作过于频繁，请稍后重试。'}, 429, {'Retry-After': '60'});
  const bucket = env.SHARED_PAPERS;
  if (method === 'GET' && path === '/share/papers') {
    const cursor = url.searchParams.get('cursor') || undefined;
    if (cursor && cursor.length > 2048) return error('分页参数无效。', 400);
    let result;
    try { result = await bucket.list({prefix: 'public/', limit: 40, cursor, include: ['customMetadata']}); }
    catch { return error('无法读取这一页，请刷新后重试。', 400); }
    return json({papers: result.objects.map(item), cursor: result.truncated ? result.cursor : ''});
  }
  const publicPaper = new RegExp(`^/share/papers/(${ID})$`).exec(path);
  if (method === 'GET' && publicPaper) return pdfResponse(await bucket.get('public/' + publicPaper[1]), 'PastPaper');
  if (method === 'POST' && path === '/share/submissions') {
    if (!canSubmit) return error('暂未开放投稿。', 503);
    if (!await authorized(request, env.SUBMISSION_CODE)) return error('投稿码无效。', 403);
    if (request.headers.get('X-Share-Consent') !== 'confirmed') return error('请先确认该文件可公开分享。', 400);
    if (request.headers.get('Content-Type') !== 'application/pdf') return error('只接受 PDF。', 415);
    let title;
    try { title = decodeURIComponent(request.headers.get('X-Share-Title') || '').trim(); }
    catch { return error('公开标题无效。', 400); }
    if (!title || title.length > 100 || /[\p{C}]/u.test(title)) return error('公开标题必须为 1–100 个可显示字符。', 400);
    const queue = await bucket.list({prefix: 'pending/', limit: 100});
    if (queue.truncated || queue.objects.length >= 100) return error('待审核队列已满，请稍后再提交。', 429);
    const pdf = await readPdf(request);
    if (!pdf) return error('PDF 最大为 10 MB。', 413);
    if (!/^%PDF-\d\.\d/.test(decoder.decode(pdf.subarray(0, 8))) || !/%%EOF\s*$/.test(decoder.decode(pdf.subarray(-1024)))) return error('无法识别这个 PDF。', 400);
    const id = hex(await hash(pdf));
    if (await bucket.head('public/' + id)) return error('相同文件已在共享题库中。', 409);
    const stored = await bucket.put('pending/' + id, pdf, {customMetadata: {title}, onlyIf: {etagDoesNotMatch: '*'}});
    if (!stored) return error('相同文件已提交审核。', 409);
    return json({id, status: 'pending'}, 201);
  }
  if (path === '/share/review' || path.startsWith('/share/review/')) {
    if (!await authorized(request, env.MODERATION_KEY)) return error('审核密钥无效。', 403);
    if (method === 'GET' && path === '/share/review') {
      const [pending, published] = await Promise.all(['pending/', 'public/'].map(prefix => bucket.list({prefix, limit: 100, include: ['customMetadata']})));
      return json({papers: [...pending.objects, ...published.objects].map(item)});
    }
    const match = new RegExp(`^/share/review/(${ID})/(file|approve|reject|remove)$`).exec(path);
    if (!match) return error('没有这个操作。', 404);
    const [, id, action] = match, key = 'pending/' + id;
    if (method === 'GET' && action === 'file') return pdfResponse(await bucket.get(key), 'Review');
    if (method !== 'POST' || action === 'file') return error('请求方式不支持。', 405);
    if (action === 'approve') {
      const original = await bucket.get(key);
      if (!original) return error('投稿已处理或不存在。', 404);
      await bucket.put('public/' + id, await original.arrayBuffer(), {customMetadata: original.customMetadata, onlyIf: {etagDoesNotMatch: '*'}});
    }
    await bucket.delete(action === 'remove' ? 'public/' + id : key);
    return json({ok: true});
  }
  return error('没有这个操作。', 404);
}

export default {async fetch(request, env) {
  try {
    const response = await handle(request, env);
    // Set a short trial only after validating the staging domain and certificate.
    if (env.HSTS_TRIAL === '1' && request.url.startsWith('https:')) response.headers.set('Strict-Transport-Security', 'max-age=300');
    return response;
  }
  catch { return error('共享服务暂时无法完成操作，请稍后重试。', 503); }
}};
