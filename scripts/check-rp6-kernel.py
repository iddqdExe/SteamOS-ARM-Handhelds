#!/usr/bin/env python3
"""Verify immutable RP6 kernel inputs before using a cached source tree."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

REQUIRED = {'linux', 'extra-firmware', 'chipone', 'regdb', 'regdb-signature',
            'gpu-sqe', 'gpu-gmu', 'gpu-zap', 'wifi-amss', 'wifi-m3', 'wifi-board'}


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def check_inputs(lockfile, cache, frame, rocknix, toolchain_id=None, busybox=None):
    lock = json.loads(Path(lockfile).read_text())
    if (lock.get('format') != 'rp6-kernel-inputs-1' or lock.get('kernel') != '7.2.8'
            or lock.get('recipe') != '7.2'):
        raise ValueError('unsupported kernel input lock')
    entries = lock.get('inputs', [])
    ids = [e.get('id') for e in entries]
    if set(ids) != REQUIRED or len(ids) != len(REQUIRED):
        raise ValueError('incomplete or duplicate kernel inputs')
    roots = {'cache': Path(cache).resolve(), 'frame': Path(frame).resolve()}
    for entry in entries:
        name = entry['id']; rel = Path(entry.get('path', ''))
        if (entry.get('location') not in roots or not entry.get('path')
                or rel.is_absolute() or '..' in rel.parts):
            raise ValueError(f'{name}: invalid input path')
        root = roots[entry['location']]; path = root / rel
        if not path.resolve().is_relative_to(root) or path.is_symlink():
            raise ValueError(f'{name}: input path escapes root or is a symlink')
        expected = entry.get('sha256', '')
        if not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError(f'{name}: missing SHA256')
        provenance = entry.get('url', '')
        if not (provenance.startswith('https://') or re.fullmatch(
                r'artifact://sha256/[0-9a-f]{64}/[^\s]+', provenance)):
            raise ValueError(f'{name}: missing pinned input provenance')
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f'{name}: missing file or SHA256 mismatch: {path}')
    expected = lock.get('rocknix_sha', '')
    if not re.fullmatch('[0-9a-f]{40}', expected):
        raise ValueError('ROCKNIX requires a full commit SHA')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(rocknix), *args], text=True).strip()
    if git('rev-parse', 'HEAD') != expected:
        raise ValueError('ROCKNIX checkout does not match locked SHA')
    if git('status', '--porcelain', '--untracked-files=all'):
        raise ValueError('ROCKNIX checkout is dirty')
    if toolchain_id is not None or busybox is not None:
        tc = lock.get('toolchain', {})
        if not toolchain_id or toolchain_id != tc.get('image'):
            raise ValueError('toolchain image does not match locked ID')
        if not busybox or sha256(Path(busybox)) != tc.get('busybox_sha256'):
            raise ValueError('BusyBox SHA256 does not match locked binary')
    return {'kernel': lock['kernel'], 'rocknix_sha': expected, 'verified': ids,
            'lock_sha256': sha256(Path(lockfile))}


def fingerprint(soc, common, rocknix, patch_dirs, skips, dtbs):
    """Include donor bytes, ordered patches, DTS, config and embedded hooks."""
    soc, common, rocknix = map(Path, (soc, common, rocknix))
    h = hashlib.sha256()
    h.update(json.dumps([patch_dirs, skips, dtbs], separators=(',', ':')).encode())
    def add(root, path):
        h.update(str(path.relative_to(root)).encode() + b'\0')
        h.update(path.read_bytes() + b'\0')
    for directory in patch_dirs:
        for path in sorted((rocknix / directory).glob('*.patch')):
            add(rocknix, path)
    for root in (soc, common):
        for path in sorted(root.rglob('*')):
            if path.is_file() and not path.is_symlink():
                add(root, path)
    for path in sorted((rocknix / 'projects/ROCKNIX/devices/SM8550/linux').rglob('*')):
        if path.is_file():
            add(rocknix, path)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    inputs = commands.add_parser('inputs')
    for option in ('lock', 'cache', 'frame', 'rocknix'):
        inputs.add_argument('--' + option, required=True)
    inputs.add_argument('--toolchain-id')
    inputs.add_argument('--busybox')
    fp = commands.add_parser('fingerprint')
    for option in ('soc', 'common', 'rocknix', 'patch-dirs', 'skips', 'dtbs'):
        fp.add_argument('--' + option, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'inputs':
            print(json.dumps(check_inputs(args.lock, args.cache, args.frame, args.rocknix,
                                          args.toolchain_id, args.busybox)))
        else:
            print(fingerprint(args.soc, args.common, args.rocknix,
                              args.patch_dirs.split(), args.skips.split(), args.dtbs.split()))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
