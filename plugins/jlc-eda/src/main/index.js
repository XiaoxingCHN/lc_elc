/**
 * lab-inventory 4.0.0 — EDA Pro extension entry (画图助手).
 *
 * 网络路径：EDA sys_ClientUrl -> Odoo ``/lab/api/eda/*``，用
 * ``Authorization: bearer <EDA 密钥>`` 认证。
 *
 * 没有本机桥接、没有配对码、没有 Cookie 会话。EDA 的请求层无法携带 Cookie
 * （``Cookie`` 是 Fetch 禁止头），所以改用 Odoo 19 原生支持的 bearer 认证。
 * 密钥由库存管理员在网页端「管理」页发放，绑定到具体账号，可随时吊销。
 */

import { ApiError, ERROR_CODES } from '../shared/jsonrpc.js';
import { createLogger } from './logger.js';
import {
  DEFAULT_SERVER_URL,
  clearToken,
  loadConfig,
  saveConfig,
} from './config.js';
import { createSdkTransport } from './transport.js';
import { createOdooClient } from './odoo.js';
import { createLabApi } from './api.js';
import { handleOutbound } from '../shared/outbound.js';
import { getEda, resolveEda, scanProjectBom, scanSchematic, toast } from './eda.js';
import { installBridge, makeNonce, openOdooAction, openPanel } from './panel.js';

export const VERSION = '4.0.0';

/**
 * 宿主每次点菜单都会重新执行整个 bundle，模块级状态会丢。把运行时挂在
 * globalThis 上，切换菜单后不必重新用密钥握手。
 */
const RUNTIME_KEY = '__LAB_EDA_V4_RUNTIME__';
function runtimeStore() {
  if (!globalThis[RUNTIME_KEY]) {
    globalThis[RUNTIME_KEY] = {
      logger: createLogger(),
      config: null,
      client: null,
      api: null,
      bridge: null,
    };
  }
  return globalThis[RUNTIME_KEY];
}
const RT = runtimeStore();
const logger = RT.logger;

let config = RT.config;
let client = RT.client;
let api = RT.api;
let bridge = RT.bridge;

function syncRuntime() {
  RT.config = config;
  RT.client = client;
  RT.api = api;
  RT.bridge = bridge;
}

function detectSdk() {
  const eda = resolveEda();
  return {
    available: Boolean(eda),
    clientUrl: Boolean(eda && eda.sys_ClientUrl && typeof eda.sys_ClientUrl.request === 'function'),
    iframe: Boolean(eda && eda.sys_IFrame && typeof eda.sys_IFrame.openIFrame === 'function'),
    storage: Boolean(eda && eda.sys_Storage && typeof eda.sys_Storage.getExtensionUserConfig === 'function'),
    messageBus: Boolean(eda && eda.sys_MessageBus && typeof eda.sys_MessageBus.rpcService === 'function'),
    schematicComponents: Boolean(
      eda && eda.sch_PrimitiveComponent && typeof eda.sch_PrimitiveComponent.getAll === 'function',
    ),
    schematicSelection: Boolean(
      eda && eda.sch_SelectControl && typeof eda.sch_SelectControl.getAllSelectedPrimitives === 'function',
    ),
    schematicPages: Boolean(
      eda && eda.dmt_Schematic && typeof eda.dmt_Schematic.getAllSchematicPagesInfo === 'function',
    ),
  };
}

function resetRuntime(nextConfig) {
  config = nextConfig;
  const eda = getEda();
  const transport = createSdkTransport({ eda, logger });
  client = createOdooClient({ config, transport, logger });
  api = createLabApi(client);
  syncRuntime();
  return { client, api };
}

function ensureRuntime() {
  if (!config) {
    try {
      config = loadConfig(getEda());
    } catch (error) {
      logger.warn('config.load_failed', { message: error.message });
      config = { serverUrl: DEFAULT_SERVER_URL, token: '' };
    }
  }
  if (!client) resetRuntime(config);
  syncRuntime();
  return { client, api };
}

function requireApi() {
  ensureRuntime();
  if (!api) throw new ApiError(ERROR_CODES.CONFIG, '接口客户端未初始化。');
  return api;
}

function publicConfig() {
  // 密钥**绝不**出现在这里：它只在保存时写进 sys_Storage，
  // 面板只需要知道「有没有配」。
  return {
    serverUrl: config ? config.serverUrl : DEFAULT_SERVER_URL,
    hasToken: Boolean(config && config.token),
  };
}

function publicState() {
  return {
    version: VERSION,
    config: publicConfig(),
    session: client ? client.publicSession() : { active: false, uid: null, sessionMode: 'none' },
    sdk: detectSdk(),
  };
}

/**
 * 保存配置并用密钥握手。
 *
 * 没有「登录」这一步——密钥本身就是凭证。保存后立刻调一次 ``/bootstrap``
 * 验证它有效，失败就把错误原样报给用户（而不是存下一个坏密钥）。
 */
