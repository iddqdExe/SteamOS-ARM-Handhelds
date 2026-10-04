#!/usr/bin/env python3
"""Derive a local RP6 test image from the exact verified, repaired beta8 base.

Includes module1 input and UP-02 touch fixes; --include-power adds module2.

Linux/root only. Uses loop devices for regular image files; no card writes.
This preserves beta8 userspace and is not a clean source distro build.
"""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[1]
BASE_SHA = '56f8541a5743d4fdb624cce09f9a4a34cd53608029e55ef51740403145f43147'
SIZE = 16447963136
LAYOUT = [(0x0c, 2048, 1048576), (0x83, 1050624, 23939072), (0x83, 24989696, 7135232)]
POWER_SOURCES = ('scripts/install-rp6-power.sh', 'sm8650-overlay/usr/lib/konkr/konkr-standby',
                 'sm8650-overlay/usr/lib/konkr/konkr-sleep',
                 'sm8650-overlay/usr/lib/konkr/konkr-suspend',
                 'sm8650-overlay/usr/lib/konkr/konkr-sleep-state',
                 'sm8650-overlay/usr/bin/konkrctl',
                 'external-and-mods/kernel-common/initramfs/bootdebug',
                 'sm8650-overlay/usr/lib/systemd/system/konkr-sleep.service',
                 'sm8650-overlay/usr/lib/systemd/system/konkr-bootflags.service',
                 'sm8650-overlay/usr/lib/systemd/system/systemd-suspend.service.d/10-konkr-standby.conf')


def run(*args, **kwargs):
    print('+', ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(16 << 20), b''): h.update(block)
    return h.hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def validate_base(path):
    if not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size != SIZE:
        raise ValueError('expected the regular, verified beta8 image file')
    with path.open('rb') as stream: mbr = stream.read(512)
    layout = []
    for i in range(3):
        entry = mbr[446 + 16 * i:462 + 16 * i]
        layout.append((entry[4], *struct.unpack_from('<II', entry, 8)))
    if mbr[510:] != b'\x55\xaa' or layout != LAYOUT:
        raise ValueError('unexpected beta8 partition layout')
    print('Verifying complete base SHA256...', flush=True)
    if digest(path) != BASE_SHA: raise ValueError('base SHA256 mismatch')


@contextmanager
def image_mounts(image):
    folder = Path(tempfile.mkdtemp(prefix='rp6-image-')); mounts = []
    try:
        for name, index in (('boot', 0), ('root', 1)):
            dest = folder / name; dest.mkdir()
            _, start, size = LAYOUT[index]
            run('mount', '-o', f'loop,offset={start * 512},sizelimit={size * 512}', image, dest)
            mounts.append(dest)
        yield folder / 'boot', folder / 'root'
    finally:
        failures = []
        for dest in reversed(mounts):
            try: run('umount', dest)
            except (OSError, subprocess.CalledProcessError) as error: failures.append(str(error))
        if failures or any(os.path.ismount(folder / name) for name in ('boot', 'root')):
            raise ValueError(f'could not unmount image; directory retained at {folder}: {failures}')
        shutil.rmtree(folder)


def install_power(root):
    run('bash', REPO / 'scripts/install-rp6-power.sh', root)
    payload = load('rp6_power_payload', REPO / 'scripts/prepare-rp6-kernel-release.py')
    return sorted(payload.POWER_FILES | payload.POWER_LINKS.keys())


def prepare_kernel(data):
    """Deliver touch and existing input fixes together, preserving boot data."""
    touch = load('rp6_image_touch', REPO / 'scripts/fix-rp6-touch.py')
    old = touch.read_boot(data)
    if old.build(old.cmdline) != data:
        raise ValueError('unsupported noncanonical base KERNEL')
    old.kernel, count = touch.paddles.process(old.kernel)
    if count != 2:
        raise ValueError('expected two RP6 trees')
    old.kernel_size = len(old.kernel)
    intermediate = old.build(old.cmdline)
    kernel, touch_count = touch.repack(intermediate, hashlib.sha256(intermediate).hexdigest())
    if touch_count != 2:
        raise ValueError('expected two RP6 touch trees')
    return kernel


