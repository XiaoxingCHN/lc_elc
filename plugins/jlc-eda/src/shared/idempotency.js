/**
 * Client-side idempotency draft.
 *
 * The server owns the real guarantee (request_key + uid + company + payload
 * fingerprint). This module only guarantees that:
 *   - a network-ambiguous retry reuses the SAME key and payload;
 *   - editing the payload rotates the key (otherwise the server correctly
 *     answers CONFLICT because the fingerprint changed);
 *   - a double click cannot start two submissions of one draft.
 */

import { ApiError, ERROR_CODES, requestId } from './jsonrpc.js';

export function defaultKeyFactory() {
  return requestId('op');
}

function canonicalValue(value) {
  if (value === null) return null;
  if (value === undefined) return null;
  const type = typeof value;
  if (type === 'number') return Number.isFinite(value) ? value : null;
  if (type === 'string' || type === 'boolean') return value;
  if (type === 'bigint') return value.toString();
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (type === 'object') {
    const output = {};
    for (const key of Object.keys(value).sort()) {
      if (value[key] === undefined) continue;
      output[key] = canonicalValue(value[key]);
    }
    return output;
  }
  return String(value);
}

export function canonicalize(value) {
  return JSON.stringify(canonicalValue(value));
}

export function assertRequestKey(key) {
  if (typeof key !== 'string' || key.length < 8 || key.length > 128) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, 'request_key 长度必须在 8~128 之间。');
  }
  if (!/^[A-Za-z0-9._:-]+$/.test(key)) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, 'request_key 只能包含字母、数字和 . _ : -。');
  }
  return key;
}

export function createDraft(operation, payload, keyFactory = defaultKeyFactory) {
  if (!operation) throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '缺少操作类型。');
  return {
    operation,
    payload: canonicalValue(payload || {}),
    canonical: canonicalize(payload || {}),
    key: assertRequestKey(keyFactory()),
    state: 'new',
    attempts: 0,
    lastError: null,
  };
}

/** Returns the same draft when the payload is unchanged, otherwise a fresh key. */
export function withPayload(draft, payload, keyFactory = defaultKeyFactory) {
  const next = canonicalize(payload || {});
  if (next === draft.canonical) {
    return { ...draft, payload: canonicalValue(payload || {}) };
  }
  return {
    operation: draft.operation,
    payload: canonicalValue(payload || {}),
    canonical: next,
    key: assertRequestKey(keyFactory()),
    state: 'new',
    attempts: 0,
    lastError: null,
  };
}

export function beginSubmit(draft, keyFactory = defaultKeyFactory) {
  if (draft.state === 'inflight') {
    throw new ApiError(ERROR_CODES.CONFLICT, '上一次提交仍在进行，已阻止重复提交。', {
      action: 'wait',
    });
  }
  const key = draft.state === 'success' ? assertRequestKey(keyFactory()) : draft.key;
  return { ...draft, key, state: 'inflight', attempts: draft.attempts + 1, lastError: null };
}

export function markSuccess(draft, data = {}) {
  return { ...draft, state: 'success', lastError: null, result: data };
}

export function markFailure(draft, error) {
  const ambiguous = Boolean(error && (error.mayHaveBeenSent || error.code === ERROR_CODES.TIMEOUT_AMBIGUOUS));
  return {
    ...draft,
    state: ambiguous ? 'ambiguous' : 'error',
    lastError: error ? { code: error.code, message: error.message } : null,
  };
}

export function canRetryWithSameKey(draft) {
  return draft.state === 'ambiguous' || draft.state === 'error';
}
