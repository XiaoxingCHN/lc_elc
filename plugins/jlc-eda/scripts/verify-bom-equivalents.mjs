// Exercise the installed package in a browser with a simulated EDA SDK and Odoo responses.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import JSZip from 'jszip';

const { chromium } = await import(process.env.PLAYWRIGHT_IMPORT || 'playwright');

/** WCAG relative-luminance contrast of two `rgb()`/`rgba()` strings. */
function contrast(foreground, background) {
  const parse = (value) => {
    const parts = String(value).match(/[\d.]+/g);
    if (!parts || parts.length < 3) throw new Error('Unreadable colour: ' + value);
    return parts.slice(0, 3).map(Number);
  };
  const luminance = (rgb) => {
    const channels = rgb.map((channel) => {
      const unit = channel / 255;
      return unit <= 0.04045 ? unit / 12.92 : ((unit + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
  };
  const a = luminance(parse(foreground));
  const b = luminance(parse(background));
  const [light, dark] = a > b ? [a, b] : [b, a];
  return (light + 0.05) / (dark + 0.05);
}
const [artifact, screenshot] = process.argv.slice(2);
assert.ok(artifact, 'Pass the .eext to verify');
const zip = await JSZip.loadAsync(await readFile(artifact));
const main = await zip.file('dist/index.js').async('string');
const panel = await zip.file('iframe/app.html').async('string');

function startHost(code) {
  const storage = new Map([
    ['lab_eda_server_url', 'https://fixture.example.test'],
    ['lab_eda_token', 'eda_' + 'A'.repeat(43)],
  ]);
  const services = new Map();
  window.equivalentRequests = [];
  window.issues = [];
  window.issueKeys = [];
  window.failNextIssue = false;
  window.includeUnmatched = true;
  const missingCode = 'C5137636';
  const parts = Array.from({ length: 61 }, (_, index) => ({
    getState_Designator: () => 'C' + (index + 4),
    getState_SupplierId: () => missingCode,
    getState_Name: () => '100nF',
    getState_OtherProperty: () => ({ Value: '100 nF' }),
    getState_Footprint: () => index === 0 ? undefined : { name: 'C0603_L1.6-W0.8' },
  }));
  parts.push({
    getState_Designator: () => 'C99',
    getState_SupplierId: () => 'C5137562',
    getState_Name: () => '2.2nF',
    getState_Footprint: () => ({ name: 'C0603' }),
  });
  const user = { id: 42, name: '验收用库存用户' };
  const eda = {
    sys_Storage: {
      getExtensionUserConfig: (key) => storage.get(key),
      setExtensionUserConfig: async (key, value) => { storage.set(key, value); },
    },
    sys_IFrame: {
      async openIFrame(src) {
        const frame = document.createElement('iframe');
        frame.id = 'panel';
        frame.style.cssText = 'width:100%;height:100%;border:0';
        frame.src = src;
        document.body.append(frame);
        return true;
      },
    },
    sys_MessageBus: {
      rpcService: (topic, callback) => services.set(topic, callback),
      rpcCall: async (topic, payload) => services.get(topic)(payload),
      removePrivateMessageBus: () => services.clear(),
    },
    sch_SelectControl: { getAllSelectedPrimitives: async () => window.includeUnmatched ? parts : parts.slice(0, -1) },
    sys_ClientUrl: {
      async request(url, method, body) {
        const { params, id } = JSON.parse(body);
        let data;
        if (url.endsWith('/bootstrap')) {
          data = { user, borrowers: [{ ...user, is_self: true }], permissions: { can_issue: true } };
        } else if (url.endsWith('/detail')) {
          if (params.item_key !== 'lab:158') {
            return new Response(JSON.stringify({ id, result: { ok: false, error: { code: 'NOT_FOUND' } } }));
          }
          data = { item: { name: '100nF ±10% 50V', lab_available_quantity: 100 },
            bags: [{ id: 313, available_quantity: 100 }] };
        } else if (url.endsWith('/inventory/issue')) {
          window.issueKeys.push(params.request_key);
          if (window.failNextIssue) {
            // The answer never arrives: the write may or may not have landed.
            window.failNextIssue = false;
            throw new Error('network down after send');
          }
          window.issues.push(params);
          data = { operation: { id: 71, actor_id: 42, borrower_id: params.borrower_id }, lines: params.lines };
        } else if (url.endsWith('/equivalents')) {
          window.equivalentRequests.push(...params.lines);
          data = { lines: params.lines.map((line) => ({
            item_key: line.item_key,
            basis: 'value_package',
            source: { package: line.footprint },
            candidates: line.item_key === 'lcsc:' + missingCode && line.footprint === '0603' && line.name === '100nF' ? [{
              item_key: 'lab:158', catalog_code: 'C30926', sn: 'LAB-000127', name: '100nF ±10% 50V',
              available: 100, package: '0603', locations: [{ name: 'R15' }],
              bags: [{ trace_code: 'LABB:313' }], confidence: 'weak', matched: [], conflicts: [],
            }] : [],
          })) };
        } else throw new Error('Unexpected fixture request: ' + method + ' ' + url);
        return new Response(JSON.stringify({ id, result: { ok: true, data } }));
      },
    },
  };
  window.eda = eda;
  const sandbox = { eda, window: undefined, document: undefined, self: undefined };
  const exports = new Function('sandbox', 'with (sandbox) {' + code + '\nreturn edaEsbuildExportName;}')(sandbox);
  return exports.bomCompare();
}

const browser = await chromium.launch({ channel: 'msedge', headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1100, height: 800 }, colorScheme: 'dark' });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/*', (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== 'http://eda.test') return route.abort();
    const body = url.pathname === '/iframe/app.html' ? panel : '<!doctype html><body style="margin:0;height:100vh"></body>';
    return route.fulfill({ status: 200, contentType: 'text/html; charset=utf-8', body });
  });
  await page.goto('http://eda.test/');
  await page.evaluate(startHost, main);
  const frame = page.frameLocator('#panel');
  await frame.getByRole('tab', { name: '原理图库存' }).waitFor();
  if (!(await frame.getByRole('button', { name: '读取并对比' }).isVisible())) {
    await frame.getByRole('tab', { name: '连接设置' }).click();
    await frame.getByRole('button', { name: '保存并连接' }).click();
    await frame.getByRole('tab', { name: '原理图库存' }).click();
  }
  await frame.getByRole('button', { name: '读取并对比' }).click();
  await page.waitForFunction(() => window.equivalentRequests.length === 2);
  const lines = await page.evaluate(() => window.equivalentRequests);
  assert.deepEqual(lines.find((line) => line.item_key === 'lcsc:C5137636'), {
    item_key: 'lcsc:C5137636', quantity: 61, name: '100nF', footprint: '0603',
  });
  await frame.getByRole('button', { name: /可选替代 1/ }).click();
  await frame.getByText('LAB-000127', { exact: true }).waitFor();
  await frame.getByRole('checkbox', { name: '选用' }).click();
  await frame.getByText('已选替代', { exact: true }).waitFor();
  assert.equal(await frame.getByRole('checkbox', { name: '已选' }).isChecked(), true);
  await frame.getByText('未找到有可用库存的替代料', { exact: true }).waitFor();
  if (screenshot) await page.screenshot({ path: screenshot });

  await frame.getByRole('button', { name: '一键出库' }).click();
  await frame.getByText('一键出库：库存不足，未扣减任何库存', { exact: true }).waitFor();
  assert.deepEqual(await page.evaluate(() => window.issues), []);

  // Narrow the selected designators to the line that has a substitute.
  await page.evaluate(() => { window.includeUnmatched = false; });
  await frame.getByRole('button', { name: '读取并对比' }).click();
  await page.waitForFunction(() => window.equivalentRequests.length === 3);
  const alternatives = frame.getByRole('button', { name: /可选替代 1/ });
  if (await alternatives.getAttribute('aria-expanded') === 'false') await alternatives.click();
  await frame.getByRole('checkbox', { name: '选用' }).click();
  await frame.getByRole('button', { name: '一键出库' }).click();
  await frame.getByText('袋#313×61', { exact: true }).waitFor();
  assert.deepEqual(await page.evaluate(() => window.issues), []);
  // Dialog focus: stays inside, Escape closes, and closing writes nothing.
  const modal = frame.locator('.modal');
  assert.equal(await modal.evaluate((node) => node.contains(document.activeElement)), true,
    'focus must start inside the dialog');
  for (let step = 0; step < 4; step += 1) {
    await page.keyboard.press('Tab');
    assert.equal(await modal.evaluate((node) => node.contains(document.activeElement)), true,
      'Tab must not escape the dialog');
  }
  await page.keyboard.press('Escape');
  await modal.waitFor({ state: 'detached' });
  assert.deepEqual(await page.evaluate(() => window.issues), [], 'Escape must write nothing');

  await frame.getByRole('button', { name: '一键出库' }).click();
  await frame.getByText('袋#313×61', { exact: true }).waitFor();
  await frame.getByPlaceholder('例如：2026 春季电源板').fill('隔离环境 BOM 验收');
  await frame.getByRole('button', { name: '确认出库' }).click();
  await page.waitForFunction(() => window.issues.length === 1);
  const [issue] = await page.evaluate(() => window.issues);
  assert.deepEqual(issue.lines, [{ bag_id: 313, quantity: 61 }]);
  assert.equal(issue.borrower_id, 42);
  assert.match(issue.note, /C5137636 → LAB-000127 ×61/);
  await frame.getByText('一键出库已完成（真实领用单）', { exact: true }).waitFor();
  const firstKey = (await page.evaluate(() => window.issueKeys))[0];
  assert.ok(firstKey, 'the issue must carry a request key');

  // ---- An issue whose answer never arrives must stay recoverable -----------
  await page.evaluate(() => { window.failNextIssue = true; });
  // A successful issue re-reads the BOM, so count relatively, never absolutely.
  const count = () => page.evaluate(() => window.equivalentRequests.length);
  const before = await count();
  await frame.getByRole('button', { name: '读取并对比' }).click();
  await page.waitForFunction((n) => window.equivalentRequests.length > n, before);
  const again = frame.getByRole('button', { name: /可选替代 1/ });
  if (await again.getAttribute('aria-expanded') === 'false') await again.click();
  await frame.getByRole('checkbox', { name: '选用' }).click();
  await frame.getByRole('button', { name: '一键出库' }).click();
  await frame.getByText('袋#313×61', { exact: true }).waitFor();
  await frame.getByPlaceholder('例如：2026 春季电源板').fill('隔离环境 BOM 验收 2');
  await frame.getByRole('button', { name: '确认出库' }).click();

  await frame.getByText('有一笔出库结果未知', { exact: true }).waitFor();
  const unknownKey = (await page.evaluate(() => window.issueKeys)).at(-1);
  assert.notEqual(unknownKey, firstKey, 'a new issue must use a new key');
  // A fresh issue is blocked while the record is unresolved.
  const outboundButton = frame.getByRole('button', { name: '先处理未决出库' });
  await outboundButton.waitFor();
  assert.equal(await outboundButton.isDisabled(), true);
  assert.equal(await page.evaluate(() => window.issues.length), 1, 'nothing new was written');

  // Re-scanning must NOT clear it.
  const beforeRescan = await count();
  await frame.getByRole('button', { name: '读取并对比' }).click();
  await page.waitForFunction((n) => window.equivalentRequests.length > n, beforeRescan);
  await frame.getByText('有一笔出库结果未知', { exact: true }).waitFor();

  // Retry reuses the SAME request key.
  await frame.getByRole('button', { name: '原样重试（同一请求号）' }).click();
  await page.waitForFunction(() => window.issues.length === 2);
  const retriedKey = (await page.evaluate(() => window.issueKeys)).at(-1);
  assert.equal(retriedKey, unknownKey, 'retry must reuse the saved request key');
  await frame.getByText('有一笔出库结果未知', { exact: true }).waitFor({ state: 'detached' });

  // ---- Primary button contrast, measured from the live styles -------------
  const colours = await frame.locator('.btn.primary').first().evaluate((button) => {
    const style = getComputedStyle(button);
    return { color: style.color, background: style.backgroundColor };
  });
  const ratio = contrast(colours.color, colours.background);
  assert.ok(ratio >= 4.5, 'primary label contrast ' + ratio.toFixed(2) + ':1 is below 4.5:1');

  assert.deepEqual(errors, []);
  console.log('PASS: packaged BOM scan, SN selection, shortage blocking, simulated issue,');
  console.log('      unresolved-outbound lock across re-scan, same-key retry and primary contrast');
} finally {
  await browser.close();
}
