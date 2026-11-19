/**
 * lab-inventory 3.1.0 — EDA Pro extension entry (画图助手).
 *
 * Default network path:
 *   EDA sys_ClientUrl -> loopback relay (127.0.0.1:49621) -> Odoo
 *
 * The relay owns the Odoo session cookie. The EDA context only keeps a
 * random pairing token in memory (never in sys_Storage), so the iframe bridge
 * never carries a cookie, password or token into persistent storage.
 */

import { ApiError, ERROR_CODES } from '../shared/jsonrpc.js';
import { createLogger } from './logger.js';
import {
  DEFAULT_DB,
  DEFAULT_RELAY_URL,
  DEFAULT_SERVER_URL,
  loadConfig,
  normalizePairingToken,
  normalizeRelayUrl,
  saveConfig,
} from './config.js';
import { createSdkTransport } from './transport.js';
import { createOdooClient } from './odoo.js';
import { createRelayClient } from './relay.js';
import { createLabApi } from './api.js';
import { handleOutbound } from '../shared/outbound.js';
import { createImageLoader } from './images.js';
import { getEda, resolveEda, scanProjectBom, scanSchematic, toast } from './eda.js';
import { installBridge, makeNonce, openOdooAction, openPanel } from './panel.js';

export const VERSION = '3.1.0';

/**
 * The host re-executes the whole bundle on every menu click, so module state is
 * gone each time. Keeping the runtime (config, session client, pairing token and
 * bridge) on globalThis makes the Odoo login survive switching between menus,
 * without ever persisting a password or cookie to sys_Storage.
 */
const RUNTIME_KEY = '__LAB_ODOO_V3_RUNTIME__';
function runtimeStore() {
  if (!globalThis[RUNTIME_KEY]) {
    globalThis[RUNTIME_KEY] = {
      logger: createLogger(),
      mode: 'relay',
      relayUrl: DEFAULT_RELAY_URL,
      pairingToken: '',
      config: null,
      client: null,
      api: null,
      imageLoader: null,
      bridge: null,
    };
  }
  return globalThis[RUNTIME_KEY];
}
const RT = runtimeStore();
const logger = RT.logger;

let mode = RT.mode;
let relayUrl = RT.relayUrl;
let pairingToken = RT.pairingToken;
let config = RT.config;
let client = RT.client;
let api = RT.api;
let imageLoader = RT.imageLoader;
let bridge = RT.bridge;

/** Write the in-memory runtime back to globalThis so the next menu click reuses it. */
function syncRuntime() {
  RT.mode = mode;
  RT.relayUrl = relayUrl;
  RT.pairingToken = pairingToken;
  RT.config = config;
  RT.client = client;
  RT.api = api;
  RT.imageLoader = imageLoader;
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
  if (mode === 'relay') {
    client = createRelayClient({
      transport,
      relayUrl,
      pairingToken,
      serverUrl: config.serverUrl,
      db: config.db,
      login: config.login,
      logger,
    });
    imageLoader = createImageLoader({
      transport,
      serverUrl: config.serverUrl,
      mode: 'relay',
      relayUrl,
      pairingToken,
    });
  } else {
    client = createOdooClient({ config, transport, logger });
    imageLoader = createImageLoader({ transport, serverUrl: config.serverUrl, mode: 'direct' });
  }
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
      config = { serverUrl: DEFAULT_SERVER_URL, db: DEFAULT_DB, login: '' };
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
  return {
    serverUrl: config ? config.serverUrl : DEFAULT_SERVER_URL,
    db: config ? config.db : DEFAULT_DB,
    login: config ? config.login : '',
  };
}

function publicConnection() {
  return { mode, relayUrl, hasPairingToken: Boolean(pairingToken) };
}

function publicState() {
  return {
    version: VERSION,
    config: publicConfig(),
    connection: publicConnection(),
    session: client ? client.publicSession() : { active: false, uid: null, sessionMode: 'none' },
    sdk: detectSdk(),
  };
}

async function applyConnection(input) {
  ensureRuntime();
  const nextMode = input.mode === 'direct' ? 'direct' : 'relay';
  const nextRelayUrl = normalizeRelayUrl(input.relayUrl || relayUrl);
  const nextConfig = {
    serverUrl: input.serverUrl !== undefined ? input.serverUrl : config.serverUrl,
    db: input.db !== undefined ? input.db : config.db,
    login: input.login !== undefined ? input.login : config.login,
  };
  const saved = await saveConfig(getEda(), nextConfig);
  const changed =
    mode !== nextMode ||
    relayUrl !== nextRelayUrl ||
    saved.serverUrl !== config.serverUrl ||
    saved.db !== config.db ||
    saved.login !== config.login;
  if (changed && client && client.publicSession().active) {
    try {
      await client.logout();
    } catch (_) {
      /* local state clears even when the old endpoint is unreachable */
    }
  }
  mode = nextMode;
  relayUrl = nextRelayUrl;
  if (nextMode === 'relay') {
    const token = String(input.pairingToken || '').trim() || pairingToken;
    pairingToken = input.requireToken ? normalizePairingToken(token) : token;
  } else {
    pairingToken = '';
  }
  resetRuntime(saved);
  syncRuntime();
  return {
    config: publicConfig(),
    connection: publicConnection(),
    session: client.publicSession(),
  };
}

async function dispatch(method, params) {
  switch (method) {
    case 'app.init':
      ensureRuntime();
      return publicState();

    case 'config.save':
      return applyConnection(Object.assign({ requireToken: false }, params || {}));

    case 'session.login': {
      ensureRuntime();
      const password = String((params && params.password) || '');
      const token = String((params && params.pairingToken) || '').trim();
      const requestedMode = params && params.mode === 'direct' ? 'direct' : 'relay';
      try {
        const connection = await applyConnection(
          Object.assign({}, params || {}, { pairingToken: token, requireToken: requestedMode === 'relay' }),
        );
        const session = await client.authenticate({
          db: (params && params.db) || config.db,
          login: params && params.login,
          password,
        });
        return { session, config: connection.config, connection: connection.connection };
      } finally {
        if (params && typeof params === 'object') {
          params.password = '';
          params.pairingToken = '';
        }
      }
    }

    case 'session.logout':
      ensureRuntime();
      return client.logout();

    case 'session.status':
      ensureRuntime();
      return client.publicSession();

    case 'catalog.search':
      return requireApi().search(params || {});

    case 'catalog.detail':
      return requireApi().detail(params && params.item_key);

    case 'catalog.categories':
      return requireApi().categories();

    case 'catalog.facets':
      return requireApi().facets(params || {});

    case 'catalog.image': {
      ensureRuntime();
      return imageLoader.load(params && params.url);
    }

    case 'inventory.bootstrap':
      return requireApi().bootstrap();

    case 'inventory.locations':
      return requireApi().locations();

    case 'inventory.resolve':
      return requireApi().resolveCode(params && params.raw);

    case 'inventory.receipt':
      return requireApi().receipt(params || {});

    case 'inventory.issue':
      return requireApi().issue(params || {});

    case 'inventory.return':
      return requireApi().returnStock(params || {});

    case 'inventory.issues':
      return requireApi().issues(params || {});

    case 'inventory.history':
      return requireApi().history(params || {});

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
