# -*- coding: utf-8 -*-
"""读取 Odoo 配置 + 备份/恢复/升级共用的**安全校验**。

安全约束：
  * 数据库密码**绝不**出现在命令行参数或进程列表里（只经 ``PGPASSWORD``）；
  * 数据库标识符（库名/角色名）先校验再用，SQL 里一律走 psql 变量（``:'v'``/``:"v"``）
    而不是字符串拼接 —— 避免注入，也避免引号/大小写导致误操作；
  * 所有由配置拼出来的路径都必须落在**预期的根目录之内**（防 ``../`` 与符号链接逃逸）。

这些校验都是纯函数，便于单元测试（见 ``lc_ops_tests.py``）。
"""
import configparser
import pathlib
import re
import shutil
import sys

DEFAULTS = {
    'db_host': '/var/run/postgresql',
    'db_port': '5432',
    'db_user': None,
    'db_password': None,
    'data_dir': '/var/lib/odoo',
    'addons_path': '',
    'logfile': '/var/log/odoo/odoo.log',
}

# PostgreSQL 标识符：以字母/下划线开头，后续字母数字/_/$，最长 63 字节
DB_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_$]{0,62}$')
# 备份目录名标签：只允许安全字符
LABEL_RE = re.compile(r'^[A-Za-z0-9._-]{0,32}$')

# 备份归档里**必须**存在的产物；多一个少一个都算异常
REQUIRED_ARTIFACTS = ('db.dump', 'filestore.tar.gz')
MANIFEST_FORMAT = 1


class OpsError(Exception):
    """运维脚本的受控失败（区别于未预期异常）。"""


# ------------------------------------------------------------------ 校验纯函数
def validate_db_identifier(name, what='数据库名'):
    """校验 PostgreSQL 标识符。空/含引号/分号/空格/超长一律拒绝。"""
    if not isinstance(name, str) or not name:
        raise OpsError('%s不能为空' % what)
    if len(name.encode('utf-8')) > 63:
        raise OpsError('%s过长（PostgreSQL 上限 63 字节）：%r' % (what, name))
    if not DB_IDENT_RE.match(name):
        raise OpsError('%s含非法字符（只允许字母/数字/下划线/$，且不能以数字开头）：%r'
                       % (what, name))
    return name


def validate_label(label):
    """校验备份目录标签（会进入目录名）。"""
    if label is None or label == '':
        return ''
    if not isinstance(label, str) or not LABEL_RE.match(label):
        raise OpsError('label 只允许字母/数字/点/下划线/连字符，且不超过 32 字符：%r' % (label,))
    return label


def safe_child_path(root, name, what='子路径'):
    """返回 ``root/name`` 并确保它**仍在 root 之内**（解析符号链接后判定）。

    任何逃逸（``../``、绝对路径、指向外部的符号链接）都抛 OpsError。
    """
    root_path = pathlib.Path(root).expanduser()
    try:
        root_real = root_path.resolve(strict=False)
    except OSError as exc:
        raise OpsError('%s：无法解析根目录 %s：%s' % (what, root, exc))
    if not name or pathlib.PurePosixPath(name).is_absolute() or pathlib.PurePath(name).is_absolute():
        raise OpsError('%s：不允许绝对路径：%r' % (what, name))
    candidate = (root_real / name)
    try:
        cand_real = candidate.resolve(strict=False)
    except OSError as exc:
        raise OpsError('%s：无法解析候选路径 %s：%s' % (what, candidate, exc))
    if cand_real != root_real and root_real not in cand_real.parents:
        raise OpsError('%s：%s 逃出了允许的根目录 %s' % (what, cand_real, root_real))
    return cand_real


def validate_service_unit(unit):
    """校验 systemd 单元名，避免把奇怪的值传给 systemctl。"""
    if not isinstance(unit, str) or not re.match(r'^[A-Za-z0-9@._-]+\.(service|socket|timer)$', unit):
        raise OpsError('systemd 单元名不合法：%r' % (unit,))
    return unit


