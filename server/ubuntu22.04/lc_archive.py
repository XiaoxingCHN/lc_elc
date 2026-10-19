# -*- coding: utf-8 -*-
"""备份归档的**预检与安全解包**。

root 审查指出的缺陷：原 ``verify_artifacts`` 允许缺 artifacts / 任意 name / 任意 path，
且用 ``tar.extractall`` —— 在 Ubuntu 22.04 的 Python 3.10 上**没有** ``filter='data'``
（3.12 才有），恶意/损坏归档里的绝对路径、``..``、符号链接、硬链接、设备文件都能逃逸。

本模块把校验做成纯函数，并且：
  * **在调用方做任何 DROP 之前**就能完整跑完（预检与执行分离）；
  * 解包改为**逐成员手工写出**，不使用 extractall；
  * 成员必须全部位于预期根目录之下，且只允许普通文件/目录。
"""
import hashlib
import json
import os
import pathlib
import shutil

from lc_odoo_conf import (MANIFEST_FORMAT, OpsError, REQUIRED_ARTIFACTS,
                          validate_db_identifier)


def sha256_file(path, chunk=1024 * 1024):
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for block in iter(lambda: fh.read(chunk), b''):
            digest.update(block)
    return digest.hexdigest()


# ------------------------------------------------------------------ MANIFEST 预检
def load_manifest(backup_dir):
    """读取并**结构校验** MANIFEST.json。任何异常都抛 OpsError。"""
    root = pathlib.Path(backup_dir)
    path = root / 'MANIFEST.json'
    if not path.is_file():
        raise OpsError('不是有效的备份目录（缺 MANIFEST.json）：%s' % root)
    try:
        manifest = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError) as exc:
        raise OpsError('MANIFEST.json 无法解析：%s' % exc)
    if not isinstance(manifest, dict):
        raise OpsError('MANIFEST.json 顶层不是对象')
    if manifest.get('format') != MANIFEST_FORMAT:
        raise OpsError('备份格式不受支持：format=%r（本脚本支持 %r）'
                       % (manifest.get('format'), MANIFEST_FORMAT))
    validate_db_identifier(manifest.get('database'), 'MANIFEST.database')

    # filestore 归档根目录：若给出，必须**严格等于** database。
    # 否则一份“合法库 dbA”的清单可声明 root=dbB，恢复时预检/解包会以 dbB 为根，
    # 在 DROP 之后把 dbB 成员写进另一个库的 filestore，再给 dbA 自动建空目录 —— 静默丢附件。
    # 因此：禁止空 / '.' / '..' / 相对 / 绝对 / 其他库根（都表现为 != database）。
    # 只有**缺字段**时才兼容取默认 database。
    far = manifest.get('filestore_archive_root')
    if far is not None:
        if not isinstance(far, str) or far != manifest['database']:
            raise OpsError(
                'MANIFEST.filestore_archive_root 非法：%r（必须严格等于 database %r；'
                '不允许空/相对/绝对/其他库根）' % (far, manifest['database']))

    artifacts = manifest.get('artifacts')
    if not isinstance(artifacts, dict) or not artifacts:
        raise OpsError('MANIFEST.artifacts 缺失或为空')
    names = set(artifacts)
    required = set(REQUIRED_ARTIFACTS)
    missing = sorted(required - names)
    if missing:
        raise OpsError('备份不完整，缺少必要产物：%s' % ', '.join(missing))
    extra = sorted(names - required)
    if extra:
        raise OpsError('MANIFEST.artifacts 含未预期条目：%s（拒绝处理来路不明的产物）'
                       % ', '.join(extra))
    for name, meta in artifacts.items():
        # 产物名必须是**纯文件名**：不能带目录、不能是绝对路径
        if not isinstance(name, str) or pathlib.PurePosixPath(name).name != name or name in ('.', '..'):
            raise OpsError('产物名不是纯文件名：%r' % (name,))
        if not isinstance(meta, dict):
            raise OpsError('产物 %s 的元数据不是对象' % name)
        for key in ('bytes', 'sha256'):
            if key not in meta:
                raise OpsError('产物 %s 缺少 %s' % (name, key))
        if not isinstance(meta['bytes'], int) or meta['bytes'] < 0:
            raise OpsError('产物 %s 的 bytes 非法：%r' % (name, meta['bytes']))
        digest = meta['sha256']
        if not isinstance(digest, str) or len(digest) != 64 or any(
                c not in '0123456789abcdef' for c in digest.lower()):
            raise OpsError('产物 %s 的 sha256 非法：%r' % (name, digest))
    return manifest, root


