import { promises as fs } from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import JSZip from 'jszip';

const ROOT = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const EXPECTED_UUID = '1329a87d576b4b8cbb8592b1c1012b8b';
const FORBIDDEN_PREFIXES = ['src/', 'tests/', 'scripts/', 'node_modules/', '_reference/', 'build/'];
const FORBIDDEN_FILES = ['package.json', 'package-lock.json', '.env'];
const SECRET_MARKERS = ['admin123', 'lab_inventory_token'];

function sha256(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

function fail(message) {
  console.error('FAIL: ' + message);
  process.exitCode = 1;
}

async function main() {
  const extension = JSON.parse(await fs.readFile(path.join(ROOT, 'extension.json'), 'utf8'));
  const file = path.join(ROOT, 'build', 'lab-inventory-odoo_v' + extension.version + '.eext');
  const buffer = await fs.readFile(file);
  const zip = await JSZip.loadAsync(buffer);
  const names = Object.keys(zip.files).filter((name) => !zip.files[name].dir).sort();

  const required = [
    'extension.json',
    'dist/index.js',
    'iframe/app.html',
    'images/logo.png',
    'README.md',
    'CHANGELOG.md',
    'LICENSE',
  ];
  for (const name of required) {
    if (!names.includes(name)) fail('missing ' + name);
  }
  for (const name of names) {
    if (FORBIDDEN_PREFIXES.some((prefix) => name.startsWith(prefix))) fail('forbidden path in package: ' + name);
    if (FORBIDDEN_FILES.includes(name)) fail('forbidden file in package: ' + name);
  }

  const manifest = JSON.parse(await zip.file('extension.json').async('string'));
  if (manifest.uuid !== EXPECTED_UUID) fail('uuid changed: ' + manifest.uuid);
  if (manifest.version !== extension.version) fail('version mismatch');
  if (manifest.entry !== './dist/index') fail('entry must be ./dist/index');
  for (const surface of ['sch', 'pcb']) {
    if (!Array.isArray(manifest.headerMenus && manifest.headerMenus[surface])) fail('missing headerMenus.' + surface);
  }

  const mainJs = await zip.file('dist/index.js').async('string');
  if (mainJs.includes('lab_odoo_v3_rpc_request')) fail('storage RPC queue must not exist');
  if (mainJs.length < 10000) fail('dist/index.js too small: ' + mainJs.length);
  if (!mainJs.includes('activate')) fail('dist/index.js missing activate export');
  if (!mainJs.includes('showInventoryPanel')) fail('dist/index.js missing menu export');

  const iframeHtml = await zip.file('iframe/app.html').async('string');
  if (!/<script>[\s\S]*lab\.odoo\.v3\.rpc[\s\S]*<\/script>/.test(iframeHtml)) fail('iframe/app.html is not self-contained');
  if (/<script[^>]+src=/.test(iframeHtml)) fail('iframe/app.html references an external script');
  if (!iframeHtml.includes('器件库')) fail('iframe/app.html missing Chinese UI');
  if (!iframeHtml.includes('lab.odoo.v3.rpc')) fail('iframe/app.html missing private MessageBus topic');
  if (iframeHtml.includes('lab_odoo_v3_rpc_request')) fail('iframe/app.html must not use storage RPC');
  if (iframeHtml.includes('__LAB_JS__') || iframeHtml.includes('__LAB_CSS__')) fail('iframe placeholders were not replaced');

  const textFiles = ['dist/index.js', 'iframe/app.html'];
  for (const name of textFiles) {
    const text = await zip.file(name).async('string');
    for (const marker of SECRET_MARKERS) {
      if (text.includes(marker)) fail('secret/hardcoded credential marker "' + marker + '" in ' + name);
    }
  }

  const readme = await zip.file('README.md').async('string');
  for (const phrase of ['Odoo 19', '3.0.3', 'CORS', 'session_id', 'group_lab_operator']) {
    if (!readme.includes(phrase)) fail('README missing required note: ' + phrase);
  }

  const manifestSha = sha256(buffer);
  console.log('Package ' + file);
  console.log('Files ' + names.length + ', bytes ' + buffer.length);
  console.log('SHA-256 ' + manifestSha);

  const bundlePath = path.join(ROOT, 'build', 'lab-inventory-odoo_v' + extension.version + '-bundle.zip');
  const bundleBuffer = await fs.readFile(bundlePath);
  const bundle = await JSZip.loadAsync(bundleBuffer);
  const bundleNames = Object.keys(bundle.files).filter((name) => !bundle.files[name].dir).sort();
  for (const required of [
    'lab-inventory-odoo_v' + extension.version + '.eext',
    'bridge/server.mjs',
    'bridge/start-windows.cmd',
    'bridge/start-linux.sh',
    'bridge/快速启动.txt',
    'bridge/runtime/node.exe',
    'bridge/runtime/NODE-LICENSE.txt',
    '安装说明.txt',
    'SHA256.txt',
    'README.md',
  ]) {
    if (!bundleNames.includes(required)) fail('missing bundle file: ' + required);
  }
  if (bundleNames.some((name) => name.startsWith('node_modules/'))) fail('bundle contains node_modules');
  const inside = await bundle.file('lab-inventory-odoo_v' + extension.version + '.eext').async('nodebuffer');
  if (sha256(inside) !== manifestSha) fail('bundle eext hash mismatch');
  const shaText = await bundle.file('SHA256.txt').async('string');
  if (!shaText.includes(manifestSha)) fail('bundle SHA256.txt missing eext hash');
  const installText = await bundle.file('安装说明.txt').async('string');
  if (!installText.includes('start-windows.cmd') || !installText.includes('配对码')) fail('bundle install instructions incomplete');
  const bundleManifest = JSON.parse(await fs.readFile(path.join(ROOT, 'build', 'bundle-manifest.json'), 'utf8'));
  if (bundleManifest.sha256 !== sha256(bundleBuffer)) fail('bundle manifest hash mismatch');
  console.log('Bundle Files ' + bundleNames.length + ', bytes ' + bundleBuffer.length);
  console.log('Bundle SHA-256 ' + sha256(bundleBuffer));
  if (process.exitCode) {
    console.error('PACKAGE VERIFY FAILED');
  } else {
    console.log('PACKAGE VERIFY OK');
  }
}

main().catch((error) => {
  console.error('VERIFY FAILED:', error && error.message ? error.message : error);
  process.exit(1);
});
