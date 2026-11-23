import assert from 'node:assert/strict';
import test from 'node:test';
import worker from '../deploy/cloudflare/worker.mjs';
import {bindings, submissionCode, moderationKey} from './share-fixture.mjs';

const origin = 'https://example.test';
const pdf = '%PDF-1.4\nfixture\n%%EOF\n';
function fixture() {
  const {env, store} = bindings(request => new Response(new URL(request.url).pathname));
  const invoke = (path, {method = 'GET', key, body, headers = {}, base = origin} = {}) => worker.fetch(new Request(base + path, {
    method, body, duplex: 'half', headers: {...(key ? {Authorization: 'Bearer ' + key} : {}), Origin: base, ...headers},
  }), env);
  const submit = (options = {}) => invoke('/share/submissions', {method: 'POST', body: pdf, key: submissionCode, ...options,
    headers: {'Content-Type': 'application/pdf', 'X-Share-Title': encodeURIComponent('公开数学题'), 'X-Share-Consent': 'confirmed', ...options.headers},
  });
  return {env, store, invoke, submit};
}

test('only the device app is served; private backend, root assets and plaintext HTTP are denied', async () => {
  const {env, invoke} = fixture();
  assert.equal((await invoke('/')).headers.get('location'), '/device/index.html');
  const asset = await invoke('/device/index.html');
  assert.equal(await asset.text(), '/index.html');
  assert.match(asset.headers.get('content-security-policy'), /frame-ancestors 'none'/);
  assert.match(asset.headers.get('content-security-policy'), /img-src blob:/);
  assert.equal(asset.headers.get('strict-transport-security'), null);
  env.HSTS_TRIAL = '1';
  assert.equal((await invoke('/device/index.html')).headers.get('strict-transport-security'), 'max-age=300');
  const font = await invoke('/device/pdf-engine/standard-fonts/LiberationSans-Regular.ttf');
  assert.equal(await font.text(), '/pdf-engine/standard-fonts/LiberationSans-Regular.ttf');
  for (const path of ['/api/auth/me', '/api/backup', '/index.html', '/device/private.sqlite3', '/device/pdf-engine/standard-fonts/private.sqlite3']) assert.equal((await invoke(path)).status, 404);
  assert.equal((await invoke('/share/papers', {base: 'http://example.test'})).status, 426);
});

test('explicit submission stays private until the owner approves; no guest identity or private workspace payload is persisted', async () => {
  const {invoke, submit, store} = fixture();
  const pending = await submit();
  assert.equal(pending.status, 201);
  const {id} = await pending.json();
  assert.equal((await invoke('/share/papers/' + id)).status, 404);
  assert.deepEqual((await (await invoke('/share/papers')).json()).papers, []);
  assert.equal((await invoke('/share/review', {key: submissionCode})).status, 403);
  assert.equal((await invoke('/share/review/' + id + '/file')).status, 403);
  assert.deepEqual([...store.values()].map(value => value.customMetadata), [{title: '公开数学题'}]);
  assert.equal((await (await invoke('/share/review', {key: moderationKey})).json()).papers[0].published, false);
  const review = await invoke(`/share/review/${id}/file`, {key: moderationKey});
  assert.equal(await review.text(), pdf);
  assert.match(review.headers.get('content-disposition'), /^attachment/);
  assert.equal((await invoke(`/share/review/${id}/approve`, {method: 'POST', key: moderationKey})).status, 200);
  assert.equal(store.has('pending/' + id), false);
  assert.equal((await (await invoke('/share/papers')).json()).papers[0].title, '公开数学题');
  assert.equal(await (await invoke('/share/papers/' + id)).text(), pdf);
  assert.equal((await submit()).status, 409);
  assert.equal((await invoke(`/share/review/${id}/remove`, {method: 'POST', key: moderationKey})).status, 200);
  assert.equal((await invoke('/share/papers/' + id)).status, 404);
});

test('fail closed for missing bindings, reused keys, wrong origin, no consent, invalid PDF and over-limit traffic', async () => {
  const {env, invoke, submit, store} = fixture();
  assert.equal((await submit({key: moderationKey})).status, 403);
  assert.equal((await submit({headers: {Origin: 'https://another.example'}})).status, 403);
  assert.equal((await submit({headers: {'X-Share-Consent': ''}})).status, 400);
  assert.equal((await submit({headers: {'X-Share-Title': '%zz'}})).status, 400);
  assert.equal((await submit({body: '<script>not a PDF</script>'})).status, 400);
  assert.equal((await submit({headers: {'Content-Length': '10485761'}})).status, 413);
  assert.equal((await submit({body: new Uint8Array(10485761)})).status, 413);
  env.SHARE_LIMIT.limit = async () => ({success: false});
  assert.equal((await submit()).status, 429);
  delete env.SHARE_LIMIT;
  assert.equal((await invoke('/share/config')).status, 503);
  env.SHARE_LIMIT = {limit: async () => ({success: true})};
  env.SUBMISSION_CODE = moderationKey;
  assert.equal((await (await invoke('/share/config')).json()).submissions, false);
  assert.equal((await submit()).status, 503);
  assert.equal(store.size, 0);
});

test('reject removes the pending object and does not publish it', async () => {
  const {invoke, submit, store} = fixture();
  const {id} = await (await submit()).json();
  assert.equal((await submit()).status, 409);
  assert.equal((await invoke(`/share/review/${id}/reject`, {method: 'POST', key: moderationKey})).status, 200);
  assert.equal((await invoke(`/share/papers/${id}`)).status, 404);
  assert.equal(store.size, 0);
});

test('read-only staging forbids writes and moderation even with both keys configured', async () => {
  const {env, invoke, submit, store} = fixture();
  assert.equal((await submit()).status, 201);
  env.STUDIO_READ_ONLY = '1';
  assert.deepEqual(await (await invoke('/share/config')).json(), {submissions:false});
  assert.equal((await invoke('/share/review', {key:moderationKey})).status,404);
  assert.equal((await submit()).status,404);
  assert.equal((await invoke('/api/auth/me')).status,404);
  assert.equal(store.size,1);
  assert.deepEqual(await (await invoke('/share/papers')).json(), {papers:[],cursor:''});
});
