/**
 * Client for the loopback relay.
 *
 * The relay owns the Odoo session cookie. The EDA context only holds a
 * short-lived pairing token (memory only) and never sees session_id.
 */

import {
  ApiError,
  ERROR_CODES,
  buildJsonRpcRequest,
  decodeOdooResponse,
  decodeOdooResult,
  requestId,
} from '../shared/jsonrpc.js';
import { joinUrl } from './transport.js';

function relayAuthError() {
  return new ApiError(
    ERROR_CODES.RELAY_AUTH,
    '本机桥接配对码不正确或已变化。请重新复制桥接窗口中的配对码。',
    { action: 'relay_pairing' },
  );
}

function relayUnavailable(error) {
  if (error instanceof ApiError) return error;
  return new ApiError(
    ERROR_CODES.RELAY_UNAVAILABLE,
    '无法连接本机桥接。请先双击压缩包里的「start-windows.cmd」并保持窗口打开。',
    { retryable: true, action: 'start_relay', cause: error },
  );
}

function parseRelayBody(text) {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch (_) {
    return null;
  }
}

export function createRelayClient(options) {
  const transport = options.transport;
  const logger = options.logger;
  const state = {
    relayUrl: String(options.relayUrl || '').replace(/\/+$/, ''),
    pairingToken: String(options.pairingToken || ''),
    serverUrl: String(options.serverUrl || ''),
    db: String(options.db || ''),
    login: String(options.login || ''),
    uid: null,
    name: '',
    username: '',
    sessionMode: 'none',
    lastLoginAt: null,
  };
  let sequence = 0;

  function nextId() {
    sequence += 1;
    return requestId('relay-' + sequence);
  }

  function baseHeaders(extra = {}) {
    if (!state.pairingToken) throw relayAuthError();
    return Object.assign(
      {
        Authorization: 'Bearer ' + state.pairingToken,
        'Content-Type': 'application/json',
        Accept: 'application/json',
      },
      extra,
    );
  }

  async function postJson(path, payload, timeoutMs = 30000) {
    const response = await transport.request({
      url: joinUrl(state.relayUrl, path),
      method: 'POST',
      body: JSON.stringify(payload || {}),
      headers: baseHeaders(),
      timeoutMs,
    });
    const body = parseRelayBody(response.text);
    return { response, body };
  }

  function throwRelayError(body, status) {
    const error = body && body.ok === false ? body.error || {} : {};
    const code = String(error.code || (status === 401 ? 'RELAY_AUTH' : 'RELAY_ERROR'));
    if (code === 'RELAY_AUTH') throw relayAuthError();
    throw new ApiError(code, String(error.message || '本机桥接请求失败。'), {
      httpStatus: status,
      fields: error.fields || {},
    });
  }

  async function authenticate(input) {
    if (!state.pairingToken) throw relayAuthError();
    const login = String((input && input.login) || '').trim();
    const password = String((input && input.password) || '');
    if (!login) throw new ApiError(ERROR_CODES.CONFIG, '请填写 Odoo 登录名。', { fields: { login: 'required' } });
    if (!password) {
      throw new ApiError(ERROR_CODES.CONFIG, '请填写 Odoo 密码。密码只用于登录，不会保存。', {
        fields: { password: 'required' },
      });
    }
    state.login = login;
    state.uid = null;
    state.sessionMode = 'none';
    let result;
    try {
      result = await postJson('/login', { login, password }, 30000);
    } catch (error) {
      throw relayUnavailable(error);
    }
    if (!result.response.ok || !result.body || result.body.ok !== true) {
      if (result.response.status === 401) throw relayAuthError();
      throwRelayError(result.body, result.response.status);
    }
    const data = result.body.data || {};
    if (!data.uid) {
      throw new ApiError(ERROR_CODES.INVALID_CREDENTIALS, '登录失败：Odoo 未返回用户。', {
        action: 'check_credentials',
      });
    }
    state.uid = Number(data.uid);
    state.name = String(data.name || '');
    state.username = String(data.username || login);
    state.db = String(data.db || state.db);
    state.sessionMode = 'relay';
    state.lastLoginAt = Date.now();
    if (logger) logger.info('relay.login_ok', { uid: state.uid, db: state.db });
    return publicSession();
  }

  async function logout() {
    const wasActive = Boolean(state.uid);
    let warning = '';
    try {
      const result = await postJson('/logout', {}, 15000);
      if (!result.response.ok || !result.body || result.body.ok !== true) {
        if (result.response.status === 401) throw relayAuthError();
        throwRelayError(result.body, result.response.status);
      }
    } catch (error) {
      warning = '本机桥接注销失败，已清除插件本地会话：' + String(error && error.message);
      if (logger) logger.warn('relay.logout_warning', { code: error && error.code });
    }
    state.uid = null;
    state.name = '';
    state.username = '';
    state.sessionMode = 'none';
    return { ok: true, warning };
  }

  async function call(path, params) {
    if (!state.uid) {
      throw new ApiError(ERROR_CODES.SESSION_REQUIRED, '尚未登录 Odoo，请先连接本机桥接并登录。', {
        action: 'login',
      });
    }
    let response;
    try {
      response = await transport.request({
        url: joinUrl(state.relayUrl, '/rpc'),
        method: 'POST',
        body: JSON.stringify(buildJsonRpcRequest(params || {}, nextId())),
        headers: baseHeaders({ 'X-Lab-Path': path }),
        timeoutMs: 60000,
      });
    } catch (error) {
      throw relayUnavailable(error);
    }
    if (response.status === 401 || response.status === 403) {
      const body = parseRelayBody(response.text);
      if (body && body.ok === false) throwRelayError(body, response.status);
      if (response.status === 401) throw relayAuthError();
    }
    try {
      return decodeOdooResponse({ status: response.status, text: response.text, path });
    } catch (error) {
      if (error instanceof ApiError && error.code === ERROR_CODES.SESSION_EXPIRED) {
        state.uid = null;
        state.sessionMode = 'none';
      }
      throw error;
    }
  }

  async function sessionInfo() {
    if (!state.uid) throw new ApiError(ERROR_CODES.SESSION_REQUIRED, '尚未登录 Odoo。');
    const response = await transport.request({
      url: joinUrl(state.relayUrl, '/rpc'),
      method: 'POST',
      body: JSON.stringify(buildJsonRpcRequest({}, nextId())),
      headers: baseHeaders({ 'X-Lab-Path': '/web/session/get_session_info' }),
      timeoutMs: 30000,
    });
    return decodeOdooResult({ status: response.status, text: response.text, path: '/web/session/get_session_info' });
  }

  function toAssetRelayUrl(odooAssetUrl) {
    return joinUrl(state.relayUrl, '/asset?url=' + encodeURIComponent(odooAssetUrl));
  }

  async function asset(odooAssetUrl) {
    const response = await transport.requestBinary({
      url: toAssetRelayUrl(odooAssetUrl),
      method: 'GET',
      headers: { Authorization: 'Bearer ' + state.pairingToken, Accept: 'image/*' },
    });
    return response;
  }

  function publicSession() {
    return {
      active: Boolean(state.uid),
      uid: state.uid,
      name: state.name,
      username: state.username,
      db: state.db,
      sessionMode: state.sessionMode,
      lastLoginAt: state.lastLoginAt,
    };
  }

  function getConfig() {
    return { serverUrl: state.serverUrl, db: state.db, login: state.login };
  }

  function updateConfig(config) {
    state.serverUrl = config.serverUrl;
    state.db = config.db || '';
    state.login = config.login || '';
  }

  return {
    authenticate,
    logout,
    sessionInfo,
    call,
    asset,
    toAssetRelayUrl,
    publicSession,
    getConfig,
    updateConfig,
    mode: 'relay',
    get relayUrl() {
      return state.relayUrl;
    },
    get hasPairingToken() {
      return Boolean(state.pairingToken);
    },
  };
}
