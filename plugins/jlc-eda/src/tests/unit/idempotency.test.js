import test from 'node:test';
import assert from 'node:assert/strict';
import {
  canonicalize,
  createDraft,
  withPayload,
  beginSubmit,
  markSuccess,
  markFailure,
  canRetryWithSameKey,
  assertRequestKey,
} from '../../shared/idempotency.js';

let counter = 0;
function keyFactory() {
  counter += 1;
  return 'op-test-' + String(counter).padStart(4, '0');
}

test('canonicalize sorts keys and normalizes non-finite numbers', () => {
  assert.equal(canonicalize({ b: 1, a: { d: 2, c: 3 } }), '{"a":{"c":3,"d":2},"b":1}');
  assert.equal(canonicalize({ a: NaN, b: Infinity }), '{"a":null,"b":null}');
  assert.equal(canonicalize([{ z: 1, a: 2 }]), '[{"a":2,"z":1}]');
});

test('createDraft keeps a valid key and initial state', () => {
  const draft = createDraft('inventory.receipt', { quantity: 1 }, keyFactory);
  assert.equal(draft.operation, 'inventory.receipt');
  assert.equal(draft.state, 'new');
  assert.equal(assertRequestKey(draft.key), draft.key);
});

test('unchanged payload keeps the key; changed payload rotates it', () => {
  const first = createDraft('inventory.receipt', { quantity: 1, item_key: 'lcsc:C1' }, keyFactory);
  const same = withPayload(first, { item_key: 'lcsc:C1', quantity: 1 }, keyFactory);
  assert.equal(same.key, first.key);
  const changed = withPayload(first, { quantity: 2, item_key: 'lcsc:C1' }, keyFactory);
  assert.notEqual(changed.key, first.key);
  assert.equal(changed.state, 'new');
});

test('beginSubmit reuses a key after error, but success starts a new logical operation', () => {
  let draft = createDraft('inventory.issue', { lines: [{ bag_id: 1, quantity: 1 }] }, keyFactory);
  const first = beginSubmit(draft, keyFactory);
  assert.equal(first.key, draft.key);
  assert.equal(first.state, 'inflight');
  assert.throws(() => beginSubmit(first, keyFactory), (error) => error.code === 'CONFLICT');

  const failed = markFailure(first, { code: 'NETWORK', message: 'down' });
  assert.equal(failed.state, 'error');
  assert.equal(canRetryWithSameKey(failed), true);
  const retry = beginSubmit(failed, keyFactory);
  assert.equal(retry.key, draft.key);

  const ambiguous = markFailure(retry, { code: 'TIMEOUT_AMBIGUOUS', mayHaveBeenSent: true });
  assert.equal(ambiguous.state, 'ambiguous');

  const success = markSuccess(beginSubmit(ambiguous, keyFactory), { ok: true });
  const next = beginSubmit(success, keyFactory);
  assert.notEqual(next.key, success.key);
  assert.equal(next.state, 'inflight');
});

test('markFailure treats mayHaveBeenSent as ambiguous even without timeout code', () => {
  const draft = createDraft('inventory.return', { quantity: 1 }, keyFactory);
  const failed = markFailure(beginSubmit(draft, keyFactory), { code: 'NETWORK', mayHaveBeenSent: true });
  assert.equal(failed.state, 'ambiguous');
});
