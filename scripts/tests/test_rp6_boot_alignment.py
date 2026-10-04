"""Appended DTBs must be readable in-place by libfdt at aligned addresses."""
import ctypes
import ctypes.util
import gzip
import importlib.util
from pathlib import Path
import struct
import unittest
import zlib

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('mkboot_align', REPO / 'external-and-mods/kernel-common/mkbootimg-v0.py')
mk = importlib.util.module_from_spec(spec); spec.loader.exec_module(mk)


def tree():
    # Minimal real FDT with root and model property; deliberately odd totalsize.
    strings = b'model\0'
    structure = struct.pack('>I', 1) + b'\0'*4 + struct.pack('>3I', 3, 4, 0) + b'RP6\0'
    structure += struct.pack('>2I', 2, 9)
    size = 56 + len(structure) + len(strings)
    return struct.pack('>10I', 0xd00dfeed, size, 56, 56+len(structure), 40, 17, 16, 0, len(strings), len(structure)) + b'\0'*16 + structure + strings


class BootAlignmentTests(unittest.TestCase):
    def test_preserves_image_and_dtb_sections_with_aligned_headers(self):
        raw = b'Linux Image fixture' * 100
        compressed = gzip.compress(raw, mtime=0)
        self.assertEqual(compressed[3], 0)
        original = tree()
        packed = mk.align_appended_dtbs(compressed + original + original)
        z = zlib.decompressobj(31)
        self.assertEqual(z.decompress(packed), raw)
        self.assertTrue(z.eof)
        pos = len(packed)-len(z.unused_data)
        if len(compressed)%8:
            extra_size=struct.unpack_from('<H',packed,10)[0]
            self.assertEqual(packed[12+extra_size:pos],compressed[10:])
        for _ in range(2):
            self.assertEqual(pos % 8, 0)
            size = struct.unpack_from('>I', packed, pos+4)[0]
            got = packed[pos:pos+size]
            self.assertEqual(got[:4], original[:4])
            self.assertEqual(got[8:len(original)], original[8:])
            self.assertEqual(got[len(original):], b'\0'*(size-len(original)))
            self.assertEqual(size % 8, 0)
            pos += size
        self.assertEqual(pos, len(packed))
        self.assertEqual(mk.align_appended_dtbs(packed), packed)
        library = ctypes.util.find_library('fdt')
        if library:
            lib = ctypes.CDLL(library); lib.fdt_check_header.argtypes=[ctypes.c_void_p];lib.fdt_check_header.restype=ctypes.c_int
            buf = ctypes.create_string_buffer(packed);pos=len(packed)-len(z.unused_data)
            for _ in range(2):
                self.assertEqual(lib.fdt_check_header(ctypes.addressof(buf)+pos),0)
                pos += struct.unpack_from('>I',packed,pos+4)[0]

    def test_rejects_truncated_or_non_dtb_tail(self):
        prefix = gzip.compress(b'fixture', mtime=0)
        for payload in (prefix+b'wrong tail', prefix+tree()[:-1], prefix[:10]):
            with self.assertRaises(ValueError): mk.align_appended_dtbs(payload)
