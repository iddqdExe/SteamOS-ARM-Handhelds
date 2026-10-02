#!/usr/bin/env python3
"""Update our external busybox initramfs without changing Image.gz or DTBs.

Embedded initramfs requires kernel-common/build.sh --repack-boot, which
rebuilds Image when EMBED_INITRAMFS=1. This tool never writes a device.
"""
import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('up01_bootimg', REPO / 'external-and-mods/ufs-install/ufs-bootimg.py')
boot = importlib.util.module_from_spec(spec); spec.loader.exec_module(boot)


def read_cpio(raw):
    entries, offset = [], 0
    while offset + 110 <= len(raw):
        if raw[offset:offset + 6] != b'070701': raise ValueError('expected newc initramfs')
        fields = [int(raw[offset + 6 + i * 8:offset + 14 + i * 8], 16) for i in range(13)]
        start = offset + 110
        name = raw[start:start + fields[11]].rstrip(b'\0').decode()
        start = (start + fields[11] + 3) & ~3
        data = raw[start:start + fields[6]]
        if len(data) != fields[6]: raise ValueError('truncated initramfs')
        if name == 'TRAILER!!!': return entries
        if name.startswith('/') or '..' in Path(name).parts: raise ValueError('unsafe initramfs path')
        entries.append((name, fields, data))
        offset = (start + fields[6] + 3) & ~3
    raise ValueError('initramfs has no cpio trailer')


def write_cpio(entries):
    output = bytearray()
    trailer = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 11, 0]
    for name, fields, data in [*entries, ('TRAILER!!!', trailer, b'')]:
        encoded = name.encode() + b'\0'
        fields = fields.copy(); fields[6] = len(data); fields[11] = len(encoded)
        output += b'070701' + ''.join(f'{n:08x}' for n in fields).encode() + encoded
        output += b'\0' * (-len(output) % 4)
        output += data; output += b'\0' * (-len(output) % 4)
    output += b'\0' * (-len(output) % 512)
    return bytes(output)


def repack(source, expected_sha256):
    if hashlib.sha256(source).hexdigest() != expected_sha256: raise ValueError('KERNEL SHA256 mismatch')
    image = boot.BootImg(source)
    if image.id != image.expected_id(): raise ValueError('invalid boot image ID')
    raw = boot.ramdisk_bytes(image.ramdisk)
    if raw[:6] != b'070701':
        raise ValueError('embedded initramfs or foreign ramdisk: rebuild Image with kernel-common/build.sh --repack-boot')
    entries = read_cpio(raw)
    names = {name.removeprefix('./'): data for name, _, data in entries}
    if 'init' not in names or 'konkr-update-recover' not in names or b'/konkr-update-recover' not in names['init']:
        raise ValueError('foreign initramfs: expected our busybox init and update recovery')
    replacements = {'init': (REPO / 'external-and-mods/kernel-common/initramfs/init').read_bytes(),
                    'mount-etc-overlay': (REPO / 'external-and-mods/kernel-common/initramfs/mount-etc-overlay').read_bytes()}
    updated = []
    inode = max(fields[0] for _, fields, _ in entries)
    for name, fields, data in entries:
        normalized = name.removeprefix('./')
        if normalized in replacements:
            data = replacements.pop(normalized)
            fields = fields.copy(); fields[1] = 0o100755 if normalized == 'init' else 0o100644
            fields[2:6] = [0, 0, 1, 0]
        updated.append((name, fields, data))
    for name, data in replacements.items():
        inode += 1
        updated.append((name, [inode, 0o100644, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(name) + 1, 0], data))
    image.ramdisk = gzip.compress(write_cpio(updated), compresslevel=9, mtime=0)
    image.ramdisk_size = len(image.ramdisk)
    candidate = image.build(image.cmdline)
    again = boot.BootImg(candidate)
    original = boot.BootImg(source)
    for field in ('kernel', 'cmdline', 'kernel_addr', 'ramdisk_addr', 'tags_addr', 'page_size', 'os_version', 'name', 'extra', 'second'):
        if getattr(again, field) != getattr(original, field): raise ValueError(f'boot repack changed {field}')
    if again.id != again.expected_id(): raise ValueError('repacked boot image ID mismatch')
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path); parser.add_argument('output', type=Path)
    parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.resolve() == args.kernel.resolve(): raise ValueError('output must be a new file')
    source = args.kernel.read_bytes()
    candidate = repack(source, args.expected_sha256)
    with args.output.open('xb') as stream: stream.write(candidate)
    print(json.dumps({'source_sha256': hashlib.sha256(source).hexdigest(),
                      'output_sha256': hashlib.sha256(candidate).hexdigest(),
                      'kernel_payload_sha256': hashlib.sha256(boot.BootImg(candidate).kernel).hexdigest(),
                      'kernel_payload_preserved': True}))


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError) as exc: raise SystemExit(str(exc))
