/**
 * Odoo 19 JSON-RPC envelope decoding and a single error taxonomy.
 *
 * The Odoo controller returns a business envelope inside the JSON-RPC
 * result:
 *   { jsonrpc: "2.0", id, result: { ok: true,  data: {...}, error: null } }
 *   { jsonrpc: "2.0", id, result: { ok: false, data: null,  error: {...} } }
 * Transport/session failures use the JSON-RPC `error` member or an HTTP
 * status. We never turn a failure into empty/zero business data.
 */

export const ERROR_CODES = Object.freeze({
  CONFIG: 'CONFIG',
  NETWORK: 'NETWORK',
  NETWORK_OR_CORS: 'NETWORK_OR_CORS',
  TIMEOUT_AMBIGUOUS: 'TIMEOUT_AMBIGUOUS',
  HTTP: 'HTTP',
  PARSE: 'PARSE',
  UNEXPECTED_ENVELOPE: 'UNEXPECTED_ENVELOPE',
  SESSION_REQUIRED: 'SESSION_REQUIRED',
  SESSION_EXPIRED: 'SESSION_EXPIRED',
  SESSION_COOKIE_UNAVAILABLE: 'SESSION_COOKIE_UNAVAILABLE',
  INVALID_CREDENTIALS: 'INVALID_CREDENTIALS',
  EXTERNAL_INTERACTION_DISABLED: 'EXTERNAL_INTERACTION_DISABLED',
  RELAY_AUTH: 'RELAY_AUTH',
  RELAY_UNAVAILABLE: 'RELAY_UNAVAILABLE',
  FORBIDDEN: 'FORBIDDEN',
  VALIDATION_ERROR: 'VALIDATION_ERROR',
  NOT_FOUND: 'NOT_FOUND',
  CONFLICT: 'CONFLICT',
  AMBIGUOUS_MATERIAL: 'AMBIGUOUS_MATERIAL',
  INTERNAL_ERROR: 'INTERNAL_ERROR',
  EDA_CONTEXT: 'EDA_CONTEXT',
  BRIDGE: 'BRIDGE',
  UNKNOWN: 'UNKNOWN',
});

const SESSION_CODES = new Set([
  'SESSION_REQUIRED',
  'SESSION_EXPIRED',
  'UNAUTHORIZED',
  'AUTH_REQUIRED',
]);

const FORBIDDEN_CODES = new Set(['FORBIDDEN', 'ACCESS_DENIED', 'PERMISSION_DENIED']);

export class ApiError extends Error {
  constructor(code, message, options = {}) {
    super(message || code || '未知错误');
    this.name = 'ApiError';
    this.code = code || ERROR_CODES.UNKNOWN;
    this.fields = options.fields && typeof options.fields === 'object' ? options.fields : {};
    this.httpStatus = options.httpStatus || null;
    this.retryable = Boolean(options.retryable);
    this.mayHaveBeenSent = Boolean(options.mayHaveBeenSent);
    this.action = options.action || '';
    this.cause = options.cause;
  }

  toJSON() {
    return {
      name: 'ApiError',
      code: this.code,
      message: this.message,
      fields: this.fields,
      httpStatus: this.httpStatus,
      retryable: this.retryable,
      mayHaveBeenSent: this.mayHaveBeenSent,
      action: this.action,
    };
  }
}

export function isApiError(value) {
  return value instanceof ApiError;
}

export function requestId(prefix = 'lab') {
  const cryptoObj = globalThis.crypto;
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') {
    return prefix + '-' + cryptoObj.randomUUID();
  }
  return prefix + '-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10);
}

export function buildJsonRpcRequest(params, id = requestId()) {
  return { jsonrpc: '2.0', method: 'call', id, params: params && typeof params === 'object' ? params : {} };
}

function looksLikeLoginHtml(text) {
  if (!text) return false;
  const head = text.slice(0, 4096).toLowerCase();
  if (!head.includes('<html') && !head.includes('<!doctype')) return false;
  return /login|session|登录|odoo/.test(head);
}

