import test from 'node:test';
import assert from 'node:assert/strict';
import { installBridge, odooActionUrl, MESSAGE_TOPIC } from '../../main/panel.js';

function fakeBus() {
  const services = new Map();
  let removed = 0;
  return {
    services,
    get removed() {
      return removed;
    },
    rpcService(topic, callback) {
      services.set(topic, callback);
    },
    removePrivateMessageBus() {
      removed += 1;
      services.clear();
    },
  };
}

function fakeWindow() {
  return {};
}

test('official private MessageBus registers a nonce-checked RPC service', async () => {
  const bus = fakeBus();
  const win = fakeWindow();
  const bridge = installBridge({
    nonce: 'nonce-1',
    window: win,
    eda: { sys_MessageBus: bus },
    dispatch: async (method, params) => ({ method, params }),
  });
  assert.equal(bridge.mode, 'messagebus');
  assert.equal(bus.services.size, 1);
  const service = bus.services.get(MESSAGE_TOPIC);
  const rejected = await service({ nonce: 'bad', method: 'x', params: {} });
  assert.equal(rejected.ok, false);
  assert.equal(rejected.error.code, 'BRIDGE');
  const good = await service({ nonce: 'nonce-1', method: 'catalog.search', params: { query: 'C1' } });
  assert.equal(good.ok, true);
  assert.deepEqual(good.data, { method: 'catalog.search', params: { query: 'C1' } });
  bridge.uninstall();
  assert.equal(bus.removed, 1);
  assert.equal(win.__LAB_ODOO_V3_BRIDGE__, undefined);
});

test('same-origin direct bridge remains available with nonce check', async () => {
  const win = fakeWindow();
  const bridge = installBridge({
    nonce: 'nonce-2',
    window: win,
    eda: null,
    dispatch: async (method) => ({ ok: method }),
  });
  assert.equal(bridge.mode, 'direct');
  const rejected = await win.__LAB_ODOO_V3_BRIDGE__.call({ nonce: 'bad', method: 'x' });
  assert.equal(rejected.ok, false);
  const good = await win.__LAB_ODOO_V3_BRIDGE__.call({ nonce: 'nonce-2', method: 'app.init' });
  assert.equal(good.ok, true);
  assert.deepEqual(good.data, { ok: 'app.init' });
  bridge.uninstall();
  assert.equal(win.__LAB_ODOO_V3_BRIDGE__, undefined);
});

test('dispatch errors are serialized without stacks or secrets', async () => {
  const bus = fakeBus();
  installBridge({
    nonce: 'nonce-3',
    window: null,
    eda: { sys_MessageBus: bus },
    dispatch: async () => {
      throw Object.assign(new Error('nope'), { code: 'FORBIDDEN', fields: { group: 'lab' } });
    },
  });
  const reply = await bus.services.get(MESSAGE_TOPIC)({ nonce: 'nonce-3', method: 'x' });
  assert.equal(reply.ok, false);
  assert.equal(reply.error.code, 'FORBIDDEN');
  assert.deepEqual(reply.error.fields, { group: 'lab' });
  assert.equal(reply.error.stack, undefined);
});

test('Odoo action URLs are built only from the allow-list', () => {
  assert.equal(
    odooActionUrl('http://lc.rm.com', 'bag_list'),
    'http://lc.rm.com/odoo/action-lab_workflow.action_lab_bag',
  );
  assert.equal(
    odooActionUrl('http://lc.rm.com/', 'label_open'),
    'http://lc.rm.com/odoo/action-lab_workflow.action_lab_label_open',
  );
  assert.throws(() => odooActionUrl('http://lc.rm.com', '<script>'), (error) => error.code === 'VALIDATION_ERROR');
});
