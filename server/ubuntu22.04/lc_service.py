# -*- coding: utf-8 -*-
"""systemd 服务控制（**强制验证实际状态**）。

为什么单独成模块：备份/恢复/升级都必须"停止成功才继续、启动成功才算完成"。
早期实现用 ``subprocess.run(..., check=False)`` 且不核对状态，于是
systemctl 失败被吞掉，脚本继续 dump / DROP，还打印"已停止"——是最危险的一类 bug。

设计：
  * 所有动作后**重新查询** ``is-active`` 来确认，未确认即抛 ``OpsError``；
  * ``systemctl`` 可执行文件可用环境变量 ``LC_SYSTEMCTL`` 覆盖，
    便于故障注入测试在不接触真实 systemd 的前提下验证失败路径；
  * 破坏性流程在调用前用 ``require_available()`` 做**前置**检查（fail-closed），
    不允许"没有 systemd 就当已停止"。
"""
import os
import shutil
import subprocess

from lc_odoo_conf import OpsError, validate_service_unit


def systemctl_path():
    return os.environ.get('LC_SYSTEMCTL') or shutil.which('systemctl')


def require_available():
    """破坏性流程的前置检查：没有可用的 systemctl 就明确报错。

    不要在这里返回 False 让调用方"继续跑"——那正是被 root 指出的缺陷。
    """
    exe = systemctl_path()
    if not exe:
        raise OpsError(
            '本机没有可用的 systemctl，无法验证服务已停止。\n'
            '  若你确认服务未由 systemd 管理（容器/chroot），显式传 --no-service；\n'
            '  否则请安装/启用 systemd 后重试。')
    return exe


def _run(unit, action, timeout=90):
    exe = systemctl_path()
    if not exe:
        raise OpsError('没有可用的 systemctl（LC_SYSTEMCTL 未设置且 PATH 中不存在）')
    try:
        proc = subprocess.run([exe, action, unit], timeout=timeout,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.TimeoutExpired:
        raise OpsError('systemctl %s %s 超时（%ss）' % (action, unit, timeout))
    except OSError as exc:
        raise OpsError('无法执行 systemctl %s %s：%s' % (action, unit, exc))
    return proc.returncode, (proc.stdout or b'').decode('utf-8', 'replace').strip()


def is_active(unit):
    """返回 True/False；状态未知返回 None（调用方不得把 None 当作"已停止"）。"""
    validate_service_unit(unit)
    exe = systemctl_path()
    if not exe:
        return None
    try:
        proc = subprocess.run([exe, 'is-active', unit], timeout=30,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except (subprocess.TimeoutExpired, OSError):
        return None
    state = (proc.stdout or b'').decode('utf-8', 'replace').strip()
    if state == 'active':
        return True
    if state in ('inactive', 'failed'):
        return False
    # 'deactivating' / 'activating' / unknown / 空 一律状态不明：
    # deactivating 表示停止**尚未完成**，进程可能仍在收尾，绝不能当作“已停机”；
    # activating 同理不能当作“已运行”。调用方必须等待或拒绝，不得据此继续破坏性动作。
    return None


def stop_verified(unit, retries=5, delay=1.0):
    """停止并**确认确实停止**；未确认则抛 OpsError（调用方必须中止后续破坏性动作）。

    只有 is-active 明确为 ``inactive``/``failed`` 才算停机。``active`` 或
    ``deactivating``/``activating``/unknown（返回 None）都**不算**——最多等待
    ``retries`` 次让它停稳，仍不确认就拒绝。
    """
    import time
    validate_service_unit(unit)
    require_available()
    rc, out = _run(unit, 'stop')
    if rc != 0:
        raise OpsError('systemctl stop %s 返回 %s：%s' % (unit, rc, out[:400]))
    last = 'unknown'
    for attempt in range(retries):
        state = is_active(unit)
        if state is False:            # 明确 inactive/failed 才认停机
            return True
        last = state                  # True(仍 active) 或 None(deactivating/activating/未知)
        time.sleep(delay)             # 等它真正停稳
    raise OpsError('systemctl stop %s 后未能确认已停止（最后 is-active=%r），拒绝继续'
                   % (unit, last))


def start_verified(unit, retries=8, delay=1.0):
    """启动并**确认已 active**；未确认则抛 OpsError（调用方不得宣称成功）。"""
    import time
    validate_service_unit(unit)
    require_available()
    rc, out = _run(unit, 'start')
    if rc != 0:
        raise OpsError('systemctl start %s 返回 %s：%s' % (unit, rc, out[:400]))
    last = 'unknown'
    for attempt in range(retries):
        state = is_active(unit)
        if state is True:
            return True
        last = state                  # False(未起来) 或 None(activating/未知)
        time.sleep(delay)
    raise OpsError('systemctl start %s 后未能确认 active（最后 is-active=%r）' % (unit, last))
