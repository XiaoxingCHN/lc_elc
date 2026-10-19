"""Compile the matching host updater and mark a disposable complete bundle."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess


def prepare(source, bundle, dart, platform):
    source = Path(source).resolve(strict=True)
    bundle = Path(bundle).resolve(strict=True)
    if 'releases' in bundle.parts or bundle == bundle.parent or source == source.parent:
        raise ValueError('Refusing to change an immutable release or filesystem root')
    binary = 'lab_inventory_client.exe' if platform == 'windows' else 'lab_inventory_client'
    if not (bundle / binary).is_file() or not (bundle / 'data/flutter_assets').is_dir():
        raise ValueError('Complete built bundle required')
    version = re.search(r'^version:\s*(\d+\.\d+\.\d+)\+(\d+)\s*$', (source/'pubspec.yaml').read_text(encoding='utf-8'), re.M)
    if not version: raise ValueError('Numeric client build required')
    helper = bundle / ('client_update_helper.exe' if platform == 'windows' else 'client_update_helper')
    subprocess.run([str(dart), 'compile', 'exe', 'tool/client_update_helper.dart', '-o', str(helper)], cwd=source, check=True)
    marker = {'app_id': 'com.example.lab_inventory_client', 'layout': 1, 'version': version[1], 'build': int(version[2]), 'platform': platform}
    (bundle/'client-install.json').write_text(json.dumps(marker, indent=2)+'\n')
    if platform == 'linux': os.chmod(helper, 0o755)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True); p.add_argument('--bundle', required=True)
    p.add_argument('--dart', required=True); p.add_argument('--platform', required=True, choices=['windows','linux'])
    a=p.parse_args(); prepare(a.source, a.bundle, a.dart, a.platform)


if __name__ == '__main__': main()
