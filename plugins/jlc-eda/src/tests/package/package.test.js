import test from 'node:test';
import { readFile } from 'node:fs/promises';
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
  const pkg = JSON.parse(await readFile(new URL('../../../package.json', import.meta.url), 'utf8'));
  assert.equal(extension.version, pkg.version);
  assert.ok(buffer.length > 50000);
});

test('iframe bundle reports the same version as extension.json', async () => {
  // 面板左上角显示的版本来自 iframe/app.js 里的 VERSION 常量，与
  // extension.json 是两个独立的地方。漏改一个，扩展管理器里显示 4.0.0
  // 而面板里显示旧版本，用户会以为装错了（真实发生过）。
  const { zip, extension } = await loadPackage();
  const html = await zip.file('iframe/app.html').async('string');
  // 构建会把 const 改成 var、单引号改成双引号，所以两种都认。
  const match = html.match(/(?:const|var|let)\s+VERSION\s*=\s*['"]([^'"]+)['"]/);
  assert.ok(match, 'iframe bundle should declare a VERSION constant');
  assert.equal(match[1], extension.version,
    'iframe VERSION must match extension.json');
});

test('package SHA-256 matches build manifest', async () => {
  const { manifest, buffer } = await loadPackage();
  assert.equal(sha256(buffer), manifest.sha256);
  assert.equal(manifest.uuid, EXPECTED_UUID);
  // Read the version from package.json instead of hard-coding it: this
  // assertion is about extension.json MATCHING the package, not about which
  // version happens to be current.
  const pkg = JSON.parse(await readFile(new URL('../../../package.json', import.meta.url), 'utf8'));
  assert.equal(manifest.version, pkg.version);
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

test('extension.json keeps the upgrade UUID and the four retained menus', async () => {
  const { zip } = await loadPackage();
  const manifest = JSON.parse(await zip.file('extension.json').async('string'));
  assert.equal(manifest.uuid, EXPECTED_UUID);
  // Read the version from package.json instead of hard-coding it: this
  // assertion is about extension.json MATCHING the package, not about which
  // version happens to be current.
  const pkg = JSON.parse(await readFile(new URL('../../../package.json', import.meta.url), 'utf8'));
  assert.equal(manifest.version, pkg.version);
  assert.equal(manifest.entry, './dist/index');
  assert.equal(manifest.name, 'lab-inventory');
  assert.ok(Array.isArray(manifest.headerMenus.sch));
  assert.ok(Array.isArray(manifest.headerMenus.pcb));
  const schItems = manifest.headerMenus.sch[0].menuItems.map((item) => item.registerFn);
  for (const fn of ['showInventoryPanel', 'bomCompare', 'openSettings', 'showDebugLog']) {
    assert.ok(schItems.includes(fn), 'missing menu ' + fn);
  }
  for (const fn of ['openReceipt', 'openIssue', 'openReturn', 'openTrace']) {
    assert.equal(schItems.includes(fn), false, 'removed menu still present ' + fn);
  }
  const pcbItems = manifest.headerMenus.pcb[0].menuItems.map((item) => item.registerFn);
  for (const fn of ['openReceipt', 'openIssue', 'openReturn', 'openTrace']) {
    assert.equal(pcbItems.includes(fn), false, 'removed pcb menu still present ' + fn);
  }
  const bomMenu = manifest.headerMenus.sch[0].menuItems.find((item) => item.registerFn === 'bomCompare');
  assert.equal(bomMenu.title, '原理图库存');
});

test('main bundle exposes activate and the retained menu handlers only', async () => {
  const { zip } = await loadPackage();
  const text = await zip.file('dist/index.js').async('string');
  assert.ok(text.length > 10000);
  for (const name of ['activate', 'showInventoryPanel', 'bomCompare', 'openSettings', 'showDebugLog']) {
    assert.ok(text.includes(name), 'bundle missing ' + name);
  }
  for (const name of ['openReceipt', 'openIssue', 'openReturn', 'openTrace']) {
    assert.equal(text.includes(name), false, 'bundle still exports ' + name);
  }
  assert.equal(text.includes('admin/admin123'), false);
  assert.equal(text.includes("password: 'admin'"), false);
});

test('iframe bundle no longer renders receipt/issue/return/trace tabs', async () => {
  const { zip } = await loadPackage();
  const html = await zip.file('iframe/app.html').async('string');
  for (const name of [
    'renderReceipt',
    'renderReceiptSuccess',
    'renderIssue',
    'renderIssueSuccess',
    'renderReturn',
    'renderReturnSuccess',
    'renderTrace',
    'prefillIssueBag',
    'queryReceiptItem',
    'buildReceiptPayload',
    'buildIssuePayload',
    'buildReturnPayload',
    'resolveTrace',
  ]) {
    assert.equal(html.includes(name), false, 'iframe bundle still contains ' + name);
  }
  for (const label of ['器件库', '原理图库存', '连接/账户', '诊断']) {
    assert.ok(html.includes(label), 'iframe missing retained tab ' + label);
  }
  assert.equal(html.includes('BOM 对比'), false);
  assert.ok(html.includes('一键出库'));
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

test('README documents the key-based connection and the 4.0.0 version', async () => {
  const { zip } = await loadPackage();
  const readme = await zip.file('README.md').async('string');
  const pkg = JSON.parse(await readFile(new URL('../../../package.json', import.meta.url), 'utf8'));
  for (const phrase of ['Odoo 19', pkg.version, 'EDA 密钥', '管理', '吊销', '外部交互']) {
    assert.ok(readme.includes(phrase), 'README missing ' + phrase);
  }
  // 4.0.0 起不再需要本机桥接，README 不该再把它当作安装步骤。
  assert.ok(!readme.includes('start-windows.cmd'), 'README still mentions the bridge launcher');
});

test('every manifest file hash matches the ZIP content', async () => {
  const { zip, manifest } = await loadPackage();
  for (const file of manifest.files) {
    const content = await zip.file(file.path).async('nodebuffer');
    assert.equal(content.length, file.bytes, 'size mismatch ' + file.path);
    assert.equal(sha256(content), file.sha256, 'hash mismatch ' + file.path);
  }
});

test('bundle contains only the eext, README, install notes and hashes', async () => {
  const { extension, manifest } = await loadPackage();
  const bundlePath = path.join(BUILD, 'lab-inventory-odoo_v' + extension.version + '-bundle.zip');
  const buffer = await fs.readFile(bundlePath);
  const bundle = await JSZip.loadAsync(buffer);
  const names = Object.keys(bundle.files).filter((name) => !bundle.files[name].dir);
  for (const name of [
    'lab-inventory-odoo_v' + extension.version + '.eext',
    '安装说明.txt',
    'SHA256.txt',
    'README.md',
  ]) {
    assert.ok(names.includes(name), 'bundle missing ' + name);
  }
  // 4.0.0 起没有本机桥接：包里绝不能出现 Node 运行时或任何凭证文件。
  for (const forbidden of [
    'bridge/server.mjs',
    'bridge/credentials.mjs',
    'bridge/runtime/node.exe',
    'bridge/lab-credentials.dat',
    'bridge/relay-token.txt',
  ]) {
    assert.ok(!names.includes(forbidden), 'bundle must not contain ' + forbidden);
  }
  // 只有这 4 个文件：再加任何东西都说明打包白名单被放宽了。
  assert.equal(names.length, 4, 'unexpected extra files: ' + names.join(', '));
  const inside = await bundle.file('lab-inventory-odoo_v' + extension.version + '.eext').async('nodebuffer');
  assert.equal(sha256(inside), manifest.sha256);
  const shaText = await bundle.file('SHA256.txt').async('string');
  assert.ok(shaText.includes(manifest.sha256));
  const install = await bundle.file('安装说明.txt').async('string');
  // 4.0.0 的安装说明讲的是「去管理页领密钥」，不再有桥接启动步骤。
  assert.ok(install.includes('EDA 密钥'), 'install notes should explain the EDA key');
  assert.ok(install.includes('管理'), 'install notes should point at the admin page');
  assert.ok(!install.includes('start-windows.cmd'), 'install notes must not mention the removed bridge');
  const bundleManifest = JSON.parse(await fs.readFile(path.join(BUILD, 'bundle-manifest.json'), 'utf8'));
  assert.equal(bundleManifest.sha256, sha256(buffer));
});
