"""Package on the image filesystem without copying its large system tree."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('rsync'), 'Linux metadata tools required')
class PackageStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name); self.root = self.base / 'root'
        for rel in ('usr/lib', 'opt', 'etc', 'home/steamos/homebrew/plugins/konkr-control',
                    'home/steamos/homebrew/plugins/decky-lsfg-vk'):
            (self.root / rel).mkdir(parents=True)
        self.layer = self.root / 'usr/lib/liblsfg-vk-layer-arm64.so'
        self.layer.write_bytes(b'fixture layer'); self.layer.chmod(0o640)
        os.setxattr(self.layer, 'user.up04', b'metadata')
        if os.geteuid() == 0: os.chown(self.layer, 123, 456)
        self.kernel = self.base / 'KERNEL'; self.kernel.write_bytes(b'fixture kernel')
        self.output = self.base / 'update.tar.gz'

    def build(self, stage):
        return subprocess.run([sys.executable, str(REPO / 'scripts/build-update-package.py'),
                               '--rootfs', str(self.root), '--kernel', str(self.kernel),
                               '--soc', 'sm8550', '--device', 'Retroid Pocket 6',
                               '--version', 'fixture', '--output', str(self.output),
                               '--staging-dir', str(stage)], capture_output=True, text=True)

    def test_image_staging_preserves_source_and_archive_metadata(self):
        before = self.layer.stat()
        result = self.build(self.root)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        after = self.layer.stat()
        self.assertEqual((before.st_ino, before.st_uid, before.st_gid, before.st_mode, before.st_nlink),
                         (after.st_ino, after.st_uid, after.st_gid, after.st_mode, after.st_nlink))
        self.assertEqual(self.layer.read_bytes(), b'fixture layer')
        self.assertEqual(os.getxattr(self.layer, 'user.up04'), b'metadata')
        self.assertEqual(list(self.root.glob('konkr-package-*')), [])
        with tarfile.open(self.output) as archive:
            member = archive.getmember('root/usr/lib/liblsfg-vk-layer-arm64.so')
            self.assertEqual((member.uid, member.gid, member.mode), (before.st_uid, before.st_gid, 0o640))
            self.assertEqual(member.pax_headers['SCHILY.xattr.user.up04'], 'metadata')

    def test_rejects_staging_inside_copied_system_tree(self):
        result = self.build(self.root / 'usr')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('staging directory overlaps payload', result.stderr)
        self.assertFalse(self.output.exists())

    def test_rejects_staging_inside_copied_home_tree(self):
        result = self.build(self.root / 'home/steamos/homebrew/plugins/konkr-control')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('staging directory overlaps payload', result.stderr)
        self.assertFalse(self.output.exists())
