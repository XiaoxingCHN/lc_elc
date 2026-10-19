import test from 'node:test';
import assert from 'node:assert/strict';
import {
  positiveQuantity,
  positiveId,
  optionalPositiveId,
  requiredText,
  optionalText,
  requireItemKey,
  validateIssueLines,
} from '../../shared/validate.js';

test('positiveQuantity accepts decimal strings and rejects zero/NaN', () => {
  assert.equal(positiveQuantity('2.5'), 2.5);
  assert.equal(positiveQuantity(1), 1);
  assert.throws(() => positiveQuantity(0), (error) => error.code === 'VALIDATION_ERROR');
  assert.throws(() => positiveQuantity(-1), (error) => error.code === 'VALIDATION_ERROR');
  assert.throws(() => positiveQuantity('abc'), (error) => error.code === 'VALIDATION_ERROR');
  assert.throws(() => positiveQuantity(''), (error) => error.code === 'VALIDATION_ERROR');
});

test('positiveId and optionalPositiveId enforce integer ids', () => {
  assert.equal(positiveId('42', 'id'), 42);
  assert.throws(() => positiveId('4.2', 'id'), (error) => error.code === 'VALIDATION_ERROR');
  assert.throws(() => positiveId(0, 'id'), (error) => error.code === 'VALIDATION_ERROR');
  assert.equal(optionalPositiveId(null, 'id'), null);
  assert.equal(optionalPositiveId('', 'id'), null);
  assert.equal(optionalPositiveId(false, 'id'), null);
  assert.equal(optionalPositiveId(7, 'id'), 7);
});

test('requiredText trims and enforces max length', () => {
  assert.equal(requiredText('  Project A  ', 'project'), 'Project A');
  assert.throws(() => requiredText('   ', 'project'), (error) => error.code === 'VALIDATION_ERROR');
  assert.throws(() => requiredText('x'.repeat(6), 'project', 5), (error) => error.code === 'VALIDATION_ERROR');
  assert.equal(optionalText('  note  ', 'note'), 'note');
});

test('requireItemKey canonicalizes and rejects invalid keys', () => {
  assert.equal(requireItemKey('c123'), 'lcsc:C123');
  assert.equal(requireItemKey('lab:42'), 'lab:42');
  assert.throws(() => requireItemKey('C0'), (error) => error.code === 'VALIDATION_ERROR');
  assert.throws(() => requireItemKey('garbage'), (error) => error.code === 'VALIDATION_ERROR');
});

test('validateIssueLines rejects empty, duplicate and over-100 lists', () => {
  assert.deepEqual(validateIssueLines([{ bag_id: '1', quantity: '2' }]), [{ bag_id: 1, quantity: 2 }]);
  assert.throws(() => validateIssueLines([]), (error) => error.code === 'VALIDATION_ERROR');
  assert.throws(
    () => validateIssueLines([{ bag_id: 1, quantity: 1 }, { bag_id: 1, quantity: 2 }]),
    (error) => error.code === 'VALIDATION_ERROR' && error.fields.lines === 'duplicate_bag',
  );
  const tooMany = Array.from({ length: 101 }, (_, index) => ({ bag_id: index + 1, quantity: 1 }));
  assert.throws(() => validateIssueLines(tooMany), (error) => error.code === 'VALIDATION_ERROR');
});
