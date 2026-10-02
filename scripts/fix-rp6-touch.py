#!/usr/bin/env python3
"""Port UP-02 touch DT settings to build files, never to a device.

ROCKNIX 3829f7c5a80a8a9e78576ea5a3bb0c1ceeebb939 (Diogo Trindade):
400 kHz and bulk reads for RP6's focaltech,ft5426. The source adaptation is
SteamOS ARM 3b01fcc60759b590a064387379b6858c2cbbb3cd (hashtagbasit).
Use fdtput only; preserve Image.gz, other models and unrelated properties.
"""
import argparse
import hashlib
import importlib.util
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib

REPO = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


paddles = load('rp6_touch_paddles', REPO / 'scripts/fix-rp6-paddles.py')
boot = load('rp6_touch_boot', REPO / 'external-and-mods/ufs-install/ufs-bootimg.py')


def touch_nodes(props):
    matches = [node for node, values in props.items()
               if b'focaltech,ft5426' in values.get('compatible', b'').split(b'\0')]
    if len(matches) != 1:
        raise ValueError('expected exactly one RP6 focaltech,ft5426 touchscreen')
    node = matches[0]
    parent = node.rsplit('/', 1)[0]
    if props[node].get('reg') != paddles.cells(0x38):
        raise ValueError('unexpected RP6 touchscreen address')
    if b'qcom,geni-i2c-master-hub' not in props[parent].get('compatible', b'').split(b'\0'):
        raise ValueError('unexpected RP6 touchscreen I2C controller')
    for ancestor in props:
        if (ancestor == '/' or node == ancestor or node.startswith(ancestor + '/')) and \
                props[ancestor].get('status', b'okay\0') not in {b'okay\0', b'ok\0'}:
            raise ValueError('disabled RP6 touchscreen path: ' + ancestor)
    if props[parent].get('clock-frequency') not in {paddles.cells(100000), paddles.cells(400000)}:
        raise ValueError('conflicting RP6 I2C clock-frequency; expected 100000 or 400000')
    if props[node].get('no-regmap-bulk-read', b'') != b'':
        raise ValueError('malformed RP6 no-regmap-bulk-read boolean')
    return parent, node


def reservations(data):
    """Protect memory reservations, which are outside the FDT properties."""
    pos = struct.unpack_from('>I', data, 16)[0]
    if pos < 40 or pos % 8:
        raise ValueError('invalid FDT reservation offset')
    start = pos
    while pos + 16 <= len(data):
        address, size = struct.unpack_from('>2Q', data, pos)
        pos += 16
        if address == size == 0:
            return data[start:pos]
    raise ValueError('truncated FDT reservations')


def fix_tree(data, check_only=False):
    before = paddles.properties(data)
    if before['/'].get('model') not in paddles.MODELS:
        return data, False
    reserved = reservations(data)
    parent, node = touch_nodes(before)
    slow = before[parent]['clock-frequency'] != paddles.cells(400000)
    blocked = 'no-regmap-bulk-read' in before[node]
    if not slow and not blocked:
        return data, True
    if check_only:
        raise ValueError('RP6 touch requires 400000 Hz I2C and bulk reads; rebuild/reimport with UP-02')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'rp6.dtb'
        path.write_bytes(data)
        if slow:
            subprocess.run(['fdtput', '-t', 'i', str(path), parent, 'clock-frequency', '400000'],
                           check=True, capture_output=True)
        if blocked:
            subprocess.run(['fdtput', '-d', str(path), node, 'no-regmap-bulk-read'],
                           check=True, capture_output=True)
        result = path.read_bytes()
    expected = {path: dict(values) for path, values in before.items()}
    expected[parent]['clock-frequency'] = paddles.cells(400000)
    expected[node].pop('no-regmap-bulk-read', None)
    if paddles.properties(result) != expected or reservations(result) != reserved:
        raise ValueError('RP6 touch repair changed unrelated DTB data')
    return result, True


def process(data, check_only=False):
    prefix, trees = paddles.split_payload(data)
    results = [fix_tree(tree, check_only) for tree in trees]
    count = sum(is_rp6 for _, is_rp6 in results)
    if not count:
        raise ValueError('SM8550 kernel has no RP6 DTB')
    return prefix + b''.join(tree for tree, _ in results), count


def read_boot(data):
    try:
        image = boot.BootImg(data)
    except SystemExit as error:
        raise ValueError(str(error)) from error
    if len(image.second) != image.second_size or image.id != image.expected_id():
        raise ValueError('invalid boot image checksum or second stage')
    return image


def repack(data, expected_sha256):
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError('input KERNEL SHA256 mismatch')
    image = read_boot(data)
    # Reject signatures, trailers and noncanonical layouts that BootImg cannot retain.
    if image.build(image.cmdline) != data:
        raise ValueError('unsupported noncanonical boot image; refusing to discard data')
    paddles.process(image.kernel, check_only=True)
    image.kernel, count = process(image.kernel)
    image.kernel_size = len(image.kernel)
    result = image.build(image.cmdline)
    again = read_boot(result)
    for name in ('kernel', 'ramdisk', 'second', 'cmdline', 'extra', 'name', 'os_version',
                 'kernel_addr', 'ramdisk_addr', 'second_addr', 'tags_addr', 'page_size'):
        if getattr(again, name) != getattr(image, name):
            raise ValueError('boot repack changed component: ' + name)
    paddles.process(again.kernel, check_only=True)
    return result, count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-boot', type=Path, help='read-only validation of KERNEL touch DTBs')
    parser.add_argument('--patch-boot', action='store_true', help='repack a checksummed Android v0 KERNEL')
    parser.add_argument('--expect-sha256', help='required input checksum for --patch-boot')
    parser.add_argument('input', nargs='?', type=Path, help='Image.gz + DTBs (KERNEL with --patch-boot)')
    parser.add_argument('output', nargs='?', type=Path, help='new output file; never overwritten')
    args = parser.parse_args()
    if args.check_boot:
        if args.input or args.output or args.patch_boot or args.expect_sha256:
            parser.error('--check-boot does not accept other arguments')
        image = read_boot(args.check_boot.read_bytes())
        _, count = process(image.kernel, check_only=True)
        print(f'PASS: {count} RP6 DTBs use 400 kHz I2C and bulk reads')
        return
    if not args.input or not args.output:
        parser.error('input and output required')
    if args.patch_boot != bool(args.expect_sha256):
        parser.error('--patch-boot requires --expect-sha256; checksum is only for boot images')
    data = args.input.read_bytes()
    result, count = repack(data, args.expect_sha256) if args.patch_boot else process(data)
    with args.output.open('xb') as stream:
        stream.write(result)
    print(f'RP6 touch: verified {count} DTBs; compressed kernel and unrelated DTB properties preserved')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, IndexError, struct.error, zlib.error,
            OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'ERROR: {error}')
