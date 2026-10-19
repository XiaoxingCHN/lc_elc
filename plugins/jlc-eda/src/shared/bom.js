/**
 * Read-only BOM grouping and stock comparison.
 *
 * Identity is always the C code (lcsc:C123). A component without a valid C
 * code is reported as unmapped and is never merged into another line.
 * Unknown stock is `null`, never 0.
 */

import { normalizeCatalogCode } from './codes.js';

export const BOM_STATUS = Object.freeze({
  OK: 'ok',
  SHORT: 'short',
  UNKNOWN: 'unknown',
  NOT_IN_CATALOG: 'not_in_catalog',
  NO_CODE: 'no_code',
});

function clean(value) {
  return value === null || value === undefined ? '' : String(value).trim();
}

export function groupBom(components, options = {}) {
  const bomOnly = options.bomOnly !== false;
  const lines = new Map();
  const unmapped = [];
  const excluded = [];
  let bomComponents = 0;

  for (const component of components || []) {
    if (!component || typeof component !== 'object') continue;
    const inBom = component.addIntoBom !== false;
    if (bomOnly && !inBom) {
      excluded.push(component);
      continue;
    }
    const code = normalizeCatalogCode(component.code);
    if (!code) {
      unmapped.push(component);
      continue;
    }
    bomComponents += 1;
    const key = 'lcsc:' + code;
    if (!lines.has(key)) {
      lines.set(key, {
        itemKey: key,
        code,
        name: clean(component.name),
        mpn: clean(component.mpn),
        manufacturerId: clean(component.manufacturerId),
        quantity: 0,
        designators: [],
        pages: [],
      });
    }
    const line = lines.get(key);
    line.quantity += 1;
    if (component.designator) {
      for (const designator of String(component.designator).split(/[,，\s]+/)) {
        if (designator) line.designators.push(designator);
      }
    }
    if (component.page && !line.pages.includes(component.page)) line.pages.push(component.page);
    if (!line.name && component.name) line.name = clean(component.name);
    if (!line.mpn && component.mpn) line.mpn = clean(component.mpn);
  }

  return {
    lines: Array.from(lines.values()).sort((a, b) => a.code.localeCompare(b.code, 'en', { numeric: true })),
    unmapped,
    excluded,
    bomComponents,
    totalComponents: (components || []).length,
  };
}

export function compareLine(line, detail, error) {
  const need = Number(line.quantity) || 0;
  if (error) {
    const notFound = error.code === 'NOT_FOUND';
    return {
      ...line,
      need,
      available: null,
      total: null,
      gap: null,
      status: notFound ? BOM_STATUS.NOT_IN_CATALOG : BOM_STATUS.UNKNOWN,
      detailError: { code: error.code, message: error.message },
      locations: [],
      bags: [],
      localTemplateCount: 0,
    };
  }
  if (!detail || !detail.item) {
    return {
      ...line,
      need,
      available: null,
      total: null,
      gap: null,
      status: BOM_STATUS.UNKNOWN,
      detailError: null,
      locations: [],
      bags: [],
      localTemplateCount: 0,
    };
  }
  const item = detail.item;
  const availableRaw = item.lab_available_quantity;
  const totalRaw = item.lab_quantity;
  const available = Number.isFinite(Number(availableRaw)) && availableRaw !== null ? Number(availableRaw) : null;
  const total = Number.isFinite(Number(totalRaw)) && totalRaw !== null ? Number(totalRaw) : null;
  const gap = available === null ? null : Math.max(0, need - available);
  return {
    ...line,
    need,
    name: clean(item.name) || line.name,
    mpn: clean(item.mpn) || line.mpn,
    available,
    total,
    gap,
    status: available === null ? BOM_STATUS.UNKNOWN : gap > 0 ? BOM_STATUS.SHORT : BOM_STATUS.OK,
    detailError: null,
    locations: Array.isArray(detail.locations) ? detail.locations : [],
    bags: Array.isArray(detail.bags) ? detail.bags : [],
    localTemplateCount: Array.isArray(detail.lab_templates) ? detail.lab_templates.length : 0,
  };
}

