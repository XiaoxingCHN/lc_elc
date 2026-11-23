"""Package the three platform builds and publish them as immutable releases.

Packages follow docs/development/CLIENT_UPDATE_IMPLEMENTATION.md: the bundle is
the top level of each archive (no extra wrapper directory), Linux keeps the
executable bit, and the Android APK is the signed release build.

Run after `tools/build_client.py` succeeded for all three platforms. Publishing
to the in-app update channel (signed manifest + production data_dir) is a
separate production step and is NOT performed here.
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = Path(subprocess.check_output(
    ['git', 'rev-parse', '--path-format=absolute', '--git-common-dir'],
    cwd=ROOT, text=True).strip()).resolve().parent
VERSION = '1.4.0+26'
MANIFEST = ROOT / 'maintenance/registry/source-client-1.4.0-26-20261123.json'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def zip_bundle(bundle: Path, target: Path) -> None:
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(bundle).as_posix())


def tar_bundle(bundle: Path, target: Path) -> None:
    with tarfile.open(target, 'w:gz') as archive:
        for path in sorted(bundle.rglob('*')):
            archive.add(path, arcname=path.relative_to(bundle).as_posix(),
                        recursive=False)


def publish(platform: str, artifact: Path, name: str) -> dict:
    releases = (MAIN / 'clients' / platform / 'releases').resolve(strict=True)
    assert releases.is_relative_to(MAIN)
    destination = releases / VERSION
    assert not destination.exists(), f'{destination} exists; releases are immutable'
    destination.mkdir()
    target = destination / name
    shutil.copyfile(artifact, target)
    assert sha256(target) == sha256(artifact)
    shutil.copyfile(MANIFEST, destination / 'SOURCE_MANIFEST.json')
    record = {
        'platform': platform,
        'file': str(target.relative_to(MAIN)).replace('\\', '/'),
        'bytes': target.stat().st_size,
        'sha256': sha256(target),
        'version': VERSION,
        'source_manifest': str(MANIFEST.relative_to(ROOT)).replace('\\', '/'),
        'source_tree_sha256': json.loads(MANIFEST.read_text())['tree_sha256'],
        'release_status': 'built and packaged; device acceptance and update-channel publish pending',
    }
    (destination / 'ARTIFACT.json').write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return record


if __name__ == '__main__':
    # Explicit paths, never guessed: `windows=<Release dir> android=<apk> linux=<bundle dir>`.
    # Omitted platforms are skipped so a finished build can ship without waiting
    # for the others; re-running for a platform already published is refused.
    given = dict(argument.split('=', 1) for argument in sys.argv[1:])
    scratch = ROOT / 'local/build/client-packages'
    scratch.mkdir(parents=True, exist_ok=True)
    records = []
    if 'windows' in given:
        archive = scratch / f'LC_ELC-Windows-{VERSION}-x64.zip'
        zip_bundle(Path(given['windows']), archive)
        records.append(publish('windows', archive, archive.name))
    if 'android' in given:
        records.append(publish('android', Path(given['android']),
                               f'LC_ELC-Android-{VERSION}.apk'))
    if 'linux' in given:
        archive = scratch / f'LC_ELC-Linux-{VERSION}.tar.gz'
        tar_bundle(Path(given['linux']), archive)
        records.append(publish('linux', archive, archive.name))
    print(json.dumps(records, indent=2, ensure_ascii=False))
