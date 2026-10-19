/**
 * Canonical identity helpers shared by the EDA extension and tests.
 *
 * Contract (lc_elc/docs/business_api_contract.json):
 *   catalog / bound   -> "lcsc:C123"
 *   unbound local     -> "lab:42"
 * Normalisation is NFKC + trim + uppercase. A C code is "C" followed by
 * positive decimal digits; short codes such as C1 are valid. Null, empty,
 * C0, C-1 and arbitrary strings are invalid and must never be merged.
 */

const ZERO_WIDTH = /[\u200b\u200c\u200d\ufeff]/g;
const WHITESPACE = /\s+/g;

export function normalizeCatalogCode(value) {
  if (value === null || value === undefined) return null;
  let text;
  try {
    text = String(value).normalize('NFKC');
  } catch (_) {
    text = String(value);
  }
  text = text.replace(ZERO_WIDTH, '').replace(WHITESPACE, '').trim().toUpperCase();
  if (!text) return null;
  const match = /^C([0-9]+)$/.exec(text);
  if (!match) return null;
  // C0 / C000 are not real catalogue codes (positive value required).
  if (Number(match[1]) <= 0) return null;
  return 'C' + match[1];
}

export function isCatalogCode(value) {
  return normalizeCatalogCode(value) !== null;
}

export function catalogItemKey(value) {
  const code = normalizeCatalogCode(value);
  return code ? 'lcsc:' + code : null;
}

export function localItemKey(templateId) {
  const id = Number(templateId);
  return Number.isInteger(id) && id > 0 ? 'lab:' + id : null;
}

/** Parse "lcsc:C123" / "lab:42"; bare C codes are accepted as a convenience. */
export function parseItemKey(value) {
  if (value === null || value === undefined) return { kind: null, value: null, key: null };
  const raw = String(value).normalize('NFKC').trim();
  if (!raw) return { kind: null, value: null, key: null };
  const lower = raw.toLowerCase();
  if (lower.startsWith('lcsc:')) {
    const code = normalizeCatalogCode(raw.slice(5));
    return code
      ? { kind: 'lcsc', value: code, key: 'lcsc:' + code }
      : { kind: null, value: null, key: null };
  }
  if (lower.startsWith('lab:')) {
    const suffix = raw.slice(4).trim();
    const id = Number(suffix);
    return Number.isInteger(id) && id > 0
      ? { kind: 'lab', value: id, key: 'lab:' + id }
      : { kind: null, value: null, key: null };
  }
  const code = normalizeCatalogCode(raw);
  return code ? { kind: 'lcsc', value: code, key: 'lcsc:' + code } : { kind: null, value: null, key: null };
}

/** First valid C code from a list of candidate supplier/property values. */
export function firstCatalogCode(candidates) {
  for (const candidate of candidates || []) {
    const code = normalizeCatalogCode(candidate);
    if (code) return code;
  }
  return null;
}
