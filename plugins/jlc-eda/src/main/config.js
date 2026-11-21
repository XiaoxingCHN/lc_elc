/**
 * 插件配置：服务器地址 + EDA 密钥。
 *
 * **密钥是明文存在 sys_Storage 里的。** EDA 扩展拿不到 Windows DPAPI，
 * 所以这一点绕不过去——与浏览器保存密码同一水位。缓解手段在服务端：
 * 密钥绑定到具体账号、可随时吊销、有 last_used_at 可查。
 */

import { ApiError, ERROR_CODES } from '../shared/jsonrpc.js';

export const DEFAULT_SERVER_URL = 'https://team.l-creation.club';
export const STORAGE = Object.freeze({
  serverUrl: 'lab_eda_server_url',
  token: 'lab_eda_token',
  panel: 'lab_eda_panel_payload',
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
    throw new ApiError(ERROR_CODES.CONFIG, '服务器地址不能为空。',
      { fields: { serverUrl: 'required' } });
  }
  let url;
  try {
    url = new URL(text);
  } catch (_) {
    throw new ApiError(ERROR_CODES.CONFIG,
      '服务器地址必须是完整的 http(s) URL，例如 https://team.l-creation.club。',
      { fields: { serverUrl: 'invalid' } });
  }
  if (!/^https?:$/.test(url.protocol)) {
    throw new ApiError(ERROR_CODES.CONFIG, '服务器地址只允许 http 或 https。',
      { fields: { serverUrl: 'protocol' } });
  }
  if (url.username || url.password) {
    throw new ApiError(ERROR_CODES.CONFIG, '服务器地址不能包含用户名或密码。',
      { fields: { serverUrl: 'credentials_not_allowed' } });
  }
  if (url.search || url.hash) {
    throw new ApiError(ERROR_CODES.CONFIG, '服务器地址不要带查询参数或锚点。',
      { fields: { serverUrl: 'query_not_allowed' } });
  }
  const path = url.pathname.replace(/\/+$/, '');
  return url.protocol + '//' + url.host + path;
}

/**
 * EDA 密钥格式：``eda_`` + base64url。
 *
 * 只做**形状**校验——真正的有效性只有服务端知道。这里挡掉明显是粘贴错误的输入，
 * 让用户立刻看到提示，而不是等到请求失败。
 */
export function normalizeToken(raw) {
  const text = String(raw ?? '').trim();
  if (!text) {
    throw new ApiError(ERROR_CODES.CONFIG, '请填写 EDA 密钥。',
      { fields: { token: 'required' } });
  }
  if (!/^eda_[A-Za-z0-9_-]{20,}$/.test(text)) {
    throw new ApiError(ERROR_CODES.CONFIG,
      'EDA 密钥格式不正确，应形如 eda_xxxxxxxx。请向库存管理员索取。',
      { fields: { token: 'invalid' } });
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
  let token = '';
  try {
    token = normalizeToken(read(STORAGE.token));
  } catch (_) {
    token = '';
  }
  return { serverUrl, token };
}

export async function saveConfig(eda, input) {
  const storage = getStorage(eda);
  const config = {
    serverUrl: normalizeBaseUrl(input.serverUrl),
    token: normalizeToken(input.token),
  };
  const write = async (key, value) => {
    if (typeof storage.setExtensionUserConfig !== 'function') return;
    await storage.setExtensionUserConfig(key, value);
  };
  await write(STORAGE.serverUrl, config.serverUrl);
  await write(STORAGE.token, config.token);
  return config;
}

export async function clearToken(eda) {
  const storage = getStorage(eda);
  if (typeof storage.setExtensionUserConfig === 'function') {
    await storage.setExtensionUserConfig(STORAGE.token, '');
  }
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
