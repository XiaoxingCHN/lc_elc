import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createRelayServer } from '../../../bridge/server.mjs';

const TOKEN = 'test-pair-token-1234567890';
const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

function json(res, status, body, headers = {}) {
  const text = JSON.stringify(body);
  res.writeHead(status, Object.assign({ 'Content-Type': 'application/json' }, headers));
  res.end(text);
}

async function startMockOdoo() {
  const state = {
    active: false,
    cookies: [],
    paths: [],
    bodies: [],
  };
  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    state.paths.push(url.pathname);
    const body = await readBody(req);
    state.bodies.push(body);
    const cookie = String(req.headers.cookie || '');
    state.cookies.push(cookie);
    if (url.pathname === '/web/session/authenticate') {
      const payload = JSON.parse(body || '{}');
      if (payload.params && payload.params.login === 'alice' && payload.params.password === 'secret') {
        state.active = true;
        return json(
          res,
          200,
          {
            jsonrpc: '2.0',
            id: payload.id,
            result: { uid: 7, name: 'Alice', username: 'alice', db: 'LcHardwareHouse' },
          },
          { 'Set-Cookie': 'session_id=upstream-sid; Path=/; HttpOnly' },
        );
      }
      return json(res, 200, {
        jsonrpc: '2.0',
        id: payload.id,
        error: { code: 200, message: 'Access denied', data: { name: 'odoo.exceptions.AccessError' } },
      });
    }
    if (url.pathname === '/web/session/get_session_info') {
      if (!state.active || !cookie.includes('session_id=upstream-sid')) {
        return json(res, 200, {
          jsonrpc: '2.0',
          id: null,
          error: { code: 100, message: 'Odoo Session Expired', data: { name: 'odoo.http.SessionExpiredException' } },
        });
      }
      return json(res, 200, { jsonrpc: '2.0', id: 1, result: { uid: 7, name: 'Alice' } });
    }
    if (url.pathname === '/lab/api/catalog/search') {
      if (!state.active || !cookie.includes('session_id=upstream-sid')) {
        return json(res, 401, { error: 'session expired' });
      }
      return json(res, 200, {
        jsonrpc: '2.0',
        id: 1,
        result: { ok: true, data: { items: [{ item_key: 'lcsc:C1' }], total: 1, next_cursor: null }, error: null },
      });
    }
    if (url.pathname === '/lab/api/inventory/receipt') {
      if (!state.active || !cookie.includes('session_id=upstream-sid')) {
        return json(res, 401, { error: 'session expired' });
      }
      return json(res, 200, {
        jsonrpc: '2.0',
        id: 1,
        result: { ok: true, data: { operation: { name: 'RECV/1' }, bag: { trace_code: 'LABB:1' } }, error: null },
      });
    }
    if (url.pathname === '/lab/api/asset') {
      if (!state.active || !cookie.includes('session_id=upstream-sid')) {
        res.writeHead(401);
        return res.end('no');
      }
      res.writeHead(200, { 'Content-Type': 'image/png', 'Content-Length': String(PNG.length) });
      return res.end(PNG);
    }
    if (url.pathname === '/web/session/destroy') {
      state.active = false;
      // production returns no result member
      return json(res, 200, { jsonrpc: '2.0', id: null });
    }
    return json(res, 404, { error: 'not found' });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  return {
    url: 'http://127.0.0.1:' + port,
    state,
    close: () =>
      new Promise((resolve) => {
        if (typeof server.closeAllConnections === 'function') server.closeAllConnections();
        server.close(resolve);
      }),
  };
}

async function startRelay(upstream, logs) {
  const relay = createRelayServer({
    upstream,
    db: 'LcHardwareHouse',
    port: 0,
    token: TOKEN,
    logger: { log: (...args) => logs.push(args.join(' ')) },
  });
  const address = await relay.listen();
  return { relay, url: address.url };
}

function headers(extra = {}) {
  return Object.assign({ Authorization: 'Bearer ' + TOKEN, 'Content-Type': 'application/json' }, extra);
}

