#!/usr/bin/env python3
"""Carry the verified RP6 GPIO paddle fix into imported SM8550 kernels.

Edits DTBs with fdtput, never a DTS round trip. Compressed kernel bytes and
other models stay unchanged. This operates on build files, never a device.
"""
import argparse
from pathlib import Path
import struct
import subprocess
import tempfile
import zlib

MAGIC = b'\xd0\x0d\xfe\xed'
MODELS = {b'Retroid Pocket 6\0', b'Retroid Pocket 6 TOP-DPAD\0'}
TLMM = '/soc@0/pinctrl@f100000'
STATE = TLMM + '/paddle-keys-default-state'
PADDLES = [('left', 57, 0x135), ('right', 58, 0x132)]


def cells(*values):
    return struct.pack('>' + 'I' * len(values), *values)


def properties(data):
    """Read FDT property values verbatim, including regulator u32s."""
    size, start, strings = struct.unpack_from('>3I', data, 4)
    end_struct = start + struct.unpack_from('>I', data, 36)[0]
    end_strings = strings + struct.unpack_from('>I', data, 32)[0]
    if size != len(data) or not (40 <= start < end_struct <= size) or end_strings > size:
        raise ValueError('invalid FDT bounds')
    pos, stack, result = start, [], {}
    while pos + 4 <= end_struct:
        token = struct.unpack_from('>I', data, pos)[0]
        pos += 4
        if token == 1:
            end = data.index(0, pos, end_struct)
            stack.append(data[pos:end].decode())
            result['/'.join(stack) or '/'] = {}
            pos = (end + 4) & ~3
        elif token == 2:
            stack.pop()
        elif token == 3:
            length, offset = struct.unpack_from('>2I', data, pos)
            pos += 8
            if pos + length > end_struct or not strings <= strings + offset < end_strings:
                raise ValueError('invalid FDT property bounds')
            end = data.index(0, strings + offset, end_strings)
            name = data[strings + offset:end].decode()
            result['/'.join(stack) or '/'][name] = data[pos:pos + length]
            pos = (pos + length + 3) & ~3
        elif token == 4:
            continue
        elif token == 9 and not stack:
            return result
        else:
            raise ValueError('invalid FDT structure token')
    raise ValueError('missing FDT end token')


def split_payload(data):
    decompressor = zlib.decompressobj(31)
    decompressor.decompress(data)
    if not decompressor.eof:
        raise ValueError('truncated gzip kernel')
    tail = decompressor.unused_data
    prefix = data[:len(data) - len(tail)]
    trees = []
    while tail:
        if len(tail) < 40 or tail[:4] != MAGIC:
            raise ValueError('unexpected data between appended DTBs')
        size = struct.unpack_from('>I', tail, 4)[0]
        if not 40 <= size <= len(tail):
            raise ValueError('truncated appended DTB')
        tree, tail = tail[:size], tail[size:]
        properties(tree)
        trees.append(tree)
    if not trees:
        raise ValueError('no appended DTBs')
    return prefix, trees


def verify_paddles(props):
    keys = props['/gpio-keys']
    if b'gpio-keys' not in keys.get('compatible', b'').split(b'\0'):
        raise ValueError('RP6 paddle controller is not gpio-keys')
    if keys.get('pinctrl-names', b'').split(b'\0')[0] != b'default':
        raise ValueError('RP6 paddle pinctrl-0 is not the default state')
    for path in [TLMM, '/gpio-keys', '/gpio-keys/key-paddle-left',
                 '/gpio-keys/key-paddle-right']:
        if props[path].get('status', b'okay\0') not in {b'okay\0', b'ok\0'}:
            raise ValueError('disabled RP6 paddle node: ' + path)
    handle = props[TLMM]['phandle']
    state = props[STATE]
    expected = {'pins': b'gpio57\0gpio58\0', 'function': b'gpio\0',
                'bias-pull-up': b'', 'input-enable': b'', 'drive-strength': cells(2)}
    for name, value in expected.items():
        if state.get(name) != value:
            raise ValueError('conflicting RP6 paddle pinctrl: ' + name)
    pinctrl = props['/gpio-keys']['pinctrl-0']
    handles = [pinctrl[i:i + 4] for i in range(0, len(pinctrl), 4)]
    if state['phandle'] not in handles:
        raise ValueError('RP6 paddle pinctrl not connected')
    for side, gpio, code in PADDLES:
        node = props['/gpio-keys/key-paddle-' + side]
        if node.get('linux,input-type', cells(1)) != cells(1):
            raise ValueError('RP6 paddle must emit EV_KEY: ' + side)
        if node.get('gpios') != handle + cells(gpio, 1) or node.get('linux,code') != cells(code):
            raise ValueError('conflicting RP6 paddle: ' + side)


