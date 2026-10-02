#!/usr/bin/env python3
"""Verify staged UP-01 session, Decky and its matching BOOT artifact."""
import argparse
import gzip
import importlib.util
import json
from pathlib import Path
import re
import struct
import zlib

REPO = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def check(root, kernel, home=None):
    home = home or root / 'home/steamos'
    files = {
        'usr/lib/steamos/gamescope-session': 'steamos-overlay',
        'usr/lib/steamos/wait-gamescope-env': 'steamos-overlay',
        'usr/lib/systemd/user/steam.service.d/60-gamescope-env.conf': 'steamos-overlay',
        'usr/lib/systemd/user/steam.service.d/61-gamescope-env-wait.conf': 'steamos-overlay',
        'usr/lib/systemd/system/plugin_loader.service': 'sm8650-overlay',
        'usr/lib/systemd/user/konkr-focusfix.service': 'sm8650-overlay',
        'usr/lib/konkr/konkr-focusfix': 'sm8650-overlay',
    }
    for rel, source in files.items():
        installed = root / rel
        if not installed.is_file(): raise ValueError(f'missing UP-01 session file: {rel}')
        if installed.read_bytes() != (REPO / source / rel).read_bytes(): raise ValueError(f'UP-01 staged content differs: {rel}')
        if rel in ('usr/lib/steamos/gamescope-session', 'usr/lib/steamos/wait-gamescope-env', 'usr/lib/konkr/konkr-focusfix') and not installed.stat().st_mode & 0o111:
            raise ValueError(f'UP-01 file is not executable: {rel}')
    header = (root / 'usr/lib/konkr/konkr-focusfix').read_bytes()[:20]
    if header[:5] != b'\x7fELF\x02' or struct.unpack_from('<H', header, 18)[0] != 183:
        raise ValueError('focusfix must be AArch64 ELF')
    links = {
        'usr/lib/systemd/user/gamescope-session.target.wants/konkr-focusfix.service': '../konkr-focusfix.service',
        'usr/lib/systemd/system/multi-user.target.wants/plugin_loader.service': '../plugin_loader.service',
    }
    for rel, target in links.items():
        path = root / rel
        if not path.is_symlink() or str(path.readlink()) != target: raise ValueError(f'invalid UP-01 enable link: {rel}')
    for name in ('VkLayer_VALVE_rpo.json', 'VkLayer_VALVE_fdm_injection.json'):
        if (root / 'usr/share/vulkan/explicit_layer.d' / name).exists(): raise ValueError(f'Frame VR layer still active: {name}')
    decky = json.loads((REPO / 'external-and-mods/Decky/loader.json').read_text())
    fetch = load('up01_fetch', REPO / 'scripts/fetch-decky-loader.py')
    if not (home / 'homebrew/services/PluginLoader').stat().st_mode & 0o111: raise ValueError('Decky loader is not executable')
    fetch.verify_artifact(home / 'homebrew/services/PluginLoader', decky['sha256'])
    if (home / 'homebrew/services/.loader.version').read_text() != decky['version']: raise ValueError('Decky version mismatch')
    boot = load('up01_boot', REPO / 'external-and-mods/ufs-install/ufs-bootimg.py')
    image = boot.BootImg(kernel.read_bytes())
    if image.id != image.expected_id(): raise ValueError('BOOT image ID mismatch')
    payload = zlib.decompressobj(31).decompress(image.kernel)
    release = re.search(rb'Linux version (\S+)', payload)
    if not release or not (root / 'usr/lib/modules' / release[1].decode()).is_dir(): raise ValueError('BOOT kernel/modules mismatch')
    repacker = load('up01_repack', REPO / 'scripts/repack-rp6-initramfs.py')
    raw = boot.initramfs_bytes(image)
    entries, position = None, 0
    while True:
        position = raw.find(b'070701', position)
        if position < 0: break
        try:
            parsed = repacker.read_cpio(raw[position:])
            found = {name.removeprefix('./'): data for name, _, data in parsed}
            if 'init' in found: entries = found; break
        except (ValueError, UnicodeError): pass
        position += 6
    if entries is None: raise ValueError('BOOT has no readable initramfs')
    for name in ('init', 'mount-etc-overlay', 'konkr-update-recover'):
        expected = (REPO / 'external-and-mods/kernel-common/initramfs' / name).read_bytes()
        if entries.get(name) != expected: raise ValueError(f'BOOT lacks matching UP-01 {name}; rebuild/repack the real initramfs')
    return {'module': 'UP-01', 'kernel_release': release[1].decode(), 'decky_version': decky['version'],
            'session_delivery': 'passed', 'boot_initramfs_delivery': 'passed', 'device': 'untested'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rootfs', type=Path); parser.add_argument('kernel', type=Path)
    parser.add_argument('--home', type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.rootfs, args.kernel, args.home), indent=2))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError) as exc: raise SystemExit(str(exc))
