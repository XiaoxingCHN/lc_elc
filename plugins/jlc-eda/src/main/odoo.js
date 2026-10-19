/**
 * Direct Odoo 19 session client (advanced fallback; relay is the default).
 *
 * Odoo 19 reads the session exclusively from the `session_id` cookie. The
 * authenticate JSON does not contain session_id. Browser-like fetch contexts
 * cannot read Set-Cookie or set Cookie. We therefore do NOT attempt a Cookie
 * header: after login we probe /web/session/get_session_info and fail loudly
 * if the SDK did not retain the cookie. The loopback relay is the supported
 * route for production use.
 */

import { ApiError, ERROR_CODES, buildJsonRpcRequest, decodeOdooResponse, decodeOdooResult, requestId } from '../shared/jsonrpc.js';
import { joinUrl } from './transport.js';

export function createOdooClient(options) {
  const config = options.config || {};
  const transport = options.transport;
  const logger = options.logger;
  const now = options.now || (() => Date.now());
  const state = {
    baseUrl: config.serverUrl,
    db: config.db || '',
    login: config.login || '',
    uid: null,
    name: '',
    username: '',
    sessionMode: 'none',
    lastLoginAt: null,
  };
  let sequence = 0;

  function nextId() {
    sequence += 1;
    return requestId('lab-' + sequence);
  }

  function requireTransport() {
    if (!transport || typeof transport.request !== 'function') {
      throw new ApiError(ERROR_CODES.EXTERNAL_INTERACTION_DISABLED, 'EDA 网络接口未配置。');
    }
  }

  function sessionHeaders() {
    return { 'Content-Type': 'application/json', Accept: 'application/json' };
  }

  function requireSession() {
    if (!state.uid) {
      throw new ApiError(ERROR_CODES.SESSION_REQUIRED, '尚未登录 Odoo，请先连接本机桥接或直接登录。', {
        action: 'login',
      });
    }
  }

  async function rawRpc(path, params, options = {}) {
    requireTransport();
    const requiresSession = options.session !== false;
    if (requiresSession) requireSession();
    const body = JSON.stringify(buildJsonRpcRequest(params || {}, nextId()));
    const url = joinUrl(state.baseUrl, path);
    const response = await transport.request({ url, method: 'POST', body, headers: sessionHeaders() });
    let data;
    try {
      data = options.standard
        ? decodeOdooResult(
            { status: response.status, text: response.text, path },
            { allowMissingResult: path === '/web/session/destroy' },
          )
        : decodeOdooResponse({ status: response.status, text: response.text, path });
    } catch (error) {
      if (error instanceof ApiError && error.code === ERROR_CODES.SESSION_EXPIRED) {
        state.uid = null;
        state.sessionMode = 'none';
      }
      throw error;
    }
    return { data, response, at: now() };
  }

  async function authenticate(input) {
    const db = String((input && input.db) || '').trim();
    const login = String((input && input.login) || '').trim();
    const password = String((input && input.password) || '');
    if (!db) throw new ApiError(ERROR_CODES.CONFIG, '请填写 Odoo 数据库名。', { fields: { db: 'required' } });
    if (!login) throw new ApiError(ERROR_CODES.CONFIG, '请填写 Odoo 登录名。', { fields: { login: 'required' } });
    if (!password) {
      throw new ApiError(ERROR_CODES.CONFIG, '请填写 Odoo 密码。密码只用于本次登录，不会保存。', {
        fields: { password: 'required' },
      });
    }

    state.db = db;
    state.login = login;
    state.uid = null;
    state.name = '';
    state.username = '';
    state.sessionMode = 'none';

    let first;
    try {
      first = await rawRpc(
        '/web/session/authenticate',
        { db, login, password },
        { session: false, standard: true },
      );
    } catch (error) {
      if (error instanceof ApiError && error.code === ERROR_CODES.FORBIDDEN) {
        throw new ApiError(ERROR_CODES.INVALID_CREDENTIALS, '登录失败：用户名、密码或数据库不正确。', {
          action: 'check_credentials',
        });
      }
      throw error;
    }
    const info = first.data || {};
    if (!info.uid) {
      throw new ApiError(
        ERROR_CODES.INVALID_CREDENTIALS,
        '登录失败：Odoo 未返回用户 ID。请检查数据库名、登录名、密码；若账号启用了两步验证（MFA），请先在 Odoo 网页端处理。',
        { action: 'check_credentials' },
      );
    }

    state.uid = Number(info.uid);
    state.name = String(info.name || info.display_name || '');
    state.username = String(info.username || login);
    state.db = String(info.db || db);

    // Critical probe: if the SDK does not retain the cookie, later calls are
    // anonymous. Report that instead of showing an empty catalogue.
    let probe;
    try {
      probe = await rawRpc('/web/session/get_session_info', {}, { standard: true });
    } catch (error) {
      state.uid = null;
      state.sessionMode = 'none';
      if (error instanceof ApiError && error.code === ERROR_CODES.SESSION_EXPIRED) {
        throw new ApiError(
          ERROR_CODES.SESSION_COOKIE_UNAVAILABLE,
          'Odoo 已接受账号密码，但 EDA 网络层没有保留会话 Cookie。请改用默认的「本机桥接」，或由管理员确认 EDA 客户端保留 session_id Cookie。',
          { action: 'use_relay', cause: error },
        );
      }
      throw error;
    }
    const probeInfo = probe.data || {};
    if (!probeInfo.uid || Number(probeInfo.uid) !== state.uid) {
      state.uid = null;
      state.sessionMode = 'none';
      throw new ApiError(
        ERROR_CODES.SESSION_COOKIE_UNAVAILABLE,
        '登录后会话探测失败：Odoo 返回的 uid 与登录用户不一致，会话 Cookie 未被保留。请改用默认的「本机桥接」。',
        { action: 'use_relay' },
      );
    }

    state.sessionMode = 'cookie-jar';
    state.lastLoginAt = now();
    if (logger) logger.info('session.login_ok', { uid: state.uid, db: state.db, sessionMode: state.sessionMode });
    return publicSession();
  }

  async function logout() {
    const wasActive = Boolean(state.uid);
    let warning = '';
    if (wasActive) {
      try {
        await rawRpc('/web/session/destroy', {}, { standard: true });
      } catch (error) {
        warning = 'Odoo 注销接口调用失败，已清除本地会话：' + String(error && error.message);
        if (logger) logger.warn('session.logout_warning', { code: error && error.code });
      }
    }
    state.uid = null;
    state.name = '';
    state.username = '';
    state.sessionMode = 'none';
    if (logger) logger.info('session.logout', { wasActive });
    return { ok: true, warning };
  }

  async function sessionInfo() {
    requireSession();
    const result = await rawRpc('/web/session/get_session_info', {}, { standard: true });
    return result.data || {};
  }

  async function businessCall(path, params) {
    requireSession();
    const result = await rawRpc(path, params || {}, { standard: false });
    return result.data;
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
    return { serverUrl: state.baseUrl, db: state.db, login: state.login };
  }

  function updateConfig(config) {
    state.baseUrl = config.serverUrl;
    state.db = config.db || '';
    state.login = config.login || '';
  }

  return {
    authenticate,
    logout,
    sessionInfo,
    call: businessCall,
    publicSession,
    getConfig,
    updateConfig,
    mode: 'direct',
  };
}
