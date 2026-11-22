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
  assert.equal(call.path, '/lab/api/eda/catalog/search');
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
  assert.deepEqual(client.calls[0], { path: '/lab/api/eda/catalog/detail', params: { item_key: 'lcsc:C123' } });
  await assert.rejects(() => api.detail('C0'), (error) => error.code === 'VALIDATION_ERROR');
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

test('equivalents forwards name and footprint with each line', async () => {
  // 服务端要靠 name/footprint 在资料库没有该 C 编号时去实验室库存找候选。
  // 旧断言把「只有 item_key+quantity」当成正确结果，等于把 bug 固化进测试
  // ——这正是 4.1.2 包测试全绿却功能不生效的原因。
  const client = makeClient();
  const api = createLabApi(client);
  await api.equivalents([
    { item_key: 'lcsc:C51376376', quantity: 20, name: '100nF', footprint: '0603' },
    { item_key: '', quantity: 2 },
    null,
    { item_key: 'lcsc:C25804', quantity: '1', name: '  ' },
  ]);
  assert.deepEqual(client.calls[0], {
    path: '/lab/api/eda/catalog/equivalents',
    params: {
      lines: [
        { item_key: 'lcsc:C51376376', quantity: 20, name: '100nF', footprint: '0603' },
        { item_key: 'lcsc:C25804', quantity: 1 },
      ],
      limit_per_line: 5,
    },
  });
  await api.equivalents(null, 3);
  assert.deepEqual(client.calls[1].params, { lines: [], limit_per_line: 3 });
});

