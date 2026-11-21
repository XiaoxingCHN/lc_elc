/**
 * Odoo 19 客户端：``Authorization: bearer <EDA 密钥>``。
 *
 * 为什么不用 Cookie 会话
 * ----------------------
 * EDA 的 ``sys_ClientUrl.request()`` 的 ``options`` 只暴露 ``headers`` 和
 * ``integrity``，**没有 ``credentials``**；而 ``Cookie`` 是 Fetch 规范的
 * 禁止请求头，浏览器层面设不进去。所以 Cookie 会话在插件里物理上不可能。
 *
 * ``Authorization`` 不是禁止头，可以自由设置 —— 这也是 Odoo 19 官方推荐的
 * 无状态认证方式（``auth='bearer'``）。
 *
 * 密钥明文存在 sys_Storage，与浏览器保存密码同一水位；服务端可随时吊销。
 */

import { ApiError, ERROR_CODES, decodeOdooResponse, requestId } from '../shared/jsonrpc.js';
import { joinUrl } from './transport.js';

export function createOdooClient(options) {
  const config = options.config || {};
  const transport = options.transport;
  const logger = options.logger;
  const now = options.now || (() => Date.now());
  const state = {
    baseUrl: config.serverUrl,
    token: config.token || '',
    uid: null,
    name: '',
    username: '',
    lastLoginAt: null,
  };
  let sequence = 0;

  function nextId() {
    sequence += 1;
    return requestId('eda-' + sequence);
  }

  function requireTransport() {
    if (!transport || typeof transport.request !== 'function') {
      throw new ApiError(ERROR_CODES.EXTERNAL_INTERACTION_DISABLED, 'EDA 网络接口未配置。');
    }
  }

  function authHeaders() {
    if (!state.token) {
      throw new ApiError(ERROR_CODES.SESSION_REQUIRED,
        '尚未填写 EDA 密钥。请向库存管理员索取后填入「连接设置」。',
        { action: 'login' });
    }
    return {
      Authorization: 'bearer ' + state.token,
      'Content-Type': 'application/json',
      Accept: 'application/json',
    };
  }

  /** 调一个 ``/lab/api/eda/*`` 端点。 */
  async function call(path, params) {
    requireTransport();
    const body = JSON.stringify({
      jsonrpc: '2.0',
      id: nextId(),
      method: 'call',
      params: params || {},
    });
    const url = joinUrl(state.baseUrl, path);
    const response = await transport.request({
      url, method: 'POST', body, headers: authHeaders(),
    });
    let data;
    try {
      data = decodeOdooResponse({ status: response.status, text: response.text, path });
    } catch (error) {
      // decodeOdooResponse 已经把 {ok:false,error} 信封抛成 ApiError 了。
      // 这里只把「密钥问题」统一翻译成会话失效，让 UI 回到设置页；
      // 其余业务错误（FORBIDDEN 等）原样上抛。
      const code = String((error && error.code) || '');
      if (code === 'MISSING_TOKEN' || code === 'INVALID_TOKEN') {
        state.uid = null;
        throw new ApiError(ERROR_CODES.SESSION_EXPIRED,
          (error && error.message) || 'EDA 密钥无效、已过期或已吊销。',
          { action: 'login', code });
      }
      throw error;
    }
    return data && Object.prototype.hasOwnProperty.call(data, 'data') ? data.data : data;
  }

  /**
   * 用密钥换身份：调 ``/bootstrap``，成功就记住 uid/name。
   * 没有独立的「登录」步骤——密钥本身就是凭证。
   */
  async function connect() {
    const data = await call('/lab/api/eda/bootstrap', {});
    const user = (data && data.user) || {};
    state.uid = Number(user.id) || null;
    state.name = String(user.name || '');
    state.username = String(user.login || '');
    state.lastLoginAt = now();
    if (logger) logger.info('eda.connect_ok', { uid: state.uid });
    return publicSession();
  }

  function disconnect() {
    state.uid = null;
    state.name = '';
    state.username = '';
    if (logger) logger.info('eda.disconnect');
    return { ok: true };
  }

  function publicSession() {
    return {
      active: Boolean(state.uid),
      uid: state.uid,
      name: state.name,
      username: state.username,
      sessionMode: state.token ? 'bearer' : 'none',
      lastLoginAt: state.lastLoginAt,
    };
  }

  function getConfig() {
    return { serverUrl: state.baseUrl, token: state.token };
  }

  function updateConfig(next) {
    state.baseUrl = next.serverUrl;
    state.token = next.token || '';
  }

  return {
    connect,
    disconnect,
    call,
    publicSession,
    getConfig,
    updateConfig,
    mode: 'bearer',
  };
}