function odooErrorName(error) {
  const data = error && error.data;
  if (!data || typeof data !== 'object') return '';
  return String(data.name || data.type || '');
}

function mapOdooRpcError(error, httpStatus) {
  const name = odooErrorName(error);
  const message = String(
    (error && (error.message || (error.data && (error.data.message || error.data.debug)))) || 'Odoo 请求失败',
  );
  const numericCode = Number(error && error.code);
  if (numericCode === 100 || /SessionExpiredException/i.test(name) || /session expired/i.test(message)) {
    return new ApiError(ERROR_CODES.SESSION_EXPIRED, 'Odoo 会话已失效，请重新登录。', {
      httpStatus,
      action: 'relogin',
    });
  }
  if (/AccessError|AccessDenied|SecurityError/i.test(name)) {
    return new ApiError(ERROR_CODES.FORBIDDEN, message || '当前账号没有执行该操作的权限。', {
      httpStatus,
      action: 'contact_admin',
    });
  }
  if (/ValidationError|UserError/i.test(name)) {
    return new ApiError(ERROR_CODES.VALIDATION_ERROR, message, { httpStatus });
  }
  return new ApiError(httpStatus >= 500 ? ERROR_CODES.INTERNAL_ERROR : ERROR_CODES.UNKNOWN, message, {
    httpStatus,
  });
}

function mapEnvelopeError(error, httpStatus) {
  const code = String((error && error.code) || ERROR_CODES.UNKNOWN).toUpperCase();
  const message = String((error && error.message) || '服务器返回业务错误');
  if (SESSION_CODES.has(code)) {
    return new ApiError(ERROR_CODES.SESSION_EXPIRED, message, { httpStatus, action: 'relogin' });
  }
  if (FORBIDDEN_CODES.has(code)) {
    return new ApiError(ERROR_CODES.FORBIDDEN, message, { httpStatus, action: 'contact_admin' });
  }
  if (code === 'AMBIGUOUS_MATERIAL') {
    return new ApiError(ERROR_CODES.AMBIGUOUS_MATERIAL, message, {
      httpStatus,
      fields: error.fields || {},
      action: 'choose_material',
    });
  }
  if (code === 'CONFLICT') {
    return new ApiError(ERROR_CODES.CONFLICT, message, {
      httpStatus,
      fields: error.fields || {},
      action: 'new_request_key',
    });
  }
  if (code === 'VALIDATION_ERROR') {
    return new ApiError(ERROR_CODES.VALIDATION_ERROR, message, { httpStatus, fields: error.fields || {} });
  }
  if (code === 'NOT_FOUND') {
    return new ApiError(ERROR_CODES.NOT_FOUND, message, { httpStatus, fields: error.fields || {} });
  }
  if (code === 'INTERNAL_ERROR') {
    return new ApiError(ERROR_CODES.INTERNAL_ERROR, message, { httpStatus, fields: error.fields || {} });
  }
  return new ApiError(code || ERROR_CODES.UNKNOWN, message, { httpStatus, fields: error.fields || {} });
}

/**
 * Decode one HTTP response.
 * @param {{status:number, text:string, path?:string, contentType?:string}} input
 * @returns {any} the business `data` object
 */
