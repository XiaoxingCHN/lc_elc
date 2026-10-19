/**
 * Non-secret extension configuration. The password is NEVER written here.
 */

import { ApiError, ERROR_CODES } from '../shared/jsonrpc.js';

export const DEFAULT_SERVER_URL = 'http://lc.rm.com';
export const DEFAULT_DB = 'LcHardwareHouse';
export const DEFAULT_RELAY_URL = 'http://127.0.0.1:49621';
export const STORAGE = Object.freeze({
  serverUrl: 'lab_odoo_v3_server_url',
  db: 'lab_odoo_v3_db',
  login: 'lab_odoo_v3_login',
  panel: 'lab_odoo_v3_panel_payload',
});

function getStorage(eda) {
  const storage = eda && eda.sys_Storage;
  if (!storage || typeof storage.getExtensionUserConfig !== 'function') {
    throw new ApiError(ERROR_CODES.CONFIG, 'EDA 本地配置接口不可用（sys_Storage 未加载）。');
  }
  return storage;
}

export function normalizeBaseUrl(raw) {
  const text = String(raw ?? '').trim();
  if (!text) {
    throw new ApiError(ERROR_CODES.CONFIG, '服务器地址不能为空。', { fields: { serverUrl: 'required' } });
  }
  let url;
  try {
    url = new URL(text);
  } catch (_) {
    throw new ApiError(ERROR_CODES.CONFIG, '服务器地址必须是完整的 http(s) URL，例如 http://lc.rm.com。', {
      fields: { serverUrl: 'invalid' },
    });
  }
  if (!/^https?:$/.test(url.protocol)) {
    throw new ApiError(ERROR_CODES.CONFIG, '服务器地址只允许 http 或 https。', {
      fields: { serverUrl: 'protocol' },
    });
  }
  if (url.username || url.password) {
    throw new ApiError(ERROR_CODES.CONFIG, '服务器地址不能包含用户名或密码。', {
      fields: { serverUrl: 'credentials_not_allowed' },
    });
  }
  if (url.search || url.hash) {
    throw new ApiError(ERROR_CODES.CONFIG, '服务器地址不要带查询参数或锚点。', {
      fields: { serverUrl: 'query_not_allowed' },
    });
  }
  const path = url.pathname.replace(/\/+$/, '');
  return url.protocol + '//' + url.host + path;
}

export function normalizeRelayUrl(raw) {
  const text = String(raw ?? '').trim() || DEFAULT_RELAY_URL;
  let url;
  try {
    url = new URL(text);
  } catch (_) {
    throw new ApiError(ERROR_CODES.CONFIG, '本机桥接地址无效。', { fields: { relayUrl: 'invalid' } });
  }
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1') {
    throw new ApiError(ERROR_CODES.CONFIG, '本机桥接地址只能是 http://127.0.0.1:<端口>。', {
      fields: { relayUrl: 'loopback_required' },
    });
  }
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new ApiError(ERROR_CODES.CONFIG, '本机桥接地址不能包含路径、参数或账号。', {
      fields: { relayUrl: 'invalid' },
    });
  }
  const port = Number(url.port || 80);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new ApiError(ERROR_CODES.CONFIG, '本机桥接端口无效。', { fields: { relayUrl: 'port' } });
  }
  return 'http://127.0.0.1:' + port;
}

export function normalizePairingToken(raw) {
  const text = String(raw ?? '').trim();
  if (!text) {
    throw new ApiError(ERROR_CODES.CONFIG, '请填写本机桥接窗口显示的配对码。', {
      fields: { pairingToken: 'required' },
    });
  }
  if (text.length < 16 || text.length > 256 || !/^[A-Za-z0-9._:-]+$/.test(text)) {
    throw new ApiError(ERROR_CODES.CONFIG, '配对码格式不正确，请从桥接窗口完整复制。', {
      fields: { pairingToken: 'invalid' },
    });
  }
  return text;
}

export function normalizeDbName(raw) {
  const text = String(raw ?? '').trim();
  if (!text) return '';
  if (!/^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$/.test(text)) {
    throw new ApiError(ERROR_CODES.CONFIG, '数据库名只能包含字母、数字、下划线、点和连字符。', {
      fields: { db: 'invalid' },
    });
  }
  return text;
}

export function normalizeLogin(raw) {
  const text = String(raw ?? '').trim();
  if (text.length > 200) {
    throw new ApiError(ERROR_CODES.CONFIG, '登录名过长。', { fields: { login: 'too_long' } });
  }
  return text;
}

export function loadConfig(eda) {
  const storage = getStorage(eda);
  const read = (key) => {
    try {
      const value = storage.getExtensionUserConfig(key);
      return typeof value === 'string' ? value : '';
    } catch (_) {
      return '';
    }
  };
  let serverUrl = DEFAULT_SERVER_URL;
  try {
    serverUrl = normalizeBaseUrl(read(STORAGE.serverUrl) || DEFAULT_SERVER_URL);
  } catch (_) {
    serverUrl = DEFAULT_SERVER_URL;
  }
  return {
    serverUrl,
    db: normalizeDbName(read(STORAGE.db)) || DEFAULT_DB,
    login: normalizeLogin(read(STORAGE.login)) || '',
  };
}

export async function saveConfig(eda, input) {
  const storage = getStorage(eda);
  const config = {
    serverUrl: normalizeBaseUrl(input.serverUrl),
    db: normalizeDbName(input.db) || DEFAULT_DB,
    login: normalizeLogin(input.login),
  };
  const write = async (key, value) => {
    if (typeof storage.setExtensionUserConfig !== 'function') return;
    await storage.setExtensionUserConfig(key, value);
  };
  await write(STORAGE.serverUrl, config.serverUrl);
  await write(STORAGE.db, config.db);
  await write(STORAGE.login, config.login);
  return config;
}

export async function writePanelPayload(eda, payload) {
  const storage = getStorage(eda);
  if (typeof storage.setExtensionUserConfig !== 'function') {
    throw new ApiError(ERROR_CODES.CONFIG, 'EDA 本地配置接口不支持写入。');
  }
  await storage.setExtensionUserConfig(STORAGE.panel, JSON.stringify(payload));
}

export function readPanelPayload(eda) {
  const storage = getStorage(eda);
  const raw = storage.getExtensionUserConfig(STORAGE.panel);
  if (typeof raw !== 'string' || !raw) return null;
  try {
    return JSON.parse(raw);
  } catch (_) {
    return null;
  }
}
