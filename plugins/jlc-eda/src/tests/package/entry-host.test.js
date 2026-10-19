/**
 * Regression: the extension entry must run inside the JLCEDA Pro host wrapper.
 *
 * The real host (pro-api) executes the entry bundle as
 *
 *   new Function('sandbox', 'with (sandbox) { <bundle> ... }')
 *
 * and injects the API object as the bare `eda` binding of that with-scope. It
 * shadows window/document/self to undefined inside the scope and does NOT set
 * window.eda / globalThis.eda for the entry script. Release 3.0.0 read
 * globalThis.eda, so every menu click failed with "未检测到 EDA 扩展 API" and the
 * panel never opened in a real EDA install.
 *
 * This test executes the built dist/index.js exactly like the host does and
 * asserts that the menu handler opens the panel and that the private
 * MessageBus bridge serves requests.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(fileURLToPath(new URL('../../..', import.meta.url)));
const BUNDLE = path.join(ROOT, 'dist', 'index.js');
const TOPIC = 'lab.odoo.v3.rpc';

function createFakeEda(events) {
  const storage = new Map();
  const services = new Map();
  const eda = {
    sys_Storage: {
      getExtensionUserConfig: (key) => storage.get(key),
      async setExtensionUserConfig(key, value) {
        storage.set(key, value);
        return true;
      },
    },
    sys_IFrame: {
      async openIFrame(htmlFileName, width, height, id, props) {
        events.opened.push({ htmlFileName, width, height, id, title: props && props.title });
        return true;
      },
      async closeIFrame(id) {
        events.closed.push(id);
        return true;
      },
    },
    sys_MessageBus: {
      rpcService(topic, callback) {
        services.set(topic, callback);
        events.topics.push(topic);
      },
      async rpcCall(topic, message) {
        const callback = services.get(topic);
        if (!callback) throw new Error('no rpc service for ' + topic);
        return callback(message);
      },
      removePrivateMessageBus() {
        services.clear();
        events.removedBuses += 1;
      },
    },
    sys_Message: {
      showToastMessage(message, type, seconds) {
        events.toasts.push({ message, type, seconds });
      },
    },
    sys_ClientUrl: {
      async request() {
        throw new Error('network is not available in this test');
      },
    },
    sch_PrimitiveComponent: { getAll: async () => [] },
  };
  return { eda, storage, services };
}

async function runHost(options = {}) {
  const code = await fs.readFile(BUNDLE, 'utf8');
  const events = { opened: [], closed: [], toasts: [], topics: [], removedBuses: 0 };
  const { eda, storage, services } = createFakeEda(events);

  // Sandbox base exactly like pro-api's `og()`: web globals shadowed to
  // undefined, `eda` injected, enum placeholders present.
  const sandbox = {
    document: undefined,
    getDirectory: undefined,
    indexedDB: undefined,
    localStorage: undefined,
    location: undefined,
    navigator: undefined,
    postMessage: undefined,
    self: undefined,
    sessionStorage: undefined,
    window: undefined,
    $: undefined,
    fetch: () => Promise.reject(new Error('fetch() is disabled by the EDA host')),
    alert: () => {},
    console,
    eda,
    ESYS_ToastMessageType: { info: 'info', error: 'error', warn: 'warn', success: 'success' },
  };

  const menu = options.menu || 'showInventoryPanel';
  const invocation =
    '\n/**/\nif (typeof ' +
    menu +
    " === 'function') { " +
    menu +
    '(); } else if (edaEsbuildExportName && typeof edaEsbuildExportName.' +
    menu +
    " === 'function') { edaEsbuildExportName." +
    menu +
    '(); }';

  delete globalThis.eda;
  const wrapper = new Function('sandbox', 'with (sandbox) { ' + code + invocation + ' }');
  wrapper(sandbox);
  await new Promise((resolve) => setTimeout(resolve, 50));
  return { events, storage, services, sandbox };
}

test('menu handlers open the panel through the injected bare `eda` binding', async () => {
  const extension = JSON.parse(await fs.readFile(path.join(ROOT, 'extension.json'), 'utf8'));
  for (const menu of ['showInventoryPanel', 'openReceipt', 'openIssue', 'openReturn', 'openTrace', 'openSettings']) {
    const { events } = await runHost({ menu });
    assert.equal(events.opened.length, 1, menu + ' must open exactly one iframe window');
    assert.equal(events.opened[0].htmlFileName, '/iframe/app.html');
    assert.equal(events.opened[0].id, 'labOdooV3Panel');
    assert.ok(events.opened[0].width > 0 && events.opened[0].height > 0);
    assert.ok(events.opened[0].title && events.opened[0].title.length > 0);
    assert.deepEqual(events.toasts, [], menu + ' must not report an error toast in the real host sandbox');
    assert.ok(events.topics.includes(TOPIC), 'private MessageBus service must be registered');
  }
  assert.equal(extension.version, JSON.parse(await fs.readFile(path.join(ROOT, 'package.json'), 'utf8')).version);
});

test('the private bridge answers app.init without window.eda/globalThis.eda', async () => {
  const extension = JSON.parse(await fs.readFile(path.join(ROOT, 'extension.json'), 'utf8'));
  const { events, storage, services } = await runHost();
  assert.equal(events.opened.length, 1);

  const panelKey = [...storage.keys()].find((key) => key.includes('panel_payload'));
  assert.ok(panelKey, 'panel payload must be written to sys_Storage');
  const payload = JSON.parse(storage.get(panelKey));
  assert.equal(payload.protocol, 'lab-odoo-v3');
  assert.equal(payload.tab, 'inventory');
  assert.ok(payload.nonce && payload.nonce.length >= 8);

  const callback = services.get(TOPIC);
  assert.equal(typeof callback, 'function');

  const reply = await callback({ nonce: payload.nonce, method: 'app.init', params: {} });
  assert.equal(reply.ok, true);
  assert.equal(reply.data.version, extension.version);
  assert.equal(reply.data.sdk.available, true);
  assert.equal(reply.data.sdk.iframe, true);
  assert.equal(reply.data.sdk.messageBus, true);
  assert.equal(reply.data.session.active, false);

  const rejected = await callback({ nonce: 'wrong-nonce', method: 'app.init', params: {} });
  assert.equal(rejected.ok, false);
  assert.equal(rejected.error.code, 'BRIDGE');
});

test('the bundle never assumes globalThis.eda exists', async () => {
  const code = await fs.readFile(BUNDLE, 'utf8');
  assert.ok(code.includes('typeof eda !== "undefined"') || code.includes("typeof eda !== 'undefined'"));
  // Only the documented fallback may read globalThis.eda; the primary lookup
  // must be the host-injected binding.
  const primary = code.indexOf('typeof eda');
  const fallback = code.indexOf('globalThis.eda');
  assert.ok(primary >= 0 && (fallback === -1 || primary < fallback));
});
