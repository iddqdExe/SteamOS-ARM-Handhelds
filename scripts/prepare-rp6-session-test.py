#!/usr/bin/env python3
"""Derive an UP-01 test image from a checksummed RP6 image; never write a card.

Linux/root only. This is an opt-in candidate derived from an existing image,
not a clean source distro build or a claim of hardware acceptance.
"""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


base_builder = load('up01_base', REPO / 'scripts/prepare-rp6-beta8-test.py')


@contextmanager
def image_mounts(image):
    folder = Path(tempfile.mkdtemp(prefix='rp6-up01-')); mounted = []
    try:
        for name, (_, start, size) in zip(('boot', 'root', 'home'), base_builder.LAYOUT):
            dest = folder / name; dest.mkdir()
            base_builder.run('mount', '-o', f'loop,offset={start * 512},sizelimit={size * 512}', image, dest)
            mounted.append(dest)
        yield tuple(folder / name for name in ('boot', 'root', 'home'))
    finally:
        failures = []
        for dest in reversed(mounted):
            try: base_builder.run('umount', dest)
            except (OSError, subprocess.CalledProcessError) as exc: failures.append(str(exc))
        if failures or any(os.path.ismount(folder / name) for name in ('boot', 'root', 'home')):
            raise ValueError(f'could not unmount image; directory retained at {folder}: {failures}')
        shutil.rmtree(folder)


def build(base, output, expected_sha256, update_package=None):
    partial = output.with_name(output.name + '.partial')
    if output.exists() or partial.exists(): raise ValueError('output already exists; choose a new filename')
    if not sys.platform.startswith('linux') or os.geteuid() != 0: raise ValueError('Linux/root required for candidate image mounts')
    if not base.is_file(): raise ValueError('base must be a regular image file')
    if base.stat().st_size != base_builder.SIZE: raise ValueError('unexpected RP6 base image size')
    with base.open('rb') as stream: mbr = stream.read(512)
    import struct
    layout = [(mbr[446 + i * 16 + 4], *struct.unpack_from('<II', mbr, 446 + i * 16 + 8)) for i in range(3)]
    if layout != base_builder.LAYOUT: raise ValueError('unexpected RP6 base partition layout')
    print('Verifying base SHA256...', flush=True)
    if base_builder.digest(base) != expected_sha256: raise ValueError('base SHA256 mismatch')
    loader = Path(subprocess.check_output(['python3', str(REPO / 'scripts/fetch-decky-loader.py'), '--offline'], text=True).strip())
    base_builder.run('cp', '--reflink=auto', '--sparse=always', base, partial)
    repacker = load('up01_repack', REPO / 'scripts/repack-rp6-initramfs.py')
    checker = load('up01_check', REPO / 'scripts/check-rp6-session.py')
    info = {'module': 'UP-01', 'source_sha': subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD'], text=True).strip(),
            'source_dirty': bool(subprocess.check_output(['git', '-C', str(REPO), 'status', '--porcelain'], text=True).strip()),
            'base_sha256': expected_sha256, 'target': 'Retroid Pocket 6 / SM8550 / 12 GB RAM / microSD',
            'donor_sha': '682281c0d82319324fd3f7d09b34d0f7005148fc', 'decision': 'untested',
            'device_validation': 'not performed', 'clean_source_build': False}
    with image_mounts(partial) as (boot, root, home):
        old = (boot / 'KERNEL').read_bytes()
        candidate = repacker.repack(old, hashlib.sha256(old).hexdigest())
        (boot / 'KERNEL-before-UP-01').write_bytes(old)
        (boot / 'KERNEL').write_bytes(candidate)
        (boot / 'KERNEL.md5').write_text(hashlib.md5(candidate).hexdigest() + '  KERNEL\n')
        base_builder.run('bash', REPO / 'scripts/install-rp6-session.sh', root, home / 'steamos', loader)
        base_builder.run('chown', '-R', '1000:1000', home / 'steamos/homebrew/services')
        info['delivery'] = checker.check(root, boot / 'KERNEL', home / 'steamos')
        base_builder.run('bash', REPO / 'scripts/check-rp6-input.sh', root, boot / 'KERNEL')
        info['input_preflight'] = 'passed'
        info['kernel_before_sha256'] = hashlib.sha256(old).hexdigest()
        info['kernel_sha256'] = hashlib.sha256(candidate).hexdigest()
        info['kernel_payload_sha256'] = hashlib.sha256(repacker.boot.BootImg(candidate).kernel).hexdigest()
        if update_package:
            base_builder.run('python3', REPO / 'scripts/build-update-package.py', '--rootfs', root, '--home', home / 'steamos',
                             '--kernel', boot / 'KERNEL', '--soc', 'sm8550', '--device', 'Retroid Pocket 6',
                             '--version', 'rp6-up01-test-20261002', '--output', update_package)
    info['image_sha256'] = base_builder.digest(partial)
    os.replace(partial, output)
    output.with_name(output.name + '.json').write_text(json.dumps(info, indent=2) + '\n')
    output.with_name(output.name + '.sha256').write_text(info['image_sha256'] + '  ' + output.name + '\n')
    print(json.dumps(info, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path); parser.add_argument('output', type=Path)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--update-package', type=Path)
    args = parser.parse_args()
    build(args.base, args.output, args.expected_sha256, args.update_package)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc: raise SystemExit(str(exc))
