#!/usr/bin/env node
/**
 * Lab Odoo Relay 3.0.0 — zero-dependency loopback relay.
 *
 * Why this exists
 * ---------------
 * EDA's sys_ClientUrl.request is a fetch-like API. Its documented options do
 * not include `credentials`, and Set-Cookie / Cookie are not controllable
 * from that context. Odoo 19 authenticates JSON-RPC `auth='user'` routes only
 * through the session_id cookie. This relay is a native Node HTTP client that
 * owns the Odoo cookie jar, so the EDA extension can use a small bearer token
 * and never depends on browser cookie rules.
 *
 * Security model
 * --------------
 * - bind 127.0.0.1 only (no 0.0.0.0, no LAN);
 * - random pairing token generated at startup, required on login/rpc/logout/
 *   asset; token lives in process memory and is printed once;
 * - fixed upstream (CLI default http://lc.rm.com) and fixed database
 *   (LcHardwareHouse); request bodies cannot select another URL;
 * - fixed endpoint allow-list; no open proxy, no redirect following;
 * - body/response size limits and upstream timeouts;
 * - upstream session cookie stays inside this process and is never returned
 *   to the EDA extension;
 * - password only exists in the login request body, is never logged or
 *   persisted; cookies are memory-only;
 * - CORS is `*` without credentials because the relay uses an Authorization
 *   header, not cookies, towards the browser context.
 */

import http from 'node:http';
import https from 'node:https';
import crypto from 'node:crypto';
import process from 'node:process';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

export const SERVICE = 'lab-odoo-relay';
export const DEFAULT_HOST = '127.0.0.1';
export const DEFAULT_PORT = 49621;
export const DEFAULT_UPSTREAM = 'http://lc.rm.com';
export const DEFAULT_DB = 'LcHardwareHouse';

const MAX_LOGIN_BODY = 16 * 1024;
const MAX_RPC_BODY = 256 * 1024;
const MAX_JSON_RESPONSE = 8 * 1024 * 1024;
const MAX_ASSET_RESPONSE = 5 * 1024 * 1024;
const RPC_TIMEOUT_MS = 20 * 1000;
const ASSET_TIMEOUT_MS = 30 * 1000;

/** Exact upstream paths the relay is willing to touch. */
export const ALLOWED_RPC_PATHS = Object.freeze([
  '/lab/api/catalog/search',
  '/lab/api/catalog/detail',
  '/lab/api/catalog/categories',
  '/lab/api/catalog/facets',
  '/lab/api/inventory/bootstrap',
  '/lab/api/inventory/locations',
  '/lab/api/inventory/resolve_code',
  '/lab/api/inventory/receipt',
  '/lab/api/inventory/issue',
  '/lab/api/inventory/return',
  '/lab/api/inventory/issues',
  '/lab/api/inventory/history',
  '/web/session/get_session_info',
]);

const ALLOWED_RPC = new Set(ALLOWED_RPC_PATHS);

class CookieJar {
  constructor() {
    this.cookies = new Map();
  }

  absorb(setCookie) {
    if (!setCookie) return;
    const list = Array.isArray(setCookie) ? setCookie : [setCookie];
    for (const line of list) {
      const text = String(line || '');
      const first = text.split(';', 1)[0];
      const index = first.indexOf('=');
      if (index <= 0) continue;
      const name = first.slice(0, index).trim();
      const value = first.slice(index + 1).trim();
      if (!name) continue;
      if (/^deleted$/i.test(value) || value === '') this.cookies.delete(name);
      else this.cookies.set(name, value);
    }
  }

  header() {
    if (!this.cookies.size) return '';
    return Array.from(this.cookies.entries())
      .map(([name, value]) => name + '=' + value)
      .join('; ');
  }

  clear() {
    this.cookies.clear();
  }

  get size() {
    return this.cookies.size;
  }
}

function isLoopback(address) {
  const text = String(address || '');
  return text === '127.0.0.1' || text === '::1' || text === '::ffff:127.0.0.1';
}

function nowMs() {
  return Number(process.hrtime.bigint() / 1000000n);
}

function safeError(code, message) {
  return { ok: false, data: null, error: { code, message } };
}

function setCors(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type, X-Lab-Path');
  res.setHeader('Access-Control-Max-Age', '600');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  if (String(req.headers['access-control-request-private-network'] || '').toLowerCase() === 'true') {
    res.setHeader('Access-Control-Allow-Private-Network', 'true');
  }
}

function sendJson(req, res, status, payload) {
  setCors(req, res);
  const body = Buffer.from(JSON.stringify(payload), 'utf8');
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Content-Length', String(body.length));
  res.end(body);
}

