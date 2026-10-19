/**
 * Thin, validating wrappers over the real /lab/api endpoints.
 * Payload shapes mirror business_api_contract.json exactly.
 */

import { ApiError, ERROR_CODES } from '../shared/jsonrpc.js';
import { parseItemKey } from '../shared/codes.js';
import { assertRequestKey } from '../shared/idempotency.js';
import {
  optionalPositiveId,
  optionalText,
  positiveId,
  positiveQuantity,
  requiredText,
  requireItemKey,
  validateIssueLines,
} from '../shared/validate.js';

function clampLimit(value, fallback = 30) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(1, Math.min(200, Math.floor(number)));
}

function stringList(value) {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item)).filter(Boolean);
}

function parameterObject(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  const output = {};
  for (const [key, raw] of Object.entries(value)) {
    const list = Array.isArray(raw) ? raw : [raw];
    const clean = list.map((item) => String(item)).filter((item) => item.length > 0);
    if (clean.length) output[String(key)] = clean;
  }
  return output;
}

export function createLabApi(client) {
  async function search(params = {}) {
    return client.call('/lab/api/catalog/search', {
      query: String(params.query || '').trim(),
      category_id: optionalPositiveId(params.category_id, 'category_id'),
      brands: stringList(params.brands),
      packages: stringList(params.packages),
      parameters: parameterObject(params.parameters),
      stock_only: Boolean(params.stock_only),
      cursor: params.cursor ? String(params.cursor) : null,
      limit: clampLimit(params.limit),
    });
  }

  async function detail(itemKey) {
    return client.call('/lab/api/catalog/detail', { item_key: requireItemKey(itemKey) });
  }

  async function categories() {
    return client.call('/lab/api/catalog/categories', {});
  }

  async function facets(params = {}) {
    return client.call('/lab/api/catalog/facets', {
      query: String(params.query || '').trim(),
      category_id: optionalPositiveId(params.category_id, 'category_id'),
      brands: stringList(params.brands),
      packages: stringList(params.packages),
      parameters: parameterObject(params.parameters),
    });
  }

  async function bootstrap() {
    return client.call('/lab/api/inventory/bootstrap', {});
  }

  async function locations() {
    return client.call('/lab/api/inventory/locations', {});
  }

  async function resolveCode(raw) {
    const text = requiredText(raw, 'raw', 2000);
    return client.call('/lab/api/inventory/resolve_code', { raw: text });
  }

  async function receipt(input = {}) {
    const requestKey = assertRequestKey(input.request_key);
    const payload = {
      request_key: requestKey,
      item_key: requireItemKey(input.item_key),
      product_template_id: optionalPositiveId(input.product_template_id, 'product_template_id'),
      location_id: positiveId(input.location_id, 'location_id'),
      quantity: positiveQuantity(input.quantity, 'quantity'),
      supplier_qr: optionalText(input.supplier_qr, 'supplier_qr', 2000),
      note: optionalText(input.note, 'note', 500),
    };
    if (input.trace_code) payload.trace_code = optionalText(input.trace_code, 'trace_code', 128);
    if (input.sn) payload.sn = optionalText(input.sn, 'sn', 128);
    return client.call('/lab/api/inventory/receipt', payload);
  }

  async function issue(input = {}) {
    const requestKey = assertRequestKey(input.request_key);
    const lines = validateIssueLines(input.lines);
    return client.call('/lab/api/inventory/issue', {
      request_key: requestKey,
      borrower_id: positiveId(input.borrower_id, 'borrower_id'),
      project: requiredText(input.project, 'project', 200),
      lines,
      note: optionalText(input.note, 'note', 500),
    });
  }

  async function returnStock(input = {}) {
    const requestKey = assertRequestKey(input.request_key);
    return client.call('/lab/api/inventory/return', {
      request_key: requestKey,
      issue_line_id: positiveId(input.issue_line_id, 'issue_line_id'),
      quantity: positiveQuantity(input.quantity, 'quantity'),
      note: optionalText(input.note, 'note', 500),
    });
  }

  async function issues(params = {}) {
    return client.call('/lab/api/inventory/issues', {
      query: String(params.query || '').trim(),
      outstanding_only: params.outstanding_only !== false,
      cursor: params.cursor ? String(params.cursor) : null,
      limit: clampLimit(params.limit, 50),
    });
  }

  async function history(params = {}) {
    let itemKey = null;
    if (params.item_key) {
      const parsed = parseItemKey(params.item_key);
      if (!parsed.key) {
        throw new ApiError(ERROR_CODES.VALIDATION_ERROR, 'history.item_key 无效。');
      }
      itemKey = parsed.key;
    }
    return client.call('/lab/api/inventory/history', {
      item_key: itemKey,
      bag_id: optionalPositiveId(params.bag_id, 'bag_id'),
      cursor: params.cursor ? String(params.cursor) : null,
      limit: clampLimit(params.limit, 50),
    });
  }

  return { search, detail, categories, facets, bootstrap, locations, resolveCode, receipt, issue, returnStock, issues, history };
}
