import test from 'node:test';
import assert from 'node:assert/strict';
import { createRelayClient } from '../../main/relay.js';

function makeTransport(handler) {
  const calls = [];
  return {
    calls,
    async request(input) {
      calls.push(input);
      return handler(input);
    },
    async requestBinary(input) {
      calls.push(input);
      return { buffer: new Uint8Array([1, 2]).buffer, contentType: 'image/png', status: 200 };
    },
  };
}

function jsonResponse(body, status = 200) {
  return { status, text: JSON.stringify(body), ok: status >= 200 && status < 300 };
}

test('relay client logs in without any upstream sid/cookie header', async () => {
  const transport = makeTransport(() =>
    jsonResponse({ ok: true, data: { uid: 7, name: 'Alice', username: 'alice', db: 'LcHardwareHouse', sessionMode: 'relay' }, error: null }),
  );
  const client = createRelayClient({
    transport,
    relayUrl: 'http://127.0.0.1:49621',
    pairingToken: 'pair-token-123456',
    serverUrl: 'http://lc.rm.com',
    db: 'LcHardwareHouse',
  });
  const session = await client.authenticate({ login: 'alice', password: 'secret' });
  assert.equal(session.active, true);
  assert.equal(session.sessionMode, 'relay');
  assert.equal(transport.calls[0].headers.Authorization, 'Bearer pair-token-123456');
  assert.equal(transport.calls[0].headers.Cookie, undefined);
  assert.equal(JSON.stringify(transport.calls[0].body).includes('session_id'), false);
});

test('relay client sends path header and decodes the business envelope', async () => {
  const transport = makeTransport((input) => {
    if (input.url.endsWith('/login')) {
      return jsonResponse({ ok: true, data: { uid: 7, name: 'Alice' }, error: null });
    }
    return jsonResponse({
      jsonrpc: '2.0',
      id: 1,
      result: { ok: true, data: { items: [{ item_key: 'lcsc:C1' }] }, error: null },
    });
  });
  const client = createRelayClient({
    transport,
    relayUrl: 'http://127.0.0.1:49621',
    pairingToken: 'pair-token-123456',
    serverUrl: 'http://lc.rm.com',
    db: 'LcHardwareHouse',
  });
  await client.authenticate({ login: 'alice', password: 'secret' });
  const data = await client.call('/lab/api/catalog/search', { query: 'C1' });
  assert.deepEqual(data.items[0].item_key, 'lcsc:C1');
  assert.equal(transport.calls[1].headers['X-Lab-Path'], '/lab/api/catalog/search');
  assert.equal(transport.calls[1].headers.Cookie, undefined);
});

test('relay auth errors are explicit', async () => {
  const transport = makeTransport(() =>
    jsonResponse({ ok: false, data: null, error: { code: 'RELAY_AUTH', message: 'bad token' } }, 401),
  );
  const client = createRelayClient({
    transport,
    relayUrl: 'http://127.0.0.1:49621',
    pairingToken: 'bad-token-123456',
    serverUrl: 'http://lc.rm.com',
    db: 'LcHardwareHouse',
  });
  await assert.rejects(
    () => client.authenticate({ login: 'alice', password: 'secret' }),
    (error) => error.code === 'RELAY_AUTH' && error.action === 'relay_pairing',
  );
});

test('relay asset URL wraps the Odoo asset URL and logout tolerates empty result', async () => {
  const transport = makeTransport((input) => {
    if (input.url.endsWith('/login')) return jsonResponse({ ok: true, data: { uid: 7 }, error: null });
    if (input.url.endsWith('/logout')) {
      return jsonResponse({ ok: true, data: { upstreamOk: true }, error: null });
    }
    return jsonResponse({ ok: true, data: {}, error: null });
  });
  const client = createRelayClient({
    transport,
    relayUrl: 'http://127.0.0.1:49621',
    pairingToken: 'pair-token-123456',
    serverUrl: 'http://lc.rm.com',
    db: 'LcHardwareHouse',
  });
  await client.authenticate({ login: 'alice', password: 'secret' });
  const asset = await client.asset('http://lc.rm.com/lab/api/asset?url=x');
  assert.equal(asset.contentType, 'image/png');
  assert.ok(transport.calls.at(-1).url.includes('/asset?url='));
  const result = await client.logout();
  assert.equal(result.ok, true);
  assert.equal(client.publicSession().active, false);
});
