import test from 'node:test';
import assert from 'node:assert/strict';
import {
  OUTBOUND_OUTCOME,
  OUTBOUND_OUTCOME_LABEL,
  freezeOutboundAttempt,
  outboundRequestParams,
  classifyOutboundResponse,
  classifyOutboundError,
  outboundNotice,
  outboundToast,
} from '../../shared/outbound.js';

let counter = 0;
function keyFactory() {
  counter += 1;
  return 'out-test-' + String(counter).padStart(4, '0');
}

const PLAN = [
  {
    item_key: 'lcsc:C1',
    name: '10k',
    need: 3,
    available: 10,
    bags: [
      { bag_id: 7, quantity: 2 },
      { bag_id: 8, quantity: 1 },
    ],
  },
  { item_key: 'lcsc:C2', name: '100nF', need: 1, available: 4, bags: [{ bag_id: 9, quantity: 1 }] },
];

function attempt() {
  return freezeOutboundAttempt(
    { borrowerId: 5, project: '  项目 A  ', note: 'BOM 一键出库', plan: PLAN },
    keyFactory,
  );
}

test('freezeOutboundAttempt binds bags, borrower, project and one request key', () => {
  const frozen = attempt();
  assert.equal(frozen.borrower_id, 5);
  assert.equal(frozen.project, '项目 A');
  assert.deepEqual(frozen.lines, [
    { bag_id: 7, quantity: 2 },
    { bag_id: 8, quantity: 1 },
    { bag_id: 9, quantity: 1 },
  ]);
  assert.match(frozen.draft.key, /^out-test-/);
  // Frozen plan is a copy: mutating the source must not change the attempt.
  PLAN[0].bags[0].quantity = 999;
  assert.equal(frozen.plan[0].bags[0].quantity, 2);
  PLAN[0].bags[0].quantity = 2;
});

test('freezeOutboundAttempt rejects empty allocation, duplicates and bad borrower', () => {
  assert.throws(
    () => freezeOutboundAttempt({ borrowerId: 1, project: 'p', plan: [] }, keyFactory),
    (error) => error.code === 'VALIDATION_ERROR',
  );
  assert.throws(
    () =>
      freezeOutboundAttempt(
        {
          borrowerId: 1,
          project: 'p',
          plan: [{ item_key: 'lcsc:C1', bags: [{ bag_id: 7, quantity: 1 }, { bag_id: 7, quantity: 1 }] }],
        },
        keyFactory,
      ),
    (error) => error.code === 'VALIDATION_ERROR',
  );
  assert.throws(
    () => freezeOutboundAttempt({ borrowerId: 0, project: 'p', plan: PLAN }, keyFactory),
    (error) => error.code === 'VALIDATION_ERROR',
  );
  assert.throws(
    () => freezeOutboundAttempt({ borrowerId: 1, project: '   ', plan: PLAN }, keyFactory),
    (error) => error.code === 'VALIDATION_ERROR',
  );
});

test('outboundRequestParams carries frozen issue_lines and the same request key on retry', () => {
  const frozen = attempt();
  const first = outboundRequestParams(frozen);
  assert.equal(first.dry_run, false);
  assert.equal(first.request_key, frozen.draft.key);
  assert.deepEqual(first.issue_lines, [
    { bag_id: 7, quantity: 2 },
    { bag_id: 8, quantity: 1 },
    { bag_id: 9, quantity: 1 },
  ]);
  // `lines` stays in the legacy {item_key, quantity} shape so an old host that
  // ignores issue_lines degrades to re-allocation instead of failing.
  assert.deepEqual(first.lines, [
    { item_key: 'lcsc:C1', quantity: 3 },
    { item_key: 'lcsc:C2', quantity: 1 },
  ]);
  // A retry of the same frozen attempt must send the exact same key + payload.
  const retry = outboundRequestParams(frozen);
  assert.equal(retry.request_key, first.request_key);
  assert.deepEqual(retry.issue_lines, first.issue_lines);
  assert.deepEqual(retry.lines, first.lines);
});

test('classifyOutboundResponse: success requires a real issue operation', () => {
  assert.equal(
    classifyOutboundResponse({ ok: true, outcome: 'success', result: { operation: { id: 1 }, lines: [] } }),
    OUTBOUND_OUTCOME.SUCCESS,
  );
  // Old host build (no outcome) but real result: still success.
  assert.equal(
    classifyOutboundResponse({ ok: true, plan: [], result: { operation: { id: 2 }, lines: [] } }),
    OUTBOUND_OUTCOME.SUCCESS,
  );
  // ok:true but no operation must NOT be success.
  assert.equal(classifyOutboundResponse({ ok: true, plan: [] }), OUTBOUND_OUTCOME.UNKNOWN);
  assert.equal(classifyOutboundResponse({ ok: true, outcome: 'success' }), OUTBOUND_OUTCOME.UNKNOWN);
});