export function summarize(rows) {
  const result = {
    lineCount: rows.length,
    need: 0,
    available: 0,
    gap: 0,
    shortLines: 0,
    unknownLines: 0,
    notInCatalogLines: 0,
    okLines: 0,
  };
  for (const row of rows) {
    result.need += Number(row.need) || 0;
    if (row.available !== null && row.available !== undefined) result.available += Number(row.available) || 0;
    if (row.gap !== null && row.gap !== undefined) result.gap += Number(row.gap) || 0;
    if (row.status === BOM_STATUS.SHORT) result.shortLines += 1;
    else if (row.status === BOM_STATUS.UNKNOWN) result.unknownLines += 1;
    else if (row.status === BOM_STATUS.NOT_IN_CATALOG) result.notInCatalogLines += 1;
    else if (row.status === BOM_STATUS.OK) result.okLines += 1;
  }
  return result;
}

/* ------------------------------------------------------------------------- */
/* Project BOM import (EDA "Manufacture > BOM" CSV export)                    */
/* ------------------------------------------------------------------------- */

const COLUMN_MATCHERS = [
  ['designators', /位号|designator|reference/i],
  ['quantity', /数量|quantity|qty/i],
  ['code', /立创编号|lcsc|supplier\s*part|供应商编号|supplierid|c\s*编号/i],
  ['name', /名称|comment|value|器件名称/i],
  ['mpn', /型号|manufacturer\s*part|mpn|规格/i],
  ['footprint', /封装|footprint|package/i],
  ['addIntoBom', /add\s*into\s*bom|加入\s*bom/i],
];

