import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildValueQuery,
  normalizePackage,
  groupUnmappedByValue,
  attachValueMatches,
  pickValueCandidate,
  valueSubstituteLines,
  valueSubstitutionNote,
} from '../../shared/bom.js';

/**
 * 没有立创 C 编号的器件（原理图里只填了值 100nF 和封装 0402）以前直接被
 * 丢进「未并入库存」表，用户看到一屏「禁止猜测或合并」却毫无帮助。
 *
 * 现在按「值 + 封装」去器件库搜候选，让用户自己判断。
 */

function comp(overrides = {}) {
  return Object.assign(
    { designator: 'C12', name: '100nF', footprint: '0402', code: '' },
    overrides,
  );
}

test('buildValueQuery combines value and footprint', () => {
  assert.equal(buildValueQuery(comp()), '100nF 0402');
});

test('buildValueQuery drops an empty footprint', () => {
  assert.equal(buildValueQuery(comp({ footprint: '' })), '100nF');
});

test('buildValueQuery returns empty when there is no value', () => {
  assert.equal(buildValueQuery(comp({ name: '' })), '');
  assert.equal(buildValueQuery(null), '');
});

test('groupUnmappedByValue merges same value+footprint and counts designators', () => {
  const groups = groupUnmappedByValue([
    comp({ designator: 'C12' }),
    comp({ designator: 'C4' }),
    comp({ designator: 'C5', name: '2.2uF' }),
    comp({ designator: 'R9', name: '10K', footprint: '0603' }),
  ]);
  assert.equal(groups.length, 3);
  const cap = groups.find((g) => g.value === '100nF' && g.footprint === '0402');
  assert.deepEqual(cap.designators, ['C12', 'C4']);
  assert.equal(cap.quantity, 2);
});

test('groupUnmappedByValue keeps components without a value in their own group', () => {
  const groups = groupUnmappedByValue([comp({ name: '', designator: 'P3' })]);
  assert.equal(groups.length, 1);
  assert.equal(groups[0].query, '');
  assert.deepEqual(groups[0].designators, ['P3']);
});

test('attachValueMatches puts candidates on the matching group', () => {
  const groups = groupUnmappedByValue([comp(), comp({ name: '10K', footprint: '0603' })]);
  const response = {
    results: [
      { query: '100nF 0402', items: [{ item_key: 'lcsc:C1525', catalog_code: 'C1525' }] },
      { query: '10K 0603', items: [] },
    ],
  };
  const out = attachValueMatches(groups, response);
  const cap = out.find((g) => g.value === '100nF');
  assert.equal(cap.candidates.length, 1);
  assert.equal(cap.candidates[0].catalog_code, 'C1525');
  const res = out.find((g) => g.value === '10K');
  assert.deepEqual(res.candidates, []);
});

test('attachValueMatches leaves groups untouched when the response is missing', () => {
  const groups = groupUnmappedByValue([comp()]);
  const out = attachValueMatches(groups, null);
  assert.deepEqual(out[0].candidates, []);
});

/* ------------------------------------------------------------------ */
/* 勾选候选 → 进出库                                                    */
/* ------------------------------------------------------------------ */

test('pickValueCandidate records the choice on the group', () => {
  const groups = groupUnmappedByValue([comp()]);
  const withCandidates = attachValueMatches(groups, {
    results: [{ query: '100nF 0402', items: [{ item_key: 'lcsc:C1525', catalog_code: 'C1525' }] }],
  });
  const picked = pickValueCandidate(withCandidates, '100nF\u00000402', 'lcsc:C1525');
  assert.equal(picked[0].substitute.item_key, 'lcsc:C1525');
});

test('pickValueCandidate with null clears the choice', () => {
  const groups = attachValueMatches(groupUnmappedByValue([comp()]), {
    results: [{ query: '100nF 0402', items: [{ item_key: 'lcsc:C1525', catalog_code: 'C1525' }] }],
  });
  const picked = pickValueCandidate(groups, groups[0].key, 'lcsc:C1525');
  const cleared = pickValueCandidate(picked, groups[0].key, null);
  assert.equal(cleared[0].substitute, undefined);
});

test('valueSubstituteLines issues picked groups only', () => {
  const groups = attachValueMatches(groupUnmappedByValue([
    comp({ designator: 'C12' }),
    comp({ designator: 'R9', name: '10K', footprint: '0603' }),
  ]), {
    results: [
      { query: '100nF 0402', items: [{ item_key: 'lcsc:C1525', catalog_code: 'C1525' }] },
      { query: '10K 0603', items: [{ item_key: 'lcsc:C101254', catalog_code: 'C101254' }] },
    ],
  });
  const picked = pickValueCandidate(groups, groups[0].key, 'lcsc:C1525');
  const lines = valueSubstituteLines(picked);
  assert.equal(lines.length, 1);
  assert.equal(lines[0].item_key, 'lcsc:C1525');
  assert.equal(lines[0].quantity, 1);
});

test('valueSubstituteLines returns nothing when no group is picked', () => {
  const groups = attachValueMatches(groupUnmappedByValue([comp()]), {
    results: [{ query: '100nF 0402', items: [{ item_key: 'lcsc:C1525' }] }],
  });
  assert.deepEqual(valueSubstituteLines(groups), []);
});

test('valueSubstitutionNote lists the replacements', () => {
  const groups = attachValueMatches(groupUnmappedByValue([comp({ designator: 'C12,C4' })]), {
    results: [{ query: '100nF 0402', items: [{ item_key: 'lcsc:C1525', catalog_code: 'C1525' }] }],
  });
  const picked = pickValueCandidate(groups, groups[0].key, 'lcsc:C1525');
  const note = valueSubstitutionNote(picked);
  assert.ok(note.includes('100nF 0402'), note);
  assert.ok(note.includes('C1525'), note);
});

/* ------------------------------------------------------------------ */
/* 封装归一化                                                           */
/* ------------------------------------------------------------------ */

test('normalizePackage strips the EDA C/R prefix', () => {
  // EDA 原理图里电容写 C0603、电阻写 R0603，实验室库里统一是 0603。
  assert.equal(normalizePackage('C0603'), '0603');
  assert.equal(normalizePackage('R0603'), '0603');
  assert.equal(normalizePackage('L0805'), '0805');
});

test('normalizePackage keeps footprints that are not chip sizes', () => {
  assert.equal(normalizePackage('SOT-23'), 'SOT-23');
  assert.equal(normalizePackage('SOD-323'), 'SOD-323');
  assert.equal(normalizePackage('TO-252-2(DPAK)'), 'TO-252-2(DPAK)');
  assert.equal(normalizePackage('RES-ARRAY-SMD_0603-8P-L3.2-W1.6-BL'),
    'RES-ARRAY-SMD_0603-8P-L3.2-W1.6-BL');
});

test('normalizePackage handles empty and whitespace', () => {
  assert.equal(normalizePackage(''), '');
  assert.equal(normalizePackage('  C0402  '), '0402');
  assert.equal(normalizePackage(null), '');
});

test('buildValueQuery uses the normalized footprint', () => {
  assert.equal(buildValueQuery({ name: '100nF', footprint: 'C0603' }), '100nF 0603');
});
