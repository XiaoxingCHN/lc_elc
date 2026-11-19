"""Restore the NIIMBOT (精臣) x64 SDK runtime next to the Windows client build.

The vendor DLLs and fonts are NOT committed to Git (the repository boundary
refuses *.dll and binary payloads). This script extracts ONLY the x64 runtime
files the Flutter Windows client needs from the registered SDK archive, checks
each SHA256, and writes them to:

    clients/app/windows/niimbot/runtime/         (DLLs + icudtl.dat)
    clients/app/windows/niimbot/runtime/font/    (ZT001.ttf + language.json)

CMake then copies them beside lab_inventory_client.exe (see
clients/app/windows/runner/CMakeLists.txt).

The script never runs anything from the archive, never touches Resources_x86,
and refuses to overwrite a file whose hash does not match.

Usage (from the repository root):
    python tools/restore_niimbot_runtime.py
    python tools/restore_niimbot_runtime.py --zip D:/sdk/CPP-4.0.6_release_20251114.zip
    python tools/restore_niimbot_runtime.py --verify-only
"""
import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ZIP = ROOT / 'CPP-4.0.6_release_20251114.zip'
TARGET = ROOT / 'clients/app/windows/niimbot/runtime'
ARCHIVE_PREFIX = 'CPP-4.0.6_release_20251114/接入包/Resources_x64/'
ZIP_SHA256 = 'dbe9c4d0bbb256f4eb9fe2ce4e961f1353a4ea45833c3f41f61c52995b70793f'

# (archive relative path under Resources_x64/, destination relative to TARGET, sha256)
FILES = [
    ('jcPrinterApi.dll',
     'jcPrinterApi.dll',
     'bc9acc1c6dd1baf4bbe91a9d19d9e12b1cf0179bd89564700d54454d46ab111e'),
    ('jcPrinterSdk.dll',
     'jcPrinterSdk.dll',
     '64998e07eac481ed4e38f8822ddc44d97428ddde2042df8658e6f38f6c638dc9'),
    ('USBPrintDll.dll',
     'USBPrintDll.dll',
     'a0af1af673f9274399b23a0e5ea81583e3bb141c0bcf107c3017cecff8ed6b66'),
    ('BYNetPortAPI.dll',
     'BYNetPortAPI.dll',
     '41d66667fd3f014084f1c70e5b10263ca04a7a43212a21821027057bd04d9b64'),
    ('NBCanvasImageSzwy.dll',
     'NBCanvasImageSzwy.dll',
     '7ebd602c04ee654bdfb7c9d65a4018b2ad975dadfb5ab41d86b686abe0680c73'),
    ('SimpleLogModule.dll',
     'SimpleLogModule.dll',
     'e3ad9ffa39c3faa2de2d213c1f122662db33da5568b96494f46d13c63cd2b395'),
    ('SNBCSDKForBarcodePrinter.dll',
     'SNBCSDKForBarcodePrinter.dll',
     'b626d747c830ddb442521d70e2ec2d45534a848146e80dfe728264b4aa86458f'),
    ('netal_windows.dll',
     'netal_windows.dll',
     'b2475e74cfe42a2a1560fbdb14de4476b16154bc8114c627c8a30abb9f5a4df5'),
    ('icudtl.dat',
     'icudtl.dat',
     '846942a316b4e38fdbd4de3ad83e4faae78a8bced50f4720acdbdab6ee7c4b8e'),
    ('font/ZT001.ttf',
     'font/ZT001.ttf',
     '297b088424be212207df2ce8b98e335468b782aa6b96832af0b8b773d711e2b1'),
    ('font/language.json',
     'font/language.json',
     '70a854b27e078c9db783eacbcf98dd43f72572e60331ffe0bf591e1824020a19'),
]


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_existing():
    missing, bad = [], []
    for _archive_name, relative, expected in FILES:
        destination = TARGET / relative
        if not destination.is_file():
            missing.append(relative)
        elif sha256_file(destination) != expected:
            bad.append(relative)
    return missing, bad


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--zip', default=str(DEFAULT_ZIP),
                        help='path to CPP-4.0.6_release_20251114.zip')
    parser.add_argument('--target', default=str(TARGET),
                        help='destination directory (default: clients/app/windows/niimbot/runtime)')
    parser.add_argument('--verify-only', action='store_true',
                        help='only check the files already present')
    parser.add_argument('--skip-zip-hash', action='store_true',
                        help='accept an archive whose SHA256 differs from the registered one '
                             '(each extracted file is still hash-checked)')
    args = parser.parse_args()

    target = Path(args.target).resolve()
    if not target.is_relative_to(ROOT.resolve()):
        print(json.dumps({'result': 'FAIL', 'error': 'target escapes the repository'},
                         ensure_ascii=False))
        return 2

    if args.verify_only:
        missing, bad = verify_existing()
        ok = not missing and not bad
        print(json.dumps({'result': 'PASS' if ok else 'FAIL',
                          'target': str(target.relative_to(ROOT)),
                          'missing': missing, 'hash_mismatch': bad,
                          'file_count': len(FILES) - len(missing) - len(bad)},
                         ensure_ascii=False, indent=2))
        return 0 if ok else 1

    archive = Path(args.zip).resolve()
    if not archive.is_file():
        print(json.dumps({'result': 'FAIL',
                          'error': 'SDK archive not found: %s' % archive,
                          'hint': 'Pass --zip <path to CPP-4.0.6_release_20251114.zip>'},
                         ensure_ascii=False, indent=2))
        return 2

    archive_hash = sha256_file(archive)
    if archive_hash != ZIP_SHA256 and not args.skip_zip_hash:
        print(json.dumps({'result': 'FAIL',
                          'error': 'SDK archive SHA256 does not match the registered payload',
                          'expected': ZIP_SHA256, 'actual': archive_hash,
                          'hint': 'Confirm the archive version, or pass --skip-zip-hash to '
                                  'accept it (each extracted file is still verified).'},
                         ensure_ascii=False, indent=2))
        return 2

    written, unchanged = [], []
    with zipfile.ZipFile(archive) as bundle:
        names = set(bundle.namelist())
        for archive_name, relative, expected in FILES:
            member = ARCHIVE_PREFIX + archive_name
            if member not in names:
                print(json.dumps({'result': 'FAIL',
                                  'error': 'missing member in archive: %s' % member},
                                 ensure_ascii=False, indent=2))
                return 2
            data = bundle.read(member)
            actual = sha256_bytes(data)
            if actual != expected:
                print(json.dumps({'result': 'FAIL',
                                  'error': 'hash mismatch: %s' % relative,
                                  'expected': expected, 'actual': actual},
                                 ensure_ascii=False, indent=2))
                return 2
            destination = target / relative
            if destination.is_file() and sha256_file(destination) == expected:
                unchanged.append(relative)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            written.append(relative)

    print(json.dumps({'result': 'PASS',
                      'target': str(target.relative_to(ROOT)),
                      'archive_sha256': archive_hash,
                      'written': written,
                      'unchanged': unchanged,
                      'next': 'flutter build windows --release (CMake installs the DLLs '
                              'beside the executable)'},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