def fix_tree(data, check_only):
    before = properties(data)
    if before['/'].get('model') not in MODELS:
        return data, False
    if before[TLMM].get('compatible') != b'qcom,sm8550-tlmm\0':
        raise ValueError('unexpected RP6 GPIO controller')
    existing = [p for p in [STATE, '/gpio-keys/key-paddle-left',
                           '/gpio-keys/key-paddle-right'] if p in before]
    if existing:
        if len(existing) != 3:
            raise ValueError('partial RP6 paddle definitions; refusing to overwrite')
        verify_paddles(before)
        return data, True
    if check_only:
        raise ValueError('RP6 paddle definitions missing; reimport with import-sm8550-kernel.sh')
    handle = struct.unpack('>I', before[TLMM]['phandle'])[0]
    new_handle = max(struct.unpack('>I', p['phandle'])[0]
                     for p in before.values() if 'phandle' in p) + 1
    if new_handle >= 0xffffffff:
        raise ValueError('no free FDT phandle')
    pinctrl = before['/gpio-keys']['pinctrl-0']
    if len(pinctrl) % 4:
        raise ValueError('invalid RP6 pinctrl list')
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'rp6.dtb'
        path.write_bytes(data)

        def put(*args):
            subprocess.run(['fdtput', *map(str, args)], check=True, capture_output=True)

        put('-c', path, STATE)
        put('-t', 's', path, STATE, 'pins', 'gpio57', 'gpio58')
        put('-t', 's', path, STATE, 'function', 'gpio')
        put(path, STATE, 'bias-pull-up')
        put(path, STATE, 'input-enable')
        put('-t', 'i', path, STATE, 'drive-strength', 2)
        put('-t', 'i', path, STATE, 'phandle', new_handle)
        for side, gpio, code in PADDLES:
            node = '/gpio-keys/key-paddle-' + side
            put('-c', path, node)
            put('-t', 's', path, node, 'label', 'Back Paddle ' + side.title())
            put('-t', 'i', path, node, 'debounce-interval', 15)
            put('-t', 'i', path, node, 'gpios', handle, gpio, 1)
            put('-t', 'i', path, node, 'linux,code', code)
        old_handles = struct.unpack('>' + 'I' * (len(pinctrl) // 4), pinctrl)
        put('-t', 'i', path, '/gpio-keys', 'pinctrl-0', *old_handles, new_handle)
        result = path.read_bytes()
        subprocess.run(['dtc', '-q', '-I', 'dtb', '-O', 'dts', str(path)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    after = properties(result)
    # Protect every original property: the earlier DTS round trip corrupted
    # a 3296000 uV regulator value and stopped beta8 RP6 from booting.
    for node, values in before.items():
        expected = dict(values)
        if node == '/gpio-keys':
            expected['pinctrl-0'] = pinctrl + cells(new_handle)
        if after[node] != expected:
            raise ValueError('DTB repair changed an unrelated property: ' + node)
    if set(after) - set(before) != {STATE, '/gpio-keys/key-paddle-left',
                                   '/gpio-keys/key-paddle-right'}:
        raise ValueError('DTB repair changed unrelated nodes')
    verify_paddles(after)
    return result, True


def process(data, check_only=False):
    prefix, trees = split_payload(data)
    results = [fix_tree(tree, check_only) for tree in trees]
    count = sum(is_rp6 for _, is_rp6 in results)
    if not count:
        raise ValueError('SM8550 kernel has no RP6 DTB')
    return prefix + b''.join(tree for tree, _ in results), count


def boot_payload(data):
    if len(data) < 44 or data[:8] != b'ANDROID!':
        raise ValueError('expected Android boot image')
    size = struct.unpack_from('<I', data, 8)[0]
    page = struct.unpack_from('<I', data, 36)[0]
    version = struct.unpack_from('<I', data, 40)[0]
    if version > 2 or page < 608 or page & (page - 1) or page + size > len(data):
        raise ValueError('unsupported or truncated Android boot image')
    return data[page:page + size]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-boot', type=Path, help='validate an existing KERNEL without changes')
    parser.add_argument('input', nargs='?', type=Path, help='Image.gz plus concatenated DTBs')
    parser.add_argument('output', nargs='?', type=Path)
    args = parser.parse_args()
    if args.check_boot:
        if args.input or args.output:
            parser.error('--check-boot does not accept input/output')
        data = boot_payload(args.check_boot.read_bytes())
        _, count = process(data, check_only=True)
        print(f'PASS: {count} RP6 DTBs have independent left/right paddles')
    else:
        if not args.input or not args.output:
            parser.error('input and output required')
        result, count = process(args.input.read_bytes())
        args.output.write_bytes(result)
        print(f'RP6 paddles: verified {count} DTBs; compressed kernel and other DTBs unchanged')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, IndexError, struct.error, zlib.error,
            OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'ERROR: {error}')
