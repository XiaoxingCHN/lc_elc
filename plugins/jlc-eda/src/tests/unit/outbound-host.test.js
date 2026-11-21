/**
 * Host-side contract for `inventory.outbound` (shared `handleOutbound`).
 *
 * Two paths must coexist:
 *   - legacy (no `issue_lines`): re-read stock, re-allocate, keep the old
 *     response shape so an already-installed old panel keeps working;
 *   - frozen (`issue_lines` present): issue EXACTLY those bags, never re-read
 *     stock, so a same-key retry cannot allocate different bags or create a
 *     second issue.
 *
 * The EDA entry point `dispatch('inventory.outbound', ...)` is a thin delegate
 * to this handler; testing the handler directly avoids needing the EDA host.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import { handleOutbound } from '../../shared/outbound.js';

function installFakeApi(overrides = {}) {
  const calls = { detail: [], issue: [] };
  const bags = overrides.bags || [
    { id: 7, available_quantity: 5, trace_code: 'LABB:7' },
    { id: 8, available_quantity: 5, trace_code: 'LABB:8' },
  ];
  const api = {
    async detail(itemKey) {
      calls.detail.push(itemKey);
      if (overrides.detailError) throw overrides.detailError;
      return {
        item: { name: 'R', lab_available_quantity: overrides.available ?? 10 },
        bags,
      };
    },
    async issue(input) {
      calls.issue.push(input);
      if (overrides.issueError) throw overrides.issueError;
      return (
        overrides.issueResult || {
          operation: { id: 99, name: 'LAB/ISS/99' },
          lines: input.lines.map((line, index) => ({
            issue_line_id: 500 + index,
            bag_id: line.bag_id,
            trace_code: 'LABB:' + line.bag_id,
            quantity: line.quantity,
            outstanding_quantity: line.quantity,
          })),
          replayed: Boolean(overrides.replayed),
        }
      );
    },
  };
  return { api, calls };
}

test('legacy path (no issue_lines) keeps old response and re-allocates', async () => {
  const { api, calls } = installFakeApi();
  const response = await handleOutbound(api, {
    lines: [{ item_key: 'lcsc:C1', quantity: 6 }],
    dry_run: false,
    request_key: 'out-legacy-0001',
    borrower_id: 5,
    project: 'P',
    note: '',
  });
  // Old panel reads response.plan and response.result; both must still exist.
  assert.equal(response.ok, true);
  assert.ok(Array.isArray(response.plan));
  assert.ok(response.result && response.result.operation);
  assert.equal(response.outcome, 'success');
  // The host re-read stock and allocated across both bags.
  assert.equal(calls.detail.length, 1);
  assert.deepEqual(calls.issue[0].lines, [
    { bag_id: 7, quantity: 5 },
    { bag_id: 8, quantity: 1 },
  ]);
});

test('legacy path tolerates a detail read failure as SHORT, never success', async () => {
  const { api } = installFakeApi({
    detailError: Object.assign(new Error('down'), { code: 'NETWORK_OR_CORS' }),
  });
  const response = await handleOutbound(api, {
    lines: [{ item_key: 'lcsc:C1', quantity: 1 }],
    dry_run: false,
    request_key: 'out-legacy-0002',
    borrower_id: 5,
    project: 'P',
  });
  assert.equal(response.ok, false);
  assert.equal(response.code, 'SHORT');
  assert.equal(response.outcome, 'reconfirm');
  assert.ok(!response.result, 'no issue result on detail failure');
});

test('frozen path issues exactly the supplied bags and never re-reads stock', async () => {
  const { api, calls } = installFakeApi();
  const frozen = [{ bag_id: 8, quantity: 2 }];
  const response = await handleOutbound(api, {
    lines: [{ item_key: 'lcsc:C1', quantity: 2 }],
    issue_lines: frozen,
    plan: [{ item_key: 'lcsc:C1', bags: frozen }],
    dry_run: false,
    request_key: 'out-frozen-0001',
    borrower_id: 5,
    project: 'P',
    note: '',
  });
  assert.equal(response.ok, true);
  assert.equal(response.outcome, 'success');
  assert.equal(response.frozen, true);
  assert.equal(response.request_key, 'out-frozen-0001');
  assert.equal(calls.detail.length, 0, 'frozen path must not re-read stock');
  assert.deepEqual(calls.issue[0].lines, frozen);
});

test('frozen retry reuses the same key and payload (server idempotency replays)', async () => {
  const { api, calls } = installFakeApi({ replayed: true });
  const params = {
    issue_lines: [{ bag_id: 7, quantity: 3 }],
    dry_run: false,
    request_key: 'out-frozen-0002',
    borrower_id: 5,
    project: 'P',
    note: '',
  };
  const first = await handleOutbound(api, params);
  const second = await handleOutbound(api, { ...params });
  assert.equal(calls.issue.length, 2);
  assert.equal(calls.issue[0].request_key, 'out-frozen-0002');
  assert.equal(calls.issue[1].request_key, 'out-frozen-0002');
  assert.deepEqual(calls.issue[1].lines, calls.issue[0].lines);
  assert.equal(first.outcome, 'success');
  assert.equal(second.outcome, 'success');
});

test('legacy dry run still returns a preview and a SHORT preview stays ok:false', async () => {
  const { api, calls } = installFakeApi();
  const preview = await handleOutbound(api, {
    lines: [{ item_key: 'lcsc:C1', quantity: 2 }],
    dry_run: true,
  });
  assert.equal(preview.ok, true);
  assert.equal(preview.dryRun, true);
  assert.equal(preview.outcome, undefined);
  assert.equal(calls.issue.length, 0);

  const short = await handleOutbound(api, {
    lines: [{ item_key: 'lcsc:C1', quantity: 999 }],
    dry_run: true,
  });
  assert.equal(short.ok, false);
  assert.equal(short.code, 'SHORT');
  assert.equal(short.outcome, 'reconfirm');
});

test('frozen path surfaces business rejections as thrown errors (no success)', async () => {
  const { api } = installFakeApi({
    issueError: Object.assign(new Error('库存不足'), {
      code: 'PRECONDITION_FAILED',
      fields: { lines: 'insufficient_stock' },
    }),
  });
  await assert.rejects(
    () =>
      handleOutbound(api, {
        issue_lines: [{ bag_id: 7, quantity: 99 }],
        dry_run: false,
        request_key: 'out-frozen-0003',
        borrower_id: 5,
        project: 'P',
      }),
    (error) => error.code === 'PRECONDITION_FAILED',
  );
});

test('frozen path rejects malformed issue_lines before touching Odoo', async () => {
  const { api, calls } = installFakeApi();
  await assert.rejects(
    () =>
      handleOutbound(api, {
        issue_lines: [{ bag_id: 0, quantity: 1 }],
        dry_run: false,
        request_key: 'out-frozen-0004',
        borrower_id: 5,
        project: 'P',
      }),
    (error) => error.code === 'VALIDATION_ERROR',
  );
  assert.equal(calls.issue.length, 0);
});
