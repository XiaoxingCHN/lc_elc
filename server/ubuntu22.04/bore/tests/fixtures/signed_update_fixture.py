#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P2 合成更新清单夹具：真实 Ed25519 签名 + 独立公钥验证（仅隔离测试）。

生成（默认子命令，兼容旧 --root/--keys/--evidence 调用）：<root>/android/universal/
stable.json 与 <root>/releases/<rel>/manifest.json + <filename>。
独立验证：verify --manifest <m.json> --public-key-evidence <seed-evidence/signing.json>；
成功 stdout 只输出安全 JSON 摘要并 exit 0，失败 exit 1，不输出私钥或响应正文。
契约来源只按源码：lab_workflow/tools/client_release.py 与 update_manifest.dart。
安全边界：只接受 test-only 身份（release-id 前缀 test-、key-id 含 test-only）；私钥只写
--keys(0700) 下固定文件(0600)，从不打印/不写证据/不进 Git；拒绝符号链接链与
release-id/filename/key-id 穿越；临时文件用 TemporaryDirectory/mkstemp（不用 mktemp），
只清理自己创建的文件；合成包不是可安装 APK，不用于生产发布。私钥目录 chmod 0700/0600
尽力而为：DrvFs/9p 等文件系统可能忽略权限，证据里记录实测模式。
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP_ID = "com.example.lab_inventory_client"
SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,100}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")
SPKI_DER_LEN = len(SPKI_PREFIX) + 32
PRIVATE_KEY_NAME = "p2-test-ed25519.pem"
PACKAGE = b"P2-SYNTHETIC-UPDATE-PACKAGE-NOT-A-REAL-APK-0123456789\n"
EVIDENCE_SCHEMA = "p2-signed-update-fixture/1"
MAX_JSON = 65536


class FixtureError(Exception):
    def __init__(self, message, code=2):
        Exception.__init__(self, message)
        self.code = code


def _fail(message, code=2):
    raise FixtureError(message, code)


# ------------------------------------------------------- 路径/临时文件安全 ---
def _no_symlink(path):
    p = Path(os.path.abspath(str(path)))
    return not any(item.is_symlink() for item in [p] + list(p.parents))


def _within(root, child):
    """realpath 级别包含关系；用于拒绝 root/keys 交叉与逃逸。"""
    root, child = os.path.realpath(str(root)), os.path.realpath(str(child))
    return child == root or child.startswith(root + os.sep)


def _safe_path(raw, label, code=2, create_dir=False):
    """绝对路径 + 整条链无符号链接；create_dir 时按需建目录，否则要求普通文件。"""
    if not os.path.isabs(raw):
        _fail("%s 必须是绝对路径" % label, code)
    p = Path(os.path.abspath(raw))
    if create_dir and not p.exists():
        p.mkdir(parents=True)
    if not _no_symlink(p):
        _fail("%s 禁止符号链接链" % label, code)
    if create_dir:
        if not p.is_dir() or os.path.realpath(str(p)) != str(p):
            _fail("%s 必须是原路径普通目录" % label, code)
    elif p.exists() and not p.is_file():
        _fail("%s 必须是普通文件" % label, code)
    return p


