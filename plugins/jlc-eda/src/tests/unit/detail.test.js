import test from 'node:test';
import assert from 'node:assert/strict';
import {
  many2oneName,
  bagLocationName,
  bagAvailableQuantity,
  bagLotName,
  issueBagName,
  issueBorrowerName,
  locationSummary,
} from '../../shared/detail.js';

test('many2oneName handles [id, name], scalar and empty values', () => {
  assert.equal(many2oneName([3, 'R01']), 'R01');
  assert.equal(many2oneName('R01'), 'R01');
  assert.equal(many2oneName(null), '');
  assert.equal(many2oneName([]), '');
});

test('catalog-detail bag shape uses many2one names and does not fake available', () => {
  const bag = { location_id: [1, 'R01'], lot_id: [2, 'LOT-A'], quantity: 5, available_quantity: undefined };
  assert.equal(bagLocationName(bag), 'R01');
  assert.equal(bagAvailableQuantity(bag), null);
  assert.equal(bagLotName(bag), 'LOT-A');
});

test('workflow flat bag shape keeps available_quantity separate from on-hand', () => {
  const bag = { location_id: 1, location_path: 'Lab/R01', quantity: 5, available_quantity: 3, lot_name: 'LOT-B' };
  assert.equal(bagLocationName(bag), 'Lab/R01');
  assert.equal(bagAvailableQuantity(bag), 3);
  assert.equal(bagLotName(bag), 'LOT-B');
});

test('issue shapes work for catalog search_read and workflow flat rows', () => {
  assert.equal(issueBagName({ bag_id: [9, 'LABB:1'] }), 'LABB:1');
  assert.equal(issueBorrowerName({ borrower_id: [4, 'Alice'] }), 'Alice');
  assert.equal(issueBagName({ bag_id: 9, trace_code: 'LABB:2' }), 'LABB:2');
  assert.equal(issueBorrowerName({ borrower_id: 4, borrower_name: 'Bob' }), 'Bob');
});

test('locationSummary labels on-hand versus available explicitly', () => {
  assert.equal(locationSummary({ location: 'R01', quantity: 5 }), 'R01(在库 5)');
  assert.equal(locationSummary({ location: 'R01', quantity: 5, available_quantity: 3 }), 'R01(可用 3)');
});
