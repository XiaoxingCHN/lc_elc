/**
 * One-click BOM outbound result contract, shared by the EDA host and iframe.
 *
 * Exactly four outcomes:
 *   success   – a real issue operation exists (fresh or server replay)
 *   reconfirm – nothing was written; the preview/allocation must be redone
 *   failed    – the server rejected the request; no stock change is claimed
 *   unknown   – the request may or may not have been processed (lost response)
 *
 * The attempt (confirmed bags + borrower + project + note) is frozen together
 * with ONE request key. A retry reuses that key and payload, so the server's
 * existing idempotency (`request_key` + user + company + method fingerprint)
 * returns the original result instead of creating a second issue operation.
 * This module reuses `shared/idempotency.js` for the draft lifecycle rather
 * than inventing a second state machine.
 */

import { ApiError, ERROR_CODES } from './jsonrpc.js';
import { createDraft, defaultKeyFactory } from './idempotency.js';
import { allocateBags } from './bom.js';
import { positiveId, positiveQuantity, requireItemKey } from './validate.js';

export const OUTBOUND_OUTCOME = Object.freeze({
  SUCCESS: 'success',
  RECONFIRM: 'reconfirm',
  FAILED: 'failed',
  UNKNOWN: 'unknown',
});

export const OUTBOUND_OUTCOME_LABEL = Object.freeze({
  success: '已完成',
  reconfirm: '需重新确认',
  failed: '失败',
  unknown: '结果未知',
});

/** Error codes whose request may already have reached (and been processed by) Odoo. */
const AMBIGUOUS_ERROR_CODES = new Set([
  ERROR_CODES.TIMEOUT_AMBIGUOUS,
  ERROR_CODES.TIMEOUT,
  ERROR_CODES.NETWORK,
  ERROR_CODES.NETWORK_OR_CORS,
  ERROR_CODES.BRIDGE,
  ERROR_CODES.HTTP,
  ERROR_CODES.PARSE,
  ERROR_CODES.UNEXPECTED_ENVELOPE,
  ERROR_CODES.INTERNAL_ERROR,
  ERROR_CODES.RELAY_UNAVAILABLE,
  ERROR_CODES.UNKNOWN,
]);

function clonePlan(plan) {
  return (Array.isArray(plan) ? plan : []).map((entry) => ({
    item_key: String((entry && entry.item_key) || ''),
    name: (entry && entry.name) || '',
    need: Number((entry && entry.need) || 0),
    available: entry && entry.available !== undefined ? entry.available : null,
    bags: ((entry && entry.bags) || []).map((bag) => ({
      bag_id: Number(bag && bag.bag_id),
      quantity: Number(bag && bag.quantity),
    })),
  }));
}

/**
 * Bind the confirmed allocation, borrower and project into an immutable attempt.
 * The attempt's request key is created once here and must be reused verbatim on
 * every retry of the same business action.
 */
export function freezeOutboundAttempt(input, keyFactory = defaultKeyFactory) {
  const borrowerId = Number(input && input.borrowerId);
  if (!Number.isInteger(borrowerId) || borrowerId <= 0) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '请选择领用人。', { fields: { borrower_id: 'required' } });
  }
  const project = String((input && input.project) || '').trim();
  if (!project) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '请填写项目/用途。', { fields: { project: 'required' } });
  }
  if (project.length > 200) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '项目/用途不能超过 200 个字符。', {
      fields: { project: 'too_long' },
    });
  }
  const note = String((input && input.note) || '');
  const plan = clonePlan(input && input.plan);
  const lines = [];
  const seen = new Set();
  for (const entry of plan) {
    for (const bag of entry.bags) {
      if (!Number.isInteger(bag.bag_id) || bag.bag_id <= 0) {
        throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '分配计划里的袋 ID 无效，请重新预览。', {
          fields: { lines: 'invalid_bag' },
        });
      }
      if (!Number.isFinite(bag.quantity) || bag.quantity <= 0) {
        throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '分配计划里的袋数量无效，请重新预览。', {
          fields: { lines: 'invalid_quantity' },
        });
      }
      if (seen.has(bag.bag_id)) {
        throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '同一袋在分配计划中重复出现，请重新预览。', {
          fields: { lines: 'duplicate_bag' },
        });
      }
      seen.add(bag.bag_id);
      lines.push({ bag_id: bag.bag_id, quantity: bag.quantity });
    }
  }
  if (!lines.length) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '分配计划为空，无法出库。', {
      fields: { lines: 'required' },
    });
  }
  const payload = { borrower_id: borrowerId, project, note, lines };
  return {
    borrower_id: borrowerId,
    project,
    note,
    lines,
    plan,
    draft: createDraft('inventory.outbound', payload, keyFactory),
  };
}

/**
 * Request params for the host. `issue_lines` tells the host to issue exactly
 * these frozen bags instead of re-reading stock and re-allocating.
 */
