"""Repack only external RP6 ramdisks; preserve Image/DTBs and boot metadata."""
from pathlib import Path
import gzip
import hashlib
import importlib.util
import struct
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('up01_bootimg', REPO / 'external-and-mods/ufs-install/ufs-bootimg.py')
boot = importlib.util.module_from_spec(spec); spec.loader.exec_module(boot)


def cpio_fixture(files):
    data = bytearray()
    for inode, (name, blob) in enumerate([*files.items(), ('TRAILER!!!', b'')], 1):
        name = name.encode() + b'\0'
        fields = (inode, 0o100755, 0, 0, 1, 0, len(blob), 0, 0, 0, 0, len(name), 0)
        data += b'070701' + ''.join(f'{n:08x}' for n in fields).encode() + name
        data += b'\0' * (-len(data) % 4)
        data += blob; data += b'\0' * (-len(data) % 4)
    return bytes(data)


class InitramfsRepackTests(unittest.TestCase):
    def run_repack(self, *, embedded=False, bad_digest=False, bad_id=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = cpio_fixture({'init': b'#!/bin/busybox sh\n. /konkr-update-recover\n',
                                    'konkr-update-recover': b'keep recovery', 'custom-marker': b'preserve'})
            kernel = gzip.compress(b'Linux version fixture\0' + (archive if embedded else b''), mtime=0) + b'unchanged DTBs'
            ramdisk = b'dummy' if embedded else gzip.compress(archive, mtime=0)
            (root / 'payload').write_bytes(kernel); (root / 'ramdisk').write_bytes(ramdisk)
            src, dst = root / 'KERNEL', root / 'candidate'
            subprocess.run(['python3', str(REPO / 'external-and-mods/kernel-common/mkbootimg-v0.py'),
                            '--kernel', str(root / 'payload'), '--ramdisk', str(root / 'ramdisk'),
                            '--cmdline', 'root=PARTUUID=keep-02 quiet', '--out', str(src)], check=True, capture_output=True)
            original = src.read_bytes()
            if bad_id:
                corrupted = bytearray(original); corrupted[576] ^= 1
                src.write_bytes(corrupted); original = bytes(corrupted)
            result = subprocess.run(['python3', str(REPO / 'scripts/repack-rp6-initramfs.py'),
                                     str(src), str(dst), '--expected-sha256',
                                     '0' * 64 if bad_digest else hashlib.sha256(original).hexdigest()],
                                    capture_output=True, text=True)
            return result, original, dst.read_bytes() if dst.exists() else None

    def test_external_ramdisk_preserves_kernel_metadata_and_recovery(self):
        result, original, candidate = self.run_repack()
        self.assertEqual(result.returncode, 0, result.stderr)
        before, after = boot.BootImg(original), boot.BootImg(candidate)
        for field in ('kernel', 'cmdline', 'kernel_addr', 'ramdisk_addr', 'tags_addr', 'page_size', 'os_version', 'name', 'extra', 'second'):
            self.assertEqual(getattr(before, field), getattr(after, field), field)
        self.assertEqual(after.id, after.expected_id())
        raw = gzip.decompress(after.ramdisk)
        self.assertIn(b'mount-etc-overlay', raw)
        self.assertIn(b'preserve', raw)
        self.assertIn(b'keep recovery', raw)

    def test_embedded_initramfs_requires_kernel_rebuild(self):
        result, _, candidate = self.run_repack(embedded=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('embedded initramfs', result.stderr)
        self.assertIsNone(candidate)

    def test_wrong_input_digest_leaves_no_output(self):
        result, _, candidate = self.run_repack(bad_digest=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA256 mismatch', result.stderr)
        self.assertIsNone(candidate)

    def test_invalid_boot_id_is_rejected(self):
        result, _, candidate = self.run_repack(bad_id=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('boot image ID', result.stderr)
        self.assertIsNone(candidate)


if __name__ == '__main__': unittest.main()
