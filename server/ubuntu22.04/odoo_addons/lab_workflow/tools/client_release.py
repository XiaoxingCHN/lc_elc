"""Read-only release store; no database, credentials or caller-controlled paths."""
import base64
import json
import re
from pathlib import Path

SAFE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+-]{0,100}$')
MAX_PACKAGE = 512 * 1024 * 1024


def safe_path(root, *parts):
    root = Path(root).resolve()
    path = root
    for part in parts:
        if not isinstance(part, str) or not SAFE.fullmatch(part) or part in ('.', '..'):
            raise ValueError('invalid release path')
        path = path / part
        if path.is_symlink():
            raise ValueError('release links forbidden')
    if not path.resolve().is_relative_to(root):
        raise ValueError('release path escaped')
    return path


def decode_manifest(envelope):
    if not isinstance(envelope, dict) or len(json.dumps(envelope)) > 65536:
        raise ValueError('invalid envelope')
    if not isinstance(envelope.get('key_id'), str) or not SAFE.fullmatch(envelope['key_id']):
        raise ValueError('invalid signing key id')
    if not all(isinstance(envelope.get(k), str) for k in ('payload', 'signature')):
        raise ValueError('invalid envelope encoding')
    payload = base64.b64decode(envelope['payload'], validate=True)
    if len(base64.b64decode(envelope['signature'], validate=True)) != 64:
        raise ValueError('invalid signature length')
    data = json.loads(payload)
    if not isinstance(data, dict) or data.get('schema') != 1 or data.get('app_id') != 'com.example.lab_inventory_client':
        raise ValueError('invalid application')
    for key in ('release_id', 'filename', 'channel', 'platform', 'arch'):
        if not isinstance(data.get(key), str) or not SAFE.fullmatch(data[key]) or data[key] in ('.', '..'):
            raise ValueError('invalid release identity')
    if data['platform'] not in ('windows', 'linux', 'android') or data['channel'] != 'stable':
        raise ValueError('unsupported target')
    for key in ('build_number', 'release_sequence', 'size'):
        if type(data.get(key)) is not int or data[key] <= 0:
            raise ValueError('invalid release number')
    if data['size'] > MAX_PACKAGE or not re.fullmatch(r'[0-9a-f]{64}', data.get('sha256', '')):
        raise ValueError('invalid package integrity')
    formats = {'windows': 'zip', 'linux': 'tar.gz', 'android': 'apk'}
    if data.get('package_type') != formats[data['platform']] or not data['filename'].endswith('.'+formats[data['platform']]):
        raise ValueError('invalid package format')
    if not isinstance(data.get('version'), str) or not re.fullmatch(r'\d+\.\d+\.\d+([.-][A-Za-z0-9.-]+)?', data['version']):
        raise ValueError('invalid display version')
    if type(data.get('api_min')) is not int or type(data.get('api_max')) is not int or data['api_min'] > data['api_max']:
        raise ValueError('invalid API range')
    if not isinstance(data.get('requirements', {}), dict):
        raise ValueError('invalid requirements')
    return data


class ReleaseStore:
    def __init__(self, root):
        self.root = Path(root)

    def manifest(self, platform, arch, channel='stable'):
        if platform not in ('windows', 'linux', 'android') or arch not in ('x64', 'arm64', 'universal') or channel != 'stable':
            raise ValueError('unsupported target')
        path = safe_path(self.root, platform, arch, channel + '.json')
        if not path.is_file():
            return None
        if path.stat().st_size > 65536:
            raise ValueError('manifest too large')
        envelope = json.loads(path.read_text(encoding='utf-8'))
        data = decode_manifest(envelope)
        if (data['platform'], data['arch'], data['channel']) != (platform, arch, channel):
            raise ValueError('manifest target mismatch')
        return envelope

    def asset(self, release_id, filename):
        receipt = safe_path(self.root, 'releases', release_id, 'manifest.json')
        if not receipt.is_file() or receipt.stat().st_size > 65536:
            raise FileNotFoundError('unknown release')
        data = decode_manifest(json.loads(receipt.read_text(encoding='utf-8')))
        if data['release_id'] != release_id or data['filename'] != filename:
            raise FileNotFoundError('unknown artifact')
        path = safe_path(self.root, 'releases', release_id, filename)
        if not path.is_file() or path.stat().st_size != data['size']:
            raise FileNotFoundError('incomplete artifact')
        return path, data
