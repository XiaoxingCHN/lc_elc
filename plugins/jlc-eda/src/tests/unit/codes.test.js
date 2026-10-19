import test from 'node:test';
import assert from 'node:assert/strict';
import {
  normalizeCatalogCode,
  isCatalogCode,
  catalogItemKey,
  localItemKey,
  parseItemKey,
  firstCatalogCode,
} from '../../shared/codes.js';

test('normalizes C codes: case, NFKC, whitespace, zero-width', () => {
  assert.equal(normalizeCatalogCode(' c123 '), 'C123');
  assert.equal(normalizeCatalogCode('Ｃ１２３'), 'C123');
  assert.equal(normalizeCatalogCode('C\u200b123'), 'C123');
  assert.equal(normalizeCatalogCode('C 1 2 3'), 'C123');
});

test('accepts short codes but rejects zero and malformed values', () => {
  assert.equal(normalizeCatalogCode('C1'), 'C1');
  assert.equal(normalizeCatalogCode('C001'), 'C001');
  assert.equal(normalizeCatalogCode('C0'), null);
  assert.equal(normalizeCatalogCode('C000'), null);
  assert.equal(normalizeCatalogCode('C-1'), null);
  assert.equal(normalizeCatalogCode('C'), null);
  assert.equal(normalizeCatalogCode('ABC123'), null);
  assert.equal(normalizeCatalogCode(''), null);
  assert.equal(normalizeCatalogCode(null), null);
  assert.equal(normalizeCatalogCode(123), null);
});

test('isCatalogCode and catalogItemKey agree', () => {
  assert.equal(isCatalogCode('c7'), true);
  assert.equal(isCatalogCode('7'), false);
  assert.equal(catalogItemKey('c7'), 'lcsc:C7');
  assert.equal(catalogItemKey('bad'), null);
});

test('local item keys require positive integer ids', () => {
  assert.equal(localItemKey(42), 'lab:42');
  assert.equal(localItemKey('42'), 'lab:42');
  assert.equal(localItemKey(0), null);
  assert.equal(localItemKey(-1), null);
  assert.equal(localItemKey('4.2'), null);
});

test('parseItemKey handles lcsc, lab, bare code and invalid input', () => {
  assert.deepEqual(parseItemKey('lcsc:C123'), { kind: 'lcsc', value: 'C123', key: 'lcsc:C123' });
  assert.deepEqual(parseItemKey('C123'), { kind: 'lcsc', value: 'C123', key: 'lcsc:C123' });
  assert.deepEqual(parseItemKey('lab:42'), { kind: 'lab', value: 42, key: 'lab:42' });
  assert.deepEqual(parseItemKey('LAB:42'), { kind: 'lab', value: 42, key: 'lab:42' });
  assert.equal(parseItemKey('lab:0').key, null);
  assert.equal(parseItemKey('lab:abc').key, null);
  assert.equal(parseItemKey('lcsc:C0').key, null);
  assert.equal(parseItemKey('').key, null);
});

test('firstCatalogCode picks the first valid candidate only', () => {
  assert.equal(firstCatalogCode(['MPN-1', 'c9', 'C10']), 'C9');
  assert.equal(firstCatalogCode(['', null, 'C0', 'C5']), 'C5');
  assert.equal(firstCatalogCode(['', null]), null);
});
