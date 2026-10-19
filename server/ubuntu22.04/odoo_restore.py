#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Odoo 实验室库存系统 —— 从备份恢复（同时就是**回滚**）。

恢复某个备份点即回滚，不需要单独的降级路径。

**顺序与 fail-closed 语义（root 审查后重写）**

  1. 读 MANIFEST 并做**结构校验**（format / 必要产物 / 名称与 sha256 形态）；
  2. ``--db`` 必须与 ``MANIFEST.database`` **一致** —— 不同名会去解旧库的 filestore 目录，
     造成"目标目录为空 + 静默丢文件"。不做静默重映射：明确拒绝。
  3. 校验产物**字节数与 sha256**、并**预检归档成员**（绝对路径/``..``/符号链接/硬链接/设备/
     越界成员一律拒绝）。**这一整套预检在任何破坏性动作之前完成。**
  4. 停服务并**验证**已停止（验证不通过则中止，绝不在服务运行时 DROP）。
  5. 目标库存在时，默认先生成一份**恢复前成套备份**并保存；备份失败 → 中止，**不执行 DROP**。
  6. 终止连接 → DROP → CREATE → ``pg_restore --exit-on-error``；
  7. 换 filestore：旧目录保留为 ``<db>.pre-restore-<ts>``，新内容**手工安全解包**（不用 extractall）；
  8. 修正归属并**校验生效**（失败即 fail-closed）；
  9. **只有 6+7+8 全部成功**，才把服务恢复到原来的状态（原来 active 才 start，并复核）；
     否则保持停机，并打印准确的人工恢复指引。

用法：
    sudo python3 odoo_restore.py --list <备份目录>
    sudo python3 odoo_restore.py --backup <目录> --db LcHardwareHouse --yes --dry-run
    sudo python3 odoo_restore.py --backup <目录> --db LcHardwareHouse --yes
    sudo python3 odoo_restore.py --backup <目录> --db LcHardwareHouse --yes --no-service

退出码：0 成功；1 受控失败；3 数据已恢复但服务未能回到原状态。
"""
import argparse
import datetime
import os
import pathlib
import pwd
import shutil
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import lc_archive as archive  # noqa: E402
import lc_odoo_conf as conf_mod  # noqa: E402
import lc_service as service  # noqa: E402
from lc_odoo_conf import OpsError  # noqa: E402


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


def run_psql(conf, sql, params=None, dbname='postgres', check=True):
    """psql 变量传值（``:'name'`` / ``:"name"``），不拼接 SQL 文本。

    ⚠️ 用 ``-f -``（stdin）而非 ``-c``：``psql -c`` 不插值变量，``:'dbname'`` 会原样
    发给服务器报语法错；stdin 才会插值。加 ``ON_ERROR_STOP=1`` 让 SQL 错误也非零退出。
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
    return run(cmd, env=env, check=check, input=payload.encode('utf-8')) \
        .stdout.decode('utf-8', 'replace').strip()


def show_manifest(manifest):
    print('==== 备份清单 ====')
    for key in ('created_utc', 'label', 'database', 'odoo_base_version',
                'database_size_bytes', 'addons_path', 'service_managed',
                'service_unit', 'service_was_active'):
        print('  %-20s %s' % (key, manifest.get(key)))
    for name, meta in manifest['artifacts'].items():
        print('  artifact %-18s %10d bytes  sha256=%s' % (name, meta['bytes'], meta['sha256']))
    modules = manifest.get('installed_modules') or []
    print('  已安装模块 %d 个：%s' % (len(modules), ', '.join(m.split('|')[0] for m in modules[:12])))


def precheck_archive(manifest, backup_dir):
    """**只读**预检：产物完整性 + 归档成员安全。必须在任何 DROP 之前调用。"""
    print('\n---- 预检 1/2：产物字节数与 sha256 ----')
    archive.verify_artifacts(manifest, backup_dir)
    for name in manifest['artifacts']:
        print('  OK  %s' % name)

    print('---- 预检 2/2：归档成员安全性 ----')
    import tarfile
    tarball = pathlib.Path(backup_dir) / 'filestore.tar.gz'
    expected_root = manifest.get('filestore_archive_root') or manifest['database']
    with tarfile.open(tarball, 'r:gz') as tar:
        members, problems = archive.inspect_tar_members(tar, expected_root)
    if problems:
        raise OpsError('归档预检未通过，已拒绝恢复（未做任何修改）：\n  - '
                       + '\n  - '.join(problems[:20]))
    files = sum(1 for m in members if m.isfile())
    print('  OK  成员 %d 个（其中普通文件 %d），根目录 %s'
          % (len(members), files, expected_root))


