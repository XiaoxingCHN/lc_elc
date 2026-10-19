import test from 'node:test';
import assert from 'node:assert/strict';
import { createLabApi } from '../../main/api.js';

function makeClient() {
  const calls = [];
  return {
    calls,
    async call(path, params) {
      calls.push({ path, params });
      return { ok: true };
    },
  };
}

test('search maps contract params and clamps limit', async () => {
  const client = makeClient();
  const api = createLabApi(client);
  await api.search({
    query: '  C123  ',
    category_id: '4',
    brands: ['Yageo', ''],
    packages: ['0402'],
    parameters: { resistance: '10k', tolerance: ['1%'] },
    stock_only: 1,
    cursor: 'abc',
    limit: 999,
  });
  const call = client.calls[0];
  assert.equal(call.path, '/lab/api/catalog/search');
  assert.equal(call.params.query, 'C123');
  assert.equal(call.params.category_id, 4);
  assert.deepEqual(call.params.brands, ['Yageo']);
  assert.deepEqual(call.params.packages, ['0402']);
  assert.deepEqual(call.params.parameters, { resistance: ['10k'], tolerance: ['1%'] });
  assert.equal(call.params.stock_only, true);
  assert.equal(call.params.cursor, 'abc');
  assert.equal(call.params.limit, 200);
});

test('detail canonicalizes a bare C code and rejects invalid keys', async () => {
  const client = makeClient();
  const api = createLabApi(client);
  await api.detail('c123');
  assert.deepEqual(client.calls[0], { path: '/lab/api/catalog/detail', params: { item_key: 'lcsc:C123' } });
  await assert.rejects(() => api.detail('C0'), (error) => error.code === 'VALIDATION_ERROR');
});

test('receipt sends the exact contract payload', async () => {
  const client = makeClient();
  const api = createLabApi(client);
  await api.receipt({
    request_key: 'op-12345678',
    item_key: 'c1',
    product_template_id: '42',
    location_id: '3',
    quantity: '5',
    supplier_qr: 'JLC-RAW',
    note: 'note',
  });
  const call = client.calls[0];
  assert.equal(call.path, '/lab/api/inventory/receipt');
  assert.equal(call.params.request_key, 'op-12345678');
  assert.equal(call.params.item_key, 'lcsc:C1');
  assert.equal(call.params.product_template_id, 42);
  assert.equal(call.params.location_id, 3);
  assert.equal(call.params.quantity, 5);
  assert.equal(call.params.supplier_qr, 'JLC-RAW');
});

test('issue validates borrower, project and unique bag lines', async () => {
  const client = makeClient();
  const api = createLabApi(client);
  await api.issue({
    request_key: 'op-12345678',
    borrower_id: '7',
    project: '  Project A  ',
    lines: [{ bag_id: '1', quantity: '2' }],
    note: '',
  });
  assert.equal(client.calls[0].params.borrower_id, 7);
  assert.equal(client.calls[0].params.project, 'Project A');
  assert.deepEqual(client.calls[0].params.lines, [{ bag_id: 1, quantity: 2 }]);

  await assert.rejects(
    () =>
      api.issue({
        request_key: 'op-12345678',
        borrower_id: 7,
        project: 'P',
        lines: [{ bag_id: 1, quantity: 1 }, { bag_id: 1, quantity: 2 }],
      }),
    (error) => error.code === 'VALIDATION_ERROR',
  );
  await assert.rejects(
    () => api.issue({ request_key: 'op-12345678', borrower_id: 7, project: '   ', lines: [{ bag_id: 1, quantity: 1 }] }),
    (error) => error.code === 'VALIDATION_ERROR',
  );
});

test('return sends issue_line_id, quantity and note', async () => {
  const client = makeClient();
  const api = createLabApi(client);
  await api.returnStock({ request_key: 'op-12345678', issue_line_id: '9', quantity: '2', note: 'ok' });
  assert.deepEqual(client.calls[0], {
    path: '/lab/api/inventory/return',
    params: { request_key: 'op-12345678', issue_line_id: 9, quantity: 2, note: 'ok' },
  });
});

test('issues and history clamp pagination and canonicalize item key', async () => {
  const client = makeClient();
  const api = createLabApi(client);
  await api.issues({ query: ' LABB ', outstanding_only: true, limit: 999 });
  assert.equal(client.calls[0].params.limit, 200);
  assert.equal(client.calls[0].params.query, 'LABB');
  await api.history({ item_key: 'c7', bag_id: '2', limit: 0 });
  assert.equal(client.calls[1].params.item_key, 'lcsc:C7');
  assert.equal(client.calls[1].params.bag_id, 2);
  assert.equal(client.calls[1].params.limit, 1);
  await assert.rejects(() => api.history({ item_key: 'bad' }), (error) => error.code === 'VALIDATION_ERROR');
});
