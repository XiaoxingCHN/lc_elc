/**
 * EDA Pro API adapters. Only documented SDK methods are used:
 *   sch_PrimitiveComponent.getAll('part'[, allSchematicPages])
 *   sch_SelectControl.getAllSelectedPrimitives()
 *   dmt_Schematic.getAllSchematicPagesInfo()
 *   getState_Designator / Name / SupplierId / ManufacturerId /
 *   AddIntoBom / OtherProperty / Footprint / PrimitiveType
 */

import { ApiError, ERROR_CODES } from '../shared/jsonrpc.js';
import { firstCatalogCode } from '../shared/codes.js';
import { parseBomCsv } from '../shared/bom.js';

/**
 * Resolve the EDA extension API object.
 *
 * JLCEDA Pro runs the extension entry as
 *   new Function('sandbox', 'with (sandbox) { <bundle> }')
 * and passes the API object as the bare `eda` binding of that with-scope. The
 * host explicitly shadows window/document/self to undefined inside the scope
 * and does NOT define window.eda / globalThis.eda for the entry script. It only
 * assigns `eda` to the panel iframe's contentWindow, which is why the iframe
 * side may use window.eda.
 *
 * Therefore the injected binding must be preferred; globalThis.eda stays only
 * as a fallback for unit tests and standalone/browser harnesses.
 */
export function resolveEda() {
  try {
    /* eslint-disable-next-line no-undef -- injected by the EDA host with-scope */
    if (typeof eda !== 'undefined' && eda) return eda;
  } catch (_) {
    /* not executed inside the host with-scope */
  }
  try {
    if (typeof globalThis !== 'undefined' && globalThis.eda) return globalThis.eda;
  } catch (_) {
    /* ignore */
  }
  return null;
}

export function getEda() {
  const eda = resolveEda();
  if (!eda) {
    throw new ApiError(ERROR_CODES.EDA_CONTEXT, '未检测到 EDA 扩展 API，请在嘉立创 EDA 专业版中运行本插件。');
  }
  return eda;
}

export function safeCall(fn, fallback) {
  try {
    const value = fn();
    return value === undefined ? fallback : value;
  } catch (_) {
    return fallback;
  }
}

export function toast(message, type = 'info', seconds = 3) {
  const map = { error: 'error', warning: 'warn', info: 'info', success: 'success', question: 'question' };
  const t = map[type] || 'info';
  const eda = resolveEda();
  if (!eda) return;
  try {
    if (eda.sys_Message && typeof eda.sys_Message.showToastMessage === 'function') {
      eda.sys_Message.showToastMessage(String(message), t, seconds);
      return;
    }
    if (eda.sys_ToastMessage && typeof eda.sys_ToastMessage.showMessage === 'function') {
      eda.sys_ToastMessage.showMessage(String(message), t, seconds);
    }
  } catch (_) {
    /* a toast failure must not break a command */
  }
}

export function resolveTemplateName(rawName, otherProps, manufacturerId) {
  const raw = String(rawName || '');
  const match = /^=\{(.+)\}$/.exec(raw);
  if (!match) return raw;
  const key = match[1].trim();
  if (otherProps && typeof otherProps === 'object') {
    if (otherProps[key] !== undefined && otherProps[key] !== null && String(otherProps[key]).trim()) {
      return String(otherProps[key]);
    }
    const lower = key.toLowerCase();
    for (const candidate of Object.keys(otherProps)) {
      if (candidate.toLowerCase() === lower && String(otherProps[candidate] ?? '').trim()) {
        return String(otherProps[candidate]);
      }
    }
  }
  return String(manufacturerId || raw);
}

const CODE_PROPERTY_KEYS = [
  'Supplier Part',
  'SupplierPart',
  'LCSC Part',
  'LCSC Part #',
  'LCSC',
  'LCSC Part Number',
  '立创编号',
  '立创编号(C)',
  '供应商编号',
  'SupplierId',
];