def run_pre_backup(conf, dbname, out_root):
    """恢复前对**现存**目标库做一份成套备份；失败即抛错（调用方不得 DROP）。

    这里一律给子进程传 ``--no-service``：服务状态由本脚本统一管理，
    子备份不得再去 stop/start（否则会打乱"原状态"的判定）。
    """
    print('\n---- 恢复前快照（保护现有数据）----')
    script = pathlib.Path(__file__).resolve().parent / 'odoo_backup.py'
    cmd = [sys.executable, str(script), '--config', conf['config_path'], '--db', dbname,
           '--out-root', str(out_root), '--label', 'pre-restore', '--no-service']
    proc = subprocess.run(cmd, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = (proc.stdout or b'').decode('utf-8', 'replace')
    if proc.returncode != 0:
        raise OpsError('恢复前快照失败（退出码 %s），拒绝继续 DROP：\n%s'
                       % (proc.returncode, out[-2000:]))
    path = None
    for line in out.splitlines():
        if line.startswith('BACKUP_DIR='):
            path = line.split('=', 1)[1].strip()
    if not path or not pathlib.Path(path).is_dir():
        raise OpsError('恢复前快照未返回有效目录，拒绝继续 DROP：\n%s' % out[-1200:])
    print('  已保存恢复前快照：%s' % path)
    return path


def resolve_odoo_ids(uid_name='odoo'):
    try:
        entry = pwd.getpwnam(uid_name)
    except KeyError:
        return None
    return entry.pw_uid, entry.pw_gid


def chown_and_verify(path, uid, gid):
    """chown -R 并**校验生效**；任何不符即抛错（不允许"打印完成"了事）。"""
    run(['chown', '-R', '%d:%d' % (uid, gid), str(path)])
    bad = []
    for item in [path] + [p for p in path.rglob('*')]:
        try:
            st = item.stat()
        except OSError as exc:
            bad.append('%s（无法 stat：%s）' % (item, exc))
            continue
        if st.st_uid != uid or st.st_gid != gid:
            bad.append('%s（uid=%s gid=%s）' % (item, st.st_uid, st.st_gid))
        if len(bad) >= 5:
            break
    if bad:
        raise OpsError('归属修正未完全生效，拒绝宣告成功：\n  - ' + '\n  - '.join(bad))


def main():
    parser = argparse.ArgumentParser(description='从备份恢复/回滚 Odoo 实验室库存系统')
    parser.add_argument('backup_dir', nargs='?', help='备份目录（或用 --backup 指定）')
    parser.add_argument('--backup', dest='backup_opt', default=None)
    parser.add_argument('--list', action='store_true', help='只显示清单，不恢复')
    parser.add_argument('--config', default='/etc/odoo.conf')
    parser.add_argument('--db', default=None, help='目标数据库名（必须与清单一致）')
    parser.add_argument('--yes', action='store_true', help='确认执行破坏性恢复')
    parser.add_argument('--dry-run', action='store_true', help='只打印将要执行的动作')
    parser.add_argument('--keep-filestore', action='store_true', help='不换 filestore，只恢复数据库')
    parser.add_argument('--no-pre-backup', action='store_true',
                        help='显式跳过"恢复前快照"（危险：失败将无法回到恢复前状态）')
    parser.add_argument('--pre-backup-root', default='/var/backups/lc-elc')
    parser.add_argument('--no-chown', action='store_true',
                        help='显式跳过归属修正（本机没有 odoo 用户时）')
    parser.add_argument('--odoo-user', default='odoo')
    parser.add_argument('--unit', default='odoo.service')
    parser.add_argument('--no-service', '--no-stop', dest='no_service', action='store_true',
                        help='显式声明不管理服务（容器/chroot）')
    args = parser.parse_args()

    backup_dir = args.backup_opt or args.backup_dir
    if not backup_dir:
        raise OpsError('请给出备份目录（位置参数或 --backup）')
    manifest, backup_dir = archive.load_manifest(backup_dir)
    show_manifest(manifest)

    if args.list:
        return 0

    conf = conf_mod.load(args.config)
    unit = conf_mod.validate_service_unit(args.unit)
    dbname = conf_mod.validate_db_identifier(args.db or manifest['database'])
    if dbname != manifest['database']:
        raise OpsError(
            '目标库名（%s）与备份里的库名（%s）不一致。\n'
            '  备份中的 filestore 归档根目录是 %r；换名恢复会把它解到别处、目标目录为空，\n'
            '  属于静默丢文件，因此明确拒绝。\n'
            '  如确需换名：先用原名恢复，再在 Odoo 内改名 / 重命名数据库，不要在这里绕。'
            % (dbname, manifest['database'],
               manifest.get('filestore_archive_root') or manifest['database']))

    if not args.yes and not args.dry_run:
        raise OpsError('恢复是破坏性操作（会 DROP 并重建目标库）。确认后加 --yes。')

    filestore = conf_mod.filestore_path(conf, dbname)
    print('\n==== 恢复计划 ====')
    print('  备份点     %s' % manifest['created_utc'])
    print('  目标库     %s @ %s' % (dbname, conf['db_host']))
    print('  filestore  %s%s' % (filestore, '（不换）' if args.keep_filestore else '（换入）'))
    print('  服务       %s' % ('不管理（--no-service）' if args.no_service else unit))

    # ---------- 预检（任何破坏性动作之前）
    precheck_archive(manifest, backup_dir)

    existing = run_psql(conf, "SELECT 1 FROM pg_database WHERE datname = :'dbname'",
                        {'dbname': dbname}) == '1'
    print('\n  目标库当前%s存在' % ('' if existing else '不'))
    if existing and args.no_pre_backup:
        print('  !! 你显式指定了 --no-pre-backup：失败将无法回到恢复前状态')

    odoo_ids = resolve_odoo_ids(args.odoo_user)
    if not args.no_chown and not args.keep_filestore and odoo_ids is None:
        raise OpsError('本机没有 %r 用户，无法修正归属。\n'
                       '  若确认不需要（例如容器内以 root 运行），显式传 --no-chown。'
                       % args.odoo_user)

    if args.dry_run:
        print('\n[dry-run] 将执行：')
        if not args.no_service:
            print('  1) 记录服务当前状态并 stop（验证已停止）')
        if existing and not args.no_pre_backup:
            print('  2) 对现存 %s 做恢复前成套备份（失败则中止，不 DROP）' % dbname)
        if existing:
            print('  3) 终止 %s 的连接并 DROP DATABASE' % dbname)
        print('  4) CREATE DATABASE %s OWNER %s' % (dbname, conf['db_user']))
        print('  5) pg_restore --exit-on-error')
        if not args.keep_filestore:
            print('  6) 旧 filestore 改名保留为 %s.pre-restore-<ts>，再安全解包新内容' % filestore)
        if not args.no_chown:
            print('  7) chown -R %s:%s 并校验生效' % (args.odoo_user, args.odoo_user))
        if not args.no_service:
            print('  8) 仅在 4-7 全部成功后，把服务恢复到原状态（并复核）')
        print('\n[dry-run] 未做任何修改。')
        return 0

    if os.geteuid() != 0:
        raise OpsError('请用 sudo 运行')

    stamp = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    moved_filestore = None
    originally_active = False
    service_stopped = False
    stamp_dir = None
    restored_ok = False
    pre_backup_path = None
    try:
        # ---------- 1) 服务
        if not args.no_service:
            service.require_available()
            state = service.is_active(unit)
            if state is None:
                raise OpsError('无法确认 %s 当前状态，拒绝在状态不明时进行破坏性恢复' % unit)
            originally_active = state
            print('\n---- 1) 停止服务并验证 ----')
            if originally_active:
                service.stop_verified(unit)
                service_stopped = True
                print('  已确认 %s inactive' % unit)
            else:
                print('  %s 本来就不是 active' % unit)
        else:
            print('\n---- 1) 按 --no-service 跳过服务控制 ----')

        # ---------- 2) 恢复前快照（服务已在上一步停止，子备份固定 --no-service）
        if existing and not args.no_pre_backup:
            pre_backup_path = run_pre_backup(conf, dbname, args.pre_backup_root)

        # ---------- 3) 重建数据库
        print('\n---- 2) 重建数据库 ----')
        if existing:
            run_psql(conf, "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                           "WHERE datname = :'dbname' AND pid <> pg_backend_pid()",
                     {'dbname': dbname})
            run_psql(conf, 'DROP DATABASE :"dbname"', {'dbname': dbname})
            print('  已 DROP %s' % dbname)
        run_psql(conf, 'CREATE DATABASE :"dbname" OWNER :"owner"',
                 {'dbname': dbname, 'owner': conf['db_user']})
        print('  已 CREATE %s (owner=%s)' % (dbname, conf['db_user']))

        # ---------- 4) pg_restore
        print('\n---- 3) 还原数据库 ----')
        env = {'PGPASSWORD': conf['db_password']} if conf['db_password'] else {}
        run([conf_mod.pg_tool('pg_restore'), '--exit-on-error', '--no-owner',
             '-h', conf['db_host'], '-p', conf['db_port'], '-U', conf['db_user'],
             '-d', dbname, str(pathlib.Path(backup_dir) / 'db.dump')], env=env)
        tables = run_psql(conf, "SELECT count(*) FROM information_schema.tables "
                                "WHERE table_schema='public'", None, dbname)
        print('  还原完成，public 表数量 = %s' % tables)
        if tables == '0':
            raise OpsError('还原后没有任何表，判定失败')

        # ---------- 5) filestore
        print('\n---- 4) 还原 filestore ----')
        if args.keep_filestore:
            print('  按 --keep-filestore 跳过')
        else:
            filestore.parent.mkdir(parents=True, exist_ok=True)
            if filestore.exists():
                moved_filestore = filestore.with_name(filestore.name + '.pre-restore-' + stamp)
                if moved_filestore.exists():
                    raise OpsError('保留目录已存在，拒绝覆盖：%s' % moved_filestore)
                filestore.rename(moved_filestore)
                print('  旧 filestore 保留为 %s' % moved_filestore)
            expected_root = manifest.get('filestore_archive_root') or dbname
            written = archive.safe_extract_tar(pathlib.Path(backup_dir) / 'filestore.tar.gz',
                                               filestore.parent, expected_root)
            if not filestore.exists():
                filestore.mkdir(parents=True, exist_ok=True)
                print('  归档中无该库目录（可能从未上传过文件），已建空目录')
            print('  已解包 %d 个文件' % written)

            # ---------- 6) 归属
            print('\n---- 5) 修正归属并校验 ----')
            if args.no_chown:
                print('  按 --no-chown 跳过')
            else:
                uid, gid = odoo_ids
                chown_and_verify(filestore, uid, gid)
                print('  归属已校验为 %s:%s（含递归子项）' % (uid, gid))

        restored_ok = True
    except BaseException as exc:
        print('\n!! 恢复失败：%s' % exc)
        if moved_filestore:
            print('   旧 filestore 仍在：%s' % moved_filestore)
        if pre_backup_path:
            print('   恢复前快照在：%s' % pre_backup_path)
        if service_stopped:
            print('   服务保持停机（不会带着半恢复的库对外服务）')
        print('   人工处理建议：')
        print('     1) 检查上面的错误；数据库可能处于中间态')
        print('     2) 需要回到恢复前状态：python3 %s --backup %s --db %s --yes'
              % (pathlib.Path(__file__).name, pre_backup_path or '<恢复前快照目录>', dbname))
        print('     3) 确认数据库就绪后再启动服务：systemctl start %s' % unit)
        raise

    # ---------- 7) 只有全部成功才恢复服务到原状态
    exit_code = 0
    if not args.no_service and originally_active:
        print('\n---- 6) 恢复服务到原状态并复核 ----')
        try:
            service.start_verified(unit)
            print('  已确认 %s active' % unit)
        except OpsError as exc:
            print('\n!! 数据已恢复，但**服务未能回到 active**：%s' % exc)
            print('   请手动检查：systemctl status %s --no-pager' % unit)
            exit_code = 3
    elif not args.no_service:
        print('\n---- 6) 服务原本非 active，保持停机 ----')

    print('\n==== 恢复完成 ====' if exit_code == 0 else '\n==== 恢复完成（服务异常，见上）====')
    print('  数据库   %s（备份点 %s）' % (dbname, manifest['created_utc']))
    if pre_backup_path:
        print('  恢复前快照 %s（确认无误后可自行清理）' % pre_backup_path)
    if moved_filestore:
        print('  旧 filestore %s（确认无误后可自行清理）' % moved_filestore)
    if restored_ok:
        print('  下一步：核对器件库/库存/流水是否为该备份点状态')
        print('          代码也要回滚时，用 MANIFEST 的 code_fingerprint 对照后再 -u')
    return exit_code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except OpsError as exc:
        print('\n错误：%s' % exc, file=sys.stderr)
        sys.exit(1)