async function applyConnection(input) {
  ensureRuntime();
  const nextConfig = {
    serverUrl: input.serverUrl !== undefined ? input.serverUrl : config.serverUrl,
    token: input.token !== undefined ? input.token : config.token,
  };
  const saved = await saveConfig(getEda(), nextConfig);
  if (client && client.publicSession().active) {
    try {
      client.disconnect();
    } catch (_) {
      /* 本地状态照常清空 */
    }
  }
  resetRuntime(saved);
  const session = await client.connect();
  return {
    config: publicConfig(),
    session,
  };
}

async function dispatch(method, params) {
  switch (method) {
    case 'app.init':
      ensureRuntime();
      return publicState();

    case 'config.save':
      return applyConnection(params || {});

    case 'session.connect': {
      ensureRuntime();
      const session = await client.connect();
      return { session, config: publicConfig() };
    }

    case 'session.disconnect':
      ensureRuntime();
      client.disconnect();
      await clearToken(getEda());
      config = Object.assign({}, config, { token: '' });
      resetRuntime(config);
      return { session: client.publicSession(), config: publicConfig() };

    case 'session.status':
      ensureRuntime();
      return client.publicSession();

    case 'catalog.search':
      return requireApi().search(params || {});

    case 'catalog.detail':
      return requireApi().detail(params && params.item_key);

    case 'catalog.categories':
      return requireApi().categories();

    case 'catalog.valueMatch':
      // 无 C 编号器件：按「值 + 封装」查候选（只返回候选，不自动合并）。
      return requireApi().valueMatch(
        params && params.queries,
        params && params.limit,
      );

    case 'catalog.equivalents':
      return requireApi().equivalents(
        params && params.lines,
        params && params.limit_per_line,
      );

    case 'inventory.bootstrap':
      return requireApi().bootstrap();

    case 'inventory.locations':
      return requireApi().locations();

    case 'inventory.issue':
      return requireApi().issue(params || {});

    case 'eda.scan': {
      const result = await scanSchematic({ scope: (params && params.scope) || 'page' });
      logger.info('eda.scan', {
        scope: result.scope,
        components: result.totals.components,
        missingCode: result.totals.missingCode,
      });
      return result;
    }

    case 'eda.bom': {
      const result = await scanProjectBom({});
      logger.info('eda.bom', { source: result.source, lines: (result.totals && result.totals.lines) || 0 });
      return result;
    }

    case 'inventory.outbound': {
      // Legacy vs frozen behaviour lives in the shared handler so it can be
      // unit-tested without the EDA host. Odoo endpoint signatures unchanged.
      return handleOutbound(requireApi(), params || {}, {
        log: (event, fields) => logger.info(event, fields),
      });
    }

    case 'ui.open':
      ensureRuntime();
      return openOdooAction(config.serverUrl, params && params.action);

    case 'diag.logs':
      ensureRuntime();
      return {
        state: publicState(),
        entries: logger.snapshot(),
        text: logger.toText(),
      };

    case 'diag.clear':
      logger.clear();
      return { ok: true };

    default:
      throw new ApiError(ERROR_CODES.BRIDGE, '未知的面板请求：' + String(method));
  }
}

async function openTab(tab, title, width, height) {
  ensureRuntime();
  const nonce = makeNonce();
  if (bridge) bridge.uninstall();
  const eda = getEda();
  const nextBridge = installBridge({
    nonce,
    dispatch,
    logger,
    eda,
    window: globalThis,
  });
  bridge = nextBridge;
  syncRuntime();
  try {
    await openPanel({
      eda,
      nonce,
      tab,
      title,
      width,
      height,
      onBeforeClose: () => {
        if (bridge === nextBridge) {
          nextBridge.uninstall();
          bridge = null;
        }
        return true;
      },
    });
    logger.info('panel.opened', { tab, nonceLength: nonce.length, bridge: nextBridge.mode });
  } catch (error) {
    if (bridge === nextBridge) {
      nextBridge.uninstall();
      bridge = null;
    }
    throw error;
  }
}

function menuAction(name, tab, title, width = 1100, height = 780) {
  return async function run() {
    try {
      await openTab(tab, title, width, height);
    } catch (error) {
      logger.error('menu.failed', { name, code: error.code, message: error.message });
      toast(name + '打开失败：' + String(error.message || error), 'error', 6);
    }
  };
}

export function activate() {
  logger.info('activate', { version: VERSION, mode });
  try {
    ensureRuntime();
  } catch (error) {
    logger.error('activate.failed', { message: error.message });
  }
}

export const showInventoryPanel = menuAction('器件库与库存', 'inventory', '器件库与库存', 1160, 800);
export const bomCompare = menuAction('原理图库存', 'bom', '原理图库存', 1160, 800);
export const openSettings = menuAction('连接与账户', 'settings', '连接与账户', 860, 720);
export const showDebugLog = menuAction('诊断日志', 'diagnostics', '诊断日志', 980, 760);
