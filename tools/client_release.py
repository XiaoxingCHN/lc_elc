"""Create an offline signing identity or publish a signed immutable client release.

Only explicitly supplied local paths are written. This tool never contacts production.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import tempfile
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('release_store', ROOT / 'server/ubuntu22.04/odoo_addons/lab_workflow/tools/client_release.py')
store = importlib.util.module_from_spec(spec); spec.loader.exec_module(store)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    key = sub.add_parser('keygen'); key.add_argument('--private', required=True); key.add_argument('--public', required=True); key.add_argument('--key-id', required=True)
    pub = sub.add_parser('publish'); pub.add_argument('--private', required=True); pub.add_argument('--key-id', required=True); pub.add_argument('--root', required=True); pub.add_argument('--package', required=True); pub.add_argument('--metadata', required=True)
    a = parser.parse_args()
    if not store.SAFE.fullmatch(a.key_id): parser.error('Invalid key id')
    private = Path(a.private).resolve()
    if a.action == 'keygen':
        public = Path(a.public).resolve()
        if private == public or private.exists() or public.exists(): parser.error('Refusing to replace signing identity')
        if private.is_relative_to(ROOT) and not private.is_relative_to(ROOT/'local/private'):
            parser.error('Private signing keys inside this repository must stay in ignored local/private')
        key = Ed25519PrivateKey.generate()
        private.parent.mkdir(parents=True, exist_ok=True); public.parent.mkdir(parents=True, exist_ok=True)
        with private.open('xb') as stream:
            os.chmod(private, 0o600)
            stream.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        with public.open('x') as stream:
            stream.write(json.dumps({a.key_id: base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()}, indent=2) + '\n')
        print('Signing identity created; public key file: ' + str(public))
        return
    root = Path(a.root).resolve(); root.mkdir(parents=True, exist_ok=True)
    lock = root / '.publish.lock'
    try: handle = lock.open('x')
    except FileExistsError: parser.error('Another publisher or unresolved publication holds the release lock')
    try:
        handle.write(str(os.getpid())); handle.close()
        publish(a, parser, private, root)
    finally: lock.unlink()


def publish(a, parser, private, root):
    package = Path(a.package).resolve(strict=True)
    meta = json.loads(Path(a.metadata).read_text(encoding='utf-8'))
    for field, length in [('source_tree_sha256', 64), ('source_manifest_sha256', 64), ('source_commit', 40)]:
        if not isinstance(meta.get(field), str) or not re.fullmatch('[0-9a-f]{%d}' % length, meta[field]):
            parser.error('Release metadata must contain frozen source provenance: ' + field)
    if not re.fullmatch(r'maintenance/registry/source-client-[A-Za-z0-9.-]+\.json', meta.get('source_manifest', '')):
        parser.error('Release metadata must reference a portable client source manifest')
    meta['size'] = package.stat().st_size
    with package.open('rb') as stream: meta['sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    meta['filename'] = package.name
    key = serialization.load_pem_private_key(private.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey): parser.error('Expected Ed25519 identity')
    payload = json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    envelope = {'key_id': a.key_id, 'payload': base64.b64encode(payload).decode(), 'signature': base64.b64encode(key.sign(payload)).decode()}
    store.decode_manifest(envelope)
    releases = store.safe_path(root, 'releases'); releases.mkdir(exist_ok=True)
    release = store.safe_path(root, 'releases', meta['release_id'])
    if release.exists(): parser.error('Immutable release already exists')
    pointer = store.safe_path(root, meta['platform'], meta['arch'], meta['channel'] + '.json')
    if pointer.exists():
        old = store.decode_manifest(json.loads(pointer.read_text()))
        if meta['release_sequence'] <= old['release_sequence'] or meta['build_number'] <= old['build_number']:
            parser.error('Release sequence and build must increase')
    encoded = json.dumps(envelope, ensure_ascii=False, separators=(',', ':'))
    temp = Path(tempfile.mkdtemp(prefix='.publish-', dir=releases))
    shutil.copyfile(package, temp / package.name)
    (temp / 'manifest.json').write_text(encoded, encoding='utf-8')
    temp.rename(release)
    pointer.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=pointer.parent, delete=False) as stream:
        stream.write(encoded); staged = stream.name
    os.replace(staged, pointer)
    print(json.dumps({'release': meta['release_id'], 'bytes': meta['size'], 'sha256': meta['sha256']}))


if __name__ == '__main__': main()