def verify_artifacts(manifest, backup_dir):
    """校验产物**存在、字节数一致、sha256 一致**；任何一个不符即抛错。

    必须在任何破坏性动作（DROP/CREATE/pg_restore/换 filestore）之前调用。
    """
    root = pathlib.Path(backup_dir).resolve(strict=False)
    checked = []
    for name, meta in manifest['artifacts'].items():
        path = (root / name)
        real = path.resolve(strict=False)
        if real != root and root not in real.parents:
            raise OpsError('产物路径逃出备份目录：%s' % real)
        if not path.is_file():
            raise OpsError('备份不完整，缺文件：%s' % path)
        size = path.stat().st_size
        if size != meta['bytes']:
            raise OpsError('字节数不符：%s（清单 %d，实际 %d）' % (path, meta['bytes'], size))
        actual = sha256_file(path)
        if actual != meta['sha256']:
            raise OpsError('sha256 校验失败：%s\n  清单 %s\n  实际 %s'
                           % (path, meta['sha256'], actual))
        checked.append(name)
    return checked


# ------------------------------------------------------------------ tar 预检与安全解包
def inspect_tar_members(tar, expected_root):
    """返回 (ok_members, problems)。只允许 expected_root 之下的普通文件/目录。

    禁止：绝对路径、``..``、符号链接、硬链接、设备/FIFO/字符设备、越界成员。
    """
    expected = pathlib.PurePosixPath(expected_root)
    ok, problems = [], []
    for member in tar.getmembers():
        name = member.name
        pure = pathlib.PurePosixPath(name)
        if pure.is_absolute():
            problems.append('绝对路径成员：%s' % name)
            continue
        if '..' in pure.parts:
            problems.append('含 .. 的成员：%s' % name)
            continue
        if member.issym():
            problems.append('符号链接成员：%s -> %s' % (name, member.linkname))
            continue
        if member.islnk():
            problems.append('硬链接成员：%s -> %s' % (name, member.linkname))
            continue
        if not (member.isfile() or member.isdir()):
            problems.append('非普通文件/目录成员：%s（type=%r）' % (name, member.type))
            continue
        if not (pure == expected or expected in pure.parents):
            problems.append('成员不在预期根 %s 之下：%s' % (expected_root, name))
            continue
        ok.append(member)
    return ok, problems


def safe_extract_tar(archive_path, target_parent, expected_root):
    """把归档安全解包到 ``target_parent``（归档内根目录为 ``expected_root``）。

    * 先整体预检，**有任何问题就一个字节都不写**；
    * 逐成员手工写出，不使用 ``tar.extractall``；
    * 返回解包出的文件数。
    """
    import tarfile
    target_parent = pathlib.Path(target_parent).resolve(strict=False)
    written = 0
    with tarfile.open(archive_path, 'r:gz') as tar:
        members, problems = inspect_tar_members(tar, expected_root)
        if problems:
            raise OpsError('归档预检未通过，已拒绝解包：\n  - ' + '\n  - '.join(problems[:20]))
        for member in members:
            dest = target_parent / pathlib.PurePosixPath(member.name)
            dest_real = dest.resolve(strict=False)
            if dest_real != target_parent and target_parent not in dest_real.parents:
                raise OpsError('解包目标逃出目录：%s' % dest_real)
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            if src is None:
                raise OpsError('归档成员无法读取：%s' % member.name)
            with open(dest, 'wb') as fh:
                shutil.copyfileobj(src, fh)
            os.chmod(dest, member.mode & 0o777)
            try:
                os.utime(dest, (member.mtime, member.mtime))
            except OSError:
                pass
            written += 1
    return written
