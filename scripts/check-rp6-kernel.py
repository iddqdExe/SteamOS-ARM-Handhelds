#!/usr/bin/env python3
"""Verify immutable RP6 kernel inputs before using a cached source tree."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import struct
import zlib

REQUIRED = {'linux', 'extra-firmware', 'chipone', 'regdb', 'regdb-signature',
            'gpu-sqe', 'gpu-gmu', 'gpu-zap', 'wifi-amss', 'wifi-m3', 'wifi-board'}
REPO = Path(__file__).resolve().parents[1]
FIRMWARE = {'gpu-sqe': 'qcom/a740_sqe.fw', 'gpu-gmu': 'qcom/gmu_gen70200.bin',
            'gpu-zap': 'qcom/sm8550/a740_zap.mbn', 'wifi-amss': 'ath12k/WCN7850/hw2.0/amss.bin',
            'wifi-m3': 'ath12k/WCN7850/hw2.0/m3.bin', 'wifi-board': 'ath12k/WCN7850/hw2.0/board-2.bin',
            'regdb': 'regulatory.db', 'regdb-signature': 'regulatory.db.p7s'}


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, REPO / relative)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def check_inputs(lockfile, cache, frame, rocknix, toolchain_id=None, busybox=None, chipone_ref=None):
    lock = json.loads(Path(lockfile).read_text())
    if (lock.get('format') != 'rp6-kernel-inputs-1' or lock.get('kernel') != '7.2.8'
            or lock.get('recipe') != '7.2'):
        raise ValueError('unsupported kernel input lock')
    entries = lock.get('inputs', [])
    ids = [e.get('id') for e in entries]
    if set(ids) != REQUIRED or len(ids) != len(REQUIRED):
        raise ValueError('incomplete or duplicate kernel inputs')
    if chipone_ref is not None:
        chipone = next(e for e in entries if e['id'] == 'chipone')
        if not re.fullmatch('[0-9a-f]{40}', chipone_ref) or chipone['path'] != f'chipone_tddi-{chipone_ref}.tar.gz':
            raise ValueError('effective chipone ref differs from locked archive')
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


def check_artifacts(lockfile, kernel_dir, rootfs=None):
    lock = json.loads(Path(lockfile).read_text()); folder = Path(kernel_dir)
    boot = load('rp6_kernel_boot', 'external-and-mods/ufs-install/ufs-bootimg.py')
    paddles = load('rp6_kernel_paddles', 'scripts/fix-rp6-paddles.py')
    cpio = load('rp6_kernel_cpio', 'scripts/repack-rp6-initramfs.py')
    kernel = folder / 'boot/KERNEL'
    image = boot.BootImg(kernel.read_bytes())
    if image.id != image.expected_id() or image.ramdisk != b'dummy':
        raise ValueError('KERNEL must have valid ID and an embedded initramfs')
    compressed, trees = paddles.split_payload(image.kernel)
    dtb_offset = len(compressed)
    for tree in trees:
        if dtb_offset % 8:
            raise ValueError('unaligned appended DTB: offset ' + str(dtb_offset))
        dtb_offset += len(tree)
    raw = zlib.decompress(compressed, 31)
    match = re.search(rb'Linux version (\S+)', raw)
    if not match or not match[1].decode().startswith(lock['kernel'] + '-'):
        raise ValueError('KERNEL release does not match locked Linux version')
    release = match[1].decode()
    config = (folder / ('config-' + release)).read_bytes()
    marker = raw.find(b'IKCFG_ST')
    if marker < 0 or zlib.decompress(raw[marker + 8:], 31) != config:
        raise ValueError('embedded config differs from delivered config')
    for flag in (b'CONFIG_OVERLAY_FS=y', b'CONFIG_IKCONFIG=y', b'CONFIG_INITRAMFS_COMPRESSION_NONE=y'):
        if flag not in config.splitlines():
            raise ValueError('required kernel config missing: ' + flag.decode())
    models = [paddles.properties(tree)['/'].get('model') for tree in trees]
    if len(trees) != 2 or set(models) != paddles.MODELS:
        raise ValueError('KERNEL requires exactly both RP6 DTBs')
    for tree in trees:
        props = paddles.properties(tree); paddles.verify_paddles(props)
        controller = props.get('/soc@0/mmc@8804000', {})
        if controller.get('status') != b'okay\0' or controller.get('bus-width') != paddles.cells(4):
            raise ValueError('RP6 DTB lacks an enabled four-bit SD controller')
        if 'sdhci-caps-mask' in controller:
            raise ValueError('RP6 DTB still masks SD capabilities')
    # Match exact early-boot hooks inside the packed Image, not an external file.
    entries = None; position = 0
    while True:
        position = raw.find(b'070701', position)
        if position < 0: break
        try:
            parsed = cpio.read_cpio(raw[position:])
            candidate = {name.removeprefix('./'): (fields, data) for name, fields, data in parsed}
            if 'init' in candidate:
                entries = candidate; break
        except (ValueError, UnicodeError): pass
        position += 6
    if entries is None:
        raise ValueError('embedded initramfs missing')
    for name in ('init', 'mount-etc-overlay', 'konkr-update-recover', 'bootdebug'):
        expected = (REPO / 'external-and-mods/kernel-common/initramfs' / name).read_bytes()
        if name not in entries or entries[name][1] != expected:
            raise ValueError('stale embedded initramfs: ' + name)
        if name != 'mount-etc-overlay' and not entries[name][0][1] & 0o111:
            raise ValueError('initramfs hook is not executable: ' + name)
    if ('bin/busybox' not in entries or hashlib.sha256(entries['bin/busybox'][1]).hexdigest()
            != lock['toolchain']['busybox_sha256']):
        raise ValueError('initramfs BusyBox SHA256 mismatch')
    inputs = {entry['id']: entry for entry in lock['inputs']}
    fwroot = Path(rootfs) / 'usr/lib/firmware' if rootfs else folder / 'firmware'
    builtins = re.search(rb'^CONFIG_EXTRA_FIRMWARE="([^"]*)"$', config, re.M)
    names = builtins[1].decode().split() if builtins else []
    for key, path in FIRMWARE.items():
        firmware = fwroot / path
        if not firmware.is_file() or sha256(firmware) != inputs[key]['sha256']:
            raise ValueError('firmware SHA256 mismatch: ' + path)
        if key.startswith('wifi-') or key.startswith('regdb'):
            if path not in names or path.encode() + b'\0' not in raw or firmware.read_bytes() not in raw:
                raise ValueError('missing or incorrect built-in firmware: ' + path)
    modroot = Path(rootfs) / 'usr/lib/modules' / release if rootfs else folder / 'modules' / release
    modules = list(modroot.rglob('*.ko'))
    if not modules:
        raise ValueError('matching modules missing: ' + release)
    vermagic = set()
    for module in modules:
        data = module.read_bytes()
        if data[:6] != b'\x7fELF\x02\x01' or len(data) < 64 or struct.unpack_from('<H', data, 18)[0] != 183:
            raise ValueError('module must be ELF64 AArch64: ' + str(module))
        vm = re.search(rb'\0vermagic=([^\0]+)\0', data)
        if not vm or vm[1].split()[0].decode() != release:
            raise ValueError('module vermagic mismatch: ' + str(module))
        vermagic.add(vm[1])
    if len(vermagic) != 1:
        raise ValueError('module vermagic flags differ within bundle')
    return {'kernel_release': release, 'kernel_sha256': sha256(kernel),
            'config_sha256': hashlib.sha256(config).hexdigest(), 'dtb_models': [m.rstrip(b'\0').decode() for m in models],
            'modules_checked': len(modules), 'vermagic': next(iter(vermagic)).decode(),
            'firmware_verified': list(FIRMWARE.values()), 'initramfs': 'passed', 'device': 'untested'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    inputs = commands.add_parser('inputs')
    for option in ('lock', 'cache', 'frame', 'rocknix'):
        inputs.add_argument('--' + option, required=True)
    inputs.add_argument('--toolchain-id')
    inputs.add_argument('--busybox')
    inputs.add_argument('--chipone-ref')
    fp = commands.add_parser('fingerprint')
    for option in ('soc', 'common', 'rocknix', 'patch-dirs', 'skips', 'dtbs'):
        fp.add_argument('--' + option, required=True)
    artifacts = commands.add_parser('artifacts')
    artifacts.add_argument('--lock', required=True)
    artifacts.add_argument('--kernel-dir', required=True)
    artifacts.add_argument('--rootfs')
    args = parser.parse_args()
    try:
        if args.command == 'inputs':
            print(json.dumps(check_inputs(args.lock, args.cache, args.frame, args.rocknix,
                                          args.toolchain_id, args.busybox, args.chipone_ref)))
        elif args.command == 'fingerprint':
            print(fingerprint(args.soc, args.common, args.rocknix,
                              args.patch_dirs.split(), args.skips.split(), args.dtbs.split()))
        else:
            print(json.dumps(check_artifacts(args.lock, args.kernel_dir, args.rootfs), indent=2))
    except (ValueError, OSError, KeyError, struct.error, zlib.error, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
