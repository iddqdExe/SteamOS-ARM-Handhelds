#!/usr/bin/env python3
"""Fetch the pinned x86 Decky artifact, or verify its offline cache."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import os

REPO = Path(__file__).resolve().parents[1]


def verify_artifact(path, sha256):
    with Path(path).open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        stream.seek(0); header = stream.read(20)
    if digest != sha256:
        raise ValueError(f'Decky SHA256 mismatch: {path}')
    if len(header) < 20 or header[:7] != b'\x7fELF\x02\x01\x01' or struct.unpack_from('<H', header, 18)[0] != 62:
        raise ValueError('Decky loader must be a little-endian x86-64 ELF for Box64')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path, default=REPO / 'external-and-mods/Decky/loader.json')
    parser.add_argument('--cache-dir', type=Path, default=REPO / 'external-and-mods/Decky/loader')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--verify', type=Path, help='verify an existing loader at an explicit path')
    args = parser.parse_args()
    meta = json.loads(args.metadata.read_text())
    if args.verify:
        verify_artifact(args.verify, meta['sha256'])
        print(args.verify.resolve())
        return
    version = meta['version']
    if not version or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_' for c in version):
        raise ValueError('invalid Decky version')
    cached = args.cache_dir / f'PluginLoader-{version}'
    if cached.exists():
        verify_artifact(cached, meta['sha256'])
    else:
        if args.offline: raise ValueError(f'Decky {version} missing from offline cache: {cached}')
        args.cache_dir.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.PluginLoader-', dir=args.cache_dir)
        os.close(fd)
        try:
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                            '--proto', '=https', '--retry', '2', '--max-time', '120',
                            '--output', temporary, meta['url']], check=True)
            verify_artifact(temporary, meta['sha256'])
            os.replace(temporary, cached)
        finally:
            Path(temporary).unlink(missing_ok=True)
    print(cached.resolve())


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(str(exc))
