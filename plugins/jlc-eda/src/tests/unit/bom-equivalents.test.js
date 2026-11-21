import test from 'node:test';
import assert from 'node:assert/strict';
import {
  equivalentsRequestLines,
  attachEquivalents,
  substituteLines,
  substitutionNote,
  BOM_STATUS,
} from '../../shared/bom.js';

function row(overrides = {}) {
  return Object.assign(
    { code: 'C14663', itemKey: 'lcsc:C14663', need: 4, available: 0, gap: 4, status: BOM_STATUS.SHORT },
    overrides,
  );
}

const C1525 = {
  item_key: 'lcsc:C1525',
  catalog_code: 'C1525',
  name: '0.1uF ±10% 50V X7R 0402',
  brand: '国巨',
  available: 320,
  confidence: 'strong',
  matched: [{ name: '容值', value: '0.1uF' }],
  conflicts: [],
};

test('equivalentsRequestLines asks only for missing lines and sends the gap', () => {
  const rows = [
    row({ code: 'C1', itemKey: 'lcsc:C1', status: BOM_STATUS.OK, gap: 0, need: 2 }),
    row({ code: 'C2', itemKey: 'lcsc:C2', status: BOM_STATUS.SHORT, gap: 3, need: 5 }),
    row({ code: 'C3', itemKey: 'lcsc:C3', status: BOM_STATUS.NOT_IN_CATALOG, gap: null, need: 7 }),
    row({ code: 'C4', itemKey: 'lcsc:C4', status: BOM_STATUS.UNKNOWN, gap: null, need: 1 }),
  ];
  assert.deepEqual(equivalentsRequestLines(rows), [
    { item_key: 'lcsc:C2', quantity: 3 },
    { item_key: 'lcsc:C3', quantity: 7 },
  ]);
  assert.deepEqual(equivalentsRequestLines([]), []);
  assert.deepEqual(equivalentsRequestLines(null), []);
});

test('attachEquivalents returns new rows without mutating the input', () => {
  const original = [row(), row({ code: 'C9', itemKey: 'lcsc:C9', status: BOM_STATUS.OK, gap: 0 })];
  const snapshot = JSON.parse(JSON.stringify(original));
  const response = {
    lines: [{ item_key: 'lcsc:C14663', basis: 'params', source: { package: '0402' }, candidates: [C1525] }],
  };
  const next = attachEquivalents(original, response);
  assert.notEqual(next, original);
  assert.notEqual(next[0], original[0]);
  assert.deepEqual(original, snapshot);
  assert.equal(original[0].equivalents, undefined);
  assert.equal(next[0].equivalents.basis, 'params');
  assert.equal(next[0].equivalents.candidates.length, 1);
  assert.equal(next[1].equivalents, null);
});

test('attachEquivalents drops a substitute the server no longer offers', () => {
  const chosen = { code: 'C14663', itemKey: 'lcsc:C14663', need: 4, gap: 4, status: BOM_STATUS.SHORT, substitute: C1525 };
  const kept = attachEquivalents([chosen], {
    lines: [{ item_key: 'lcsc:C14663', basis: 'params', candidates: [C1525] }],
  });
  assert.equal(kept[0].substitute.item_key, 'lcsc:C1525');
  const gone = attachEquivalents([chosen], {
    lines: [{ item_key: 'lcsc:C14663', basis: 'params', candidates: [] }],
  });
  assert.equal(gone[0].substitute, undefined);
});

test('substituteLines issues the candidate instead of the original code, never both', () => {
  const rows = [
    row({ code: 'C14663', itemKey: 'lcsc:C14663', need: 4, gap: 2, substitute: C1525 }),
    row({ code: 'C25804', itemKey: 'lcsc:C25804', need: 1, gap: 0, status: BOM_STATUS.OK }),
  ];
  const lines = substituteLines(rows);
  assert.deepEqual(lines, [
    { item_key: 'lcsc:C1525', quantity: 2 },
    { item_key: 'lcsc:C25804', quantity: 1 },
  ]);
  assert.equal(lines.filter((line) => line.item_key === 'lcsc:C14663').length, 0);
  assert.equal(lines.length, 2);
});

test('substitutionNote keeps the plain prefix without substitutes and lists them otherwise', () => {
  assert.equal(substitutionNote([row(), row({ code: 'C1', itemKey: 'lcsc:C1' })]), 'BOM 一键出库');
  const rows = [
    row({ code: 'C14663', itemKey: 'lcsc:C14663', gap: 2, substitute: C1525 }),
    row({
      code: 'C25804',
      itemKey: 'lcsc:C25804',
      gap: 1,
      substitute: { item_key: 'lcsc:C7711', catalog_code: 'C7711' },
    }),
    row({ code: 'C1', itemKey: 'lcsc:C1', gap: 1 }),
  ];
  assert.equal(
    substitutionNote(rows),
    'BOM 一键出库；替代：C14663 → C1525 ×2, C25804 → C7711 ×1',
  );
});