test('classifyOutboundResponse: SHORT is reconfirm and never success (old and new host)', () => {
  const short = { ok: false, code: 'SHORT', shortage: [{ item_key: 'lcsc:C1' }], plan: [] };
  assert.equal(classifyOutboundResponse(short), OUTBOUND_OUTCOME.RECONFIRM);
  assert.equal(classifyOutboundResponse({ ...short, outcome: 'reconfirm' }), OUTBOUND_OUTCOME.RECONFIRM);
  assert.notEqual(classifyOutboundResponse(short), OUTBOUND_OUTCOME.SUCCESS);
  assert.equal(classifyOutboundResponse({ ok: false, code: 'PRECONDITION_FAILED' }), OUTBOUND_OUTCOME.RECONFIRM);
  assert.equal(classifyOutboundResponse({ ok: false, code: 'FORBIDDEN' }), OUTBOUND_OUTCOME.FAILED);
  assert.equal(classifyOutboundResponse(null), OUTBOUND_OUTCOME.UNKNOWN);
});

test('classifyOutboundError distinguishes unknown / reconfirm / failed', () => {
  // Lost response: may have reached the server.
  assert.equal(classifyOutboundError({ code: 'TIMEOUT_AMBIGUOUS', mayHaveBeenSent: true }), OUTBOUND_OUTCOME.UNKNOWN);
  assert.equal(classifyOutboundError({ code: 'NETWORK', mayHaveBeenSent: true }), OUTBOUND_OUTCOME.UNKNOWN);
  assert.equal(classifyOutboundError({ code: 'BRIDGE' }), OUTBOUND_OUTCOME.UNKNOWN);
  // Live re-validation after preview: nothing written.
  assert.equal(
    classifyOutboundError({ code: 'PRECONDITION_FAILED', fields: { lines: 'insufficient_stock' } }),
    OUTBOUND_OUTCOME.RECONFIRM,
  );
  // Deterministic business rejection.
  assert.equal(classifyOutboundError({ code: 'VALIDATION_ERROR' }), OUTBOUND_OUTCOME.FAILED);
  assert.equal(classifyOutboundError({ code: 'FORBIDDEN' }), OUTBOUND_OUTCOME.FAILED);
});

test('only SUCCESS notice claims stock was deducted', () => {
  const success = outboundNotice(OUTBOUND_OUTCOME.SUCCESS, { count: 3 });
  assert.equal(success.tone, 'ok');
  assert.match(success.text, /已按袋扣减/);

  for (const outcome of [OUTBOUND_OUTCOME.RECONFIRM, OUTBOUND_OUTCOME.UNKNOWN, OUTBOUND_OUTCOME.FAILED]) {
    const notice = outboundNotice(outcome, { count: 3 });
    assert.notEqual(notice.tone, 'ok');
    assert.equal(/已按袋扣减|出库成功|已出库/.test(notice.text), false, outcome + ' must not claim success');
    assert.equal(/已按袋扣减|出库成功|已出库/.test(notice.title), false, outcome + ' title must not claim success');
  }
  assert.equal(OUTBOUND_OUTCOME_LABEL.reconfirm, '需重新确认');
});

test('UNKNOWN notice tells the operator to retry with the same key and not to expect a query', () => {
  const notice = outboundNotice(OUTBOUND_OUTCOME.UNKNOWN);
  assert.match(notice.text, /原样重试/);
  assert.match(notice.text, /同一请求号/);
  assert.match(notice.text, /可能已处理/);
});

test('only SUCCESS toast claims completion; other outcomes never do', () => {
  const success = outboundToast(OUTBOUND_OUTCOME.SUCCESS, { count: 2 });
  assert.equal(success.tone, 'ok');
  assert.match(success.text, /出库完成/);
  for (const outcome of [OUTBOUND_OUTCOME.RECONFIRM, OUTBOUND_OUTCOME.UNKNOWN, OUTBOUND_OUTCOME.FAILED]) {
    const toast = outboundToast(outcome, { count: 2 });
    assert.notEqual(toast.tone, 'ok');
    assert.equal(/已按袋扣减|出库成功|出库完成|已出库/.test(toast.text), false, outcome + ' toast must not claim success');
  }
});
