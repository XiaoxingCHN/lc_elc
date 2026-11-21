import test from 'node:test';
import assert from 'node:assert/strict';
import { createOdooClient } from '../../main/odoo.js';

const TOKEN = 'eda_' + 'A'.repeat(43);

function makeTransport(responder) {
  const requests = [];
  return {
    requests,
    async request(input) {
      requests.push(input);
      return responder(input);
    },
  };
}

function jsonRpc(result, id = 1) {
  return { status: 200, text: JSON.stringify({ jsonrpc: '2.0', id, result }) };
}

test('every request carries Authorization: bearer <token>', async () => {
  const transport = makeTransport(() =>
    jsonRpc({ ok: true, data: { items: [] }, error: null }));
  const client = createOdooClient({
    config: { serverUrl: 'https://lab.example.test', token: TOKEN },
    transport,
  });
  await client.call('/lab/api/eda/catalog/search', { query: 'x' });
  assert.equal(transport.requests.length, 1);
  assert.equal(transport.requests[0].headers.Authorization, 'bearer ' + TOKEN);
  assert.equal(transport.requests[0].url, 'https://lab.example.test/lab/api/eda/catalog/search');
});

test('no token means no request and a login action', async () => {
  const transport = makeTransport(() => jsonRpc({}));
  const client = createOdooClient({
    config: { serverUrl: 'https://lab.example.test', token: '' },
    transport,
  });
  await assert.rejects(
    () => client.call('/lab/api/eda/bootstrap', {}),
    (error) => error.code === 'SESSION_REQUIRED' && error.action === 'login',
  );
  assert.equal(transport.requests.length, 0);
});

test('MISSING_TOKEN / INVALID_TOKEN map to SESSION_EXPIRED', async () => {
  for (const code of ['MISSING_TOKEN', 'INVALID_TOKEN']) {
    const transport = makeTransport(() =>
      jsonRpc({ ok: false, data: null, error: { code, message: '密钥无效', fields: {} } }));
    const client = createOdooClient({
      config: { serverUrl: 'https://lab.example.test', token: TOKEN },
      transport,
    });
    await assert.rejects(
      () => client.call('/lab/api/eda/bootstrap', {}),
      (error) => error.code === 'SESSION_EXPIRED' && error.action === 'login',
      code,
    );
  }
});

test('business errors keep their own code', async () => {
  const transport = makeTransport(() =>
    jsonRpc({ ok: false, data: null,
      error: { code: 'FORBIDDEN', message: '没有代领权限', fields: { borrower_id: 'x' } } }));
  const client = createOdooClient({
    config: { serverUrl: 'https://lab.example.test', token: TOKEN },
    transport,
  });
  await assert.rejects(
    () => client.call('/lab/api/eda/inventory/issue', {}),
    (error) => error.code === 'FORBIDDEN' && error.fields.borrower_id === 'x',
  );
});

test('successful call unwraps the data envelope', async () => {
  const transport = makeTransport(() =>
    jsonRpc({ ok: true, data: { user: { id: 7, name: '张三' } }, error: null }));
  const client = createOdooClient({
    config: { serverUrl: 'https://lab.example.test', token: TOKEN },
    transport,
  });
  const data = await client.call('/lab/api/eda/bootstrap', {});
  assert.deepEqual(data, { user: { id: 7, name: '张三' } });
});

test('connect() reads the identity from bootstrap', async () => {
  const transport = makeTransport(() =>
    jsonRpc({ ok: true, data: { user: { id: 9, name: '李四', login: 'lisi' } }, error: null }));
  const client = createOdooClient({
    config: { serverUrl: 'https://lab.example.test', token: TOKEN },
    transport,
  });
  const session = await client.connect();
  assert.equal(session.active, true);
  assert.equal(session.uid, 9);
  assert.equal(session.name, '李四');
  assert.equal(session.sessionMode, 'bearer');
});

test('disconnect clears the identity but keeps the token', async () => {
  const transport = makeTransport(() =>
    jsonRpc({ ok: true, data: { user: { id: 9, name: '李四' } }, error: null }));
  const client = createOdooClient({
    config: { serverUrl: 'https://lab.example.test', token: TOKEN },
    transport,
  });
  await client.connect();
  client.disconnect();
  const session = client.publicSession();
  assert.equal(session.active, false);
  assert.equal(session.uid, null);
  // token 仍在 config 里（由调用方决定是否清除）
  assert.equal(client.getConfig().token, TOKEN);
});

test('never sends a Cookie header', async () => {
  const transport = makeTransport(() => jsonRpc({ ok: true, data: {}, error: null }));
  const client = createOdooClient({
    config: { serverUrl: 'https://lab.example.test', token: TOKEN },
    transport,
  });
  await client.call('/lab/api/eda/bootstrap', {});
  const headers = transport.requests[0].headers;
  assert.equal(headers.Cookie, undefined);
  assert.equal(headers.cookie, undefined);
});
