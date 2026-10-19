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
const NODE_EXE = path.join(ROOT, 'bridge', 'runtime', 'node.exe');
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

const INSTALL_TEXT = `实验室库存插件 3.0.3 安装说明

一、安装 EDA 插件
1. 打开嘉立创 EDA 专业版。
2. 进入「高级 → 扩展管理器 → 导入」。
3. 选择本压缩包内的 lab-inventory-odoo_v3.0.3.eext。
4. 启用「实验室库存联动（Odoo 19）」，并开启「外部交互」权限。
5. 顶部菜单出现「库存联动」。

二、启动本机桥接（推荐）
1. 双击 bridge\\start-windows.cmd。
2. 窗口会显示「地址」和「配对码」，使用期间不要关闭。
3. 桥接只监听本机，不需要对局域网开放端口。

三、连接
1. 打开「库存联动 → 连接与账户」。
2. 连接方式选「本机桥接（推荐）」。
3. 本机地址保持 http://127.0.0.1:49621。
4. 复制桥接窗口中的配对码。
5. 填写 Odoo 登录名和密码，点击「连接并登录」。
6. 登录成功后即可查询器件库、BOM、袋追溯和库存作业。

四、说明
- 配对码每次启动都会变化，只保存在内存中。
- 插件不保存密码，不把 Odoo 会话 Cookie 返回给 EDA。
- 桥接只绑定 127.0.0.1，固定连接实验室库存服务器和 LcHardwareHouse 数据库。
- 入库、领用、归还必须在确认弹窗后才会写入 Odoo。
- 如果连接失败，先确认 start-windows.cmd 窗口仍然打开。

五、Linux
使用 bridge/start-linux.sh，需要系统已安装 Node.js（>= 20.5）。
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
  await ensureClean(BUNDLE_STAGE);
  await fs.copyFile(eextPath, path.join(BUNDLE_STAGE, path.basename(eextPath)));
  await fs.copyFile(path.join(ROOT, 'README.md'), path.join(BUNDLE_STAGE, 'README.md'));
  await fs.writeFile(path.join(BUNDLE_STAGE, '安装说明.txt'), INSTALL_TEXT, 'utf8');
  const bridgeDir = path.join(BUNDLE_STAGE, 'bridge');
  await fs.mkdir(path.join(bridgeDir, 'runtime'), { recursive: true });
  for (const rel of ['server.mjs', 'start-windows.cmd', 'start-linux.sh', '快速启动.txt']) {
    await fs.copyFile(path.join(ROOT, 'bridge', rel), path.join(bridgeDir, rel));
  }
  await fs.copyFile(
    path.join(ROOT, 'bridge', 'runtime', 'NODE-LICENSE.txt'),
    path.join(bridgeDir, 'runtime', 'NODE-LICENSE.txt'),
  );
  const stat = await fs.stat(NODE_EXE).catch(() => null);
  if (!stat) throw new Error('缺少 bridge/runtime/node.exe；请先复制随包 Node 运行时');
  await fs.copyFile(NODE_EXE, path.join(bridgeDir, 'runtime', 'node.exe'));
  const hashes = [];
  for (const rel of [
    'lab-inventory-odoo_v' + extension.version + '.eext',
    'bridge/server.mjs',
    'bridge/runtime/node.exe',
  ]) {
    const content = await fs.readFile(path.join(BUNDLE_STAGE, rel));
    hashes.push(sha256(content) + '  ' + rel);
  }
  await fs.writeFile(path.join(BUNDLE_STAGE, 'SHA256.txt'), hashes.join('\n') + '\n', 'utf8');
}

async function makeBundleZip() {
  const files = await collectFiles(BUNDLE_STAGE);
  const zip = new JSZip();
  const manifestFiles = [];
  for (const rel of files) {
    const content = await fs.readFile(path.join(BUNDLE_STAGE, rel));
    const isRuntime = rel === 'bridge/runtime/node.exe';
    const isScript = rel.endsWith('.sh') || rel.endsWith('.cmd');
    zip.file(rel, content, {
      date: FIXED_DATE,
      unixPermissions: isRuntime || isScript ? 0o100755 : 0o100644,
      createFolders: false,
      compression: isRuntime ? 'STORE' : 'DEFLATE',
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
