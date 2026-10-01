#!/usr/bin/env python3
"""Verify the ARM64 InputPlumber loader and direct DT_NEEDED libraries in a rootfs."""
import argparse
import os
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess


def target_path(root, path):
    """Resolve absolute target symlinks relative to rootfs, never the build host."""
    pending = list(PurePosixPath(path).parts)
    current = []
    links = 0
    while pending:
        part = pending.pop(0)
        if part in {'/', '.'}:
            continue
        if part == '..':
            if not current:
                raise ValueError('library symlink escapes rootfs: ' + str(path))
            current.pop()
            continue
        candidate = root.joinpath(*current, part)
        if candidate.is_symlink():
            links += 1
            if links > 40:
                raise ValueError('library symlink loop in rootfs: ' + str(path))
            destination = os.readlink(candidate)
            if destination.startswith('/'):
                current = []
            pending = list(PurePosixPath(destination).parts) + pending
        else:
            current.append(part)
    return root.joinpath(*current)


def require_arm64(path):
    with path.open('rb') as stream:
        header = stream.read(64)
    if len(header) < 64 or header[:7] != b'\x7fELF\x02\x01\x01' or struct.unpack_from('<H', header, 18)[0] != 183:
        raise ValueError('expected a 64-bit little-endian AArch64 ELF: ' + str(path))


def check(binary, root):
    require_arm64(binary)

    def analyze(flag):
        try:
            return subprocess.run(['readelf', flag, str(binary)], check=True,
                                  env={**os.environ, 'LC_ALL': 'C'}, capture_output=True,
                                  text=True).stdout
        except (OSError, subprocess.CalledProcessError) as error:
            raise ValueError('readelf analysis failed; install binutils and verify the ELF: ' + str(error)) from error

    dynamic = analyze('-dW')
    needed = re.findall(r'\(NEEDED\).*\[([^\]]+)\]', dynamic)
    if 'Dynamic section at offset' not in dynamic or not needed:
        raise ValueError('dynamic dependencies could not be determined for InputPlumber')
    program = analyze('-lW')
    interpreter = re.search(r'Requesting program interpreter:\s*([^\]]+)\]', program)
    if not interpreter:
        raise ValueError('readelf did not report the InputPlumber program interpreter')
    loader = interpreter.group(1).strip()
    if not loader.startswith('/') or not target_path(root, loader).is_file():
        raise ValueError('missing loader in rootfs: ' + loader)
    require_arm64(target_path(root, loader))
    directories = ['/usr/lib', '/usr/lib64', '/lib', '/lib64',
                   '/usr/lib/aarch64-linux-gnu', '/lib/aarch64-linux-gnu']
    for soname in needed:
        if '/' in soname:
            raise ValueError('unsupported DT_NEEDED path: ' + soname)
        candidates = [target_path(root, directory + '/' + soname) for directory in directories]
        library = next((path for path in candidates if path.is_file()), None)
        if library is None:
            raise ValueError('missing library in rootfs: ' + soname)
        require_arm64(library)
    print('AArch64 ELF verified; loader:', loader)
    print('NEEDED:', ', '.join(needed))
    print('all direct NEEDED libraries present in rootfs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('rootfs', type=Path)
    args = parser.parse_args()
    check(args.binary, args.rootfs.resolve())


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, struct.error) as error:
        raise SystemExit('ERROR: ' + str(error))
