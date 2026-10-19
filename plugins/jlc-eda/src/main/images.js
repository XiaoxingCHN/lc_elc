/**
 * Image loading.
 *
 * Catalog detail returns the original mall/CDN image_url for most parts. The
 * Odoo server already exposes a controlled proxy at /lab/api/asset?url=...,
 * which applies the server-side SSRF/asset whitelist. We convert the external
 * image URL into that Odoo URL, then fetch it through the relay (which owns
 * the Odoo session) or through direct Odoo mode.
 */

import { ApiError, ERROR_CODES } from '../shared/jsonrpc.js';
import { joinUrl } from './transport.js';

const MAX_BYTES = 1_500_000;
const MAX_SOURCE_URL = 2048;
const SAME_ORIGIN_PREFIXES = ['/lab/api/asset', '/web/image', '/lab_catalog/static'];

/** Convert a catalog image URL to an Odoo-controlled asset URL, or null. */
export function toOdooAssetUrl(raw, serverUrl) {
  if (!raw) return null;
  const text = String(raw).trim();
  if (!text || text.length > MAX_SOURCE_URL) return null;
  let base;
  let url;
  try {
    base = new URL(serverUrl);
    url = new URL(text, base);
  } catch (_) {
    return null;
  }
  if (!/^https?:$/.test(url.protocol)) return null;
  if (url.username || url.password) return null;
  if (url.origin === base.origin) {
    if (SAME_ORIGIN_PREFIXES.some((prefix) => url.pathname === prefix || url.pathname.startsWith(prefix + '/'))) {
      return url.toString();
    }
    return null;
  }
  return base.origin + '/lab/api/asset?url=' + encodeURIComponent(url.toString());
}

export function bytesToBase64(bytes) {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  if (typeof Buffer !== 'undefined') return Buffer.from(view).toString('base64');
  let binary = '';
  const chunk = 0x8000;
  for (let i = 0; i < view.length; i += chunk) {
    binary += String.fromCharCode.apply(null, view.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export function createImageLoader(options) {
  const transport = options.transport;
  const serverUrl = options.serverUrl;
  const mode = options.mode || 'direct';
  const relayUrl = options.relayUrl;
  const pairingToken = options.pairingToken;
  const cache = new Map();
  const maxCache = options.maxCache || 40;

  async function load(raw) {
    const odooAsset = toOdooAssetUrl(raw, serverUrl);
    if (!odooAsset) {
      return {
        supported: false,
        reason: '该图片不是可用的商城/Odoo 资源，插件不会代理任意地址。',
      };
    }
    let target;
    let headers;
    if (mode === 'relay') {
      if (!relayUrl || !pairingToken) {
        throw new ApiError(ERROR_CODES.RELAY_AUTH, '请先填写本机桥接配对码并登录。');
      }
      target = joinUrl(relayUrl, '/asset?url=' + encodeURIComponent(odooAsset));
      headers = { Authorization: 'Bearer ' + pairingToken, Accept: 'image/*' };
    } else {
      target = odooAsset;
      headers = { Accept: 'image/*' };
    }
    if (cache.has(target)) return cache.get(target);
    const result = await transport.requestBinary({ url: target, method: 'GET', headers, timeoutMs: 30000 });
    const contentType = String(result.contentType || '').toLowerCase();
    if (!contentType.startsWith('image/')) {
      throw new ApiError(ERROR_CODES.HTTP, '服务器返回的资源不是图片（' + contentType + '）。');
    }
    const bytes = new Uint8Array(result.buffer);
    if (bytes.byteLength > MAX_BYTES) {
      throw new ApiError(ERROR_CODES.HTTP, '图片超过 1.5MB，已停止加载以免阻塞面板。');
    }
    const value = {
      supported: true,
      dataUrl: 'data:' + contentType.split(';')[0] + ';base64,' + bytesToBase64(bytes),
      contentType,
      bytes: bytes.byteLength,
    };
    cache.set(target, value);
    if (cache.size > maxCache) cache.delete(cache.keys().next().value);
    return value;
  }

  return { load, toOdooAssetUrl };
}
