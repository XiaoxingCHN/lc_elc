import { ApiError, ERROR_CODES } from './jsonrpc.js';
import { parseItemKey } from './codes.js';

export function positiveQuantity(value, field = 'quantity') {
  const number = typeof value === 'number' ? value : Number(String(value ?? '').trim());
  if (!Number.isFinite(number) || number <= 0) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '数量必须是大于 0 的数字。', {
      fields: { [field]: 'positive_required' },
    });
  }
  return number;
}

export function positiveId(value, field) {
  const number = Number(value);
  if (!Number.isInteger(number) || number <= 0) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '「' + field + '」必须是正整数。', {
      fields: { [field]: 'positive_integer_required' },
    });
  }
  return number;
}

export function optionalPositiveId(value, field) {
  if (value === null || value === undefined || value === '' || value === false) return null;
  return positiveId(value, field);
}

export function requiredText(value, field, maxLength = 500) {
  const text = String(value ?? '').trim();
  if (!text) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '「' + field + '」不能为空。', {
      fields: { [field]: 'required' },
    });
  }
  if (text.length > maxLength) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '「' + field + '」不能超过 ' + maxLength + ' 个字符。', {
      fields: { [field]: 'too_long' },
    });
  }
  return text;
}

export function optionalText(value, field, maxLength = 500) {
  const text = String(value ?? '').trim();
  if (text.length > maxLength) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '「' + field + '」不能超过 ' + maxLength + ' 个字符。', {
      fields: { [field]: 'too_long' },
    });
  }
  return text;
}

export function requireItemKey(value) {
  const parsed = parseItemKey(value);
  if (!parsed.key) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '物料编号无效：需要 C 编号（如 C123）或 lab:<id>。', {
      fields: { item_key: 'invalid' },
    });
  }
  return parsed.key;
}

export function validateIssueLines(lines) {
  if (!Array.isArray(lines) || lines.length === 0) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '领用明细不能为空。', {
      fields: { lines: 'required' },
    });
  }
  if (lines.length > 100) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '一次领用最多 100 条明细。', {
      fields: { lines: 'too_many' },
    });
  }
  const seen = new Set();
  return lines.map((line, index) => {
    const bagId = positiveId(line && line.bag_id, 'lines[' + index + '].bag_id');
    if (seen.has(bagId)) {
      throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '同一袋不能在一次领用中重复出现，请合并数量。', {
        fields: { lines: 'duplicate_bag' },
      });
    }
    seen.add(bagId);
    return { bag_id: bagId, quantity: positiveQuantity(line && line.quantity, 'lines[' + index + '].quantity') };
  });
}
