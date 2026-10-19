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