export function parseCsvRows(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let quoted = false;
  const source = String(text === null || text === undefined ? '' : text).replace(/^\ufeff/, '');
  for (let i = 0; i < source.length; i += 1) {
    const ch = source[i];
    if (quoted) {
      if (ch === '"') {
        if (source[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += ch;
      }
      continue;
    }
    if (ch === '"') {
      quoted = true;
    } else if (ch === ',') {
      row.push(cell);
      cell = '';
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && source[i + 1] === '\n') i += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else {
      cell += ch;
    }
  }
  if (cell !== '' || row.length) rows.push(row.concat(cell));
  return rows.filter((cells) => cells.some((value) => String(value).trim() !== ''));
}

/**
 * Parse the CSV exported by EDA (PCBoard manufacture data / schematic BOM).
 * Rows are grouped per C code so the result is directly comparable with stock.
 */
export function parseBomCsv(text) {
  const rows = parseCsvRows(text);
  const warnings = [];
  if (!rows.length) return { lines: [], unmapped: [], excluded: 0, warnings: ['BOM 文件为空。'], columns: [] };

  const header = rows[0].map((cell) => String(cell).trim());
  const columns = {};
  for (const [field, pattern] of COLUMN_MATCHERS) {
    const at = header.findIndex((cell) => cell && pattern.test(cell));
    if (at >= 0 && columns[field] === undefined) columns[field] = at;
  }
  const used = Object.keys(columns);
  if (!used.length) {
    const hint = header.slice(0, 6).join(' | ');
    return {
      lines: [],
      unmapped: [],
      excluded: 0,
      warnings: ['无法识别 BOM 表头（' + hint + '），请检查 BOM 模板是否包含位号/数量/立创编号列。'],
      columns: header,
    };
  }
  if (columns.code === undefined) warnings.push('BOM 没有「立创编号/Supplier Part」列，所有器件都会被列为未映射。');

  const cellAt = (cells, field) => (columns[field] === undefined ? '' : String(cells[columns[field]] ?? '').trim());
  const lines = new Map();
  const unmapped = [];
  let excluded = 0;

  for (const cells of rows.slice(1)) {
    const designators = cellAt(cells, 'designators')
      .split(/[,，;；\s]+/)
      .map((value) => value.trim())
      .filter(Boolean);
    const rawQuantity = cellAt(cells, 'quantity');
    const parsedQuantity = Number(String(rawQuantity).replace(/[^0-9.]/g, ''));
    const quantity = Number.isFinite(parsedQuantity) && parsedQuantity > 0 ? parsedQuantity : Math.max(1, designators.length);
    const addFlag = cellAt(cells, 'addIntoBom').toLowerCase();
    if (addFlag && /^(no|false|0|n|否)$/.test(addFlag)) {
      excluded += quantity;
      continue;
    }
    const code = normalizeCatalogCode(cellAt(cells, 'code'));
    const name = cellAt(cells, 'name');
    const mpn = cellAt(cells, 'mpn');
    const footprint = cellAt(cells, 'footprint');
    if (!code) {
      unmapped.push({ code: '', designator: designators.join(','), name, mpn, footprint, quantity });
      continue;
    }
    const key = 'lcsc:' + code;
    if (!lines.has(key)) {
      lines.set(key, {
        itemKey: key,
        code,
        name,
        mpn,
        manufacturerId: '',
        footprint,
        quantity: 0,
        designators: [],
        pages: [],
      });
    }
    const line = lines.get(key);
    line.quantity += quantity;
    for (const designator of designators) if (!line.designators.includes(designator)) line.designators.push(designator);
    if (!line.name && name) line.name = name;
    if (!line.mpn && mpn) line.mpn = mpn;
    if (!line.footprint && footprint) line.footprint = footprint;
  }

  if (unmapped.length) warnings.push(unmapped.length + ' 行没有有效的立创 C 编号，已单独列出，不会并入库存款。');
  return {
    lines: Array.from(lines.values()),
    unmapped,
    excluded,
    warnings,
    columns: header,
  };
}

/**
 * Pick bags for a BOM line (FIFO by bag id). Never invents stock: only bags with
 * a server-provided available quantity are used.
 */
export function allocateBags(bags, need) {
  const wanted = Math.max(0, Number(need) || 0);
  const candidates = (Array.isArray(bags) ? bags : [])
    .filter((bag) => bag && Number(bag.id) > 0 && Number(bag.available_quantity) > 0)
    .map((bag) => ({ ...bag, id: Number(bag.id), available: Number(bag.available_quantity) }))
    .sort((a, b) => a.id - b.id);
  let remaining = wanted;
  const picked = [];
  for (const bag of candidates) {
    if (remaining <= 0) break;
    const take = Math.min(bag.available, remaining);
    if (take <= 0) continue;
    picked.push({ bag_id: bag.id, quantity: take, available: bag.available, traceCode: bag.trace_code || '' });
    remaining -= take;
  }
  return {
    lines: picked.map((entry) => ({ bag_id: entry.bag_id, quantity: entry.quantity })),
    picked,
    need: wanted,
    shortfall: Math.max(0, remaining),
  };
}

export function bomTsv(rows) {
  const header = ['状态', 'C 编号', '名称', '型号', '位号', '需求', '可用', '缺口', '库位'];
  const body = rows.map((row) => {
    const locations = (row.locations || [])
      .map((location) => {
        const name = location.location || location.name || location.path || '';
        const qty = location.available_quantity ?? location.quantity;
        return name + (qty === undefined ? '' : '(' + qty + ')');
      })
      .join(' ');
    return [
      row.status,
      row.code,
      row.name || '',
      row.mpn || '',
      (row.designators || []).join(','),
      row.need,
      row.available === null ? '未知' : row.available,
      row.gap === null ? '未知' : row.gap,
      locations,
    ]
      .map((value) => String(value).replace(/[\t\r\n]+/g, ' '))
      .join('\t');
  });
  return [header.join('\t')].concat(body).join('\n');
}