test('relay performs a real loopback Cookie login -> catalog -> asset -> logout flow', async () => {
  const logs = [];
  const odoo = await startMockOdoo();
  const { relay, url } = await startRelay(odoo.url, logs);
  try {
    const noAuth = await fetch(url + '/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login: 'alice', password: 'secret' }),
    });
    assert.equal(noAuth.status, 401);

    const badLogin = await fetch(url + '/login', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({ login: 'alice', password: 'wrong' }),
    });
    const badBody = await badLogin.json();
    assert.equal(badBody.ok, false);
    assert.equal(badBody.error.code, 'INVALID_CREDENTIALS');

    const login = await fetch(url + '/login', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify({ login: 'alice', password: 'secret' }),
    });
    const loginBody = await login.json();
    assert.equal(loginBody.ok, true);
    assert.equal(loginBody.data.uid, 7);
    assert.equal(login.headers.get('set-cookie'), null);
    assert.equal(JSON.stringify(loginBody).includes('upstream-sid'), false);
    assert.equal(JSON.stringify(loginBody).includes('session_id'), false);

    const rpc = await fetch(url + '/rpc', {
      method: 'POST',
      headers: headers({ 'X-Lab-Path': '/lab/api/catalog/search' }),
      body: JSON.stringify({ jsonrpc: '2.0', id: 'r1', method: 'call', params: { query: 'C1' } }),
    });
    const rpcText = await rpc.text();
    assert.equal(rpc.status, 200);
    assert.match(rpcText, /lcsc:C1/);
    assert.ok(odoo.state.cookies.some((cookie) => cookie.includes('session_id=upstream-sid')));
    assert.equal(rpc.headers.get('set-cookie'), null);

    const forbiddenPath = await fetch(url + '/rpc', {
      method: 'POST',
      headers: headers({ 'X-Lab-Path': '/lab/api/evil' }),
      body: JSON.stringify({ jsonrpc: '2.0', id: 'r2', method: 'call', params: {} }),
    });
    assert.equal(forbiddenPath.status, 403);

    const assetUrl = odoo.url + '/lab/api/asset?url=' + encodeURIComponent('https://cdn.example.com/p.png');
    const asset = await fetch(url + '/asset?url=' + encodeURIComponent(assetUrl), {
      headers: { Authorization: 'Bearer ' + TOKEN },
    });
    assert.equal(asset.status, 200);
    assert.equal(asset.headers.get('content-type'), 'image/png');
    assert.deepEqual(Buffer.from(await asset.arrayBuffer()), PNG);

    const badAsset = await fetch(url + '/asset?url=' + encodeURIComponent('https://evil.example/x'), {
      headers: { Authorization: 'Bearer ' + TOKEN },
    });
    assert.equal(badAsset.status, 403);

    const options = await fetch(url + '/rpc', {
      method: 'OPTIONS',
      headers: {
        Origin: 'http://eda.example',
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'authorization,content-type',
        'Access-Control-Request-Private-Network': 'true',
      },
    });
    assert.equal(options.status, 204);
    assert.equal(options.headers.get('access-control-allow-origin'), '*');
    assert.equal(options.headers.get('access-control-allow-credentials'), null);
    assert.match(options.headers.get('access-control-allow-headers'), /Authorization/);
    assert.match(options.headers.get('access-control-allow-headers'), /X-Lab-Path/i);
    assert.equal(options.headers.get('access-control-allow-private-network'), 'true');

    const logout = await fetch(url + '/logout', { method: 'POST', headers: headers(), body: '{}' });
    const logoutBody = await logout.json();
    assert.equal(logoutBody.ok, true);
    assert.equal(logoutBody.data.upstreamOk, true);

    const afterLogout = await fetch(url + '/rpc', {
      method: 'POST',
      headers: headers({ 'X-Lab-Path': '/lab/api/catalog/search' }),
      body: JSON.stringify({ jsonrpc: '2.0', id: 'r3', method: 'call', params: {} }),
    });
    assert.equal(afterLogout.status, 401);

    assert.equal(logs.join('\n').includes('secret'), false);
    assert.equal(logs.join('\n').includes('upstream-sid'), false);
  } finally {
    await relay.close();
    await odoo.close();
  }
});

test('relay rejects unknown paths and oversized RPC bodies', async () => {
  const logs = [];
  const odoo = await startMockOdoo();
  const { relay, url } = await startRelay(odoo.url, logs);
  try {
    const health = await fetch(url + '/health');
    assert.equal(health.status, 200);
    const unknown = await fetch(url + '/anything');
    assert.equal(unknown.status, 404);
    const oversized = await fetch(url + '/rpc', {
      method: 'POST',
      headers: headers({ 'X-Lab-Path': '/lab/api/catalog/search' }),
      body: 'x'.repeat(300 * 1024),
    });
    assert.equal(oversized.status, 413);
  } finally {
    await relay.close();
    await odoo.close();
  }
});
