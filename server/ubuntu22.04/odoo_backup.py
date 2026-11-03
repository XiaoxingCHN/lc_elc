#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Odoo 实验室库存系统 —— 成套备份（数据库 + filestore + 清单）。

成套的含义：只备份数据库、不备份 filestore，恢复后图片/手册会丢；反之业务数据丢失。
两者必须同一时间点、同一清单。

**服务语义（fail-closed）**
  * 默认要求 systemd 可用并**验证服务确实已停止**后才开始 dump；停止失败/无法确认
    → 立即中止，不生成任何"一致"假象的备份。
  * 备份结束后按原状态恢复（原来 active 才重新 start），并通过 ``is-active`` 复核；
    重启失败 → 退出码非 0，绝不打印"备份成功"。
  * 若服务不由 systemd 管理（容器/chroot），必须**显式** ``--no-service``；
    脚本不会偷偷跳过也不会偷偷调用 systemctl。

产物：``<out-root>/<UTC 时间戳>[-label]/``
    db.dump / filestore.tar.gz / MANIFEST.json / odoo.log.tail

用法：
    sudo python3 odoo_backup.py --db LcHardwareHouse --label before-upgrade
    sudo python3 odoo_backup.py --db LcHardwareHouse --unit odoo.service
    sudo python3 odoo_backup.py --db LcHardwareHouse --no-service   # 显式声明不管理服务

