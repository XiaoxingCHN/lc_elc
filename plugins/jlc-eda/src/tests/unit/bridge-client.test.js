import test from 'node:test';
import assert from 'node:assert/strict';
import { createBridge, MESSAGE_TOPIC, BRIDGE_KEY } from '../../iframe/bridge-client.js';

function installFakeWindow(options = {}) {
  const calls = [];
  const storage = new Map();
  const eda = options.eda
    ? {
        sys_Storage: {
          getExtensionUserConfig: (key) => storage.get(key) || '',
          setExtensionUserConfig: async (key, value) => {
            storage.set(key, value);
          },
        },
        sys_MessageBus: options.eda.sys_MessageBus,
      }
    : null;
  globalThis.window = {
    eda,
    parent: options.parent || {},
  };
  return { calls, storage };
}

test('iframe uses private MessageBus and never writes RPC/password to storage', async () => {
  const calls = [];
  const { storage } = installFakeWindow({
    eda: {
      sys_MessageBus: {
        async rpcCall(topic, message, timeout) {
          calls.push({ topic, message, timeout });
          return { ok: true, data: { uid: 7 }, error: null };
        },
      },
    },
  });
  try {
    const bridge = createBridge({ nonce: 'nonce-1' });
    assert.equal(bridge.mode, 'messagebus');
    const data = await bridge.call('session.login', { password: 'secret', pairingToken: 'token-123456' }, 1234);
    assert.deepEqual(data, { uid: 7 });
    assert.equal(calls[0].topic, MESSAGE_TOPIC);
    assert.equal(calls[0].message.nonce, 'nonce-1');
    assert.equal(calls[0].timeout, 1234);
    assert.equal(storage.size, 0);
  } finally {
    delete globalThis.window;
  }
});

test('same-origin parent bridge fallback keeps nonce and does not use storage', async () => {
  const calls = [];
  const parent = {
    [BRIDGE_KEY]: {
      nonce: 'nonce-2',
      async call(payload) {
        calls.push(payload);
        return { ok: true, data: { mode: 'direct' }, error: null };
      },
    },
  };
  installFakeWindow({ parent });
  try {
    const bridge = createBridge({ nonce: 'nonce-2' });
    assert.equal(bridge.mode, 'direct');
    const data = await bridge.call('app.init', {});
    assert.deepEqual(data, { mode: 'direct' });
    assert.equal(calls[0].nonce, 'nonce-2');
  } finally {
    delete globalThis.window;
  }
});

test('bridge unwraps explicit errors and rejects wrong nonce direct bridge', async () => {
  const parent = {
    [BRIDGE_KEY]: {
      nonce: 'nonce-3',
      async call() {
        return { ok: false, data: null, error: { code: 'FORBIDDEN', message: 'no' } };
      },
    },
  };
  installFakeWindow({ parent });
  try {
    const bridge = createBridge({ nonce: 'nonce-3' });
    await assert.rejects(() => bridge.call('inventory.issue', {}), (error) => error.code === 'FORBIDDEN');
    assert.throws(() => createBridge({ nonce: 'other' }), (error) => error.code === 'BRIDGE');
  } finally {
    delete globalThis.window;
  }
});
