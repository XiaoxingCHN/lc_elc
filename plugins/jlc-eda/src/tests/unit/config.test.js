import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_DB,
  DEFAULT_RELAY_URL,
  normalizeBaseUrl,
  normalizeDbName,
  normalizeRelayUrl,
  normalizePairingToken,
} from '../../main/config.js';

test('relay URL only accepts loopback http with no path or query', () => {
  assert.equal(normalizeRelayUrl(DEFAULT_RELAY_URL), DEFAULT_RELAY_URL);
  assert.equal(normalizeRelayUrl('http://127.0.0.1:50000'), 'http://127.0.0.1:50000');
  assert.throws(() => normalizeRelayUrl('http://192.168.1.2:49621'), (error) => error.code === 'CONFIG');
  assert.throws(() => normalizeRelayUrl('https://127.0.0.1:49621'), (error) => error.code === 'CONFIG');
  assert.throws(() => normalizeRelayUrl('http://127.0.0.1:49621/path'), (error) => error.code === 'CONFIG');
});

test('pairing token is non-empty, bounded and URL-safe', () => {
  assert.equal(normalizePairingToken('abcdefghijklmnop'), 'abcdefghijklmnop');
  assert.throws(() => normalizePairingToken(''), (error) => error.fields.pairingToken === 'required');
  assert.throws(() => normalizePairingToken('short'), (error) => error.fields.pairingToken === 'invalid');
  assert.throws(() => normalizePairingToken('has space 1234567890'), (error) => error.code === 'CONFIG');
});

test('server and database normalization keeps defaults clear', () => {
  assert.equal(normalizeBaseUrl('http://lc.rm.com/'), 'http://lc.rm.com');
  assert.equal(normalizeDbName('LcHardwareHouse'), 'LcHardwareHouse');
  assert.equal(DEFAULT_DB, 'LcHardwareHouse');
  assert.throws(() => normalizeBaseUrl('http://user:pass@lc.rm.com'), (error) => error.code === 'CONFIG');
});