退出码：0 成功；非 0 失败（失败时删除本次新建的半成品目录）。
"""
import argparse
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tarfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lc_archive as archive  # noqa: E402
import lc_odoo_conf as conf_mod  # noqa: E402
import lc_service as service  # noqa: E402
from lc_odoo_conf import OpsError  # noqa: E402

LAB_MODULES = ('lab_inventory', 'lab_catalog', 'lab_workflow')


def run(cmd, env=None, check=True, input=None):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    proc = subprocess.run(cmd, env=merged, check=False, input=input,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if check and proc.returncode != 0:
        raise OpsError('命令失败(%s)：%s\n%s'
                       % (proc.returncode, ' '.join(cmd),
                          (proc.stdout or b'').decode('utf-8', 'replace')[-2000:]))
    return proc


def run_psql(conf, sql, params=None, dbname='postgres'):
    """用 psql 变量（``:'name'``/``:"ident"``）传值，绝不把库名/角色名拼进 SQL 文本。

    ⚠️ 必须用 ``-f -``（从 stdin 读）而不是 ``-c``：``psql -c`` **不做** psql 变量
    插值（命令串被当作"完全可由服务器解析"的纯 SQL），``:'dbname'`` 会原样发给服务器
    导致语法错误。``-f -`` / stdin 才会插值。
    另外加 ``ON_ERROR_STOP=1``：否则 psql 遇到 SQL 错误仍返回 0，会吞掉失败。
    """
    conf_mod.validate_db_identifier(dbname)
    cmd = [conf_mod.pg_tool('psql'), '-X', '-q', '-A', '-t',
           '-v', 'ON_ERROR_STOP=1',
           '-h', conf['db_host'], '-p', conf['db_port'],
           '-U', conf['db_user'], '-d', dbname]
    for key, value in (params or {}).items():
        cmd += ['-v', '%s=%s' % (key, value)]
    cmd += ['-f', '-']
    payload = sql.strip()
    if not payload.endswith(';'):
        payload += ';'
    env = {'PGPASSWORD': conf['db_password']} if conf['db_password'] else {}
    return run(cmd, env=env, input=payload.encode('utf-8')) \
        .stdout.decode('utf-8', 'replace').strip()


def code_fingerprint(addons_path):
    """lab_* 三个模块的确定性文件指纹（相对路径 -> sha256）。"""
    out = {}
    root_base = pathlib.Path(addons_path)
    for module in LAB_MODULES:
        root = root_base / module
        if not root.is_dir():
            continue
        for path in sorted(root.rglob('*')):
            if not path.is_file():
                continue
            rel = path.relative_to(root_base).as_posix()
            if '__pycache__' in rel or rel.endswith('.pyc'):
                continue
            out[rel] = archive.sha256_file(path)
    return out


def cleanup_partial(target, out_root):
    """只删除**本次新建**且**确认在 out_root 之内**的目录。"""
    target = pathlib.Path(target).resolve(strict=False)
    out_root = pathlib.Path(out_root).resolve(strict=False)
    if target == out_root or out_root not in target.parents:
        print('  !! 拒绝清理不在 out_root 之内的路径：%s' % target, file=sys.stderr)
        return False
    shutil.rmtree(target, ignore_errors=True)
    return True


def main():
    parser = argparse.ArgumentParser(description='Odoo 成套备份（DB + filestore + 清单）')
    parser.add_argument('--config', default='/etc/odoo.conf')
    parser.add_argument('--db', default=None, help='数据库名（默认取配置 db_name，再退回 LcHardwareHouse）')
    parser.add_argument('--out-root', default='/var/backups/lc-elc')
    parser.add_argument('--label', default='', help='附加到目录名的标签（只允许 [A-Za-z0-9._-]）')
    parser.add_argument('--addons-path', default=None, help='覆盖配置里的模块目录（代码指纹用）')
    parser.add_argument('--unit', default='odoo.service', help='systemd 单元名')
    parser.add_argument('--no-service', '--no-stop', dest='no_service', action='store_true',
                        help='显式声明不管理服务（容器/chroot）；此时不调用任何 systemctl')
    args = parser.parse_args()

    if os.geteuid() != 0:
        raise OpsError('请用 sudo 运行（需要读写 filestore 与备份目录）')

    conf = conf_mod.load(args.config)
    dbname = conf_mod.validate_db_identifier(args.db or conf['db_name'] or 'LcHardwareHouse')
    label = conf_mod.validate_label(args.label)
    unit = conf_mod.validate_service_unit(args.unit)
    addons_path = args.addons_path or conf_mod.modules_dir(conf)
    if not addons_path or not pathlib.Path(addons_path).is_dir():
        raise OpsError('模块目录无效：%r' % addons_path)

    print('==== Odoo 成套备份 ====')
    for key, value in conf_mod.describe(conf).items():
        print('  %-9s %s' % (key, value))
    print('  db        %s' % dbname)
    print('  modules   %s' % addons_path)
    print('  service   %s' % ('不管理（--no-service）' if args.no_service else unit))

    # ---- 预检：库存在、大小、磁盘
    exists = run_psql(conf, "SELECT 1 FROM pg_database WHERE datname = :'dbname'",
                      {'dbname': dbname})
    if exists != '1':
        raise OpsError('数据库 %s 不存在，拒绝备份' % dbname)
    db_size = int(run_psql(conf, "SELECT pg_database_size(:'dbname')",
                           {'dbname': dbname}, dbname) or 0)

    out_root = pathlib.Path(args.out_root)
    out_root.mkdir(parents=True, exist_ok=True)
    out_root_real = out_root.resolve(strict=False)
    stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    dir_name = stamp + (('-' + label) if label else '')
    target = conf_mod.safe_child_path(out_root_real, dir_name, what='备份目录')
    if target.exists():
        raise OpsError('备份目录已存在，拒绝覆盖：%s' % target)

    filestore = conf_mod.filestore_path(conf, dbname)
    candidates = [p for p in conf_mod.filestore_candidates(conf, dbname) if p.is_dir()]
    if candidates:
        filestore = max(candidates, key=lambda p: sum(
            1 for f in p.rglob('*') if f.is_file()))
    fs_size = sum(f.stat().st_size for f in filestore.rglob('*') if f.is_file()) \
        if filestore.is_dir() else 0
    # 附件完整性：库里有 store_fname 但归档为空 → 拒绝产出“看似成功”的备份
    stored = int(run_psql(conf, "SELECT count(DISTINCT store_fname) FROM ir_attachment "
                               "WHERE store_fname IS NOT NULL AND store_fname <> ''",
                          None, dbname) or 0)
    fs_files = sum(1 for f in filestore.rglob('*') if f.is_file()) if filestore.is_dir() else 0
    print('  filestore %s（%d 个文件；库内引用 %d 个）' % (filestore, fs_files, stored))
    if stored and not fs_files:
        raise OpsError('附件完整性校验失败：数据库有 %d 个文件附件，但 filestore 目录为空：%s\n'
                       '  请确认 data_dir（Odoo 未配置时默认 ~/.local/share/Odoo），'
                       '  不要用空归档冒充完整备份' % (stored, filestore))
    if stored and fs_files < stored:
        print('  !! 警告：filestore 文件数 %d 少于库内唯一引用 %d（可能有去重/残留）'
              % (fs_files, stored))
    need = int((db_size + fs_size) * 1.6) + 64 * 1024 * 1024
    free = shutil.disk_usage(out_root_real.anchor or '/').free
    if free < need:
        raise OpsError('磁盘不足：需要约 %.1f MB，可用 %.1f MB'
                       % (need / 1048576, free / 1048576))

    # ---- 停服务：**必须验证已停止**，否则不允许开始 dump
    service_managed = not args.no_service
    originally_active = False
    if service_managed:
        service.require_available()
        state = service.is_active(unit)
        if state is None:
            raise OpsError('无法确认 %s 的当前状态（is-active 输出不可识别），拒绝备份' % unit)
        originally_active = state
        if originally_active:
            print('  停止 %s 并验证 ...' % unit)
            service.stop_verified(unit)
            print('  已确认 %s inactive' % unit)
        else:
            print('  %s 本来就不是 active' % unit)

    target.mkdir(parents=True)
    manifest = None
    failure = None
    created = True
    try:
        # ---- 数据库
        dump = target / 'db.dump'
        cmd = [conf_mod.pg_tool('pg_dump'), '-Fc', '--no-owner', '--no-acl',
               '-h', conf['db_host'], '-p', conf['db_port'],
               '-U', conf['db_user'], '-d', dbname, '-f', str(dump)]
        env = {'PGPASSWORD': conf['db_password']} if conf['db_password'] else {}
        run(cmd, env=env)
        listing = run([conf_mod.pg_tool('pg_restore'), '--list', str(dump)]) \
            .stdout.decode('utf-8', 'replace')
        if 'TABLE DATA' not in listing and 'SEQUENCE' not in listing:
            raise OpsError('备份校验失败：dump 里没有可识别的表数据')
        print('  数据库已备份 %.1f MB' % (dump.stat().st_size / 1048576))

        # ---- filestore（arcname 用目录名 = 库名，恢复端可原位还原）
        tarball = target / 'filestore.tar.gz'
        with tarfile.open(tarball, 'w:gz') as tar:
            if filestore.is_dir():
                tar.add(str(filestore), arcname=filestore.name)
        print('  filestore 已归档 %.1f MB（源 %.1f MB）'
              % (tarball.stat().st_size / 1048576, fs_size / 1048576))

        # ---- 清单
        modules = run_psql(conf,
                           "SELECT name || '|' || COALESCE(latest_version,'') || '|' || state "
                           "FROM ir_module_module WHERE state='installed' ORDER BY name", None, dbname)
        odoo_version = run_psql(conf,
                                "SELECT latest_version FROM ir_module_module WHERE name='base'",
                                None, dbname)
        manifest = {
            'format': conf_mod.MANIFEST_FORMAT,
            'created_utc': stamp,
            'label': label or None,
            'database': dbname,
            'database_size_bytes': db_size,
            'odoo_base_version': odoo_version,
            'installed_modules': [line for line in modules.splitlines() if line],
            'filestore_root': str(filestore.parent),
            'filestore_archive_root': filestore.name,
            'filestore_files_bytes': fs_size,
            'addons_path': addons_path,
            'code_fingerprint': code_fingerprint(addons_path),
            'service_managed': service_managed,
            'service_unit': unit if service_managed else None,
            'service_was_active': originally_active if service_managed else None,
            'artifacts': {
                'db.dump': {'bytes': dump.stat().st_size,
                            'sha256': archive.sha256_file(dump)},
                'filestore.tar.gz': {'bytes': tarball.stat().st_size,
                                     'sha256': archive.sha256_file(tarball)},
            },
        }
        (target / 'MANIFEST.json').write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

        logfile = pathlib.Path(conf['logfile'] or '')
        if logfile.is_file():
            (target / 'odoo.log.tail').write_bytes(logfile.read_bytes()[-64 * 1024:])
    except BaseException as exc:
        failure = exc
        shutil.rmtree(target, ignore_errors=True)
        created = False
        raise
    finally:
        # 只有备份**真正成功**才回到原状态；失败保持停机（避免半成品被当成有效备份后仍对外服务）
        if service_managed and originally_active:
            if created and failure is None:
                try:
                    print('  重新启动 %s 并验证 ...' % unit)
                    service.start_verified(unit)
                    print('  已确认 %s active' % unit)
                except OpsError as exc:
                    print('\n!! 备份已完成，但**服务重启失败**：%s' % exc)
                    print('   请手动检查：systemctl status %s --no-pager' % unit)
                    print('   备份产物仍然可用：%s' % target)
                    raise SystemExit(3)
            else:
                print('  备份未成功，保持 %s 停机（未尝试启动）' % unit)

    print('==== 备份完成 ====')
    print('  目录    %s' % target)
    print('  db.dump sha256 %s' % manifest['artifacts']['db.dump']['sha256'])
    print('  归档    sha256 %s' % manifest['artifacts']['filestore.tar.gz']['sha256'])
    print('  回滚用：sudo python3 odoo_restore.py --backup %s --db %s --yes' % (target, dbname))
    # 机器可读末行：调用方（如 odoo_restore.py 的恢复前快照）用它拿路径
    print('BACKUP_DIR=%s' % target)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except OpsError as exc:
        print('\n错误：%s' % exc, file=sys.stderr)
        sys.exit(1)