export function readPrimitive(primitive, context = {}) {
  if (!primitive || typeof primitive !== 'object') return null;
  const primitiveType = safeCall(() => primitive.getState_PrimitiveType(), undefined);
  if (primitiveType && primitiveType !== 'Component') return null;

  const properties = safeCall(() => primitive.getState_OtherProperty(), {}) || {};
  const manufacturerId = safeCall(() => primitive.getState_ManufacturerId(), '') || '';
  const supplierPartNumber = safeCall(() => primitive.getState_SupplierId(), '') || '';
  const supplierName = safeCall(() => primitive.getState_Supplier(), '') || '';
  const candidates = [supplierPartNumber];
  for (const key of CODE_PROPERTY_KEYS) candidates.push(properties[key]);
  const code = firstCatalogCode(candidates);
  const rawName = safeCall(() => primitive.getState_Name(), '') || '';
  const name = resolveTemplateName(rawName, properties, manufacturerId);
  const addIntoBom = safeCall(() => primitive.getState_AddIntoBom(), undefined);
  const footprint = safeCall(() => primitive.getState_Footprint(), undefined);

  return {
    primitiveId: safeCall(() => primitive.getState_PrimitiveId(), '') || '',
    designator: safeCall(() => primitive.getState_Designator(), '') || '',
    code: code || '',
    itemKey: code ? 'lcsc:' + code : '',
    supplierPartNumber: String(supplierPartNumber || ''),
    supplierName: String(supplierName || ''),
    manufacturerId: String(manufacturerId || ''),
    name: String(name || ''),
    footprint: String(footprint && typeof footprint === 'object' ? footprint.name || '' : footprint || ''),
    addIntoBom: typeof addIntoBom === 'boolean' ? addIntoBom : null,
    page: context.page || '',
    rawProperties: properties,
  };
}

function isComponentPrimitive(primitive) {
  const type = safeCall(() => primitive.getState_PrimitiveType(), 'Component');
  return !type || type === 'Component';
}

async function readPageInfo(eda) {
  try {
    if (!eda.dmt_Schematic || typeof eda.dmt_Schematic.getAllSchematicPagesInfo !== 'function') {
      return { total: null, names: [] };
    }
    const pages = await eda.dmt_Schematic.getAllSchematicPagesInfo();
    const list = Array.isArray(pages) ? pages : [];
    return {
      total: list.length,
      names: list.map((page) => String((page && page.name) || '')).filter(Boolean).slice(0, 100),
    };
  } catch (_) {
    return { total: null, names: [] };
  }
}

export async function scanSchematic(options = {}) {
  const eda = options.eda || getEda();
  const scope = options.scope || 'page';
  const warnings = [];
  let primitives = [];

  if (scope === 'selected') {
    const selection = eda.sch_SelectControl;
    if (!selection || typeof selection.getAllSelectedPrimitives !== 'function') {
      throw new ApiError(ERROR_CODES.EDA_CONTEXT, '当前 EDA 环境不支持读取选中图元，请在原理图编辑器中操作。');
    }
    const selected = await selection.getAllSelectedPrimitives();
    primitives = (Array.isArray(selected) ? selected : []).filter(isComponentPrimitive);
    if (primitives.length === 0) warnings.push('没有选中器件。请先在原理图中选择器件，或改用当前图页。');
  } else {
    const api = eda.sch_PrimitiveComponent;
    if (!api || typeof api.getAll !== 'function') {
      throw new ApiError(ERROR_CODES.EDA_CONTEXT, '当前 EDA 环境没有原理图器件接口，请在原理图编辑器中操作。');
    }
    const allSchematicPages = scope === 'loaded';
    const result = await api.getAll('part', allSchematicPages);
    primitives = Array.isArray(result) ? result : [];
  }

  const pageInfo = scope === 'loaded' ? await readPageInfo(eda) : { total: null, names: [] };
  if (scope === 'loaded' && pageInfo.total !== null && pageInfo.total > 1) {
    warnings.push(
      'EDA 只返回已加载图页中的器件（未打开图页不会被读取）。当前工程共 ' +
        pageInfo.total +
        ' 页；如需完整 BOM，请先在 EDA 中打开全部图页，或用「选中器件」核对局部。',
    );
  }
  if (primitives.length === 0) warnings.push('没有读取到任何器件图元。');

  const components = primitives.map((primitive) => readPrimitive(primitive, { page: '' })).filter(Boolean);
  const missingCode = components.filter((component) => !component.code).length;
  if (missingCode > 0) {
    warnings.push(missingCode + ' 个器件没有有效的立创 C 编号，已单独列出，不会并入库存款。');
  }

  return {
    scope,
    components,
    warnings,
    pageInfo,
    scannedAt: new Date().toISOString(),
    totals: {
      primitives: primitives.length,
      components: components.length,
      missingCode,
    },
  };
}

/** Bounded export: a hanging @beta manufacture-data call must never block the panel. */
const BOM_EXPORT_TIMEOUT_MS = 7000;