def build(base, output, reuse, include_power=False):
    if not sys.platform.startswith('linux') or os.geteuid() != 0:
        raise ValueError('requires Linux/root and file-backed loop mounts')
    if include_power:
        for name in POWER_SOURCES:
            if not (REPO / name).is_file():
                raise ValueError(f'module2 source missing: {name}')
    base = base.resolve(strict=True); output = output.absolute()
    partial = output.with_name(output.name + '.partial')
    if output.exists(): raise ValueError('output already exists')
    if base == output or base == partial or (partial.exists() and os.path.samefile(base, partial)):
        raise ValueError('output must be a separate copy, never the base')
    if reuse:
        validate_base(partial)
    else:
        if partial.exists(): raise ValueError('partial output already exists; use a fresh path')
        validate_base(base)
        output.parent.mkdir(parents=True, exist_ok=True)
        run('cp', '--reflink=auto', '--sparse=always', '--', base, partial)
    bootimg = load('bootimg', REPO / 'external-and-mods/ufs-install/ufs-bootimg.py')
    info = {'kind': 'local-module2-test' if include_power else 'local-module1-test', 'hardware_accepted': False, 'base_sha256': BASE_SHA,
            'created_utc': datetime.now(timezone.utc).isoformat(), 'partitions': LAYOUT,
            'git_revision': run('git', '-c', f'safe.directory={REPO}', '-C', REPO, 'rev-parse', 'HEAD', capture_output=True, text=True).stdout.strip(),
            'source_dirty': bool(run('git', '-c', f'safe.directory={REPO}', '-C', REPO, 'status', '--porcelain', capture_output=True, text=True).stdout),
            'scope': 'RP6 12GB SM8550 microSD; beta8 userspace retained'}
    info['build_source_sha256'] = {name: digest(REPO / name) for name in (
        'scripts/prepare-rp6-beta8-test.py', 'scripts/fix-rp6-paddles.py',
        'scripts/fix-rp6-touch.py',
        'scripts/install-inputplumber-sm8550.sh', 'scripts/check-inputplumber-elf.py',
        'scripts/check-rp6-input.sh', 'steamos-overlay/usr/lib/steamos/sm8550-fixpad',
        'steamos-overlay/usr/lib/systemd/system/inputplumber.service.d/99-sm8550.conf',
        'steamos-overlay/usr/lib/steamos/rp6-input-config.py',
        'steamos-overlay/usr/lib/steamos/sm8550-volume-keys',
        'steamos-overlay/usr/lib/systemd/user/sm8550-volume-keys.service',
        'sm8550-overlay/etc/inputplumber/devices.d/02-retroid-pocket.yaml',
        'steamos-overlay/etc/inputplumber/capability_maps.d/retroid_mcu.yaml')}
    if include_power:
        for name in POWER_SOURCES:
            info['build_source_sha256'][name] = digest(REPO / name)
    with image_mounts(partial) as (boot, root):
        old_bytes = (boot / 'KERNEL').read_bytes()
        old = bootimg.BootImg(old_bytes)
        kernel = prepare_kernel(old_bytes)
        again = bootimg.BootImg(kernel)
        if again.ramdisk != old.ramdisk or again.cmdline != old.cmdline or again.id != again.expected_id():
            raise ValueError('rebuilt KERNEL integrity mismatch')
        (boot / 'KERNEL-before-module1').write_bytes(old_bytes)
        (boot / 'KERNEL').write_bytes(kernel)
        (boot / 'KERNEL.md5').write_text(hashlib.md5(kernel).hexdigest() + '  KERNEL\n')
        run('bash', REPO / 'scripts/install-inputplumber-sm8550.sh', root, '--config-only')
        updater = root / 'usr/share/konkr-update/konkr-update.py'
        if not updater.is_file(): raise ValueError('base updater missing')
        shutil.copyfile(REPO / 'external-and-mods/konkr-update/konkr-update.py', updater)
        run('python3', REPO / 'scripts/check-inputplumber-elf.py', root / 'usr/bin/inputplumber', root)
        run('bash', REPO / 'scripts/check-rp6-input.sh', root, boot / 'KERNEL')
        version = run('chroot', root, '/usr/bin/inputplumber', '--version', capture_output=True, text=True).stdout.strip()
        info.update(inputplumber=version, inputplumber_sha256=digest(root / 'usr/bin/inputplumber'),
                    up02_touch='400 kHz I2C + bulk reads; hardware untested',
                    kernel_sha256=digest(boot / 'KERNEL'), kernel_payload_sha256=hashlib.sha256(again.kernel).hexdigest(),
                    previous_kernel_sha256=hashlib.sha256(old_bytes).hexdigest(), checks='ELF + factory input preflight + chroot version')
        tracked = ['usr/lib/steamos/rp6-input-config.py', 'usr/lib/steamos/sm8550-fixpad',
                   'usr/lib/steamos/sm8550-volume-keys',
                   'usr/lib/systemd/user/sm8550-volume-keys.service',
                   'usr/lib/systemd/system/sm8550-fixpad.service',
                   'usr/lib/systemd/system/inputplumber.service.d/99-sm8550.conf',
                   'usr/share/konkr-update/konkr-update.py',
                   'etc/inputplumber/capability_maps.d/retroid_mcu.yaml',
                   'etc/inputplumber/devices.d/02-retroid-pocket.yaml']
        if include_power:
            tracked.extend(install_power(root))
        info['installed_sha256'] = {path: digest(root / path) for path in tracked}
        marker = 'RP6-MODULE2.json' if include_power else 'RP6-MODULE1.json'
        (boot / marker).write_text(json.dumps(info, indent=2) + '\n')
        os.sync()
    # Filesystem checks are read-only and performed after unmounting.
    for index, checker in ((0, 'fsck.fat'), (1, 'e2fsck'), (2, 'e2fsck')):
        _, start, size = LAYOUT[index]
        device = run('losetup', '--find', '--show', '--offset', start * 512,
                     '--sizelimit', size * 512, partial, capture_output=True, text=True).stdout.strip()
        try: run(checker, '-n', device)
        finally: run('losetup', '-d', device)
    info['filesystem_checks'] = 'BOOT/root/HOME read-only checks passed'
    print('Computing final image SHA256...', flush=True)
    info.update(image_sha256=digest(partial), image_bytes=partial.stat().st_size)
    os.replace(partial, output)
    output.with_name(output.name + '.json').write_text(json.dumps(info, indent=2) + '\n')
    output.with_name(output.name + '.sha256').write_text(info['image_sha256'] + '  ' + output.name + '\n')
    print('Test image ready:', output, flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path); parser.add_argument('output', type=Path)
    parser.add_argument('--reuse-verified-copy', action='store_true', help='verify and use output.img.partial already copied on the host')
    parser.add_argument('--include-power', action='store_true', help='include module2 standby/helper pair together with all module1 fixes')
    args = parser.parse_args()
    try: build(args.base, args.output, args.reuse_verified_copy, args.include_power)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print('ERROR:', error, file=sys.stderr); return 1
    return 0


if __name__ == '__main__': sys.exit(main())