export function decodeOdooResponse(input) {
  const status = Number(input.status) || 0;
  const text = typeof input.text === 'string' ? input.text : '';
  const path = input.path || '';
  let body;
  try {
    body = text ? JSON.parse(text) : null;
  } catch (_) {
    if (status === 401 || status === 403) {
      throw new ApiError(
        status === 401 ? ERROR_CODES.SESSION_EXPIRED : ERROR_CODES.FORBIDDEN,
        status === 401 ? 'Odoo 会话已失效，请重新登录。' : '当前账号没有访问权限。',
        { httpStatus: status, action: status === 401 ? 'relogin' : 'contact_admin' },
      );
    }
    if (looksLikeLoginHtml(text)) {
      throw new ApiError(ERROR_CODES.SESSION_EXPIRED, '服务器返回了登录页而不是接口数据，会话已失效。', {
        httpStatus: status,
        action: 'relogin',
      });
    }
    throw new ApiError(
      status >= 500 ? ERROR_CODES.HTTP : ERROR_CODES.PARSE,
      status >= 500
        ? '服务器返回 HTTP ' + status + '，接口内容不是 JSON。'
        : '接口返回不是合法 JSON（' + path + '），请检查服务器地址与数据库。',
      { httpStatus: status },
    );
  }

  if (!body || typeof body !== 'object') {
    throw new ApiError(ERROR_CODES.UNEXPECTED_ENVELOPE, 'Odoo 返回了空或非对象响应（' + path + '）。', {
      httpStatus: status,
    });
  }

  if (body.error) {
    throw mapOdooRpcError(body.error, status);
  }

  if (!Object.prototype.hasOwnProperty.call(body, 'result')) {
    throw new ApiError(ERROR_CODES.UNEXPECTED_ENVELOPE, 'Odoo 响应缺少 result/error（' + path + '）。', {
      httpStatus: status,
    });
  }

  const result = body.result;
  if (!result || typeof result !== 'object' || Array.isArray(result)) {
    throw new ApiError(ERROR_CODES.UNEXPECTED_ENVELOPE, '接口 result 不是业务信封（' + path + '）。', {
      httpStatus: status,
    });
  }
  if (result.ok === false) {
    throw mapEnvelopeError(result.error || {}, status);
  }
  if (result.ok !== true) {
    throw new ApiError(ERROR_CODES.UNEXPECTED_ENVELOPE, '业务信封缺少 ok 标记（' + path + '）。', {
      httpStatus: status,
    });
  }
  return result.data === undefined ? {} : result.data;
}

/**
 * Decode a standard Odoo JSON-RPC response (no `{ok,data,error}` business
 * envelope), e.g. /web/session/authenticate and /web/session/get_session_info.
 */
export function decodeOdooResult(input, options = {}) {
  const status = Number(input.status) || 0;
  const text = typeof input.text === 'string' ? input.text : '';
  const path = input.path || '';
  let body;
  try {
    body = text ? JSON.parse(text) : null;
  } catch (_) {
    if (status === 401 || status === 403) {
      throw new ApiError(
        status === 401 ? ERROR_CODES.SESSION_EXPIRED : ERROR_CODES.FORBIDDEN,
        status === 401 ? 'Odoo 会话已失效，请重新登录。' : '当前账号没有访问权限。',
        { httpStatus: status, action: status === 401 ? 'relogin' : 'contact_admin' },
      );
    }
    if (looksLikeLoginHtml(text)) {
      throw new ApiError(ERROR_CODES.SESSION_EXPIRED, '服务器返回了登录页而不是接口数据，会话已失效。', {
        httpStatus: status,
        action: 'relogin',
      });
    }
    throw new ApiError(ERROR_CODES.PARSE, '接口返回不是合法 JSON（' + path + '）。', { httpStatus: status });
  }
  if (!body || typeof body !== 'object') {
    throw new ApiError(ERROR_CODES.UNEXPECTED_ENVELOPE, 'Odoo 返回了空响应（' + path + '）。', {
      httpStatus: status,
    });
  }
  if (body.error) throw mapOdooRpcError(body.error, status);
  if (!Object.prototype.hasOwnProperty.call(body, 'result')) {
    if (options.allowMissingResult) return null;
    throw new ApiError(ERROR_CODES.UNEXPECTED_ENVELOPE, 'Odoo 响应缺少 result/error（' + path + '）。', {
      httpStatus: status,
    });
  }
  return body.result;
}

export function serializeApiError(error) {
  if (error instanceof ApiError) return error.toJSON();
  const message = error && error.message ? String(error.message) : String(error || '未知错误');
  return {
    name: 'ApiError',
    code: ERROR_CODES.UNKNOWN,
    message,
    fields: {},
    httpStatus: null,
    retryable: false,
    mayHaveBeenSent: false,
    action: '',
  };
}