function sendEmpty(req, res, status) {
  setCors(req, res);
  res.statusCode = status;
  res.end();
}

function readBody(req, limit) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > limit) {
        reject(Object.assign(new Error('请求体过大'), { code: 'BODY_TOO_LARGE' }));
        req.removeAllListeners('data');
        req.resume();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', (error) => reject(Object.assign(error, { code: 'REQUEST_ABORTED' })));
  });
}

function readBearer(req) {
  const value = String(req.headers.authorization || '');
  const match = /^Bearer\s+(.+)$/i.exec(value);
  return match ? match[1].trim() : '';
}

function tokenMatches(provided, expected) {
  const a = Buffer.from(String(provided || ''), 'utf8');
  const b = Buffer.from(String(expected || ''), 'utf8');
  if (a.length === 0 || a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

function parseJson(buffer) {
  if (!buffer || buffer.length === 0) return null;
  try {
    return JSON.parse(buffer.toString('utf8'));
  } catch (error) {
    throw Object.assign(new Error('上游返回不是 JSON'), { code: 'UPSTREAM_INVALID_JSON', cause: error });
  }
}

function upstreamRequest(options) {
  const {
    upstream,
    method,
    path,
    body,
    headers = {},
    timeoutMs,
    maxResponseBytes,
    jar,
  } = options;
  const base = new URL(upstream);
  const target = new URL(path, base);
  if (target.origin !== base.origin) {
    return Promise.reject(Object.assign(new Error('upstream origin mismatch'), { code: 'UPSTREAM_ORIGIN' }));
  }
  const isHttps = target.protocol === 'https:';
  const transport = isHttps ? https : http;
  const cookie = jar ? jar.header() : '';
  const finalHeaders = Object.assign(
    {
      Accept: 'application/json, image/*',
      'User-Agent': 'lab-odoo-relay/3.0.0',
    },
    headers,
  );
  if (cookie) finalHeaders.Cookie = cookie;
  if (body !== undefined && body !== null) finalHeaders['Content-Length'] = String(Buffer.byteLength(body));
  return new Promise((resolve, reject) => {
    const request = transport.request(
      {
        protocol: target.protocol,
        hostname: target.hostname,
        port: target.port || (isHttps ? 443 : 80),
        path: target.pathname + target.search,
        method,
        headers: finalHeaders,
        timeout: timeoutMs,
      },
      (response) => {
        if (jar && response.headers['set-cookie']) jar.absorb(response.headers['set-cookie']);
        if (response.statusCode >= 300 && response.statusCode < 400) {
          response.resume();
          reject(Object.assign(new Error('上游返回重定向，已拒绝跟随'), { code: 'UPSTREAM_REDIRECT' }));
          return;
        }
        const chunks = [];
        let size = 0;
        response.on('data', (chunk) => {
          size += chunk.length;
          if (size > maxResponseBytes) {
            reject(Object.assign(new Error('上游响应过大'), { code: 'UPSTREAM_RESPONSE_TOO_LARGE' }));
            response.destroy();
            return;
          }
          chunks.push(chunk);
        });
        response.on('end', () => {
          resolve({
            status: Number(response.statusCode) || 0,
            headers: response.headers,
            body: Buffer.concat(chunks),
          });
        });
        response.on('error', (error) => reject(Object.assign(error, { code: 'UPSTREAM_READ_FAILED' })));
      },
    );
    request.on('timeout', () => {
      request.destroy(Object.assign(new Error('上游请求超时'), { code: 'UPSTREAM_TIMEOUT' }));
    });
    request.on('error', (error) => {
      reject(
        Object.assign(error, {
          code: error.code === 'ECONNREFUSED' ? 'UPSTREAM_REFUSED' : error.code || 'UPSTREAM_FAILED',
        }),
      );
    });
    if (body !== undefined && body !== null) request.write(body);
    request.end();
  });
}

function mapUpstreamError(error) {
  const code = String((error && error.code) || 'UPSTREAM_FAILED');
  const messages = {
    UPSTREAM_TIMEOUT: '库存连接超时，请确认 Odoo 可访问。',
    UPSTREAM_REFUSED: '无法连接 Odoo，请确认地址与网络。',
    UPSTREAM_REDIRECT: 'Odoo 返回了重定向，relay 已拒绝跟随。',
    UPSTREAM_INVALID_JSON: 'Odoo 返回内容不是 JSON。',
    UPSTREAM_RESPONSE_TOO_LARGE: 'Odoo 响应过大，已停止读取。',
    UPSTREAM_FAILED: '连接 Odoo 失败。',
  };
  return { code, message: messages[code] || '连接 Odoo 失败。' };
}

function normalizePath(raw) {
  const path = String(raw || '').trim();
  if (!path.startsWith('/')) return '';
  if (path.includes('?') || path.includes('#')) return '';
  return path;
}

function jsonRpcError(id, code, message) {
  return { jsonrpc: '2.0', id: id === undefined ? null : id, error: { code, message } };
}

export function createRelayServer(options = {}) {
  const upstream = String(options.upstream || DEFAULT_UPSTREAM).replace(/\/+$/, '');
  const db = String(options.db || DEFAULT_DB);
  const host = String(options.host || DEFAULT_HOST);
  const port = Number.isInteger(options.port) ? options.port : DEFAULT_PORT;
  const token = String(options.token || crypto.randomBytes(32).toString('base64url'));
  const logger = options.logger || console;
  const jar = new CookieJar();
  let sequence = 0;

  if (host !== DEFAULT_HOST) throw new Error('relay 只能绑定 127.0.0.1');

  function log(event, fields = {}) {
    if (!logger || typeof logger.log !== 'function') return;
    try {
      logger.log('[relay]', event, JSON.stringify(fields));
    } catch (_) {
      /* logging must never break the relay */
    }
  }

  function requireToken(req, res) {
    if (!tokenMatches(readBearer(req), token)) {
      sendJson(req, res, 401, safeError('RELAY_AUTH', '配对码无效，请从 relay 启动窗口重新复制。'));
      return false;
    }
    return true;
  }

  async function handleLogin(req, res) {
    if (!requireToken(req, res)) return;
    let body;
    try {
      body = parseJson(await readBody(req, MAX_LOGIN_BODY)) || {};
    } catch (error) {
      sendJson(req, res, error.code === 'BODY_TOO_LARGE' ? 413 : 400,
        safeError(error.code || 'BAD_REQUEST', error.code === 'BODY_TOO_LARGE' ? '登录请求过大。' : '登录请求格式错误。'));
      return;
    }
    const login = String(body.login || '').trim();
    const password = String(body.password || '');
    if (!login || !password) {
      sendJson(req, res, 400, safeError('VALIDATION_ERROR', '请填写登录名和密码。'));
      return;
    }
    jar.clear();
    const id = 'relay-login-' + ++sequence;
    const rpc = {
      jsonrpc: '2.0',
      id,
      method: 'call',
      params: { db, login, password },
    };
    try {
      const result = await upstreamRequest({
        upstream,
        method: 'POST',
        path: '/web/session/authenticate',
        body: JSON.stringify(rpc),
        headers: { 'Content-Type': 'application/json' },
        timeoutMs: RPC_TIMEOUT_MS,
        maxResponseBytes: MAX_JSON_RESPONSE,
        jar,
      });
      const parsed = parseJson(result.body);
      if (parsed && parsed.error) {
        const message = String(parsed.error.message || parsed.error.data?.message || '登录失败。');
        sendJson(req, res, 200, safeError('INVALID_CREDENTIALS', message));
        return;
      }
      const info = parsed && parsed.result;
      if (!info || !info.uid) {
        sendJson(req, res, 200, safeError('INVALID_CREDENTIALS', '登录失败：账号、密码或数据库不正确。'));
        return;
      }
      // Never return session_id or Set-Cookie to the EDA context.
      sendJson(req, res, 200, {
        ok: true,
        data: {
          uid: Number(info.uid),
          name: String(info.name || info.display_name || ''),
          username: String(info.username || login),
          db: String(info.db || db),
          sessionMode: 'relay',
        },
        error: null,
      });
      log('login.ok', { uid: Number(info.uid), db });
    } catch (error) {
      const mapped = mapUpstreamError(error);
      sendJson(req, res, 502, safeError(mapped.code, mapped.message));
      log('login.failed', { code: mapped.code });
    }
  }

  async function handleRpc(req, res) {
    if (!requireToken(req, res)) return;
    const path = normalizePath(req.headers['x-lab-path']);
    if (!path || !ALLOWED_RPC.has(path)) {
      sendJson(req, res, 403, safeError('PATH_NOT_ALLOWED', '该接口不在 relay 允许列表中。'));
      return;
    }
    let raw;
    try {
      raw = await readBody(req, MAX_RPC_BODY);
    } catch (error) {
      sendJson(req, res, error.code === 'BODY_TOO_LARGE' ? 413 : 400,
        safeError(error.code || 'BAD_REQUEST', error.code === 'BODY_TOO_LARGE' ? '请求过大。' : '请求格式错误。'));
      return;
    }
    let parsedBody;
    try {
      parsedBody = parseJson(raw);
    } catch (_) {
      sendJson(req, res, 400, safeError('BAD_REQUEST', '请求必须是合法 JSON-RPC 对象。'));
      return;
    }
    if (!parsedBody || typeof parsedBody !== 'object') {
      sendJson(req, res, 400, safeError('BAD_REQUEST', '请求必须是 JSON-RPC 对象。'));
      return;
    }
    try {
      const result = await upstreamRequest({
        upstream,
        method: 'POST',
        path,
        body: raw,
        headers: { 'Content-Type': 'application/json' },
        timeoutMs: RPC_TIMEOUT_MS,
        maxResponseBytes: MAX_JSON_RESPONSE,
        jar,
      });
      if (result.status === 401 || result.status === 403) {
        let upstreamJson = null;
        try {
          upstreamJson = JSON.parse(result.body.toString('utf8'));
        } catch (_) {
          upstreamJson = null;
        }
        if (!upstreamJson || (!upstreamJson.result && !upstreamJson.error)) {
          sendJson(req, res, result.status, jsonRpcError(parsedBody.id, 100, 'Odoo 会话已失效，请重新登录。'));
          log('rpc.session_expired', { path, status: result.status });
          return;
        }
      }
      setCors(req, res);
      res.statusCode = result.status;
      res.setHeader('Content-Type', 'application/json; charset=utf-8');
      res.setHeader('Content-Length', String(result.body.length));
      res.end(result.body);
      log('rpc', { path, status: result.status, bytes: result.body.length });
    } catch (error) {
      const mapped = mapUpstreamError(error);
      sendJson(req, res, 502, jsonRpcError(parsedBody.id, -32000, mapped.message));
      log('rpc.failed', { path, code: mapped.code });
    }
  }

  async function handleLogout(req, res) {
    if (!requireToken(req, res)) return;
    const id = 'relay-logout-' + ++sequence;
    let upstreamOk = false;
    if (jar.size) {
      try {
        const result = await upstreamRequest({
          upstream,
          method: 'POST',
          path: '/web/session/destroy',
          body: JSON.stringify({ jsonrpc: '2.0', id, method: 'call', params: {} }),
          headers: { 'Content-Type': 'application/json' },
          timeoutMs: RPC_TIMEOUT_MS,
          maxResponseBytes: MAX_JSON_RESPONSE,
          jar,
        });
        // Current production returns {"jsonrpc":"2.0","id":null} with no
        // result; an empty result is success for this exact route.
        upstreamOk = result.status >= 200 && result.status < 300;
      } catch (error) {
        log('logout.upstream_failed', { code: String(error && error.code) });
      }
    }
    jar.clear();
    sendJson(req, res, 200, { ok: true, data: { upstreamOk }, error: null });
    log('logout', { upstreamOk });
  }

  async function handleAsset(req, res, url) {
    if (!requireToken(req, res)) return;
    let target;
    try {
      target = new URL(url);
    } catch (_) {
      sendJson(req, res, 400, safeError('BAD_ASSET_URL', '图片地址无效。'));
      return;
    }
    const base = new URL(upstream);
    if (target.origin !== base.origin || target.pathname !== '/lab/api/asset') {
      sendJson(req, res, 403, safeError('BAD_ASSET_URL', '只允许读取 Odoo 的 /lab/api/asset 白名单资源。'));
      return;
    }
    try {
      const result = await upstreamRequest({
        upstream,
        method: 'GET',
        path: target.pathname + target.search,
        headers: { Accept: 'image/*' },
        timeoutMs: ASSET_TIMEOUT_MS,
        maxResponseBytes: MAX_ASSET_RESPONSE,
        jar,
      });
      if (result.status < 200 || result.status >= 300) {
        sendJson(req, res, 502, safeError('ASSET_HTTP', 'Odoo 图片返回 HTTP ' + result.status + '。'));
        return;
      }
      setCors(req, res);
      res.statusCode = 200;
      res.setHeader('Content-Type', String(result.headers['content-type'] || 'application/octet-stream'));
      res.setHeader('Content-Length', String(result.body.length));
      res.end(result.body);
      log('asset', { status: 200, bytes: result.body.length });
    } catch (error) {
      const mapped = mapUpstreamError(error);
      sendJson(req, res, 502, safeError(mapped.code, mapped.message));
      log('asset.failed', { code: mapped.code });
    }
  }

  const server = http.createServer(async (req, res) => {
    const started = nowMs();
    setCors(req, res);
    if (!isLoopback(req.socket && req.socket.remoteAddress)) {
      sendJson(req, res, 403, safeError('LOOPBACK_ONLY', 'relay 只接受本机请求。'));
      return;
    }
    if (req.method === 'OPTIONS') {
      sendEmpty(req, res, 204);
      return;
    }
    const requestUrl = new URL(req.url || '/', 'http://127.0.0.1');
    try {
      if (req.method === 'GET' && requestUrl.pathname === '/health') {
        sendJson(req, res, 200, { ok: true, data: { service: SERVICE, version: '3.0.0' }, error: null });
        return;
      }
      if (req.method === 'POST' && requestUrl.pathname === '/login') {
        await handleLogin(req, res);
        return;
      }
      if (req.method === 'POST' && requestUrl.pathname === '/rpc') {
        await handleRpc(req, res);
        return;
      }
      if (req.method === 'POST' && requestUrl.pathname === '/logout') {
        await handleLogout(req, res);
        return;
      }
      if (req.method === 'GET' && requestUrl.pathname === '/asset') {
        await handleAsset(req, res, requestUrl.searchParams.get('url') || '');
        return;
      }
      sendJson(req, res, 404, safeError('NOT_FOUND', 'relay 路径不存在。'));
    } catch (error) {
      sendJson(req, res, 500, safeError('RELAY_ERROR', 'relay 处理失败。'));
      log('unhandled', { code: String(error && error.code || 'UNKNOWN') });
    } finally {
      log('http', { method: req.method, path: requestUrl.pathname, ms: nowMs() - started });
    }
  });

  return {
    server,
    token,
    upstream,
    db,
    port,
    async listen() {
      await new Promise((resolve, reject) => {
        server.once('error', reject);
        server.listen(port, host, () => {
          server.removeListener('error', reject);
          resolve();
        });
      });
      return { url: 'http://' + host + ':' + server.address().port, port: server.address().port };
    },
    async close() {
      jar.clear();
      if (!server.listening) return;
      if (typeof server.closeAllConnections === 'function') server.closeAllConnections();
      await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
    },
    get cookieSize() {
      return jar.size;
    },
  };
}

export function parseRelayArgs(argv) {
  const options = { port: DEFAULT_PORT, upstream: DEFAULT_UPSTREAM, db: DEFAULT_DB };
  const seen = new Set();
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i];
    if (!['--port', '--upstream', '--db'].includes(key) || seen.has(key)) throw new Error('未知或重复的启动参数：' + key);
    const value = argv[i + 1];
    if (!value || value.startsWith('--')) throw new Error(key + ' 缺少参数值');
    seen.add(key);
    if (key === '--port') {
      if (!/^\d+$/.test(value) || Number(value) < 1 || Number(value) > 65535) throw new Error('--port 必须是 1~65535 的整数');
      options.port = Number(value);
    } else if (key === '--db') {
      if (!/^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$/.test(value)) throw new Error('--db 数据库名格式错误');
      options.db = value;
    } else {
      const url = new URL(value);
      if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash || url.pathname !== '/') throw new Error('--upstream 必须是不含账号、路径、参数的 http(s) 地址');
      options.upstream = url.origin;
    }
  }
  return options;
}

async function main() {
  const argv = process.argv.slice(2);
  if (argv.includes('--help') || argv.includes('-h')) {
    console.log('用法: node server.mjs [--port 49621] [--upstream http://lc.rm.com] [--db LcHardwareHouse]');
    console.log('默认上游: ' + DEFAULT_UPSTREAM + '，默认数据库: ' + DEFAULT_DB);
    console.log('每次启动生成新的配对码；只绑定 127.0.0.1。');
    return;
  }
  const relay = createRelayServer(parseRelayArgs(argv));
  const address = await relay.listen();
  console.log('');
  console.log('============================================================');
  console.log(' 实验室库存本机桥接已启动');
  console.log(' 地址: ' + address.url);
  console.log(' 上游: ' + relay.upstream + ' / ' + relay.db);
  console.log(' 配对码: ' + relay.token);
  console.log(' 把上面的配对码填到 EDA 插件「连接与账户」中。');
  console.log(' 关闭此窗口即停止桥接；配对码每次启动都会变化。');
  console.log('============================================================');
  console.log('');
  const shutdown = async () => {
    try {
      await relay.close();
    } finally {
      process.exit(0);
    }
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch((error) => {
    console.error('启动失败:', error && error.message ? error.message : error);
    process.exit(1);
  });
}