export function withTimeout(promise, ms, label) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new ApiError(ERROR_CODES.EDA_CONTEXT, label + ' 超过 ' + Math.round(ms / 1000) + ' 秒没有返回'));
    }, ms);
    Promise.resolve(promise).then(
      (value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function bomProviders(eda) {
  const list = [];
  const schematic = eda && eda.sch_ManufactureData;
  const pcb = eda && eda.pcb_ManufactureData;
  const inSchematic = Boolean(eda && eda.sch_PrimitiveComponent);
  const push = (name, api) => {
    if (api && typeof api.getBomFile === 'function') list.push([name, api]);
  };
  // The current editor decides which BOM source answers first; the other one is
  // still tried because EDA documents both and only one may exist per project.
  if (inSchematic) {
    push('sch_ManufactureData', schematic);
    push('pcb_ManufactureData', pcb);
  } else {
    push('pcb_ManufactureData', pcb);
    push('sch_ManufactureData', schematic);
  }
  return list;
}

async function fileToText(file) {
  if (!file) return '';
  if (typeof file.text === 'function') return String(await file.text());
  if (typeof file.arrayBuffer === 'function') {
    return String(new globalThis.TextDecoder('utf-8').decode(await file.arrayBuffer()));
  }
  throw new ApiError(ERROR_CODES.EDA_CONTEXT, 'BOM 文件无法读取文本内容。');
}

/**
 * Export the whole-project BOM and return its CSV text.
 *
 * Uses `sch_ManufactureData.getBomFile` (schematic editor) or
 * `pcb_ManufactureData.getBomFile` (PCB editor); both are documented @beta
 * APIs, so every attempt is time-boxed and failures are reported instead of
 * silently hanging the bridge.
 */
async function readProjectBomText(eda, timeoutMs = BOM_EXPORT_TIMEOUT_MS) {
  const providers = bomProviders(eda);
  if (!providers.length) {
    throw new ApiError(
      ERROR_CODES.EDA_CONTEXT,
      '当前 EDA 环境没有 BOM 导出接口（sch_/pcb_ManufactureData.getBomFile）。',
    );
  }
  const failures = [];
  const attemptArgs = [
    ['lab_inventory_bom', 'csv', undefined, [{ property: 'Add into BOM', includeValue: 'yes' }]],
    ['lab_inventory_bom', 'csv'],
  ];
  for (const [name, api] of providers) {
    for (const args of attemptArgs) {
      try {
        const file = await withTimeout(api.getBomFile(...args), timeoutMs, name + '.getBomFile');
        const text = await fileToText(file);
        if (text) return { text, provider: name };
        failures.push(name + ' 返回空文件');
        break;
      } catch (error) {
        failures.push(name + '：' + String((error && error.message) || error));
        // Do not pay the timeout twice for the same provider.
        break;
      }
    }
  }
  const error = new ApiError(ERROR_CODES.EDA_CONTEXT, '导出工程 BOM 失败：' + failures.join('；'));
  error.failures = failures;
  throw error;
}

/**
 * Read the project BOM (preferred) and fall back to the schematic scan when the
 * manufacture-data API is unavailable or refuses to answer.
 */
export async function scanProjectBom(options = {}) {
  const eda = options.eda || getEda();
  const warnings = [];
  let bomError = null;
  try {
    const exported = await readProjectBomText(eda, options.timeoutMs);
    const parsed = parseBomCsv(exported.text);
    if (parsed.lines.length) {
      return {
        scope: 'project',
        source: 'bom',
        provider: exported.provider,
        lines: parsed.lines,
        components: [],
        unmapped: parsed.unmapped,
        warnings: parsed.warnings,
        pageInfo: { total: null, names: [] },
        scannedAt: new Date().toISOString(),
        totals: {
          lines: parsed.lines.length,
          quantity: parsed.lines.reduce((sum, line) => sum + line.quantity, 0),
          missingCode: parsed.unmapped.length,
        },
      };
    }
    warnings.push((parsed.warnings[0] || '工程 BOM 没有解析出任何器件') + '，已改用原理图读取。');
  } catch (error) {
    bomError = error;
    warnings.push('读取工程 BOM 失败（' + String((error && error.message) || error) + '），已改用原理图读取。');
  }

  const fallback = await scanSchematic({ eda, scope: 'loaded' });
  return Object.assign({}, fallback, {
    scope: 'project',
    source: 'schematic',
    provider: 'schematic',
    lines: null,
    unmapped: [],
    bomError: bomError ? { code: bomError.code || 'EDA_BOM', message: bomError.message } : null,
    warnings: warnings.concat(fallback.warnings || []),
  });
}
