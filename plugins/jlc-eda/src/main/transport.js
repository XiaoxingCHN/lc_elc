/**
 * HTTP transport backed by eda.sys_ClientUrl.request.
 *
 * The SDK returns a fetch Response and documents that CORS must be allowed
 * by the target site; cookie persistence is not documented. We therefore
 * surface transport failures as typed errors and let OdooClient probe the
 * session rather than assuming success.
 */

import { ApiError, ERROR_CODES } from '../shared/jsonrpc.js';
import { resolveEda } from './eda.js';

export function joinUrl(baseUrl, path) {
  const base = String(baseUrl || '').replace(/\/+$/, '');
  const suffix = String(path || '').startsWith('/') ? path : '/' + path;
  return base + suffix;
}

function isAbortLike(error) {
  const message = String((error && error.message) || error || '');
  return /timeout|timed out|aborted|abort/i.test(message);
}

function isCorsOrNetwork(error) {
  const message = String((error && error.message) || error || '');
  return /cors|cross-origin|failed to fetch|networkerror|network error|load failed|fetch failed|net::|connection|socket|dns|econn/i.test(
    message,
  );
}

function isExternalInteraction(error) {
  const message = String((error && error.message) || error || '');
  return /external interaction|外部交互|permission|not allowed|forbidden by extension/i.test(message);
}

export function classifyTransportError(error, options = {}) {
  if (error instanceof ApiError) return error;
  const method = String(options.method || 'POST').toUpperCase();
  const mayHaveBeenSent = method !== 'GET' && method !== 'HEAD';
  if (isExternalInteraction(error)) {
    return new ApiError(
      ERROR_CODES.EXTERNAL_INTERACTION_DISABLED,
      '扩展未获得「外部交互」权限，无法访问 Odoo。请在 EDA 扩展管理器中启用该权限后重试。',
      { action: 'enable_external_interaction', cause: error },
    );
  }
  if (isAbortLike(error)) {
    return new ApiError(
      ERROR_CODES.TIMEOUT_AMBIGUOUS,
      '请求超时。若这是入库/领用/归还，请求可能已经送达服务器；请先用同一请求号重试，服务器会按幂等键返回原结果。',
      { retryable: true, mayHaveBeenSent, action: 'retry_same_request', cause: error },
    );
  }
  if (isCorsOrNetwork(error)) {
    return new ApiError(
      ERROR_CODES.NETWORK_OR_CORS,
      '网络请求失败：可能是地址/端口错误，或 Odoo 未允许 EDA 来源跨域（CORS）。请检查服务器地址；CORS 需由服务器/反向代理配置。',
      { retryable: true, mayHaveBeenSent, action: 'check_network_cors', cause: error },
    );
  }
  return new ApiError(ERROR_CODES.NETWORK, '网络请求失败：' + String((error && error.message) || error), {
    retryable: true,
    mayHaveBeenSent,
    cause: error,
  });
}

export function readHeader(response, name) {
  try {
    if (!response || !response.headers || typeof response.headers.get !== 'function') return null;
    return response.headers.get(name);
  } catch (_) {
    return null;
  }
}

export function createSdkTransport(options = {}) {
  const eda = options.eda || resolveEda();
  const logger = options.logger;
  const timeoutMs = Number(options.timeoutMs) || 20000;
  const now = options.now || (() => Date.now());

  function clientUrl() {
    const api = eda && eda.sys_ClientUrl;
    if (!api || typeof api.request !== 'function') {
      throw new ApiError(
        ERROR_CODES.EXTERNAL_INTERACTION_DISABLED,
        'EDA 网络接口不可用（sys_ClientUrl）。请确认扩展已启用外部交互权限。',
        { action: 'enable_external_interaction' },
      );
    }
    return api;
  }

  async function withTimeout(promise, method, url, effectiveTimeoutMs) {
    let timer;
    try {
      return await Promise.race([
        promise,
        new Promise((_, reject) => {
          timer = setTimeout(() => {
            reject(
              new ApiError(
                ERROR_CODES.TIMEOUT_AMBIGUOUS,
                '请求超时（' + effectiveTimeoutMs + 'ms）：' + method + ' ' + url,
                {
                  retryable: true,
                  mayHaveBeenSent: method !== 'GET' && method !== 'HEAD',
                  action: 'retry_same_request',
                },
              ),
            );
          }, effectiveTimeoutMs);
        }),
      ]);
    } finally {
      if (timer) clearTimeout(timer);
    }
  }

  async function request(input) {
    const method = String(input.method || 'POST').toUpperCase();
    const url = input.url;
    const headers = Object.assign({ Accept: 'application/json' }, input.headers || {});
    const data = input.body === undefined || input.body === null ? undefined : input.body;
    const started = now();
    const perRequestTimeout = Number(input.timeoutMs) || timeoutMs;
    if (logger) logger.debug('http.request', { method, url, headerNames: Object.keys(headers) });
    let response;
    try {
      response = await withTimeout(clientUrl().request(url, method, data, { headers }), method, url, perRequestTimeout);
    } catch (error) {
      const classified = classifyTransportError(error, { method });
      if (logger) {
        logger.error('http.failed', {
          method,
          url,
          code: classified.code,
          message: classified.message,
        });
      }
      throw classified;
    }
    let text = '';
    try {
      text = typeof response.text === 'function' ? await response.text() : '';
    } catch (error) {
      throw new ApiError(ERROR_CODES.PARSE, '读取服务器响应失败：' + String(error && error.message), {
        cause: error,
      });
    }
    const result = {
      status: Number(response.status) || 0,
      ok: Boolean(response.ok),
      text,
      contentType: readHeader(response, 'content-type') || '',
      setCookie: readHeader(response, 'set-cookie') || '',
      url,
      method,
      durationMs: now() - started,
    };
    if (logger) {
      logger.info('http.response', {
        method,
        url,
        status: result.status,
        bytes: text.length,
        durationMs: result.durationMs,
      });
    }
    return result;
  }

  async function requestBinary(input) {
    const method = String(input.method || 'GET').toUpperCase();
    const url = input.url;
    const headers = Object.assign({}, input.headers || {});
    let response;
    try {
      response = await withTimeout(
        clientUrl().request(url, method, undefined, { headers }),
        method,
        url,
        Number(input.timeoutMs) || timeoutMs,
      );
    } catch (error) {
      throw classifyTransportError(error, { method });
    }
    if (!response || !response.ok) {
      throw new ApiError(ERROR_CODES.HTTP, '资源请求失败（HTTP ' + (response && response.status) + '）。', {
        httpStatus: response && response.status,
      });
    }
    const contentType = readHeader(response, 'content-type') || '';
    const buffer = typeof response.arrayBuffer === 'function' ? await response.arrayBuffer() : null;
    if (!buffer) {
      throw new ApiError(ERROR_CODES.PARSE, '当前 EDA 版本不支持读取二进制资源。');
    }
    return { buffer, contentType, status: Number(response.status) || 0 };
  }

  return { request, requestBinary, timeoutMs };
}
