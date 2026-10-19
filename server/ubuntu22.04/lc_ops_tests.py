#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运维脚本的**轻量故障注入测试**（无需真实 PostgreSQL / systemd / Odoo）。

只验证失败路径与安全约束，不搭大 fixture：

  * 用伪 systemctl（``LC_SYSTEMCTL`` 指向桩脚本）注入 stop/start/状态异常；
  * 用进程内 monkeypatch 替换 ``run`` / ``run_psql``，制造命令失败；
  * 用微型 tar / MANIFEST 制造归档攻击（绝对路径、``..``、符号/硬链接、设备）。

覆盖 root 审查的 9 类缺陷：
  1. 停服务失败必须终止 dump/drop
  2. 恢复失败不得启动服务
  3. 必需 manifest / size / hash / 归档成员预检必须在 DROP 之前
  4. 数据库名严格校验 + 跨名恢复明确拒绝
  5. 现有库默认做恢复前快照（prebackup），且在 DROP 之前
  6. 升级脚本对三个模块做 preflight
  7. 升级脚本把自定义 --unit / --no-service 正确传给子进程
  8. 归属（ownership）修正必须校验生效
  9. 所有异常路径都以非零退出码结束

运行：``python3 lc_ops_tests.py``（退出码 0 = 全部通过）。
"""
import contextlib
import io
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lc_odoo_conf as conf_mod      # noqa: E402
import lc_archive as archive         # noqa: E402
import lc_service as service         # noqa: E402
import odoo_backup as backup_mod     # noqa: E402
import odoo_restore as restore_mod   # noqa: E402

OpsError = conf_mod.OpsError

_TOTAL = 0
_FAILED = 0
_TMPDIRS = []


def check(name, cond, detail=''):
    global _TOTAL, _FAILED
    _TOTAL += 1
    ok = bool(cond)
    if not ok:
        _FAILED += 1
    line = '%s  %s' % ('PASS' if ok else 'FAIL', name)
    if detail and not ok:
        line += '  [%s]' % detail
    print(line)
    return ok


def tmpdir(prefix='lc-ops-test-'):
    d = pathlib.Path(tempfile.mkdtemp(prefix=prefix))
    _TMPDIRS.append(d)
    return d


@contextlib.contextmanager
def patched(obj, **kw):
    old = {k: getattr(obj, k) for k in kw}
    for k, v in kw.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


@contextlib.contextmanager
def env_var(**kw):
    old = {k: os.environ.get(k) for k in kw}
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def capture(fn, *args, **kwargs):
    """运行 fn，吞掉 stdout/stderr，返回 (异常或 None, 输出文本)。"""
    out = io.StringIO()
    exc = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            fn(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001
            exc = e
    return exc, out.getvalue()


# ------------------------------------------------------------------ fixture 构造
def fake_systemctl(bindir, initial_active=True, stop_rc=0, start_rc=0, fixed_state=None):
    """伪 systemctl：把每次调用写进 log；is-active 读状态文件；stop/start 改状态。

    ``fixed_state`` 非空时 is-active **恒**返回该值（用于模拟持续 deactivating/activating），
    且 stop/start 不改变它。
    """
    bindir = pathlib.Path(bindir)
    bindir.mkdir(parents=True, exist_ok=True)
    exe = bindir / 'systemctl'
    log = bindir / 'sysctl.log'
    state = bindir / 'sysctl.state'
    log.write_text('', encoding='utf-8')
    if fixed_state is None:
        state.write_text('active' if initial_active else 'inactive', encoding='utf-8')
        lines = [
            '#!/bin/sh',
            'echo "$1 $2" >> "%s"' % log,
            'case "$1" in',
            '  is-active) cat "%s"; exit 0;;' % state,
            '  stop) if [ %d -ne 0 ]; then exit %d; fi; echo inactive > "%s"; exit 0;;'
            % (stop_rc, stop_rc, state),
            '  start) if [ %d -ne 0 ]; then exit %d; fi; echo active > "%s"; exit 0;;'
            % (start_rc, start_rc, state),
            'esac',
            'exit 0',
        ]
    else:
        lines = [
            '#!/bin/sh',
            'echo "$1 $2" >> "%s"' % log,
            'case "$1" in',
            '  is-active) echo "%s"; exit 0;;' % fixed_state,
            '  stop) exit %d;;' % stop_rc,
            '  start) exit %d;;' % start_rc,
            'esac',
            'exit 0',
        ]
    exe.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return str(exe), log, state


def make_config(path, addons, data_dir):
    path = pathlib.Path(path)
    path.write_text(
        '[options]\n'
        'addons_path = %s\n'
        'data_dir = %s\n'
        'db_host = /var/run/postgresql\n'
        'db_port = 5432\n'
        'db_user = odoo\n'
        'db_password = False\n'
        'logfile = %s\n' % (addons, data_dir, path.parent / 'odoo.log'),
        encoding='utf-8')
    return str(path)


def _write_tar(path, members):
    """members: [(name, type, linkname)]，type 为 tarfile 常量或 None(file)。"""
    with tarfile.open(path, 'w:gz') as tar:
        for name, typ, link in members:
            ti = tarfile.TarInfo(name)
            if typ is None:
                data = b'hello'
                ti.size = len(data)
                tar.addfile(ti, io.BytesIO(data))
            else:
                ti.type = typ
                ti.linkname = link
                tar.addfile(ti)
        # 保证至少一个普通文件，归档非空


def make_clean_tar(path, dbname):
    _write_tar(path, [('%s/f.txt' % dbname, None, '')])


def make_backup(root, dbname, tar_builder=None, db_bytes=b'DUMPDATA'):
    """生成一份**结构合法**的备份目录（产物 bytes/sha256 与 MANIFEST 自洽）。"""
    root = pathlib.Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / 'db.dump').write_bytes(db_bytes)
    tarp = root / 'filestore.tar.gz'
    (tar_builder or (lambda p: make_clean_tar(p, dbname)))(tarp)
    arts = {}
    for name in ('db.dump', 'filestore.tar.gz'):
        p = root / name
        arts[name] = {'bytes': p.stat().st_size, 'sha256': archive.sha256_file(p)}
    man = {
        'format': conf_mod.MANIFEST_FORMAT,
        'created_utc': '20260101T000000Z',
        'label': None,
        'database': dbname,
        'database_size_bytes': 1,
        'odoo_base_version': '19.0',
        'installed_modules': ['base|19.0|installed'],
        'filestore_root': '/var/lib/odoo/filestore',
        'filestore_archive_root': dbname,
        'filestore_files_bytes': 1,
        'addons_path': '/opt/odoo/custom-addons',
        'code_fingerprint': {},
        'service_managed': True,
        'service_unit': 'odoo.service',
        'service_was_active': True,
        'artifacts': arts,
    }
    (root / 'MANIFEST.json').write_text(json.dumps(man), encoding='utf-8')
    return man


def psql_stub(exists='1', tables='5', recorder=None):
    def stub(conf, sql, params=None, dbname='postgres', check=True):
        s = sql.strip()
        if recorder is not None:
            recorder.append(s)
        if 'pg_database WHERE datname' in s:
            return exists
        if 'pg_database_size' in s:
            return '1024'
        if 'DROP DATABASE' in s or 'CREATE DATABASE' in s or 'pg_terminate_backend' in s:
            return ''
        if 'information_schema.tables' in s:
            return tables
        return ''
    return stub


def run_restore(argv):
    old = sys.argv
    sys.argv = ['odoo_restore.py'] + list(argv)
    try:
        return restore_mod.main()
    finally:
        sys.argv = old


# ================================================================== 测试
def test_db_identifier():
    print('\n== T1 数据库名严格校验（缺陷 4）==')
    for good in ('LcHardwareHouse', '_x', 'a1', 'A' * 63):
        try:
            conf_mod.validate_db_identifier(good)
            check('接受合法库名 %r' % good, True)
        except OpsError:
            check('接受合法库名 %r' % good, False, '被误拒')
    for bad in ('', 'bad-name', '1abc', 'a' * 64, 'a;DROP', 'a b', 'a"b'):
        exc = None
        try:
            conf_mod.validate_db_identifier(bad)
        except OpsError as e:
            exc = e
        check('拒绝非法库名 %r' % bad, exc is not None, '未拒绝')


def test_manifest_structural():
    print('\n== T3 备份清单结构校验（缺陷 3）==')
    root = tmpdir() / 'b'
    make_backup(root, 'dbone')
    man, _ = archive.load_manifest(root)
    check('合法清单可加载', man['database'] == 'dbone')

    # 缺 MANIFEST
    r2 = tmpdir() / 'empty'; r2.mkdir()
    e, _ = capture(archive.load_manifest, r2)
    check('缺 MANIFEST.json 被拒', isinstance(e, OpsError))

    # format 错
    man_bad = dict(man); man_bad['format'] = 999
    (root / 'MANIFEST.json').write_text(json.dumps(man_bad), encoding='utf-8')
    e, _ = capture(archive.load_manifest, root)
    check('format 不受支持被拒', isinstance(e, OpsError))

    # 缺必需产物
    man_bad = json.loads(json.dumps(man)); man_bad['artifacts'].pop('filestore.tar.gz')
    (root / 'MANIFEST.json').write_text(json.dumps(man_bad), encoding='utf-8')
    e, _ = capture(archive.load_manifest, root)
    check('缺必需产物被拒', isinstance(e, OpsError))

    # 多余产物
    man_bad = json.loads(json.dumps(man)); man_bad['artifacts']['evil'] = {'bytes': 0, 'sha256': '0' * 64}
    (root / 'MANIFEST.json').write_text(json.dumps(man_bad), encoding='utf-8')
    e, _ = capture(archive.load_manifest, root)
    check('多余产物被拒', isinstance(e, OpsError))

    # 产物名带路径
    man_bad = json.loads(json.dumps(man))
    man_bad['artifacts'] = {'sub/db.dump': man['artifacts']['db.dump'],
                            'filestore.tar.gz': man['artifacts']['filestore.tar.gz']}
    (root / 'MANIFEST.json').write_text(json.dumps(man_bad), encoding='utf-8')
    e, _ = capture(archive.load_manifest, root)
    check('产物名非纯文件名被拒', isinstance(e, OpsError))

    # sha256 形态非法
    man_bad = json.loads(json.dumps(man)); man_bad['artifacts']['db.dump']['sha256'] = 'xyz'
    (root / 'MANIFEST.json').write_text(json.dumps(man_bad), encoding='utf-8')
    e, _ = capture(archive.load_manifest, root)
    check('sha256 形态非法被拒', isinstance(e, OpsError))

    # 字节数不符
    (root / 'MANIFEST.json').write_text(json.dumps(man), encoding='utf-8')
    man_bad = json.loads(json.dumps(man)); man_bad['artifacts']['db.dump']['bytes'] += 10
    e, _ = capture(archive.verify_artifacts, man_bad, root)
    check('字节数不符被拒', isinstance(e, OpsError))

    # sha256 不符
    man_bad = json.loads(json.dumps(man)); man_bad['artifacts']['db.dump']['sha256'] = 'a' * 64
    e, _ = capture(archive.verify_artifacts, man_bad, root)
    check('sha256 不符被拒', isinstance(e, OpsError))


def test_archive_members():
    print('\n== T4a 归档成员安全预检（缺陷 3）==')
    d = tmpdir()
    tarp = d / 'evil.tar.gz'
    db = 'dbx'
    with tarfile.open(tarp, 'w:gz') as tar:
        good = tarfile.TarInfo('%s/ok.txt' % db); good.size = 3
        tar.addfile(good, io.BytesIO(b'hey'))
        tar.addfile(tarfile.TarInfo('/etc/passwd'))                 # 绝对路径
        tar.addfile(tarfile.TarInfo('%s/../escape' % db))           # ..
        sym = tarfile.TarInfo('%s/sym' % db); sym.type = tarfile.SYMTYPE; sym.linkname = '/etc/passwd'
        tar.addfile(sym)                                            # 符号链接
        hln = tarfile.TarInfo('%s/hln' % db); hln.type = tarfile.LNKTYPE; hln.linkname = '%s/ok.txt' % db
        tar.addfile(hln)                                            # 硬链接
        chr_ = tarfile.TarInfo('%s/dev' % db); chr_.type = tarfile.CHRTYPE; chr_.devmajor = 1; chr_.devminor = 3
        tar.addfile(chr_)                                           # 字符设备
        fifo = tarfile.TarInfo('%s/fifo' % db); fifo.type = tarfile.FIFOTYPE
        tar.addfile(fifo)                                           # FIFO
        outside = tarfile.TarInfo('other/f.txt'); outside.size = 1
        tar.addfile(outside, io.BytesIO(b'x'))                      # 越界成员
    with tarfile.open(tarp, 'r:gz') as tar:
        ok, problems = archive.inspect_tar_members(tar, db)
    check('干净成员被接受', any(m.name == '%s/ok.txt' % db for m in ok))
    joined = '\n'.join(problems)
    for label, token in (('绝对路径', '绝对路径'), ('..', '..'), ('符号链接', '符号链接'),
                         ('硬链接', '硬链接'), ('设备/FIFO', '非普通'), ('越界', '不在预期根')):
        check('拒绝 %s 成员' % label, token in joined)
    # 干净归档应 0 problems
    clean = d / 'clean.tar.gz'; make_clean_tar(clean, db)
    with tarfile.open(clean, 'r:gz') as tar:
        ok2, problems2 = archive.inspect_tar_members(tar, db)
    check('干净归档无问题', not problems2 and ok2)


def test_restore_cross_name_and_precheck_before_drop():
    print('\n== T2/T4b 跨名拒绝 & 归档预检在 DROP 之前（缺陷 3、4）==')
    d = tmpdir()
    conf = make_config(d / 'odoo.conf', str(d), str(d / 'data'))
    db = 'dbalpha'

    # T2 跨名
    root = d / 'b1'; make_backup(root, db)
    psql_calls = []
    with patched(restore_mod, run_psql=psql_stub('1', '5', psql_calls)), \
            env_var(LC_SYSTEMCTL=None):
        exc, out = capture(run_restore, ['--backup', str(root), '--config', conf,
                                         '--db', 'dbbeta', '--yes', '--no-service'])
    check('跨名恢复被拒', isinstance(exc, OpsError), repr(exc))
    check('跨名拒绝信息指出不一致', '不一致' in str(exc))
    check('跨名拒绝未触及数据库（无 DROP）', not any('DROP' in s for s in psql_calls))

    # 非法库名
    with patched(restore_mod, run_psql=psql_stub('1', '5')), env_var(LC_SYSTEMCTL=None):
        exc, _ = capture(run_restore, ['--backup', str(root), '--config', conf,
                                       '--db', 'bad-name', '--yes', '--no-service'])
    check('非法目标库名被拒', isinstance(exc, OpsError))

    # T4b 恶意归档（符号链接）→ 预检必须拦下，且在任何 run_psql 之前
    evil = d / 'b2'
    make_backup(evil, db, tar_builder=lambda p: _write_tar(
        p, [('%s/sym' % db, tarfile.SYMTYPE, '/etc/passwd')]))
    psql_calls2 = []
    with patched(restore_mod, run_psql=psql_stub('1', '5', psql_calls2)), \
            env_var(LC_SYSTEMCTL=None):
        exc, out = capture(run_restore, ['--backup', str(evil), '--config', conf,
                                         '--db', db, '--yes', '--no-service', '--no-chown'])
    check('恶意归档恢复被拒', isinstance(exc, OpsError), repr(exc))
    check('拒绝原因含归档预检', '预检' in out or '符号链接' in out)
    check('恶意归档未触发任何 SQL（无 DROP）', not psql_calls2)


def test_default_prebackup_before_drop():
    print('\n== T5 现有库默认 prebackup，且在 DROP 之前（缺陷 5）==')
    d = tmpdir()
    conf = make_config(d / 'odoo.conf', str(d), str(d / 'data'))
    root = d / 'b'; make_backup(root, 'dbpre')
    psql_calls = []
    prebackup_calls = []

    def prebackup_stub(conf_, dbname, out_root):
        prebackup_calls.append((conf_, dbname, out_root))
        raise OpsError('SENTINEL-STOP-AFTER-PREBACKUP')

    with patched(restore_mod,
                 run_psql=psql_stub('1', '5', psql_calls),
                 run_pre_backup=prebackup_stub), \
            env_var(LC_SYSTEMCTL=None):
        exc, _ = capture(run_restore, ['--backup', str(root), '--config', conf,
                                       '--db', 'dbpre', '--yes', '--no-service', '--no-chown'])
    check('默认调用了恢复前快照', len(prebackup_calls) == 1, repr(prebackup_calls))
    check('恢复前快照参数为 (conf, db, out_root) 3 参',
          len(prebackup_calls) == 1 and len(prebackup_calls[0]) == 3)
    check('prebackup 在 DROP 之前（未发生 DROP）',
          not any('DROP' in s for s in psql_calls))
    check('prebackup 抛错后仍未 DROP', isinstance(exc, OpsError))


def test_no_prebackup_skips():
    print('\n== T5b --no-pre-backup 显式跳过（缺陷 5）==')
    d = tmpdir()
    conf = make_config(d / 'odoo.conf', str(d), str(d / 'data'))
    root = d / 'b'; make_backup(root, 'dbnp')
    psql_calls = []
    called = []

    def prebackup_stub(*a, **k):
        called.append(a)
        raise AssertionError('不应调用 prebackup')

    def run_stub(cmd, env=None, check=True):
        if any('pg_restore' in str(c) for c in cmd):
            raise OpsError('SENTINEL-STOP')
        return subprocess.CompletedProcess(cmd, 0, b'')

    with patched(restore_mod,
                 run_psql=psql_stub('1', '5', psql_calls),
                 run_pre_backup=prebackup_stub,
                 run=run_stub), \
            env_var(LC_SYSTEMCTL=None):
        exc, _ = capture(run_restore, ['--backup', str(root), '--config', conf,
                                       '--db', 'dbnp', '--yes', '--no-service',
                                       '--no-chown', '--no-pre-backup'])
    check('--no-pre-backup 时未调用快照', not called)
    check('--no-pre-backup 时照常 DROP', any('DROP' in s for s in psql_calls))


def test_restore_failure_must_not_start():
    print('\n== T2b 恢复失败不得启动服务（缺陷 2、1）==')
    d = tmpdir()
    conf = make_config(d / 'odoo.conf', str(d), str(d / 'data'))
    root = d / 'b'; make_backup(root, 'dbfail')
    exe, log, _state = fake_systemctl(d)

    def run_stub(cmd, env=None, check=True):
        if any('pg_restore' in str(c) for c in cmd):
            raise OpsError('模拟 pg_restore 失败')
        return subprocess.CompletedProcess(cmd, 0, b'')

    with patched(restore_mod, run_psql=psql_stub('1', '5'), run=run_stub), \
            env_var(LC_SYSTEMCTL=exe):
        exc, _ = capture(run_restore, ['--backup', str(root), '--config', conf,
                                       '--db', 'dbfail', '--yes', '--no-chown'])
    actions = log.read_text(encoding='utf-8')
    action_lines = [ln.split()[0] for ln in actions.splitlines() if ln.strip()]
    check('恢复失败抛出异常', isinstance(exc, OpsError), repr(exc))
    check('失败路径执行过 stop', 'stop' in action_lines, repr(action_lines))
    check('失败路径**未**执行 start', 'start' not in action_lines, repr(action_lines))


def test_restore_stop_failure_before_drop():
    print('\n== T1b 恢复端停服务失败 → 终止 DROP（缺陷 1）==')
    d = tmpdir()
    conf = make_config(d / 'odoo.conf', str(d), str(d / 'data'))
    root = d / 'b'; make_backup(root, 'dbstop')
    exe, log, _state = fake_systemctl(d, initial_active=True, stop_rc=1)
    psql_calls = []
    with patched(restore_mod, run_psql=psql_stub('1', '5', psql_calls)), \
            env_var(LC_SYSTEMCTL=exe):
        exc, out = capture(run_restore, ['--backup', str(root), '--config', conf,
                                         '--db', 'dbstop', '--yes', '--no-chown'])
    check('停服务失败时恢复中止', isinstance(exc, OpsError), repr(exc))
    check('停服务失败后未 DROP', not any('DROP' in s for s in psql_calls))


def test_backup_stop_failure_before_dump():
    print('\n== T9 备份端停服务失败 → 终止 dump（缺陷 1）==')
    d = tmpdir()
    addons = d / 'addons'; addons.mkdir()
    conf = make_config(d / 'odoo.conf', str(addons), str(d / 'data'))
    exe, log, _state = fake_systemctl(d, initial_active=True, stop_rc=1)
    ran = []

    def run_stub(cmd, env=None, check=True):
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b'')

    argv = ['odoo_backup.py', '--config', conf, '--db', 'dbbk', '--out-root',
            str(d / 'backups'), '--addons-path', str(addons), '--unit', 'odoo.service',
            '--label', 't']
    old = sys.argv
    sys.argv = argv
    try:
        with patched(backup_mod, run_psql=psql_stub('1', '1024'), run=run_stub), \
                env_var(LC_SYSTEMCTL=exe):
            exc, out = capture(backup_mod.main)
    finally:
        sys.argv = old
    check('备份端停服务失败即中止', isinstance(exc, OpsError), repr(exc))
    check('停服务失败后未调用 pg_dump', not any('pg_dump' in ' '.join(map(str, c)) for c in ran),
          repr(ran[:2]))
    check('未生成备份目录', not (d / 'backups').exists()
          or not any((d / 'backups').iterdir()))


def test_backup_restart_failure_exit3():
    print('\n== T10 备份成功但重启失败 → 退出码 3（缺陷 9）==')
    d = tmpdir()
    addons = d / 'addons'; addons.mkdir()
    (addons / 'lab_catalog').mkdir()
    data = d / 'data'; (data / 'filestore' / 'dbrt').mkdir(parents=True)
    (data / 'filestore' / 'dbrt' / 'f.txt').write_text('x')
    conf = make_config(d / 'odoo.conf', str(addons), str(data))
    exe, log, _state = fake_systemctl(d, initial_active=True, stop_rc=0, start_rc=1)
    tools = d / 'tools'; tools.mkdir()
    for t in ('pg_dump', 'pg_restore'):
        p = tools / t
        p.write_text('#!/bin/sh\nexit 0\n')
        p.chmod(0o755)

    def psql2(conf_, sql, params=None, dbname='postgres', check=True):
        s = sql.strip()
        if 'pg_database WHERE datname' in s:
            return '1'
        if 'pg_database_size' in s:
            return '2048'
        if 'ir_module_module WHERE state' in s:
            return 'lab_catalog|19.0|installed'
        if "name='base'" in s:
            return '19.0'
        return ''

    def run_stub(cmd, env=None, check=True):
        j = ' '.join(str(c) for c in cmd)
        if 'pg_dump' in j:
            i = [str(c) for c in cmd].index('-f')
            pathlib.Path(cmd[i + 1]).write_bytes(b'DUMP')
            return subprocess.CompletedProcess(cmd, 0, b'')
        if 'pg_restore' in j:
            return subprocess.CompletedProcess(cmd, 0, b'TABLE DATA\n')
        return subprocess.CompletedProcess(cmd, 0, b'')

    argv = ['odoo_backup.py', '--config', conf, '--db', 'dbrt', '--out-root',
            str(d / 'backups'), '--addons-path', str(addons), '--unit', 'odoo.service',
            '--label', 't']
    old = sys.argv
    sys.argv = argv
    try:
        with patched(backup_mod, run_psql=psql2, run=run_stub), \
                env_var(LC_SYSTEMCTL=exe,
                        LC_PG_PG_DUMP=str(tools / 'pg_dump'),
                        LC_PG_PG_RESTORE=str(tools / 'pg_restore')):
            exc, out = capture(backup_mod.main)
    finally:
        sys.argv = old
    check('备份完成后重启失败给出 SystemExit(3)',
          isinstance(exc, SystemExit) and exc.code == 3, repr(exc))
    check('重启失败前确实完成过 backup', '备份完成' in out or '重新启动' in out)


def test_chown_checked():
    print('\n== T11 归属修正必须校验生效（缺陷 8）==')
    d = tmpdir()
    tree = d / 'fs'; tree.mkdir()
    (tree / 'a.txt').write_text('x')
    (tree / 'sub').mkdir()
    (tree / 'sub' / 'b.txt').write_text('y')

    # 成功路径：root 自己 chown 到 0:0（当前即 root）→ 校验通过
    exc, _ = capture(restore_mod.chown_and_verify, tree, 0, 0)
    check('归属一致时校验通过', exc is None, repr(exc))

    # 失败路径：run 被替换成不做任何事 → 校验必须发现未生效
    def noop_run(cmd, env=None, check=True):
        return subprocess.CompletedProcess(cmd, 0, b'')
    with patched(restore_mod, run=noop_run):
        exc, _ = capture(restore_mod.chown_and_verify, tree, 4242, 4242)
    check('chown 未生效时校验失败', isinstance(exc, OpsError), repr(exc))

    check('resolve 不存在用户返回 None',
          restore_mod.resolve_odoo_ids('no-such-user-lc') is None)


# ------------------------------------------------------------------ 升级脚本（子进程）
def _upgrade_env(extra=None):
    env = os.environ.copy()
    env['LC_PYTHON'] = sys.executable
    env.setdefault('PATH', '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin')
    if extra:
        env.update(extra)
    return env


def run_upgrade(args, extra_env=None):
    proc = subprocess.run(['bash', str(HERE / 'upgrade_modules.sh')] + args,
                          env=_upgrade_env(extra_env),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, (proc.stdout or b'').decode('utf-8', 'replace')


def _make_addons(base, mods):
    base = pathlib.Path(base); base.mkdir(parents=True, exist_ok=True)
    for m in mods:
        md = base / m; md.mkdir(parents=True, exist_ok=True)
        (md / '__manifest__.py').write_text("{'name': '%s'}\n" % m)
    return str(base)


def test_upgrade_preflight_all_three():
    print('\n== T12 升级预检：三模块必须齐全（缺陷 6）==')
    d = tmpdir()
    addons = _make_addons(d / 'addons', ['lab_inventory', 'lab_catalog'])  # 缺 lab_workflow
    conf = make_config(d / 'odoo.conf', addons, str(d / 'data'))
    marker = d / 'backup-called'
    stub = d / 'backup_stub.sh'
    stub.write_text('#!/bin/sh\n: > "%s"\nexit 0\n' % marker)
    rc, out = run_upgrade(['--no-service', '--config', conf, '--addons', addons],
                          {'LC_BACKUP_SCRIPT': str(stub)})
    check('缺模块时升级非零退出', rc != 0, 'rc=%s' % rc)
    check('预检信息出现', '预检失败' in out)
    check('预检失败时未调用备份', not marker.exists())


def test_upgrade_passthrough_no_service():
    print('\n== T13 升级把 --no-service 传给子备份（缺陷 7）==')
    d = tmpdir()
    addons = _make_addons(d / 'addons', ['lab_inventory', 'lab_catalog', 'lab_workflow'])
    conf = make_config(d / 'odoo.conf', addons, str(d / 'data'))
    argslog = d / 'backup_args'
    stub = d / 'backup_stub.py'
    stub.write_text('import sys\n'
                    'open(%r, "w").write(" ".join(sys.argv[1:]))\n'
                    'sys.exit(1)\n' % str(argslog))
    rc, out = run_upgrade(['--no-service', '--config', conf, '--addons', addons],
                          {'LC_BACKUP_SCRIPT': str(stub)})
    got = argslog.read_text() if argslog.exists() else ''
    check('子备份收到 --no-service', '--no-service' in got, repr(got))
    check('子备份未收到 --unit', '--unit' not in got, repr(got))
    check('备份桩失败使升级非零退出', rc != 0, 'rc=%s' % rc)


def test_upgrade_passthrough_custom_unit():
    print('\n== T14 升级把自定义 --unit 传给子备份（缺陷 7）==')
    d = tmpdir()
    addons = _make_addons(d / 'addons', ['lab_inventory', 'lab_catalog', 'lab_workflow'])
    conf = make_config(d / 'odoo.conf', addons, str(d / 'data'))
    argslog = d / 'backup_args'
    stub = d / 'backup_stub.py'
    stub.write_text('import sys\n'
                    'open(%r, "w").write(" ".join(sys.argv[1:]))\n'
                    'sys.exit(1)\n' % str(argslog))
    rc, out = run_upgrade(['--unit', 'myodoo.service', '--config', conf, '--addons', addons],
                          {'LC_BACKUP_SCRIPT': str(stub)})
    got = argslog.read_text() if argslog.exists() else ''
    check('子备份收到自定义 --unit myodoo.service',
          '--unit' in got and 'myodoo.service' in got, repr(got))
    check('子备份未收到 --no-service', '--no-service' not in got, repr(got))
    check('备份桩失败使升级非零退出', rc != 0, 'rc=%s' % rc)


def test_upgrade_preserves_source_outside_addons():
    print('\n== 升级保留源码不得被 Odoo 当模块扫描 ==')
    d = tmpdir()
    mods = ['lab_inventory', 'lab_catalog', 'lab_workflow']
    addons = pathlib.Path(_make_addons(d / 'addons', mods))
    incoming = pathlib.Path(_make_addons(d / 'incoming', mods))
    for mod in mods:
        (addons / mod / 'generation').write_text('old')
        (incoming / mod / 'generation').write_text('new')
    backup = d / 'backups' / 'point'; backup.mkdir(parents=True)
    conf = make_config(d / 'odoo.conf', str(addons), str(d / 'data'))
    stub = d / 'backup_stub.py'
    stub.write_text('print(%r)\n' % ('  目录    ' + str(backup)))
    fake = d / 'odoo-bin'
    fake.write_text('import pathlib,re\n'
                    'root=pathlib.Path(%r)\n'
                    'assert all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*",p.name) '
                    'for p in root.iterdir() if (p/"__manifest__.py").exists())\n'
                    % str(addons))
    rc, out = run_upgrade(['--no-service', '--config', conf, '--addons', str(addons),
                           '--code-dir', str(incoming)],
                          {'LC_BACKUP_SCRIPT': str(stub), 'LC_ODOO_BIN': str(fake)})
    check('模块扫描桩与升级完成', rc == 0, out[-1200:])
    check('addons根只含当前三模块', {p.name for p in addons.iterdir()} == set(mods))
    check('完整旧源码位于配套备份之外层扫描范围', all(
        (backup / 'module-source-before-upgrade' / mod / 'generation').read_text() == 'old'
        for mod in mods))
    check('当前模块已换为新源码', all(
        (addons / mod / 'generation').read_text() == 'new' for mod in mods))
    parsed = conf_mod.load(conf)
    for label, location in [('当前addons', addons), ('另一个扫描根', d / 'other-addons')]:
        location.mkdir(exist_ok=True)
        local = dict(parsed, addons_path=str(addons) + ',' + str(d / 'other-addons'))
        error, _ = capture(conf_mod.prepare_code_backup, local, addons, location)
        check('拒绝备份落入' + label, isinstance(error, OpsError), repr(error))
    error, _ = capture(conf_mod.prepare_code_backup, parsed, addons, backup)
    check('已有源码备份拒绝覆盖', isinstance(error, OpsError), repr(error))
    escaped = d / 'escaped'; escaped.mkdir()
    symlink_backup = d / 'symlink-backup'; symlink_backup.mkdir()
    (symlink_backup / 'module-source-before-upgrade').symlink_to(escaped, target_is_directory=True)
    error, _ = capture(conf_mod.prepare_code_backup, parsed, addons, symlink_backup)
    check('拒绝符号链接越过备份根', isinstance(error, OpsError), repr(error))


def test_is_active_deactivating():
    print('\n== T17 deactivating/activating 不得当作已停机（缺陷 1）==')
    d = tmpdir()
    for st in ('deactivating', 'activating'):
        exe, _l, _s = fake_systemctl(d / ('s-' + st), fixed_state=st)
        with env_var(LC_SYSTEMCTL=exe):
            check('is_active(%r) → None（状态不明）' % st,
                  service.is_active('odoo.service') is None)
    for st in ('inactive', 'failed'):
        exe, _l, _s = fake_systemctl(d / ('s-' + st), fixed_state=st)
        with env_var(LC_SYSTEMCTL=exe):
            check('is_active(%r) → False（确认停机）' % st,
                  service.is_active('odoo.service') is False)
    exe, _l, _s = fake_systemctl(d / 's-active', fixed_state='active')
    with env_var(LC_SYSTEMCTL=exe):
        check('is_active(active) → True', service.is_active('odoo.service') is True)

    # stop 返回 0，但状态持续 deactivating → stop_verified 绝不能宣告已停机
    exe, _l, _s = fake_systemctl(d / 's-stopdeact', fixed_state='deactivating', stop_rc=0)
    with env_var(LC_SYSTEMCTL=exe):
        e = None
        try:
            service.stop_verified('odoo.service', retries=2, delay=0.05)
        except OpsError as ex:
            e = ex
        check('stop 后持续 deactivating → stop_verified 拒绝当停机', isinstance(e, OpsError),
              repr(e))


def test_deactivating_no_dump_no_drop():
    print('\n== T17b deactivating：备份不 dump、恢复不 DROP（缺陷 1）==')
    d = tmpdir()
    addons = d / 'addons'; addons.mkdir()
    conf = make_config(d / 'odoo.conf', str(addons), str(d / 'data'))

    # 备份：is-active=deactivating → 无法确认停机 → 中止，且未 pg_dump
    exe, _l, _s = fake_systemctl(d / 'sys-bk', fixed_state='deactivating')
    ran = []

    def run_stub(cmd, env=None, check=True, input=None):
        ran.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, b'')

    argv = ['odoo_backup.py', '--config', conf, '--db', 'dbdeact', '--out-root',
            str(d / 'backups'), '--addons-path', str(addons), '--unit', 'odoo.service',
            '--label', 't']
    old = sys.argv; sys.argv = argv
    try:
        with patched(backup_mod, run_psql=psql_stub('1', '1024'), run=run_stub), \
                env_var(LC_SYSTEMCTL=exe):
            exc, _out = capture(backup_mod.main)
    finally:
        sys.argv = old
    check('备份：deactivating 时中止', isinstance(exc, OpsError), repr(exc))
    check('备份：deactivating 时未 pg_dump',
          not any('pg_dump' in ' '.join(map(str, c)) for c in ran))

    # 恢复：is-active=deactivating → 状态不明 → 中止，且无 DROP
    root = d / 'rb'; make_backup(root, 'dbdeact')
    exe2, _l2, _s2 = fake_systemctl(d / 'sys-rs', fixed_state='deactivating')
    psql_calls = []
    with patched(restore_mod, run_psql=psql_stub('1', '5', psql_calls)), \
            env_var(LC_SYSTEMCTL=exe2):
        exc2, _ = capture(run_restore, ['--backup', str(root), '--config', conf,
                                        '--db', 'dbdeact', '--yes', '--no-chown'])
    check('恢复：deactivating 时中止', isinstance(exc2, OpsError), repr(exc2))
    check('恢复：deactivating 时未 DROP', not any('DROP' in s for s in psql_calls))


def test_manifest_archive_root_enforced():
    print('\n== T18 filestore_archive_root 必须严格等于 database（缺陷 2）==')
    d = tmpdir()
    root = d / 'b'; make_backup(root, 'dbA')
    base = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))

    def write(m):
        (root / 'MANIFEST.json').write_text(json.dumps(m), encoding='utf-8')

    m = json.loads(json.dumps(base)); m['filestore_archive_root'] = 'dbB'; write(m)
    e, _ = capture(archive.load_manifest, root)
    check('root=其他库(dbB) 被拒', isinstance(e, OpsError), repr(e))

    for bad in ('', '.', '..', '/abs', 'dbA/..', 'DBa', 'dbA ', 'dbA/.', './dbA'):
        m = json.loads(json.dumps(base)); m['filestore_archive_root'] = bad; write(m)
        e, _ = capture(archive.load_manifest, root)
        check('root=%r 被拒' % bad, isinstance(e, OpsError), repr(e))

    m = json.loads(json.dumps(base)); m.pop('filestore_archive_root', None); write(m)
    mm, _ = archive.load_manifest(root)
    check('缺该字段 → 兼容默认 database', mm['database'] == 'dbA')

    # 真实 tar：成员在 dbB/ 下、artifact bytes/sha256 自洽（能过 verify_artifacts）→ 恢复
    # 必须在任何 SQL/DROP 与写文件之前拒绝，且目标库(dbA)/旁库(dbB) filestore 均未被创建。
    evil = d / 'evil'
    make_backup(evil, 'dbA',
                tar_builder=lambda p: _write_tar(p, [('dbB/image.jpg', None, '')]))
    em = json.loads((evil / 'MANIFEST.json').read_text(encoding='utf-8'))
    em['filestore_archive_root'] = 'dbB'
    (evil / 'MANIFEST.json').write_text(json.dumps(em), encoding='utf-8')
    data = d / 'data'
    conf = make_config(d / 'odoo2.conf', str(d / 'addons2'), str(data))
    psql_calls = []
    with patched(restore_mod, run_psql=psql_stub('1', '5', psql_calls)), \
            env_var(LC_SYSTEMCTL=None):
        exc, out = capture(run_restore, ['--backup', str(evil), '--config', conf,
                                         '--db', 'dbA', '--yes', '--no-service',
                                         '--no-chown'])
    check('root 不符的清单恢复被拒', isinstance(exc, OpsError), repr(exc))
    check('拒绝发生在任何 SQL/DROP 之前', not psql_calls, repr(psql_calls))
    check('未创建目标库 filestore(dbA)', not (data / 'filestore' / 'dbA').exists())
    check('未创建旁库 filestore(dbB)', not (data / 'filestore' / 'dbB').exists())


def test_run_psql_uses_stdin():
    print('\n== T16 run_psql 必须用 -f - 且带 ON_ERROR_STOP（防回归）==')
    for mod, name in ((backup_mod, 'odoo_backup'), (restore_mod, 'odoo_restore')):
        captured = {}

        def fake_run(cmd, env=None, check=True, input=None):
            captured['cmd'] = list(cmd)
            captured['input'] = input
            return subprocess.CompletedProcess(cmd, 0, b'1\n')

        conf = {'db_host': '/var/run/postgresql', 'db_port': '5432',
                'db_user': 'odoo', 'db_password': None}
        with patched(mod, run=fake_run), \
                patched(conf_mod, pg_tool=lambda n, version='14': '/bin/true'):
            out = mod.run_psql(conf, "SELECT 1 FROM pg_database WHERE datname = :'dbname'",
                               {'dbname': 'probe_db'}, 'postgres')
        cmd = captured['cmd']
        inp = captured['input'] or b''
        check('%s: 不使用 -c（psql -c 不插值变量）' % name, '-c' not in cmd, repr(cmd))
        check('%s: 使用 -f -' % name,
              '-f' in cmd and cmd[cmd.index('-f') + 1] == '-', repr(cmd))
        check('%s: 传 ON_ERROR_STOP=1' % name, 'ON_ERROR_STOP=1' in cmd, repr(cmd))
        check('%s: SQL 经 stdin 传入并保留占位符' % name,
              b":'dbname'" in inp and inp.rstrip().endswith(b';'), repr(inp))
        check('%s: 正常返回 stdout' % name, out == '1', repr(out))


def test_all_exceptions_nonzero_exit():
    print('\n== T15 所有异常路径非零退出（缺陷 9）==')
    d = tmpdir()
    addons = d / 'addons'; addons.mkdir()
    conf = make_config(d / 'odoo.conf', str(addons), str(d / 'data'))
    env = os.environ.copy()
    env['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'

    p1 = subprocess.run([sys.executable, str(HERE / 'odoo_backup.py'),
                         '--config', conf, '--db', 'bad-name', '--no-service',
                         '--addons-path', str(addons)], env=env,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    check('备份：非法库名 → 退出码非 0', p1.returncode != 0, 'rc=%s' % p1.returncode)

    p2 = subprocess.run([sys.executable, str(HERE / 'odoo_restore.py'),
                         '--backup', str(d / 'nope'), '--db', 'x', '--yes'],
                        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    check('恢复：无清单目录 → 退出码非 0', p2.returncode != 0, 'rc=%s' % p2.returncode)


def main():
    print('============================================================')
    print(' 运维脚本轻量故障注入测试')
    print('============================================================')
    if os.geteuid() != 0:
        print('WARN 非 root 运行，部分测试（服务/权限）可能不适用')
    for fn in (
        test_db_identifier,
        test_manifest_structural,
        test_archive_members,
        test_restore_cross_name_and_precheck_before_drop,
        test_default_prebackup_before_drop,
        test_no_prebackup_skips,
        test_restore_failure_must_not_start,
        test_restore_stop_failure_before_drop,
        test_backup_stop_failure_before_dump,
        test_backup_restart_failure_exit3,
        test_chown_checked,
        test_is_active_deactivating,
        test_deactivating_no_dump_no_drop,
        test_manifest_archive_root_enforced,
        test_upgrade_preflight_all_three,
        test_upgrade_passthrough_no_service,
        test_upgrade_passthrough_custom_unit,
        test_upgrade_preserves_source_outside_addons,
        test_run_psql_uses_stdin,
        test_all_exceptions_nonzero_exit,
    ):
        try:
            fn()
        except BaseException as e:  # noqa: BLE001
            check('%s 未抛异常地跑完' % fn.__name__, False, 'crash: %r' % (e,))
    print('\n============================================================')
    print(' 检查项：%d   失败：%d' % (_TOTAL, _FAILED))
    print('============================================================')
    for dd in _TMPDIRS:
        shutil.rmtree(dd, ignore_errors=True)
    print('TESTS_TOTAL=%d TESTS_FAILED=%d' % (_TOTAL, _FAILED))
    rc = 1 if _FAILED else 0
    # 便于 CI/验证脚本在无法读取 $? 的环境里拿到真实退出码
    rc_out = os.environ.get('LC_OPS_RC_OUT')
    if rc_out:
        with open(rc_out, 'w', encoding='utf-8') as fh:
            fh.write('%d\n' % rc)
    return rc


if __name__ == '__main__':
    sys.exit(main())