export function outboundRequestParams(attempt) {
  const issueLines = attempt.lines.map((line) => ({ bag_id: line.bag_id, quantity: line.quantity }));
  // `lines` keeps the legacy `{item_key, quantity}` shape so a new panel that
  // happens to talk to an OLD host still degrades to the old re-allocation path
  // instead of failing validation. New hosts use `issue_lines` (frozen).
  const sourceLines = (attempt.plan || [])
    .filter((entry) => entry && entry.item_key)
    .map((entry) => ({ item_key: entry.item_key, quantity: Number(entry.need) || 0 }));
  return {
    lines: sourceLines,
    issue_lines: issueLines,
    plan: clonePlan(attempt.plan),
    borrower_id: attempt.borrower_id,
    project: attempt.project,
    note: attempt.note,
    request_key: attempt.draft.key,
    dry_run: false,
  };
}

/**
 * Classify a host response. Accepts the new explicit `outcome` field and old
 * host builds that returned `{ok, plan, result}` / `{ok:false, code:'SHORT'}`.
 */
export function classifyOutboundResponse(response) {
  if (!response || typeof response !== 'object') return OUTBOUND_OUTCOME.UNKNOWN;
  const result = response.result;
  const hasOperation = Boolean(result && typeof result === 'object' && result.operation);
  if (response.ok === false) {
    const code = String(
      response.code || (response.error && response.error.code) || '',
    ).toUpperCase();
    if (code === 'SHORT' || code === 'PRECONDITION_FAILED') return OUTBOUND_OUTCOME.RECONFIRM;
    return OUTBOUND_OUTCOME.FAILED;
  }
  if (response.outcome === OUTBOUND_OUTCOME.SUCCESS && hasOperation) return OUTBOUND_OUTCOME.SUCCESS;
  // Backward compatibility: old host builds have no `outcome` but do return the
  // real issue result (operation + lines) on success.
  if (hasOperation) return OUTBOUND_OUTCOME.SUCCESS;
  if (response.dryRun) return OUTBOUND_OUTCOME.RECONFIRM;
  return OUTBOUND_OUTCOME.UNKNOWN;
}

/**
 * Classify a thrown bridge/transport error. Anything that may already have
 * reached Odoo is UNKNOWN; only deterministic business rejections are FAILED.
 */
export function classifyOutboundError(error) {
  if (!error) return OUTBOUND_OUTCOME.FAILED;
  const code = String(error.code || '').toUpperCase();
  const fields = (error && error.fields) || {};
  // Live re-validation after the preview: nothing was written, re-confirm.
  if (code === 'PRECONDITION_FAILED' && (fields.lines === 'insufficient_stock' || fields.lines === 'stock')) {
    return OUTBOUND_OUTCOME.RECONFIRM;
  }
  if (error.mayHaveBeenSent) return OUTBOUND_OUTCOME.UNKNOWN;
  if (AMBIGUOUS_ERROR_CODES.has(code)) return OUTBOUND_OUTCOME.UNKNOWN;
  return OUTBOUND_OUTCOME.FAILED;
}

/**
 * Host-side `inventory.outbound` handler.
 *
 * Two paths, decided solely by whether `issue_lines` is present:
 *   - legacy (absent): re-read stock, re-allocate, issue the fresh bags. This
 *     is exactly the old behaviour, so an already-installed old panel keeps
 *     working; the response only gains extra optional fields.
 *   - frozen (present): issue exactly those bags. No stock read, no
 *     re-allocation, so a same-key retry cannot create a second issue.
 *
 * The Odoo endpoint signature is unchanged; this only composes existing
 * `lab.detail` / `lab.issue` calls.
 */