# ------------------------------------------------------------------ 配置读取
def load(config_path='/etc/odoo.conf'):
    """返回配置 dict。缺失项用 Odoo 默认值；密码可能为 None（socket + trust 环境）。"""
    path = pathlib.Path(config_path)
    if not path.is_file():
        raise OpsError('找不到 Odoo 配置文件：%s' % config_path)
    cfg = configparser.ConfigParser(interpolation=None)
    with path.open(encoding='utf-8-sig') as fh:
        cfg.read_file(fh)
    if not cfg.has_section('options'):
        raise OpsError('配置文件缺少 [options] 段：%s' % config_path)
    opts = cfg['options']

    def get(name, default=None):
        value = (opts.get(name) or '').strip()
        if value.lower() in ('', 'false', 'none'):
            return default
        return value

    out = {key: get(key, default) for key, default in DEFAULTS.items()}
    out['db_name'] = get('db_name')
    out['config_path'] = str(path.resolve())
    return out


def datas_root(conf):
    """``<data_dir>/filestore`` —— filestore 的允许根目录。"""
    return pathlib.Path(conf['data_dir']).expanduser().resolve(strict=False) / 'filestore'


def filestore_path(conf, dbname):
    """``<data_dir>/filestore/<dbname>``，并强制校验不逃出 ``<data_dir>/filestore``。"""
    validate_db_identifier(dbname)
    return safe_child_path(datas_root(conf), dbname, what='filestore 路径')


# ------------------------------------------------------------------ 工具定位
def pg_tool(name, version='14'):
    """定位 PostgreSQL 客户端工具。

    优先**版本化绝对路径**：Ubuntu 的 /usr/bin/pg_dump 是 postgresql-common 包装脚本，
    会按 cluster 探测决定连哪个，在 root 下容易选错集群。
    允许 ``LC_PG_<TOOL>`` 覆盖（供故障注入测试使用）。
    """
    import os
    override = os.environ.get('LC_PG_%s' % name.upper())
    if override and pathlib.Path(override).is_file():
        return override
    versioned = pathlib.Path('/usr/lib/postgresql/%s/bin/%s' % (version, name))
    if versioned.is_file():
        return str(versioned)
    found = shutil.which(name)
    if found:
        return found
    raise OpsError('找不到 %s（请确认已安装 postgresql-%s）' % (name, version))


def modules_dir(conf):
    """定位三个 lab_* 模块所在的 addons 目录。

    addons_path 第一项通常是 Odoo 自带源码目录，**不是**业务模块所在处
    （业务模块在 /opt/odoo/custom-addons）。按是否含 lab_catalog 判定。
    """
    entries = [p.strip() for p in (conf['addons_path'] or '').split(',') if p.strip()]
    for entry in entries:
        if (pathlib.Path(entry) / 'lab_catalog' / '__manifest__.py').is_file():
            return entry
    return entries[0] if entries else ''


def odoo_bin(conf):
    """定位 odoo-bin 脚本。

    ⚠️ 必须用 ``python_bin()`` 以 ``<venv python> <odoo-bin>`` 调用：
    odoo-bin 的 shebang 是 ``#!/usr/bin/env python3``，直接执行会跑到系统 python，
    缺 babel 等依赖。
    """
    import os
    override = os.environ.get('LC_ODOO_BIN')
    if override and pathlib.Path(override).is_file():
        return override
    candidate = '/opt/odoo/odoo-19/odoo-bin'
    if pathlib.Path(candidate).is_file():
        return candidate
    raise OpsError('找不到 odoo-bin（预期 %s，或用 LC_ODOO_BIN 指定）' % candidate)


def python_bin(conf):
    """定位运行 Odoo 的解释器（venv python）。允许 ``LC_PYTHON`` 覆盖。"""
    import os
    override = os.environ.get('LC_PYTHON')
    if override and pathlib.Path(override).is_file():
        return override
    for candidate in ('/opt/odoo/venv/bin/python', '/opt/odoo/venv/bin/python3'):
        if pathlib.Path(candidate).is_file():
            return candidate
    return sys.executable


def describe(conf):
    """用于打印的脱敏摘要。"""
    return {
        'config': conf['config_path'],
        'db_user': conf['db_user'],
        'db_host': conf['db_host'],
        'db_port': conf['db_port'],
        'data_dir': conf['data_dir'],
        'password': '已从配置读取' if conf['db_password'] else '未设置（依赖 socket/trust）',
    }
