import test from 'node:test';
import assert from 'node:assert/strict';
import { createSdkTransport, joinUrl, classifyTransportError } from '../../main/transport.js';

function response({ status = 200, body = '', headers = {}, arrayBuffer = null } = {}) {
  return {
    status,
    ok: status >= 200 && status < 300,
    headers: { get: (name) => headers[String(name).toLowerCase()] || null },
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
    arrayBuffer: async () => arrayBuffer || new TextEncoder().encode(body).buffer,
  };
}

function transportWith(handler, options = {}) {
  return createSdkTransport({
    eda: { sys_ClientUrl: { request: handler } },
    timeoutMs: options.timeoutMs || 500,
    ...options,
  });
}

test('joinUrl normalizes slashes', () => {
  assert.equal(joinUrl('http://lc.rm.com/', '/lab/api/catalog/search'), 'http://lc.rm.com/lab/api/catalog/search');
  assert.equal(joinUrl('http://lc.rm.com', 'lab/api'), 'http://lc.rm.com/lab/api');
});

test('sends POST and returns status/text/setCookie', async () => {
  let captured;
  const transport = transportWith(async (url, method, data, options) => {
    captured = { url, method, data, options };
    return response({ body: '{"ok":true}', headers: { 'set-cookie': 'session_id=abc; Path=/' } });
  });
  const result = await transport.request({
    url: 'http://lc.rm.com/lab/api/catalog/search',
    method: 'POST',
    body: '{"a":1}',
    headers: { 'Content-Type': 'application/json' },
  });
  assert.equal(captured.method, 'POST');
  assert.equal(captured.data, '{"a":1}');
  assert.equal(captured.options.headers['Content-Type'], 'application/json');
  assert.equal(result.status, 200);
  assert.equal(result.text, '{"ok":true}');
  assert.equal(result.setCookie, 'session_id=abc; Path=/');
});

test('classifies CORS/network errors explicitly', async () => {
  const transport = transportWith(async () => {
    throw new Error('Failed to fetch: CORS');
  });
  await assert.rejects(
    () => transport.request({ url: 'http://lc.rm.com/x', method: 'POST', body: '{}' }),
    (error) =>
      error.code === 'NETWORK_OR_CORS' &&
      error.mayHaveBeenSent === true &&
      error.action === 'check_network_cors',
  );
});

test('classifies missing external interaction permission', async () => {
  const transport = transportWith(async () => {
    throw new Error('external interaction permission not enabled');
  });
  await assert.rejects(
    () => transport.request({ url: 'http://lc.rm.com/x', method: 'POST', body: '{}' }),
    (error) => error.code === 'EXTERNAL_INTERACTION_DISABLED',
  );
});

test('timeout is ambiguous for writes and not for reads', async () => {
  const transport = transportWith(() => new Promise(() => {}), { timeoutMs: 15 });
  await assert.rejects(
    () => transport.request({ url: 'http://lc.rm.com/x', method: 'POST', body: '{}' }),
    (error) => error.code === 'TIMEOUT_AMBIGUOUS' && error.mayHaveBeenSent === true,
  );
  await assert.rejects(
    () => transport.request({ url: 'http://lc.rm.com/x', method: 'GET' }),
    (error) => error.code === 'TIMEOUT_AMBIGUOUS' && error.mayHaveBeenSent === false,
  );
});

test('missing sys_ClientUrl is explicit', async () => {
  const transport = createSdkTransport({ eda: {}, timeoutMs: 50 });
  await assert.rejects(
    () => transport.request({ url: 'http://lc.rm.com/x', method: 'POST', body: '{}' }),
    (error) => error.code === 'EXTERNAL_INTERACTION_DISABLED',
  );
});

test('requestBinary returns bytes and content type', async () => {
  const transport = transportWith(async () => response({ headers: { 'content-type': 'image/png' }, arrayBuffer: new Uint8Array([1, 2, 3]).buffer }));
  const result = await transport.requestBinary({ url: 'http://lc.rm.com/lab/api/asset?url=x', method: 'GET' });
  assert.equal(result.contentType, 'image/png');
  assert.deepEqual(Array.from(new Uint8Array(result.buffer)), [1, 2, 3]);
});

test('classifyTransportError keeps ApiError instances', () => {
  const original = classifyTransportError(new Error('Failed to fetch'), { method: 'POST' });
  assert.equal(classifyTransportError(original, { method: 'POST' }), original);
  assert.equal(original.code, 'NETWORK_OR_CORS');
});
