import test from 'node:test';
import assert from 'node:assert/strict';
import { promises as fs } from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import JSZip from 'jszip';

const ROOT = path.resolve(fileURLToPath(new URL('../../..', import.meta.url)));
const BUILD = path.join(ROOT, 'build');
const EXPECTED_UUID = '1329a87d576b4b8cbb8592b1c1012b8b';
const FORBIDDEN = ['src/', 'tests/', 'scripts/', 'node_modules/', '_reference/', 'build/'];
const SECRETS = ['admin123', 'lab_inventory_token'];

function sha256(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

async function loadPackage() {
  const extension = JSON.parse(await fs.readFile(path.join(ROOT, 'extension.json'), 'utf8'));
  const manifestPath = path.join(BUILD, 'package-manifest.json');
  const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'));
  const filePath = path.join(BUILD, 'lab-inventory-odoo_v' + extension.version + '.eext');
  const buffer = await fs.readFile(filePath);
  const zip = await JSZip.loadAsync(buffer);
  return { extension, manifest, buffer, zip };
}

test('package exists at the expected deterministic name', async () => {
  const { extension, buffer } = await loadPackage();
  assert.equal(extension.version, '3.0.3');
  assert.ok(buffer.length > 50000);
});

test('package SHA-256 matches build manifest', async () => {
  const { manifest, buffer } = await loadPackage();
  assert.equal(sha256(buffer), manifest.sha256);
  assert.equal(manifest.uuid, EXPECTED_UUID);
  assert.equal(manifest.version, '3.0.3');
});

test('ZIP root contains extension.json and all runtime resources', async () => {
  const { zip } = await loadPackage();
  const names = Object.keys(zip.files).filter((name) => !zip.files[name].dir);
  for (const required of [
    'extension.json',
    'dist/index.js',
    'iframe/app.html',
    'images/logo.png',
    'locales/zh-Hans.json',
    'locales/en.json',
    'locales/extensionJson/zh-Hans.json',
    'locales/extensionJson/en.json',
    'README.md',
    'CHANGELOG.md',
    'LICENSE',
  ]) {
    assert.ok(names.includes(required), 'missing ' + required);
  }
  assert.equal(names.length, 11);
});

test('package has no source, tests, tooling, dependencies or credentials', async () => {
  const { zip } = await loadPackage();
  const names = Object.keys(zip.files).filter((name) => !zip.files[name].dir);
  for (const name of names) {
    for (const prefix of FORBIDDEN) assert.equal(name.startsWith(prefix), false, 'forbidden path ' + name);
    assert.notEqual(name, 'package.json');
    assert.notEqual(name, 'package-lock.json');
  }
  for (const name of ['dist/index.js', 'iframe/app.html']) {
    const text = await zip.file(name).async('string');
    for (const secret of SECRETS) assert.equal(text.includes(secret), false, 'secret marker in ' + name);
    assert.equal(text.includes('lab_inventory_server'), false);
    assert.equal(text.includes('lab_odoo_v3_rpc_request'), false);
  }
});

test('extension.json keeps the upgrade UUID and expected menus', async () => {
  const { zip } = await loadPackage();
  const manifest = JSON.parse(await zip.file('extension.json').async('string'));
  assert.equal(manifest.uuid, EXPECTED_UUID);
  assert.equal(manifest.version, '3.0.3');
  assert.equal(manifest.entry, './dist/index');
  assert.equal(manifest.name, 'lab-inventory');
  assert.ok(Array.isArray(manifest.headerMenus.sch));
  assert.ok(Array.isArray(manifest.headerMenus.pcb));
  const schItems = manifest.headerMenus.sch[0].menuItems.map((item) => item.registerFn);
  for (const fn of [
    'showInventoryPanel',
    'bomCompare',
    'openReceipt',
    'openIssue',
    'openReturn',
    'openTrace',
    'openSettings',
    'showDebugLog',
  ]) {
    assert.ok(schItems.includes(fn), 'missing menu ' + fn);
  }
});

test('main bundle exposes activate and menu handlers', async () => {
  const { zip } = await loadPackage();
  const text = await zip.file('dist/index.js').async('string');
  assert.ok(text.length > 10000);
  for (const name of ['activate', 'showInventoryPanel', 'bomCompare', 'openReceipt', 'openIssue', 'openReturn', 'openTrace', 'openSettings', 'showDebugLog']) {
    assert.ok(text.includes(name), 'bundle missing ' + name);
  }
  assert.equal(text.includes('admin/admin123'), false);
  assert.equal(text.includes("password: 'admin"), false);
});

test('iframe is self-contained, Chinese and uses the trusted bridge', async () => {
  const { zip } = await loadPackage();
  const html = await zip.file('iframe/app.html').async('string');
  assert.ok(html.includes('lang="zh-Hans"'));
  assert.ok(html.includes('器件库'));
  assert.ok(html.includes('lab.odoo.v3.rpc'));
  assert.ok(html.includes('SESSION_COOKIE_UNAVAILABLE'));
  assert.equal(/<script[^>]+src=/.test(html), false);
  assert.equal(html.includes('__LAB_JS__'), false);
  assert.equal(html.includes('__LAB_CSS__'), false);
  assert.equal(html.includes('http://localhost:8000'), false);
});

test('README documents Odoo 19, CORS, session cookie and permissions', async () => {
  const { zip } = await loadPackage();
  const readme = await zip.file('README.md').async('string');
  for (const phrase of ['Odoo 19', '3.0.3', '本机桥接', '配对码', 'LcHardwareHouse', 'group_lab_operator', '外部交互']) {
    assert.ok(readme.includes(phrase), 'README missing ' + phrase);
  }
});

test('every manifest file hash matches the ZIP content', async () => {
  const { zip, manifest } = await loadPackage();
  for (const file of manifest.files) {
    const content = await zip.file(file.path).async('nodebuffer');
    assert.equal(content.length, file.bytes, 'size mismatch ' + file.path);
    assert.equal(sha256(content), file.sha256, 'hash mismatch ' + file.path);
  }
});

test('bundle contains eext, relay, node runtime and Chinese install steps', async () => {
  const { extension, manifest } = await loadPackage();
  const bundlePath = path.join(BUILD, 'lab-inventory-odoo_v' + extension.version + '-bundle.zip');
  const buffer = await fs.readFile(bundlePath);
  const bundle = await JSZip.loadAsync(buffer);
  const names = Object.keys(bundle.files).filter((name) => !bundle.files[name].dir);
  for (const name of [
    'lab-inventory-odoo_v' + extension.version + '.eext',
    'bridge/server.mjs',
    'bridge/start-windows.cmd',
    'bridge/start-linux.sh',
    'bridge/runtime/node.exe',
    'bridge/runtime/NODE-LICENSE.txt',
    '安装说明.txt',
    'SHA256.txt',
    'README.md',
  ]) {
    assert.ok(names.includes(name), 'bundle missing ' + name);
  }
  const inside = await bundle.file('lab-inventory-odoo_v' + extension.version + '.eext').async('nodebuffer');
  assert.equal(sha256(inside), manifest.sha256);
  const shaText = await bundle.file('SHA256.txt').async('string');
  assert.ok(shaText.includes(manifest.sha256));
  const install = await bundle.file('安装说明.txt').async('string');
  assert.ok(install.includes('配对码'));
  assert.ok(install.includes('start-windows.cmd'));
  const bundleManifest = JSON.parse(await fs.readFile(path.join(BUILD, 'bundle-manifest.json'), 'utf8'));
  assert.equal(bundleManifest.sha256, sha256(buffer));
});
