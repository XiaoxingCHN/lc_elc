/**
 * IFrame window + trusted parent/iframe bridge.
 *
 * openIFrame has no argument or postMessage parameter. The initial payload is
 * written to extension storage before opening the window. Runtime calls use
 * either the same-origin parent bridge object or a nonce-checked postMessage
 * channel; the iframe never performs its own cross-origin fetch.
 */

import { ApiError, ERROR_CODES } from '../shared/jsonrpc.js';
import { writePanelPayload } from './config.js';
import { getEda, resolveEda, toast } from './eda.js';

export const PANEL_PATH = '/iframe/app.html';
export const PANEL_ID = 'labOdooV3Panel';
export const BRIDGE_KEY = '__LAB_ODOO_V3_BRIDGE__';
export const BRIDGE_TAG = 'lab-odoo-v3';
export const MESSAGE_TOPIC = 'lab.odoo.v3.rpc';

export function makeNonce() {
  const cryptoObj = globalThis.crypto;
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') return cryptoObj.randomUUID();
  return 'n-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 12);
}

export async function openPanel(options) {
  const eda = options.eda || getEda();
  const nonce = options.nonce || makeNonce();
  const payload = {
    protocol: BRIDGE_TAG,
    version: 3,
    nonce,
    tab: options.tab || 'inventory',
    title: options.title || '实验室库存',
  };

  await writePanelPayload(eda, payload);
  try {
    if (eda.sys_IFrame && typeof eda.sys_IFrame.closeIFrame === 'function') {
      await eda.sys_IFrame.closeIFrame(PANEL_ID);
    }
  } catch (_) {
    /* closing a non-existent window is harmless */
  }
  if (!eda.sys_IFrame || typeof eda.sys_IFrame.openIFrame !== 'function') {
    throw new ApiError(ERROR_CODES.EDA_CONTEXT, 'EDA 内联框架接口不可用，无法打开面板。');
  }
  let opened;
  try {
    opened = await eda.sys_IFrame.openIFrame(PANEL_PATH, options.width || 1080, options.height || 760, PANEL_ID, {
      title: options.title || '实验室库存',
      minimizeButton: true,
      maximizeButton: true,
      grayscaleMask: false,
      onBeforeCloseCallFn: typeof options.onBeforeClose === 'function' ? options.onBeforeClose : undefined,
    });
  } catch (error) {
    throw new ApiError(ERROR_CODES.EDA_CONTEXT, '打开面板失败：' + String((error && error.message) || error), {
      cause: error,
    });
  }
  if (opened === false) {
    throw new ApiError(ERROR_CODES.EDA_CONTEXT, 'EDA 拒绝打开面板（openIFrame 返回 false）。');
  }
  return { nonce, payload };
}

const ODOO_ACTIONS = Object.freeze({
  bag_list: 'lab_workflow.action_lab_bag',
  issue_list: 'lab_workflow.action_lab_issue_line',
  label_open: 'lab_workflow.action_lab_label_open',
  location_list: 'lab_workflow.action_lab_location',
  operation_list: 'lab_workflow.action_lab_operation',
  scan_console: 'lab_workflow.action_lab_scan_console',
  request_log: 'lab_workflow.action_lab_request_log',
});

export function odooActionUrl(baseUrl, action) {
  const xmlid = ODOO_ACTIONS[action];
  if (!xmlid) {
    throw new ApiError(ERROR_CODES.VALIDATION_ERROR, '不支持的 Odoo 入口：' + action);
  }
  const base = String(baseUrl || '').replace(/\/+$/, '');
  return base + '/odoo/action-' + encodeURIComponent(xmlid);
}

export function openOdooAction(baseUrl, action) {
  const url = odooActionUrl(baseUrl, action);
  const eda = resolveEda();
  try {
    if (eda && eda.sys_Window && typeof eda.sys_Window.open === 'function') {
      eda.sys_Window.open(url, '_blank');
      return { url };
    }
    if (typeof globalThis.open === 'function') {
      globalThis.open(url, '_blank', 'noopener,noreferrer');
      return { url };
    }
  } catch (error) {
    toast('打开 Odoo 页面失败：' + String((error && error.message) || error), 'error', 5);
    throw new ApiError(ERROR_CODES.EDA_CONTEXT, '无法打开浏览器窗口。', { cause: error });
  }
  throw new ApiError(ERROR_CODES.EDA_CONTEXT, '当前 EDA 环境不支持打开外部页面。');
}

export function installBridge(options) {
  const nonce = options.nonce;
  const dispatch = options.dispatch;
  const logger = options.logger;
  const eda = options.eda || resolveEda();
  const win = options.window || (typeof globalThis !== 'undefined' ? globalThis : null);

  function errorPayload(error) {
    if (error && typeof error.toJSON === 'function') return error.toJSON();
    return {
      code: (error && error.code) || ERROR_CODES.UNKNOWN,
      message: String((error && error.message) || error),
      fields: (error && error.fields) || {},
      action: (error && error.action) || '',
      retryable: Boolean(error && error.retryable),
      mayHaveBeenSent: Boolean(error && error.mayHaveBeenSent),
    };
  }

  async function handleRequest(payload) {
    if (!payload || typeof payload !== 'object') {
      return { ok: false, data: null, error: { code: ERROR_CODES.BRIDGE, message: '桥接请求为空。' } };
    }
    if (!payload.nonce || payload.nonce !== nonce) {
      if (logger) logger.warn('bridge.nonce_mismatch', { method: String(payload.method || '') });
      return {
        ok: false,
        data: null,
        error: { code: ERROR_CODES.BRIDGE, message: '桥接校验失败（nonce 不匹配），已拒绝请求。' },
      };
    }
    if (typeof payload.method !== 'string' || !payload.method) {
      return { ok: false, data: null, error: { code: ERROR_CODES.BRIDGE, message: '桥接请求缺少方法名。' } };
    }
    try {
      const data = await dispatch(payload.method, payload.params || {});
      return { ok: true, data: data === undefined ? null : data, error: null };
    } catch (error) {
      if (logger) {
        logger.warn('bridge.request_failed', {
          method: payload.method,
          code: (error && error.code) || ERROR_CODES.UNKNOWN,
        });
      }
      return { ok: false, data: null, error: errorPayload(error) };
    }
  }

  const direct = {
    version: 3,
    protocol: BRIDGE_TAG,
    nonce,
    call: (payload) => handleRequest(payload),
  };

  const bus = eda && eda.sys_MessageBus;
  let busRegistered = false;
  if (bus && typeof bus.rpcService === 'function') {
    bus.rpcService(MESSAGE_TOPIC, (message) => handleRequest(message));
    busRegistered = true;
  }
  if (win) win[BRIDGE_KEY] = direct;
  if (logger) {
    logger.info('bridge.installed', {
      nonceLength: nonce.length,
      mode: busRegistered ? 'messagebus' : win ? 'direct' : 'none',
    });
  }
  if (!busRegistered && !win) {
    throw new ApiError(ERROR_CODES.EDA_CONTEXT, 'EDA 消息总线与同源桥接均不可用，无法打开面板。');
  }

  return {
    call: direct.call,
    mode: busRegistered ? 'messagebus' : 'direct',
    uninstall() {
      try {
        if (busRegistered && bus && typeof bus.removePrivateMessageBus === 'function') {
          bus.removePrivateMessageBus();
        }
        if (win && win[BRIDGE_KEY] === direct) delete win[BRIDGE_KEY];
      } catch (_) {
        /* ignore */
      }
    },
  };
}
