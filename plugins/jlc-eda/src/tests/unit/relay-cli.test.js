import test from 'node:test';
import assert from 'node:assert/strict';
import { parseRelayArgs } from '../../../bridge/server.mjs';
test('CLI selects fixed upstream/database only at startup',()=>{
 assert.deepEqual(parseRelayArgs([]),{port:49621,upstream:'http://lc.rm.com',db:'LcHardwareHouse'});
 assert.deepEqual(parseRelayArgs(['--upstream','http://192.168.31.105:8069','--db','LcHardwareHouse','--port','49622']),{port:49622,upstream:'http://192.168.31.105:8069',db:'LcHardwareHouse'});
});
test('CLI refuses malformed startup arguments',()=>{
 for(const args of [['--port'],['--port','0'],['--port','65536'],['--port','12x'],['--port','1','--port','2'],['--host','0.0.0.0'],['--db','a/b'],['--upstream','file:///tmp'],['--upstream','http://user:pw@example.com'],['--upstream','http://example.com/proxy'],['--upstream','http://example.com/?x=1']]) assert.throws(()=>parseRelayArgs(args));
});

test('a FIXED pairing token survives a restart', () => {
  // Without --token the relay mints a new random token on every start, so a
  // bridge restart invalidated the token the EDA plugin had saved and every
  // request answered 401 ("未登录"). A fixed token must be accepted and echoed.
  const token = 'lab-relay-fixed-token-0123456789';
  const parsed = parseRelayArgs(['--token', token]);
  assert.equal(parsed.token, token);

  // And it must not weaken the other arguments.
  const both = parseRelayArgs(['--token', token, '--port', '49622']);
  assert.deepEqual(both, { port: 49622, upstream: 'http://lc.rm.com', db: 'LcHardwareHouse', token });
});

test('a malformed fixed token is refused, not silently ignored', () => {
  for (const bad of [
    ['--token'],
    ['--token', ''],
    ['--token', 'short'],            // < 16 chars
    ['--token', 'has spaces in it 123456'],
    ['--token', 'x'.repeat(129)],    // > 128 chars
    ['--token', 'a'.repeat(20), '--token', 'b'.repeat(20)],
  ]) {
    assert.throws(() => parseRelayArgs(bad), /token|未知或重复/);
  }
});
