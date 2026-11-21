import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

/**
 * 面板调用的每一个方法，主模块的 dispatch 里都必须有对应分支。
 *
 * 这个错误已经犯过三次：
 *   1. catalog.equivalents 漏了 dispatch 分支
 *   2. panel storage key 两边不一致
 *   3. catalog.valueMatch 漏了 dispatch 分支
 * 共同点都是「面板加了调用，主模块没接线」，表现统一为
 * 「未知的面板请求：xxx」，而单元测试全绿——因为没有任何测试跨这两层。
 *
 * 这里直接读两个源文件做交叉检查。
 */
async function readSource(relPath) {
  return readFile(new URL(relPath, import.meta.url), 'utf8');
}

test('every method the panel calls has a dispatch case', async () => {
  const panel = await readSource('../../iframe/app.js');
  const main = await readSource('../../main/index.js');

  // 面板里所有 call('xxx.yyy', ...) 的调用名
  const called = new Set();
  for (const match of panel.matchAll(/\bcall\('([a-z]+\.[a-zA-Z]+)'/g)) {
    called.add(match[1]);
  }
  assert.ok(called.size > 5, 'expected to find several panel calls');

  // dispatch 里的 case 'xxx.yyy':
  const handled = new Set();
  for (const match of main.matchAll(/case '([a-z]+\.[a-zA-Z]+)':/g)) {
    handled.add(match[1]);
  }

  const missing = [...called].filter((name) => !handled.has(name)).sort();
  assert.deepEqual(missing, [],
    'panel calls these methods but dispatch has no case for them: ' + missing.join(', '));
});
