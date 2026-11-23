import assert from 'node:assert/strict';
import test from 'node:test';
import {runtime} from '../frontend/public/device/providers.mjs';

test('Ollama filters cloud models and sends only the selected prompt to the device', async t => {
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    calls.push({url, init});
    return Response.json(url.endsWith('/tags') ? {models: [{name: 'local'}, {name: 'other:cloud'}, {name: 'proxied', remote_host: 'example.test'}]} : {response: 'fixture output'});
  });
  const client = runtime('ollama', 11434, 'ignored');
  assert.deepEqual(await client.models(), ['local']);
  assert.equal(await client.generate('local', 'user selected text'), 'fixture output');
  assert.deepEqual(calls.map(call => call.url), ['http://127.0.0.1:11434/api/tags','http://127.0.0.1:11434/api/generate']);
  assert.deepEqual(JSON.parse(calls[1].init.body), {model: 'local', prompt: 'user selected text', stream: false});
  for (const {init} of calls) { assert.equal(init.credentials, 'omit'); assert.equal(init.redirect, 'error'); assert.equal(init.headers.Authorization, undefined); }
});

test('switching provider uses its own endpoint and optional memory-only authorization', async t => {
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    assert.equal(url, 'http://127.0.0.1:1234/v1/models');
    assert.equal(init.headers.Authorization, 'Bearer fixture-lm-token');
    return Response.json({data:[{id:'fixture-lm'}]});
  });
  assert.deepEqual(await runtime('lmstudio', 1234, 'fixture-lm-token').models(), ['fixture-lm']);
  assert.throws(() => runtime('openai', 443, 'fixture'), /提供方/);
  assert.throws(() => runtime('ollama', 'https://example.test', ''), /端口/);
  assert.throws(() => runtime('lmstudio', 1234, '\r\nsecret'), /格式/);
});

test('provider failures have useful messages without echoing provider bodies or credentials', async t => {
  let status = 401;
  t.mock.method(globalThis, 'fetch', async () => new Response('never display this provider secret', {status}));
  const client = runtime('lmstudio', 1234, 'fixture-lm-token');
  await assert.rejects(client.models(), error => /拒绝授权/.test(error.message) && !error.message.includes('secret'));
  status = 429;
  await assert.rejects(client.models(), /请求过多/);
  status = 503;
  await assert.rejects(client.models(), /503/);
  status = 200;
  await assert.rejects(client.models(), /无效/);
});
