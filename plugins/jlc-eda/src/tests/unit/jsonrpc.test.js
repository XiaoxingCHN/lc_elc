import test from 'node:test';
import assert from 'node:assert/strict';
import {
  ApiError,
  ERROR_CODES,
  buildJsonRpcRequest,
  decodeOdooResponse,
  decodeOdooResult,
  serializeApiError,
} from '../../shared/jsonrpc.js';

function envelope(result) {
  return JSON.stringify({ jsonrpc: '2.0', id: 'x', result });
}

test('buildJsonRpcRequest uses Odoo 19 call envelope', () => {
  const body = buildJsonRpcRequest({ query: 'C1' }, 'id-1');
  assert.equal(body.jsonrpc, '2.0');
  assert.equal(body.method, 'call');
  assert.equal(body.id, 'id-1');
  assert.deepEqual(body.params, { query: 'C1' });
});

test('decodes a successful business envelope', () => {
  const data = decodeOdooResponse({
    status: 200,
    text: envelope({ ok: true, data: { items: [1] }, error: null }),
    path: '/lab/api/catalog/search',
  });
  assert.deepEqual(data, { items: [1] });
});

test('decodes business errors with codes and fields', () => {
  assert.throws(
    () =>
      decodeOdooResponse({
        status: 200,
        text: envelope({ ok: false, data: null, error: { code: 'FORBIDDEN', message: 'no', fields: {} } }),
      }),
    (error) => error instanceof ApiError && error.code === ERROR_CODES.FORBIDDEN,
  );
  assert.throws(
    () =>
      decodeOdooResponse({
        status: 200,
        text: envelope({ ok: false, data: null, error: { code: 'AMBIGUOUS_MATERIAL', message: 'choose', fields: { candidates: [] } } }),
      }),
    (error) => error.code === ERROR_CODES.AMBIGUOUS_MATERIAL && error.action === 'choose_material',
  );
  assert.throws(
    () =>
      decodeOdooResponse({
        status: 200,
        text: envelope({ ok: false, data: null, error: { code: 'CONFLICT', message: 'dup' } }),
      }),
    (error) => error.code === ERROR_CODES.CONFLICT && error.action === 'new_request_key',
  );
});

test('maps Odoo SessionExpiredException to SESSION_EXPIRED', () => {
  assert.throws(
    () =>
      decodeOdooResponse({
        status: 200,
        text: JSON.stringify({
          jsonrpc: '2.0',
          id: null,
          error: { code: 100, message: 'Odoo Session Expired', data: { name: 'odoo.http.SessionExpiredException' } },
        }),
      }),
    (error) => error.code === ERROR_CODES.SESSION_EXPIRED && error.action === 'relogin',
  );
});

test('maps Odoo AccessError to FORBIDDEN', () => {
  assert.throws(
    () =>
      decodeOdooResponse({
        status: 200,
        text: JSON.stringify({
          jsonrpc: '2.0',
          error: { code: 200, message: 'Access denied', data: { name: 'odoo.exceptions.AccessError' } },
        }),
      }),
    (error) => error.code === ERROR_CODES.FORBIDDEN,
  );
});

test('detects login HTML as expired session', () => {
  assert.throws(
    () =>
      decodeOdooResponse({
        status: 200,
        text: '<!doctype html><html><body><form action="/web/login">login</form></body></html>',
      }),
    (error) => error.code === ERROR_CODES.SESSION_EXPIRED,
  );
});

test('401 non-JSON becomes SESSION_EXPIRED, 403 becomes FORBIDDEN', () => {
  assert.throws(() => decodeOdooResponse({ status: 401, text: 'Unauthorized' }), (error) => error.code === ERROR_CODES.SESSION_EXPIRED);
  assert.throws(() => decodeOdooResponse({ status: 403, text: 'Forbidden' }), (error) => error.code === ERROR_CODES.FORBIDDEN);
});

test('unexpected envelopes are explicit, never empty data', () => {
  assert.throws(() => decodeOdooResponse({ status: 200, text: '{}' }), (error) => error.code === ERROR_CODES.UNEXPECTED_ENVELOPE);
  assert.throws(
    () => decodeOdooResponse({ status: 200, text: JSON.stringify({ jsonrpc: '2.0', result: { data: {} } }) }),
    (error) => error.code === ERROR_CODES.UNEXPECTED_ENVELOPE,
  );
  assert.throws(() => decodeOdooResponse({ status: 200, text: '<html>oops</html>' }), (error) => error.code === ERROR_CODES.PARSE);
});

test('decodeOdooResult handles standard session endpoints', () => {
  const result = decodeOdooResult({
    status: 200,
    text: JSON.stringify({ jsonrpc: '2.0', id: 1, result: { uid: 7, name: 'Alice', db: 'lab' } }),
  });
  assert.equal(result.uid, 7);
  assert.equal(result.db, 'lab');
});

test('decodeOdooResult tolerates the production destroy response without result', () => {
  const result = decodeOdooResult(
    { status: 200, text: JSON.stringify({ jsonrpc: '2.0', id: null }), path: '/web/session/destroy' },
    { allowMissingResult: true },
  );
  assert.equal(result, null);
  assert.throws(
    () => decodeOdooResult({ status: 200, text: JSON.stringify({ jsonrpc: '2.0', id: null }), path: '/x' }),
    (error) => error.code === 'UNEXPECTED_ENVELOPE',
  );
});

test('serializeApiError returns safe structured fields', () => {
  const error = new ApiError(ERROR_CODES.TIMEOUT_AMBIGUOUS, 'timeout', {
    retryable: true,
    mayHaveBeenSent: true,
    fields: { lines: 'x' },
  });
  const json = serializeApiError(error);
  assert.equal(json.code, 'TIMEOUT_AMBIGUOUS');
  assert.equal(json.retryable, true);
  assert.equal(json.mayHaveBeenSent, true);
  assert.deepEqual(json.fields, { lines: 'x' });
});
