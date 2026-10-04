#!/usr/bin/env python3
"""Minimal Android boot image (header v0) writer for ROCKNIX ABL.

Same layout ROCKNIX produces with AOSP mkbootimg.py:
  --kernel_offset 0 --ramdisk_offset 0 --tags_offset 0 --header_version 0
  (base 0x10000000), ramdisk = b"dummy", os_version 12.0.0.
ABL decompresses the gzip kernel and scans the DTBs appended after it.

Without --ramdisk it writes that dummy ramdisk (the initramfs is then built
into the kernel, EMBED_INITRAMFS in soc.env).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import struct
import zlib
from pathlib import Path

BOOT_MAGIC = b"ANDROID!"
BASE = 0x10000000


def align_appended_dtbs(payload: bytes) -> bytes:
    """Keep contiguous FDTs readable in-place, preserving Image and DT sections."""
    z = zlib.decompressobj(31)
    try:
        z.decompress(payload)
    except zlib.error as error:
        raise ValueError('invalid gzip kernel') from error
    if not z.eof:
        raise ValueError('truncated gzip kernel')
    compressed = payload[:len(payload)-len(z.unused_data)]
    tail = z.unused_data
    if not tail:
        raise ValueError('missing appended DTBs')
    needed = -len(compressed) % 8
    if needed:
        if compressed[:3] != b'\x1f\x8b\x08' or compressed[3] != 0:
            raise ValueError('unaligned gzip kernel requires a plain gzip header')
        # RFC1952 FEXTRA: unknown subfields are skipped by decompressors.
        # Padding inside the gzip header keeps DTBs immediately after EOF;
        # the deflate stream, Image, CRC and ISIZE stay byte-for-byte intact.
        added = needed if needed >= 6 else needed + 8
        extra = b'AL' + struct.pack('<H', added-6) + b'\0'*(added-6)
        compressed = (compressed[:3] + b'\x04' + compressed[4:10] +
                      struct.pack('<H', len(extra)) + extra + compressed[10:])
    trees = []
    while tail:
        if len(tail) < 40 or tail[:4] != b'\xd0\x0d\xfe\xed':
            raise ValueError('unexpected data between appended DTBs')
        size = struct.unpack_from('>I', tail, 4)[0]
        if not 40 <= size <= len(tail):
            raise ValueError('truncated appended DTB')
        tree, tail = tail[:size], tail[size:]
        padded = (size + 7) & ~7
        # Only totalsize and trailing free space change. Never recompile DTS.
        trees.append(tree[:4] + struct.pack('>I', padded) + tree[8:] + b'\0'*(padded-size))
    return compressed + b''.join(trees)


def pad(data: bytes, page: int) -> bytes:
    rem = len(data) % page
    return data if rem == 0 else data + b"\0" * (page - rem)


def os_version_field(major: int, minor: int, patch: int, year: int, month: int) -> int:
    ver = (major << 14) | (minor << 7) | patch
    lvl = ((year - 2000) << 4) | month
    return (ver << 11) | lvl


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--align-dtbs", action="store_true", help="align appended RP6 DTBs for in-place libfdt access")
    ap.add_argument("--ramdisk")
    ap.add_argument("--cmdline", default="")
    ap.add_argument("--pagesize", type=int, default=2048)
    ap.add_argument("--kernel-addr", type=lambda v: int(v, 0), default=BASE)
    ap.add_argument("--ramdisk-addr", type=lambda v: int(v, 0), default=BASE)
    ap.add_argument("--tags-addr", type=lambda v: int(v, 0), default=BASE)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    kernel = Path(a.kernel).read_bytes()
    if a.align_dtbs:
        kernel = align_appended_dtbs(kernel)
    ramdisk = Path(a.ramdisk).read_bytes() if a.ramdisk else b"dummy"
    cmd = a.cmdline.encode("ascii")
    if len(cmd) >= 512:
        raise SystemExit(f"cmdline too long ({len(cmd)} >= 512)")

    today = datetime.date.today()
    sha = hashlib.sha1()
    for blob in (kernel, ramdisk, b""):
        sha.update(blob)
        sha.update(struct.pack("<I", len(blob)))

    hdr = struct.pack(
        "<8s10I16s512s32s1024s",
        BOOT_MAGIC,
        len(kernel), a.kernel_addr,    # kernel size / addr
        len(ramdisk), a.ramdisk_addr,  # ramdisk size / addr
        0, BASE + 0x00F00000,          # second size / addr
        a.tags_addr,                   # tags addr
        a.pagesize,
        0,                             # header_version
        os_version_field(12, 0, 0, today.year, today.month),
        b"",                           # name
        cmd,
        sha.digest().ljust(32, b"\0"),
        b"",                           # extra cmdline
    )
    img = pad(hdr, a.pagesize) + pad(kernel, a.pagesize) + pad(ramdisk, a.pagesize)
    Path(a.out).write_bytes(img)
    print(f"{a.out}: {len(img)} bytes, kernel {len(kernel)}, cmdline {len(cmd)} chars")


if __name__ == "__main__":
    main()
