// Ad-hoc faithful E2E: project BOM compare + one-click outbound through the real host wrapper.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
// Optional browser check (needs Playwright + Edge). Skip when unavailable:
//   $env:PLAYWRIGHT_IMPORT = 'file:///.../node_modules/playwright/index.mjs'
let chromium = null;
try {
  ({ chromium } = await import(process.env.PLAYWRIGHT_IMPORT || 'playwright'));
} catch (error) {
  console.log(JSON.stringify({ skipped: true, reason: 'playwright 不可用: ' + error.message }));
  process.exit(0);
}

const STAGE = process.argv[2];
const OUT = process.argv[3];
const PORT = 24882;
const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8', '.png': 'image/png', '.md': 'text/markdown; charset=utf-8' };

const BOM_CSV = [
  'No.,Quantity,Comment,Designator,Footprint,Supplier Part,Manufacturer Part',
  '1,2,10k,R1 R2,0402,C25804,RC0402FR-0710KL',
  '2,1,100nF,C1,0402,C1525,CL05B104KO5NNNC',
  '3,1,STM32,U1,LQFP48,C8734,STM32F103C8T6',
  '4,1,NoCode,R9,0603,,UNKNOWN-PART',
].join('\r\n');

const HOST_PAGE = `<!doctype html><html><head><meta charset="utf-8"><title>host</title>
<style>body{margin:0;font:13px sans-serif;background:#0b0d12;color:#eee}#host{padding:10px}</style></head>
<body><div id="host"></div><script>
const HOST = { storage: new Map(), topics: new Map(), opened: [], toasts: [], calls: [] };
const ENUMS = { ESYS_ToastMessageType: { info: 'info', error: 'error', warn: 'warn', success: 'success' } };
const DETAILS = {
  'lcsc:C25804': { item: { name: '10k 1%', mpn: 'RC0402FR-0710KL', lab_available_quantity: 8, lab_quantity: 9 }, bags: [{ id: 11, available_quantity: 3, trace_code: 'LABB:11' }, { id: 12, available_quantity: 5 }], locations: [{ location: 'A-01', available_quantity: 8 }], lab_templates: [{}] },
  'lcsc:C1525': { item: { name: '100nF 50V', mpn: 'CL05B104KO5NNNC', lab_available_quantity: 4, lab_quantity: 4 }, bags: [{ id: 21, available_quantity: 4 }], locations: [{ location: 'A-02', available_quantity: 4 }], lab_templates: [] },
  'lcsc:C8734': { item: { name: 'STM32F103C8T6', mpn: 'STM32F103C8T6', lab_available_quantity: 0, lab_quantity: 0 }, bags: [], locations: [], lab_templates: [] }
};
const eda = {
  sys_Storage: { getExtensionUserConfig: (k) => HOST.storage.get(k), setExtensionUserConfig: async (k, v) => { HOST.storage.set(k, v); return true; } },
  sys_IFrame: {
    async openIFrame(htmlFileName, width, height, id, props) {
      HOST.opened.push({ htmlFileName, id, title: props && props.title });
      const frame = document.createElement('iframe');
      frame.id = 'eda-window-frame';
      frame.style.cssText = 'width:' + width + 'px;height:' + height + 'px;border:0;background:#fff;border-radius:12px';
      frame.src = htmlFileName;
      document.getElementById('host').appendChild(frame);
      frame.contentWindow.eda = eda;
      for (const [k, v] of Object.entries(ENUMS)) frame.contentWindow[k] = v;
      return true;
    },
    async closeIFrame() { document.querySelectorAll('iframe').forEach((f) => f.remove()); return true; },
  },
  sys_MessageBus: {
    rpcService(topic, callback) { HOST.topics.set(topic, callback); },
    async rpcCall(topic, message) {
      HOST.calls.push(message && message.method);
      const method = message && message.method;
      if (method === 'app.init') {
        return { ok: true, data: { version: '3.0.2', config: { serverUrl: 'http://lc.rm.com', db: 'LcHardwareHouse', login: 'demo' }, connection: { mode: 'relay', relayUrl: 'http://127.0.0.1:49621', hasPairingToken: true }, session: { active: true, uid: 2, sessionMode: 'relay' }, sdk: { available: true, clientUrl: true, iframe: true, storage: true, messageBus: true } } };
      }
      if (method === 'session.status') {
        return { ok: true, data: { active: true, uid: 2, sessionMode: 'relay' } };
      }
      if (method === 'inventory.bootstrap') {
        return { ok: true, data: { borrowers: [{ id: 5, name: '张三', login: 'demo', is_self: true }], locations: [{ id: 3, path: 'A-01', name: 'A-01' }], permissions: { can_issue: true, can_receipt: true } } };
      }
      if (method === 'catalog.detail') {
        const data = DETAILS[message.params.item_key];
        if (!data) return { ok: false, error: { code: 'NOT_FOUND', message: '未找到' } };
        return { ok: true, data };
      }
      if (method === 'inventory.outbound') {
        HOST.outboundPayload = message.params;
        return { ok: true, data: { ok: true, plan: (message.params.lines || []).map((line) => ({ item_key: line.item_key, name: 'x', need: line.quantity, available: 9, bags: [{ bag_id: 11, quantity: line.quantity }], shortfall: 0 })) } };
      }
      const service = HOST.topics.get(topic);
      if (!service) throw new Error('no service ' + topic);
      return service(message);
    },
    removePrivateMessageBus() { HOST.topics.clear(); },
  },
  sys_Message: { showToastMessage: (m, t) => HOST.toasts.push({ m, t }) },
  sys_ClientUrl: { async request() { throw new Error('network disabled'); } },
  sch_PrimitiveComponent: { getAll: async () => [] },
  pcb_ManufactureData: { async getBomFile() { return { text: async () => BOM_CSV_TEXT }; } },
};
const sandbox = { document: undefined, window: undefined, self: undefined, location: undefined, navigator: undefined, localStorage: undefined, sessionStorage: undefined, indexedDB: undefined, postMessage: undefined, $: undefined, getDirectory: undefined, fetch: () => Promise.reject(new Error('disabled')), alert: () => {}, console, eda, ...ENUMS };
window.HOST = HOST;
window.runMenu = async (menu) => {
  const code = await (await fetch('/dist/index.js')).text();
  delete globalThis.eda;
  const call = '\\n/**/\\nif (typeof ' + menu + ' === "function") { ' + menu + '(); } else if (edaEsbuildExportName && typeof edaEsbuildExportName.' + menu + ' === "function") { edaEsbuildExportName.' + menu + '(); }';
  new Function('sandbox', 'with (sandbox) { ' + code + call + ' }')(sandbox);
  delete window.__LAB_ODOO_V3_BRIDGE__;
};
</script></body></html>`.replace('BOM_CSV_TEXT', JSON.stringify(BOM_CSV));

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, 'http://127.0.0.1');
    if (url.pathname === '/' || url.pathname === '/host.html') return res.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }).end(HOST_PAGE);
    const rel = decodeURIComponent(url.pathname.replace(/^\/+/, ''));
    const file = path.join(STAGE, rel);
    const data = await readFile(file);
    res.writeHead(200, { 'content-type': MIME[path.extname(file)] || 'application/octet-stream' }).end(data);
  } catch (error) {
    res.writeHead(404).end(String(error && error.message));
  }
});
await new Promise((resolve) => server.listen(PORT, '127.0.0.1', resolve));

