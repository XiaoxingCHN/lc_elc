import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildValueQuery,
  groupUnmappedByValue,
  attachValueMatches,
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
