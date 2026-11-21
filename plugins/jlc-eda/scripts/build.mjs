import { promises as fs } from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { fileURLToPath } from 'node:url';
import esbuild from 'esbuild';
import JSZip from 'jszip';

const ROOT = path.resolve(fileURLToPath(new URL('..', import.meta.url)));
const BUILD = path.join(ROOT, 'build');
const STAGE = path.join(BUILD, 'stage');
const BUNDLE_STAGE = path.join(BUILD, 'bundle-stage');
const DIST = path.join(ROOT, 'dist');
const FIXED_DATE = new Date('2026-01-01T00:00:00.000Z');

const INCLUDED = [
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
];

const installText = (version) => `实验室库存插件 ${version} 安装说明

一、安装 EDA 插件
1. 打开嘉立创 EDA 专业版。
2. 进入「高级 → 扩展管理器 → 导入」。
3. 选择本压缩包内的 lab-inventory-odoo_v${version}.eext。
4. 启用「实验室库存联动（Odoo 19）」，并开启「外部交互」权限。
5. 顶部菜单出现「库存联动」。

二、获取 EDA 密钥
1. 打开网页端 https://team.l-creation.club/team/lab/settings 的「管理」页。
2. 在「EDA 插件密钥」区块选择你自己的账号，点「发放」。
3. 复制显示的密钥（形如 eda_xxxxxxxx）。它只显示这一次，请立即保存。

三、连接
1. 打开「库存联动 → 连接与账户」。
2. 服务器地址保持默认 https://team.l-creation.club（内网可改 http://192.168.31.105:8069）。
3. 粘贴上面的 EDA 密钥，点「保存并连接」。
4. 连接成功后即可查询器件库、原理图库存与库位，并对整张 BOM 一键出库。

四、说明
- 密钥绑定到你的账号：插件里做的每一次出库，操作人都是你。
- 密钥明文保存在本机 EDA 配置里（与浏览器保存密码同一水位）；离职或换机时请管理员吊销。
- 一键出库必须在确认弹窗后才会写入 Odoo；入库、归还、扫码追溯请在网页端或 Flutter 客户端办理。
- 连接失败先检查服务器地址与密钥是否有效（管理员可在「管理」页看到最近使用时间）。
- 本版本不需要安装任何额外程序，也不需要本机桥接。
`;

function sha256(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

async function ensureClean(dir) {
  await fs.rm(dir, { recursive: true, force: true });
  await fs.mkdir(dir, { recursive: true });
}

async function copy(rel) {
  const from = rel === 'images/logo.png' ? path.join(ROOT, 'assets/logo.png') : path.join(ROOT, rel);
  const to = path.join(STAGE, rel);
  await fs.mkdir(path.dirname(to), { recursive: true });
  await fs.copyFile(from, to);
}

async function buildMain() {
  await ensureClean(DIST);
  await esbuild.build({
    entryPoints: [path.join(ROOT, 'src/main/index.js')],
    outfile: path.join(DIST, 'index.js'),
    bundle: true,
    platform: 'browser',
    format: 'iife',
    globalName: 'edaEsbuildExportName',
    minify: false,
    treeShaking: true,
    ignoreAnnotations: true,
    charset: 'utf8',
    target: ['es2020'],
    logLevel: 'silent',
  });
}

async function buildIframe() {
  const bundle = await esbuild.build({
    entryPoints: [path.join(ROOT, 'src/iframe/app.js')],
    bundle: true,
    write: false,
    platform: 'browser',
    format: 'iife',
    minify: false,
    treeShaking: true,
    charset: 'utf8',
    target: ['es2020'],
    logLevel: 'silent',
  });
  const js = bundle.outputFiles[0].text;
  if (js.includes('</script')) throw new Error('iframe bundle unexpectedly contains </script');
  const html = await fs.readFile(path.join(ROOT, 'src/iframe/app.html'), 'utf8');
  const css = await fs.readFile(path.join(ROOT, 'src/iframe/app.css'), 'utf8');
  const output = html.replace('/*__LAB_CSS__*/', css).replace('/*__LAB_JS__*/', js);
  await fs.mkdir(path.join(STAGE, 'iframe'), { recursive: true });
  await fs.writeFile(path.join(STAGE, 'iframe/app.html'), output, 'utf8');
}

async function stage() {
  await ensureClean(BUILD);
  await fs.mkdir(STAGE, { recursive: true });
  await buildMain();
  await buildIframe();
  await fs.mkdir(path.join(STAGE, 'dist'), { recursive: true });
  await fs.copyFile(path.join(DIST, 'index.js'), path.join(STAGE, 'dist/index.js'));
  for (const rel of INCLUDED) {
    if (rel === 'iframe/app.html' || rel === 'dist/index.js') continue;
    await copy(rel);
  }
}

async function collectFiles(dir, prefix = '') {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const rel = prefix ? prefix + '/' + entry.name : entry.name;
    const absolute = path.join(dir, entry.name);
    if (entry.isDirectory()) files.push(...(await collectFiles(absolute, rel)));
    else files.push(rel);
  }
  return files.sort();
}

