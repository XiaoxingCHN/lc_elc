import test from 'node:test';
import assert from 'node:assert/strict';
import { createLogger, redact } from '../../main/logger.js';

test('redact masks credential keys at any depth', () => {
  const output = redact({
    password: 'p',
    nested: { token: 't', session_id: 's', cookie: 'c', authorization: 'a' },
    safe: 'ok',
  });
  assert.equal(output.password, '[redacted]');
  assert.equal(output.nested.token, '[redacted]');
  assert.equal(output.nested.session_id, '[redacted]');
  assert.equal(output.nested.cookie, '[redacted]');
  assert.equal(output.nested.authorization, '[redacted]');
  assert.equal(output.safe, 'ok');
});

test('redact scrubs credential-looking strings', () => {
  assert.equal(redact('session_id=abc; Path=/'), 'session_id=[redacted]; Path=/');
  assert.equal(redact('password=hunter2'), 'password=[redacted]');
  assert.equal(redact('Authorization: Bearer xyz'), 'Authorization: Bearer [redacted]');
});

test('logger keeps a bounded ring buffer and never stores the password', () => {
  const logger = createLogger({ consoleObj: null, maxEntries: 2 });
  logger.info('login', { password: 'secret', session_id: 'sid', note: 'session_id=sid' });
  logger.info('second', { ok: true });
  logger.info('third', { ok: true });
  const entries = logger.snapshot();
  assert.equal(entries.length, 2);
  assert.equal(entries[0].event, 'second');
  const text = logger.toText();
  assert.equal(text.includes('secret'), false);
  assert.equal(text.includes('sid'), false);
});

test('logger clear empties the buffer', () => {
  const logger = createLogger({ consoleObj: null });
  logger.info('x');
  logger.clear();
  assert.equal(logger.snapshot().length, 0);
});
