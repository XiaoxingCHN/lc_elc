import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

/**
 * 面板和主模块通过 sys_Storage 的同一个 key 传递 nonce。
 *
 * 两边各写一份 key 字面量，改了一边忘了另一边 → 面板读不到 payload →
 * nonce 校验失败 → 整个插件不可用（真实发生过：4.0.0 把主模块改成
 * lab_eda_panel_payload，面板还是 lab_odoo_v3_panel_payload）。
 *
 * 这里直接读两个源文件比对，而不是 import：iframe 侧的模块依赖 window。
 */
async function extractKey(relPath, pattern) {
  const source = await readFile(new URL(relPath, import.meta.url), 'utf8');
  const match = source.match(pattern);
  assert.ok(match, `could not find the panel storage key in ${relPath}`);
  return match[1];
}

test('main module and iframe agree on the panel storage key', async () => {
  const mainKey = await extractKey(
    '../../main/config.js',
    /panel:\s*'([^']+)'/,
  );
  const iframeKey = await extractKey(
    '../../iframe/bridge-client.js',
    /PANEL_STORAGE_KEY\s*=\s*'([^']+)'/,
  );
  assert.equal(
    iframeKey,
    mainKey,
    `iframe reads "${iframeKey}" but the main module writes "${mainKey}"`,
  );
});
