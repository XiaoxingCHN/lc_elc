/**
 * iframe side of the trusted bridge.
 *
 * Priority:
 *   1. official private SYS_MessageBus RPC (extensionUuid-scoped, no public bus);
 *   2. same-origin parent bridge object with nonce check.
 *
 * There is deliberately no direct fetch()/sys_ClientUrl call, no postMessage
 * wildcard listener, and no RPC queue in sys_Storage. Password and pairing token
 * only travel through the in-memory RPC call.
 */

export const BRIDGE_TAG = 'lab-odoo-v3';
export const PANEL_STORAGE_KEY = 'lab_odoo_v3_panel_payload';
export const MESSAGE_TOPIC = 'lab.odoo.v3.rpc';
export const BRIDGE_KEY = '__LAB_ODOO_V3_BRIDGE__';

function edaObject() {
  try {
    if (typeof window !== 'undefined' && window.eda && window.eda.sys_Storage) return window.eda;
  } catch (_) {
    /* cross-origin access can throw */
  }
  try {
    if (typeof window !== 'undefined' && window.parent && window.parent.eda && window.parent.eda.sys_Storage) {
      return window.parent.eda;
    }
  } catch (_) {
    /* cross-origin access can throw */
  }
  return null;
}

export function readPanelPayload() {
  const eda = edaObject();
  if (!eda) return null;
  try {
    const raw = eda.sys_Storage.getExtensionUserConfig(PANEL_STORAGE_KEY);
    if (typeof raw !== 'string' || !raw) return null;
    return JSON.parse(raw);
  } catch (_) {
    return null;
  }
}

export function toError(payload) {
  const error = new Error((payload && payload.message) || '请求失败');
  error.name = 'BridgeApiError';
  error.code = (payload && payload.code) || 'UNKNOWN';
  error.fields = (payload && payload.fields) || {};
  error.action = (payload && payload.action) || '';
  error.retryable = Boolean(payload && payload.retryable);
  error.mayHaveBeenSent = Boolean(payload && payload.mayHaveBeenSent);
  return error;
}

function unwrap(reply) {
  if (!reply || typeof reply !== 'object') {
    throw toError({ code: 'BRIDGE', message: '桥接返回为空，请从 EDA 菜单重新打开面板。' });
  }
  if (reply.ok === true) return reply.data;
  if (reply.ok === false) throw toError(reply.error || {});
  throw toError({ code: 'BRIDGE', message: '桥接返回格式不正确。' });
}

export function createBridge(payload) {
  const nonce = payload && payload.nonce;
  if (!nonce) {
    throw toError({ code: 'BRIDGE', message: '面板缺少桥接 nonce，请从 EDA 菜单重新打开面板。' });
  }

  const eda = edaObject();
  const bus = eda && eda.sys_MessageBus;
  let direct = null;
  try {
    if (typeof window !== 'undefined' && window.parent && window.parent[BRIDGE_KEY]) {
      const candidate = window.parent[BRIDGE_KEY];
      if (candidate && candidate.nonce === nonce && typeof candidate.call === 'function') direct = candidate;
    }
  } catch (_) {
    direct = null;
  }

  const useBus = Boolean(bus && typeof bus.rpcCall === 'function');
  if (!useBus && !direct) {
    throw toError({
      code: 'BRIDGE',
      message: '无法连接 EDA 扩展主模块。请确认扩展已启用，并从顶部菜单重新打开面板。',
    });
  }

  async function call(method, params = {}, timeoutMs = 30000) {
    const request = { nonce, method, params };
    // The host rejects its own timeout with `undefined`, so never stringify the
    // raw rejection: report the method and the elapsed budget instead.
    const describe = (error) => {
      if (error && error.message) return String(error.message);
      if (error instanceof Error) return error.name || '未命名错误';
      return (
        '宿主在 ' + Math.round(timeoutMs / 1000) + ' 秒内没有响应' +
        '（可能 EDA 正在等待对话框，或该方法在当前编辑器不可用）'
      );
    };
    const code = (error) =>
      (error && typeof error.code === 'string' && error.code) ||
      (error && error.name === 'TimeoutError' ? 'TIMEOUT' : 'BRIDGE');
    if (useBus) {
      try {
        return unwrap(await bus.rpcCall(MESSAGE_TOPIC, request, timeoutMs));
      } catch (error) {
        if (error && error.code) throw toError(error);
        throw toError({
          code: code(error),
          message: 'EDA 消息总线调用失败（' + method + '）：' + describe(error),
        });
      }
    }
    try {
      return unwrap(await direct.call(request));
    } catch (error) {
      if (error && error.code) throw toError(error);
      throw toError({
        code: code(error),
        message: '同源桥接调用失败（' + method + '）：' + describe(error),
      });
    }
  }

  return {
    call,
    nonce,
    mode: useBus ? 'messagebus' : 'direct',
    close() {
      /* nothing to release: no listener / storage queue */
    },
  };
}