export async function handleOutbound(lab, params, options = {}) {
  const log = typeof options.log === 'function' ? options.log : () => {};
  if (Array.isArray(params && params.issue_lines) && params.issue_lines.length) {
    const frozen = params.issue_lines.map((raw, index) => ({
      bag_id: positiveId(raw && raw.bag_id, 'issue_lines[' + index + '].bag_id'),
      quantity: positiveQuantity(raw && raw.quantity, 'issue_lines[' + index + '].quantity'),
    }));
    const result = await lab.issue({
      request_key: params && params.request_key,
      borrower_id: params && params.borrower_id,
      project: params && params.project,
      note: params && params.note,
      lines: frozen,
    });
    log('inventory.outbound', {
      frozen: true,
      bags: frozen.length,
      replayed: Boolean(result && result.replayed),
    });
    return {
      ok: true,
      outcome: OUTBOUND_OUTCOME.SUCCESS,
      frozen: true,
      request_key: (params && params.request_key) || null,
      plan: Array.isArray(params && params.plan) ? params.plan : [],
      result,
    };
  }

  const requested = Array.isArray(params && params.lines) ? params.lines : [];
  if (!requested.length) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '一键出库明细不能为空。');
  }
  if (requested.length > 60) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '一次一键出库最多 60 个器件型号。');
  }
  const plan = [];
  const shortage = [];
  for (const raw of requested) {
    const itemKey = requireItemKey(raw && raw.item_key);
    const need = positiveQuantity(raw && raw.quantity, 'lines[].quantity');
    let detail = null;
    let detailError = null;
    try {
      detail = await lab.detail(itemKey);
    } catch (error) {
      detailError = error;
    }
    if (!detail || !detail.item) {
      shortage.push({
        item_key: itemKey,
        need,
        available: null,
        reason: detailError ? String(detailError.message || detailError.code || detailError) : '不在资料库中',
      });
      continue;
    }
    const allocation = allocateBags(detail.bags, need);
    const available = Number(detail.item.lab_available_quantity);
    plan.push({
      item_key: itemKey,
      name: detail.item.name || '',
      need,
      available: Number.isFinite(available) ? available : null,
      bags: allocation.lines,
      shortfall: allocation.shortfall,
    });
    if (allocation.shortfall > 0) {
      shortage.push({
        item_key: itemKey,
        need,
        available: Number.isFinite(available) ? available : null,
        shortfall: allocation.shortfall,
        reason: '库存不足',
      });
    }
  }
  if (shortage.length) {
    // Nothing was written; the caller must re-preview. `outcome` is optional
    // for old panels that only read `ok`/`code`.
    return { ok: false, code: 'SHORT', outcome: OUTBOUND_OUTCOME.RECONFIRM, shortage, plan };
  }
  if (params && params.dry_run) {
    return { ok: true, dryRun: true, plan };
  }
  const issueLines = [];
  for (const entry of plan) for (const bag of entry.bags) issueLines.push(bag);
  const result = await lab.issue({
    request_key: params && params.request_key,
    borrower_id: params && params.borrower_id,
    project: params && params.project,
    note: params && params.note,
    lines: issueLines,
  });
  log('inventory.outbound', { lines: plan.length, bags: issueLines.length });
  return {
    ok: true,
    outcome: OUTBOUND_OUTCOME.SUCCESS,
    request_key: (params && params.request_key) || null,
    plan,
    result,
  };
}

/**
 * UI notice for each outcome. Only SUCCESS may contain success wording
 * ("已按袋扣减"); the other three explicitly say nothing was confirmed.
 */
export function outboundNotice(outcome, options = {}) {
  const count = Number(options.count) || 0;
  const replayed = Boolean(options.replayed);
  switch (outcome) {
    case OUTBOUND_OUTCOME.SUCCESS:
      return {
        tone: 'ok',
        title: '一键出库完成',
        text:
          '一键出库成功：' +
          count +
          ' 个型号，已按袋扣减完成。' +
          (replayed ? '（服务器重放，未重复扣减）' : '') +
          '可在「领用」页签查看领用单。',
      };
    case OUTBOUND_OUTCOME.RECONFIRM:
      return {
        tone: 'warn',
        title: '需要重新确认',
        text: '未扣减任何库存：预览后库存或按袋分配已变化。请重新预览分配并再次确认。',
      };
    case OUTBOUND_OUTCOME.UNKNOWN:
      return {
        tone: 'warn',
        title: '结果未知',
        text:
          '服务器没有返回明确结果，本次出库可能已处理，也可能未处理；本页不会显示已扣减。' +
          '插件无法按请求号直接查询，请用「原样重试」以同一请求号重发：服务器若已处理会返回原领用单，不会产生第二张。' +
          '也可打开 Odoo「请求记账（幂等）」人工核对。',
      };
    case OUTBOUND_OUTCOME.FAILED:
    default:
      return {
        tone: 'error',
        title: '出库失败',
        text: '服务器拒绝了本次出库，未确认任何库存变更。请查看错误信息后重新预览。',
      };
  }
}

/**
 * Toast text for an outcome. Only SUCCESS may contain success wording; every
 * other outcome returns a non-success message. Kept here so the wording rule is
 * unit-testable without a DOM.
 */
export function outboundToast(outcome, options = {}) {
  const count = Number(options.count) || 0;
  switch (outcome) {
    case OUTBOUND_OUTCOME.SUCCESS:
      return { tone: 'ok', text: '出库完成：' + count + ' 个型号' };
    case OUTBOUND_OUTCOME.RECONFIRM:
      return { tone: 'warn', text: '需要重新确认：库存或分配已变化，未扣减任何库存。' };
    case OUTBOUND_OUTCOME.UNKNOWN:
      return { tone: 'warn', text: '结果未知，可用同一请求号原样重试。' };
    case OUTBOUND_OUTCOME.FAILED:
    default:
      return { tone: 'error', text: '出库失败，未确认任何库存变更。' };
  }
}