const browser = await chromium.launch({ channel: 'msedge', headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, colorScheme: 'light' });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e && e.message ? e.message : e)));
await page.goto('http://127.0.0.1:' + PORT + '/', { waitUntil: 'load' });
await page.evaluate(() => window.runMenu('bomCompare'));
await page.waitForSelector('#eda-window-frame', { timeout: 8000 });
let frame = null;
for (let attempt = 0; attempt < 40 && !frame; attempt += 1) {
  const handle = await page.$('#eda-window-frame');
  if (handle) frame = await handle.contentFrame();
  if (!frame) await page.waitForTimeout(150);
}
if (!frame) throw new Error('panel frame missing');
await frame.waitForLoadState('load');
await frame.waitForTimeout(400);
await page.screenshot({ path: path.join(OUT, 'bom-1-empty.png') });

await frame.click('button:has-text("读取并对比")');
await frame.waitForTimeout(1800);
const debug = await frame.evaluate(() => ({ text: document.body.innerText.slice(0, 1200), tables: document.querySelectorAll('table').length }));
const hostDebug = await page.evaluate(() => ({ calls: window.HOST.calls, toasts: window.HOST.toasts, topics: [...window.HOST.topics.keys()] }));
console.error(JSON.stringify({ debug, hostDebug, errors }, null, 2));
await frame.waitForSelector('table tbody tr', { timeout: 8000 });
await frame.waitForTimeout(300);
const compare = await frame.evaluate(() => ({
  rows: [...document.querySelectorAll('table tbody tr')].map((tr) => [...tr.cells].map((td) => td.innerText.trim())),
  chips: [...document.querySelectorAll('.chip')].map((c) => c.innerText.trim()),
  footer: (document.querySelector('.footer-note') || {}).innerText || '',
}));
await page.screenshot({ path: path.join(OUT, 'bom-2-compare.png') });

await frame.click('button:has-text("一键出库")');
await frame.waitForSelector('.modal', { timeout: 8000 });
await frame.waitForTimeout(400);
const modal = await frame.evaluate(() => ({ title: (document.querySelector('.modal h3') || {}).innerText, rows: [...document.querySelectorAll('.modal table tbody tr')].map((tr) => [...tr.cells].map((td) => td.innerText.trim())) }));
await page.screenshot({ path: path.join(OUT, 'bom-3-outbound-preview.png') });

await frame.fill('.modal input[type="text"]', '2026 春季电源板');
await frame.click('.modal button:has-text("确认出库")');
await frame.waitForTimeout(800);
const after = await frame.evaluate(() => ({ notices: [...document.querySelectorAll('.notice')].map((n) => n.innerText.trim()), outbound: window.__LAST__ || null }));
const outboundPayload = await page.evaluate(() => window.HOST.outboundPayload);
await page.screenshot({ path: path.join(OUT, 'bom-4-outbound-done.png') });

await browser.close();
server.close();
console.log(JSON.stringify({ compare, modal, after: { notices: after.notices }, outboundPayload, errors }, null, 2));
if (errors.length) process.exitCode = 1;
if (!compare.rows.length) process.exitCode = 1;
if (!modal.rows.length) process.exitCode = 1;
