import test from 'node:test';
import assert from 'node:assert/strict';
import { createOdooClient } from '../../main/odoo.js';

function response(result, options = {}) {
  return {
    status: options.status || 200,
    ok: (options.status || 200) < 300,
    text: JSON.stringify({ jsonrpc: '2.0', id: options.id || 1, result }),
  };
}

function rawResponse(text, options = {}) {
  return { status: options.status || 200, ok: (options.status || 200) < 300, text };
}

function errorResponse(code, message, name = '') {
  return rawResponse(
    JSON.stringify({ jsonrpc: '2.0', id: null, error: { code, message, data: name ? { name } : {} } }),
  );
}

function makeTransport(handler) {
  const calls = [];
  return {
    calls,
    async request(input) {
      const path = new URL(input.url).pathname;
      calls.push({ path, headers: input.headers || {}, body: input.body });
      return handler(path, calls.length - 1, input);
    },
  };
}

test('direct mode relies on the SDK cookie jar and never sends a Cookie header', async () => {
  const transport = makeTransport((path) => {
    if (path === '/web/session/authenticate') {
      return response({ uid: 7, name: 'Alice', username: 'alice', db: 'lab' });
    }
    if (path === '/web/session/get_session_info') return response({ uid: 7, name: 'Alice' });
    if (path === '/lab/api/catalog/search') {
      return response({ ok: true, data: { items: [], total: 0, next_cursor: null }, error: null });
    }
    throw new Error('unexpected path ' + path);
  });
  const client = createOdooClient({
    config: { serverUrl: 'http://lc.rm.com', db: 'lab', login: 'alice' },
    transport,
  });
  const session = await client.authenticate({ db: 'lab', login: 'alice', password: 'secret' });
  assert.equal(session.active, true);
  assert.equal(session.sessionMode, 'cookie-jar');
  assert.equal(transport.calls[0].headers.Cookie, undefined);
  assert.equal(transport.calls[1].headers.Cookie, undefined);
  const data = await client.call('/lab/api/catalog/search', { query: '' });
  assert.deepEqual(data.items, []);
  assert.equal(transport.calls[2].headers.Cookie, undefined);
});

test('reports SESSION_COOKIE_UNAVAILABLE when the post-login probe is anonymous', async () => {
  const transport = makeTransport((path) => {
    if (path === '/web/session/authenticate') return response({ uid: 9 });
    if (path === '/web/session/get_session_info') {
      return errorResponse(100, 'Odoo Session Expired', 'odoo.http.SessionExpiredException');
    }
    throw new Error('unexpected path ' + path);
  });
  const client = createOdooClient({
    config: { serverUrl: 'http://lc.rm.com', db: 'lab', login: 'x' },
    transport,
  });
  await assert.rejects(
    () => client.authenticate({ db: 'lab', login: 'x', password: 'pw' }),
    (error) => error.code === 'SESSION_COOKIE_UNAVAILABLE' && error.action === 'use_relay',
  );
  assert.equal(client.publicSession().active, false);
});

test('rejects uid:null as invalid credentials', async () => {
  const transport = makeTransport((path) => {
    if (path === '/web/session/authenticate') return response({ uid: null });
    throw new Error('unexpected path ' + path);
  });
  const client = createOdooClient({
    config: { serverUrl: 'http://lc.rm.com', db: 'lab', login: 'x' },
    transport,
  });
  await assert.rejects(
    () => client.authenticate({ db: 'lab', login: 'x', password: 'pw' }),
    (error) => error.code === 'INVALID_CREDENTIALS',
  );
});

test('logout tolerates the production destroy response without result', async () => {
  const transport = makeTransport((path) => {
    if (path === '/web/session/authenticate') return response({ uid: 3 });
    if (path === '/web/session/get_session_info') return response({ uid: 3 });
    if (path === '/web/session/destroy') return rawResponse(JSON.stringify({ jsonrpc: '2.0', id: null }));
    throw new Error('unexpected path ' + path);
  });
  const client = createOdooClient({
    config: { serverUrl: 'http://lc.rm.com', db: 'lab', login: 'x' },
    transport,
  });
  await client.authenticate({ db: 'lab', login: 'x', password: 'pw' });
  const result = await client.logout();
  assert.equal(result.ok, true);
  assert.equal(result.warning, '');
  assert.equal(client.publicSession().active, false);
});

test('business call without a session fails before network', async () => {
  const transport = makeTransport(() => {
    throw new Error('should not be called');
  });
  const client = createOdooClient({
    config: { serverUrl: 'http://lc.rm.com', db: 'lab', login: 'x' },
    transport,
  });
  await assert.rejects(() => client.call('/lab/api/catalog/search', {}), (error) => error.code === 'SESSION_REQUIRED');
  assert.equal(transport.calls.length, 0);
});
