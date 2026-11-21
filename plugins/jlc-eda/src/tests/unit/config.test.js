import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_SERVER_URL,
  normalizeBaseUrl,
  normalizeToken,
} from '../../main/config.js';

test('default server is the production domain', () => {
  assert.equal(DEFAULT_SERVER_URL, 'https://team.l-creation.club');
  assert.equal(normalizeBaseUrl(DEFAULT_SERVER_URL), DEFAULT_SERVER_URL);
});

test('base URL accepts http and https, strips trailing slashes', () => {
  assert.equal(normalizeBaseUrl('http://192.168.31.105:8069'), 'http://192.168.31.105:8069');
  assert.equal(normalizeBaseUrl('https://team.l-creation.club/'), 'https://team.l-creation.club');
  assert.equal(normalizeBaseUrl('  https://lab.example.test  '), 'https://lab.example.test');
});

test('base URL rejects empty, non-http, credentials, query and fragment', () => {
  for (const bad of [
    '',
    'ftp://lab.example.test',
    'http://user:pass@lab.example.test',
    'https://lab.example.test/?x=1',
    'https://lab.example.test/#frag',
    'not a url',
  ]) {
    assert.throws(() => normalizeBaseUrl(bad), (error) => error.code === 'CONFIG', bad);
  }
});

test('token must look like an EDA key', () => {
  const good = 'eda_' + 'A'.repeat(43);
  assert.equal(normalizeToken(good), good);
  assert.equal(normalizeToken('  ' + good + '  '), good);
});

test('token rejects empty, wrong prefix and too-short values', () => {
  for (const bad of ['', '   ', 'abc', 'eda_short', 'bearer eda_xxxxxxxxxxxxxxxxxxxxxxxxx', null]) {
    assert.throws(() => normalizeToken(bad), (error) => error.code === 'CONFIG', String(bad));
  }
});

test('token rejects characters that would break a header', () => {
  const base = 'eda_' + 'A'.repeat(43);
  // 内部换行/空格不是合法 base64url，必须拒绝（尾部空白会被 trim，属正常）。
  assert.throws(() => normalizeToken(base.replace('A', '\n')), (e) => e.code === 'CONFIG');
  assert.throws(() => normalizeToken(base.slice(0, 10) + ' ' + base.slice(10)),
    (e) => e.code === 'CONFIG');
  assert.throws(() => normalizeToken(base + ' extra'), (e) => e.code === 'CONFIG');
});
