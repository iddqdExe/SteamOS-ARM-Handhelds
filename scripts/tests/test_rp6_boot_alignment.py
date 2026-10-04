"""Appended DTBs must be readable in-place by libfdt at aligned addresses."""
import ctypes
import ctypes.util
import gzip
import importlib.util
from pathlib import Path
import struct
import shutil
import subprocess
import tempfile
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
        raw = b'Linux Image fixture' * 100 + b'x'
        compressed = gzip.compress(raw, mtime=0)
        self.assertEqual(compressed[3], 0)
        original = tree()
        packed = mk.align_appended_dtbs(compressed + original + original)
        z = zlib.decompressobj(31)
        self.assertEqual(z.decompress(packed), raw)
        self.assertTrue(z.eof)
        pos = len(packed)-len(z.unused_data)
        if len(compressed)%8:
            self.assertEqual(packed[3], 8)
            header_end=packed.index(0,10)+1
            self.assertEqual(packed[header_end:pos],compressed[10:])
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


@unittest.skipUnless(shutil.which('gcc'), 'host C compiler required')
class NativeABLGzipTests(unittest.TestCase):
    def test_packed_kernel_works_with_actual_qualcomm_decompressor(self):
        from test_rp6_kernel_source import function
        source=(Path(__file__).parent/'fixtures/qualcomm-abl-decompress.c').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            c=Path(tmp)/'abl.c';so=Path(tmp)/'abl.so'
            c.write_text('''#include <stdlib.h>
#include <zlib.h>
#define GZIP_HEADER_LEN 10
#define GZIP_FILENAME_LIMIT 256
#define DEBUG(args) ((void)0)
#define AllocateZeroPool(n) calloc(1,n)
#define FreePool(a) free(a)
static void zlib_free(void *o, void *a) { (void)o; free(a); }
static void *zlib_alloc(void *o, unsigned items, unsigned size) { (void)o; return calloc(items,size); }
'''+ 'int '+function(source[source.index('\nint\ndecompress ('):].replace('decompress (','decompress('),'decompress'))
            subprocess.run(['gcc','-shared','-fPIC','-Wall','-Werror',str(c),'-lz','-o',str(so)],check=True)
            lib=ctypes.CDLL(str(so));fn=lib.decompress
            fn.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_void_p,ctypes.c_uint,ctypes.POINTER(ctypes.c_uint),ctypes.POINTER(ctypes.c_uint)]
            raw=b'Linux Image fixture'*100+b'x'
            payload=mk.align_appended_dtbs(gzip.compress(raw,mtime=0)+tree()+tree())
            inp=ctypes.create_string_buffer(payload);out=ctypes.create_string_buffer(len(raw)+4096)
            pos=ctypes.c_uint();size=ctypes.c_uint()
            self.assertEqual(fn(inp,len(payload),out,len(out),ctypes.byref(pos),ctypes.byref(size)),0)
            self.assertEqual(out.raw[:size.value],raw)
            z=zlib.decompressobj(31);z.decompress(payload)
            self.assertEqual(pos.value,len(payload)-len(z.unused_data))