def _atomic_write(path, data, mode=0o600):
    """mkstemp + os.replace：只清理本次自己创建的临时文件。"""
    fd, tmp = tempfile.mkstemp(prefix=".fixture-", dir=str(Path(path).parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ------------------------------------------------------------- Ed25519 后端 ---
def _backend():
    """优先成熟 cryptography（本机 3.4.8）；缺失时才回退 openssl CLI。"""
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        if ed25519.Ed25519PrivateKey is not None:
            return "cryptography"
    except Exception:
        pass
    if shutil.which("openssl"):
        return "openssl"
    _fail("BLOCKED: 需要 cryptography 或 openssl 才能做真实 Ed25519 签名", 3)


def _load_key(backend, priv):
    """返回 (签名句柄, 32 字节公钥)；私钥缺失时生成 0600 PEM。"""
    priv = Path(priv)
    if backend == "cryptography":
        from cryptography.hazmat.primitives import serialization as ser
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        if priv.exists():
            os.chmod(str(priv), 0o600)
            try:
                key = ser.load_pem_private_key(priv.read_bytes(), password=None)
            except Exception:
                _fail("私钥无法解析（不是有效 Ed25519 PEM）", 3)
            if not isinstance(key, Ed25519PrivateKey):
                _fail("私钥不是 Ed25519", 3)
        else:
            key = Ed25519PrivateKey.generate()
            _atomic_write(priv, key.private_bytes(
                encoding=ser.Encoding.PEM, format=ser.PrivateFormat.PKCS8,
                encryption_algorithm=ser.NoEncryption()), 0o600)
        raw = key.public_key().public_bytes(
            encoding=ser.Encoding.Raw, format=ser.PublicFormat.Raw)
        if len(raw) != 32:
            _fail("公钥原始长度不是 32 字节", 3)
        return key, raw
    if not priv.exists():
        fd, staged = tempfile.mkstemp(prefix="p2key-")  # 自有临时文件，用完即删
        os.close(fd)
        try:
            subprocess.run(["openssl", "genpkey", "-algorithm", "ED25519", "-out", staged],
                           check=True, capture_output=True)
            _atomic_write(priv, Path(staged).read_bytes(), 0o600)
        finally:
            os.unlink(staged)
    os.chmod(str(priv), 0o600)
    der = subprocess.run(["openssl", "pkey", "-in", str(priv), "-pubout", "-outform", "DER"],
                         capture_output=True, check=True).stdout
    raw = der[len(SPKI_PREFIX):]
    if len(der) != SPKI_DER_LEN or not der.startswith(SPKI_PREFIX) or len(raw) != 32:
        _fail("公钥 DER 不是 Ed25519 SPKI（长度/前缀不符），拒绝使用", 3)
    return str(priv), raw


def _openssl_run(mode, key, message, signature=None):
    """在私有 TemporaryDirectory 内调用 openssl；退出即自动清理。"""
    with tempfile.TemporaryDirectory(prefix="p2ossl-") as staging:
        work = Path(staging)
        msg, sig, spki = work / "m.bin", work / "m.sig", work / "k.der"
        msg.write_bytes(message)
        if mode == "sign":
            args = ["-inkey", str(key), "-out", str(sig)]
        else:
            spki.write_bytes(SPKI_PREFIX + key)
            sig.write_bytes(signature)
            args = ["-inkey", str(spki), "-pubin", "-keyform", "DER", "-sigfile", str(sig)]
        done = subprocess.run(["openssl", "pkeyutl", "-" + mode, "-rawin", "-in", str(msg)] + args,
                              capture_output=True)
        if mode == "sign":
            done.check_returncode()
            return sig.read_bytes()
        return done.returncode == 0


def _verify_signature(backend, pub_raw, message, signature):
    """只用公钥独立验证；不信任签名函数的返回值。签名覆盖 payload 原始字节。"""
    if len(pub_raw) != 32:
        _fail("公钥原始长度不是 32 字节", 3)
    if backend == "openssl":
        return _openssl_run("verify", pub_raw, message, signature)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    try:
        Ed25519PublicKey.from_public_bytes(pub_raw).verify(signature, message)
        return True
    except Exception:
        return False


# --------------------------------------------------------------- 生成 ---
def _safe_name(label, value, code=2, prefix=None, suffix=None, needle=None):
    """契约 SAFE 正则 + 合成身份约束；前缀/后缀/子串限定 test-only 身份。"""
    if not isinstance(value, str) or not SAFE.fullmatch(value) or value in (".", ".."):
        _fail("%s 非法：只允许 [A-Za-z0-9][A-Za-z0-9._+-]* 且禁止穿越" % label, code)
    if prefix and not value.startswith(prefix):
        _fail("%s 必须以 %s 开头（不冒充 stable 发布）" % (label, prefix), code)
    if suffix and not value.endswith(suffix):
        _fail("%s 必须以 %s 结尾（合成非可安装包）" % (label, suffix), code)
    if needle and needle not in value:
        _fail("%s 必须显式包含 %s" % (label, needle), code)


def generate(args):
    backend = _backend()
    _safe_name("release-id", args.release_id, prefix="test-")
    _safe_name("filename", args.filename, suffix=".apk")
    _safe_name("key-id", args.key_id, needle="test-only")
    root = _safe_path(args.root, "--root", create_dir=True)
    keys = _safe_path(args.keys, "--keys", create_dir=True)
    os.chmod(str(keys), 0o700)
    if str(root) == "/" or _within(root, keys) or _within(keys, root):
        _fail("--root 与 --keys 不能互相包含，且 --root 不能是根")
    rel_dir = _safe_path(root / "releases" / args.release_id, "release 目录", create_dir=True)
    universal = _safe_path(root / "android" / "universal", "android/universal", create_dir=True)
    if not _within(root, rel_dir):
        _fail("release 目录逃逸出 root")

    priv_path = _safe_path(keys / PRIVATE_KEY_NAME, "私钥")
    key, pub_raw = _load_key(backend, priv_path)
    _atomic_write(_safe_path(rel_dir / args.filename, "asset"), PACKAGE, 0o644)
    sha = hashlib.sha256(PACKAGE).hexdigest()

    payload_bytes = json.dumps({
        "schema": 1, "app_id": APP_ID, "platform": "android", "arch": "universal",
        "channel": "stable", "package_type": "apk", "api_min": 1, "api_max": 99,
        "release_id": args.release_id, "filename": args.filename, "size": len(PACKAGE),
        "sha256": sha, "build_number": args.build_number,
        "release_sequence": args.release_sequence, "version": args.version,
        "requirements": {}, "notes": "P2 synthetic test payload; never a real client update",
    }, ensure_ascii=False).encode("utf-8")
    signature = (key.sign(payload_bytes) if backend == "cryptography"
                 else _openssl_run("sign", key, payload_bytes))
    if len(signature) != 64:
        _fail("签名长度不是 64 字节")
    if not _verify_signature(backend, pub_raw, payload_bytes, signature):
        _fail("公钥独立验证失败：签名无效", 3)
    envelope = {"key_id": args.key_id,
                "payload": base64.b64encode(payload_bytes).decode("ascii"),
                "signature": base64.b64encode(signature).decode("ascii")}
    body = json.dumps(envelope, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
    for target in (universal / "stable.json", rel_dir / "manifest.json"):
        _atomic_write(_safe_path(target, "manifest"), body, 0o644)

    evidence = dict(
        [(k, vars(args)[k]) for k in ("release_id", "filename", "version", "build_number",
                                      "release_sequence", "key_id")],
        schema=EVIDENCE_SCHEMA, backend=backend, key_test_only=True,
        public_key_base64=base64.b64encode(pub_raw).decode("ascii"),
        public_key_sha256=hashlib.sha256(pub_raw).hexdigest(),
        signature_base64=envelope["signature"], signature_verified_by_public_key=True,
        signature_sha256=hashlib.sha256(signature).hexdigest(),
        payload_sha256=hashlib.sha256(payload_bytes).hexdigest(),
        package_sha256=sha, package_size=len(PACKAGE), private_key_exported=False,
        # DrvFs/9p 可能忽略 chmod；记录实测模式而非宣称 0600
        private_key_mode=oct(Path(priv_path).stat().st_mode & 0o777),
        note="local test-only Ed25519 key; not a release identity; never printed or exported")
    if args.evidence:
        target = _safe_path(args.evidence, "--evidence")
        if _within(keys, target):
            _fail("--evidence 不能写入私钥目录")
        _safe_path(str(target.parent), "--evidence 目录", create_dir=True)
        _atomic_write(target, json.dumps(evidence, ensure_ascii=False, indent=2,
                                         sort_keys=True).encode("utf-8") + b"\n")
    print("FIXTURE " + json.dumps(evidence, ensure_ascii=False, sort_keys=True))
    return 0


# --------------------------------------------------------------- 验证 ---
def _read_json(path, label):
    p = _safe_path(path, label, 1)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.stat().st_size <= MAX_JSON else None
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _b64(value, label, length=None):
    """严格 base64（validate=True）并按需校验解码长度。"""
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True) if value else None
    except Exception:
        raw = None
    if raw is None or (length is not None and len(raw) != length):
        _fail("%s 不是严格 base64 或长度不符" % label, 1)
    return raw


def verify(args):
    ev = _read_json(args.public_key_evidence, "--public-key-evidence")
    if not isinstance(ev, dict) or ev.get("schema") != EVIDENCE_SCHEMA \
            or ev.get("key_test_only") is not True:
        _fail("公钥证据必须是 test-only 且结构符合 %s" % EVIDENCE_SCHEMA, 1)
    key_id = ev.get("key_id")
    if not isinstance(key_id, str) or not SAFE.fullmatch(key_id) or "test-only" not in key_id:
        _fail("证据 key_id 非法或未声明 test-only", 1)
    pub_raw = _b64(ev.get("public_key_base64"), "证据公钥", 32)
    if hashlib.sha256(pub_raw).hexdigest() != ev.get("public_key_sha256"):
        _fail("证据公钥指纹不匹配", 1)

    env = _read_json(args.manifest, "--manifest")
    if not isinstance(env, dict) or len(json.dumps(env)) > MAX_JSON:
        _fail("manifest 信封非法", 1)
    if env.get("key_id") != key_id:
        _fail("manifest key_id 与公钥证据不匹配", 1)
    payload = _b64(env.get("payload"), "payload")
    signature = _b64(env.get("signature"), "signature", 64)
    if signature == b"\x00" * 64:
        _fail("签名为全零（伪造）", 1)

    # 先做纯密码学验证，再核对证据摘要：证据字段本身不作信任来源。
    backend = _backend()
    if not _verify_signature(backend, pub_raw, payload, signature):
        _fail("公钥独立验证失败：签名无效", 1)
    if hashlib.sha256(payload).hexdigest() != ev.get("payload_sha256"):
        _fail("payload_sha256 与证据不一致", 1)
    if ev.get("signature_base64") not in (None, env.get("signature")):
        _fail("manifest 签名与证据签名不一致", 1)
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        _fail("payload 不是有效 JSON", 1)
    if not isinstance(data, dict) or data.get("schema") != 1 or data.get("app_id") != APP_ID:
        _fail("payload 应用标识不符", 1)
    if (data.get("channel"), data.get("platform"), data.get("arch"),
            data.get("package_type")) != ("stable", "android", "universal", "apk"):
        _fail("payload 目标平台不符", 1)
    _safe_name("payload release_id", data.get("release_id"), 1, prefix="test-")
    _safe_name("payload filename", data.get("filename"), 1, suffix=".apk")
    if type(data.get("size")) is not int or data["size"] <= 0 \
            or not isinstance(data.get("sha256"), str) or not SHA256.fullmatch(data["sha256"]):
        _fail("payload 完整性字段非法", 1)

    print(json.dumps({
        "ok": True, "verified": "ed25519-public-key", "backend": backend, "key_id": key_id,
        "public_key_sha256": ev["public_key_sha256"], "release_id": data["release_id"],
        "filename": data["filename"], "size": data["size"],
        "package_sha256": data["sha256"], "payload_sha256": ev["payload_sha256"],
        "signature_sha256": hashlib.sha256(signature).hexdigest(),
        "signature_length": len(signature),
    }, ensure_ascii=False, sort_keys=True))
    return 0


GEN_OPTS = (
    ("--root", True, None, "lab-client-updates 根目录（Git 忽略，绝对路径）"),
    ("--keys", True, None, "临时测试密钥目录（Git 忽略，0700）"),
    ("--release-id", False, "test-rel-p2-001", "必须 test-* 合成身份"),
    ("--filename", False, "p2-test-app.apk", "必须 .apk（合成非可安装包）"),
    ("--version", False, "0.0.1-p2test", "x.y.z 形式显示版本"),
    ("--build-number", False, 999001, "整数构建号"),
    ("--release-sequence", False, 1, "整数发布序号"),
    ("--key-id", False, "p2-test-only-ed25519", "必须包含 test-only"),
    ("--evidence", False, "", "公钥/摘要 JSON 输出（不含私钥）"),
)


def build_parser():
    parser = argparse.ArgumentParser(description="P2 合成更新清单夹具（真实 Ed25519，test-only）")
    sub = parser.add_subparsers(dest="command")
    gen = sub.add_parser("generate", help="生成合成更新清单（默认）")
    for name, required, default, text in GEN_OPTS:
        gen.add_argument(name, required=required, default=default, help=text)
    ver = sub.add_parser("verify", help="用公钥证据独立验证下载到的 manifest")
    for name, text in (("--manifest", "下载到的 manifest JSON 文件"),
                       ("--public-key-evidence", "seed 生成的 signing.json")):
        ver.add_argument(name, required=True, help=text)
    return parser





def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in ("generate", "verify", "-h", "--help"):
        argv.insert(0, "generate")  # 兼容旧调用（省略子命令即生成）
    ns = build_parser().parse_args(argv)
    try:
        return generate(ns) if ns.command == "generate" else verify(ns)
    except FixtureError as exc:
        sys.stderr.write("fixture: %s\n" % exc)
        return exc.code
    except (OSError, ValueError):
        sys.stderr.write("fixture: 文件或取值错误（细节已省略）\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