async function makeZip() {
  const files = await collectFiles(STAGE);
  const zip = new JSZip();
  const manifestFiles = [];
  for (const rel of files) {
    const content = await fs.readFile(path.join(STAGE, rel));
    zip.file(rel, content, { date: FIXED_DATE, unixPermissions: 0o100644, createFolders: false });
    manifestFiles.push({ path: rel, bytes: content.length, sha256: sha256(content) });
  }
  const buffer = await zip.generateAsync({
    type: 'nodebuffer',
    compression: 'DEFLATE',
    compressionOptions: { level: 9 },
    platform: 'UNIX',
    streamFiles: false,
  });
  return { buffer, manifestFiles };
}

async function stageBundle(eextPath, extension) {
  // 4.0.0 起没有本机桥接：插件直连 Odoo，用 API 密钥认证。
  // 包里只有 .eext 本身 + 说明，体积从 89 MB 降到 100 KB 量级。
  await ensureClean(BUNDLE_STAGE);
  await fs.copyFile(eextPath, path.join(BUNDLE_STAGE, path.basename(eextPath)));
  await fs.copyFile(path.join(ROOT, 'README.md'), path.join(BUNDLE_STAGE, 'README.md'));
  await fs.writeFile(path.join(BUNDLE_STAGE, '安装说明.txt'), installText(extension.version), 'utf8');
  const rel = 'lab-inventory-odoo_v' + extension.version + '.eext';
  const content = await fs.readFile(path.join(BUNDLE_STAGE, rel));
  await fs.writeFile(path.join(BUNDLE_STAGE, 'SHA256.txt'),
    sha256(content) + '  ' + rel + '\n', 'utf8');
}

async function makeBundleZip() {
  const files = await collectFiles(BUNDLE_STAGE);
  const zip = new JSZip();
  const manifestFiles = [];
  for (const rel of files) {
    const content = await fs.readFile(path.join(BUNDLE_STAGE, rel));
    const isScript = rel.endsWith('.sh') || rel.endsWith('.cmd');
    zip.file(rel, content, {
      date: FIXED_DATE,
      unixPermissions: isScript ? 0o100755 : 0o100644,
      createFolders: false,
      compression: 'DEFLATE',
    });
    manifestFiles.push({ path: rel, bytes: content.length, sha256: sha256(content) });
  }
  const buffer = await zip.generateAsync({
    type: 'nodebuffer',
    compression: 'DEFLATE',
    compressionOptions: { level: 9 },
    platform: 'UNIX',
    streamFiles: false,
  });
  return { buffer, manifestFiles };
}

async function main() {
  const extension = JSON.parse(await fs.readFile(path.join(ROOT, 'extension.json'), 'utf8'));
  if (!/^[0-9a-f]{32}$/i.test(String(extension.uuid || ''))) {
    throw new Error('extension.json uuid must be 32 hex characters');
  }
  if (!/^\d+\.\d+\.\d+$/.test(String(extension.version || ''))) {
    throw new Error('extension.json version must be semver');
  }
  await stage();
  const first = await makeZip();
  const second = await makeZip();
  if (sha256(first.buffer) !== sha256(second.buffer)) {
    throw new Error('package is not reproducible: two runs produced different hashes');
  }
  const fileName = 'lab-inventory-odoo_v' + extension.version + '.eext';
  const outputPath = path.join(BUILD, fileName);
  await fs.writeFile(outputPath, first.buffer);
  const manifest = {
    name: extension.name,
    uuid: extension.uuid,
    version: extension.version,
    fileName,
    bytes: first.buffer.length,
    sha256: sha256(first.buffer),
    files: first.manifestFiles,
  };
  await fs.writeFile(path.join(BUILD, 'package-manifest.json'), JSON.stringify(manifest, null, 2) + '\n', 'utf8');

  await stageBundle(outputPath, extension);
  const bundle = await makeBundleZip();
  const bundleAgain = await makeBundleZip();
  if (sha256(bundle.buffer) !== sha256(bundleAgain.buffer)) {
    throw new Error('bundle is not reproducible: two runs produced different hashes');
  }
  const bundlePath = path.join(BUILD, 'lab-inventory-odoo_v' + extension.version + '-bundle.zip');
  await fs.writeFile(bundlePath, bundle.buffer);
  const bundleManifest = {
    version: extension.version,
    fileName: path.basename(bundlePath),
    bytes: bundle.buffer.length,
    sha256: sha256(bundle.buffer),
    files: bundle.manifestFiles,
  };
  await fs.writeFile(path.join(BUILD, 'bundle-manifest.json'), JSON.stringify(bundleManifest, null, 2) + '\n', 'utf8');

  console.log('Built ' + outputPath);
  console.log('SHA-256 ' + manifest.sha256);
  console.log('Files ' + first.manifestFiles.length + ', bytes ' + manifest.bytes);
  console.log('Built ' + bundlePath);
  console.log('Bundle SHA-256 ' + bundleManifest.sha256);
  console.log('Bundle bytes ' + bundleManifest.bytes);
}

main().catch((error) => {
  console.error('BUILD FAILED:', error && error.message ? error.message : error);
  process.exit(1);
});
