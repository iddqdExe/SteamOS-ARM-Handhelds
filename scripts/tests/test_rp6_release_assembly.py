"""Sealed-base refusal paths and metadata preservation, without mounting a card."""
import importlib.util
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('assembly', REPO / 'scripts/prepare-rp6-release.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


class ReleaseAssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.base = self.folder / 'base.img'
        mbr = bytearray(512); mbr[510:] = b'\x55\xaa'
        for i, (kind, start, size) in enumerate(builder.LAYOUT):
            mbr[446 + i * 16 + 4] = kind
            struct.pack_into('<II', mbr, 446 + i * 16 + 8, start, size)
        self.base.write_bytes(mbr)

    def test_sealed_image_rejects_wrong_hash_and_symlink(self):
        with patch.object(builder, 'SIZE', 512):
            with self.assertRaisesRegex(ValueError, 'SHA256'):
                builder.validate_base(self.base, '0' * 64)
            alias = self.folder / 'alias.img'; alias.symlink_to(self.base)
            with self.assertRaisesRegex(ValueError, 'regular'):
                builder.validate_base(alias, builder.release.digest(self.base))
            builder.validate_base(self.base, builder.release.digest(self.base))

    def test_sealed_image_rejects_layout_even_with_correct_hash(self):
        data = bytearray(self.base.read_bytes()); data[450] = 0x83
        self.base.write_bytes(data)
        with patch.object(builder, 'SIZE', 512):
            with self.assertRaisesRegex(ValueError, 'layout'):
                builder.validate_base(self.base, builder.release.digest(self.base))

    def test_existing_partial_or_output_alias_is_refused_before_any_mount(self):
        image = self.folder / 'candidate.img'; package = self.folder / 'candidate.tar.gz'
        image.with_name(image.name + '.partial').write_bytes(b'unfinished')
        with self.assertRaisesRegex(ValueError, 'exists'):
            builder.output_paths(image, package)
        image.with_name(image.name + '.partial').unlink()
        package.symlink_to(self.folder / 'missing')
        with self.assertRaisesRegex(ValueError, 'exists'):
            builder.output_paths(image, package)

    def test_failure_to_unmount_retains_all_mounted_files(self):
        folder = self.folder / 'mounts'; folder.mkdir()
        commands = []
        def run(*args, **kwargs):
            commands.append(args)
            if args[0] == 'umount' and args[1].name == 'root':
                raise OSError('fixture unmount failed')
        with patch.object(builder.tempfile, 'mkdtemp', return_value=str(folder)), \
             patch.object(builder, 'run', run), patch.object(builder.shutil, 'rmtree') as remove:
            with self.assertRaisesRegex(ValueError, 'retained'):
                with builder.image_mounts(self.base): pass
            remove.assert_not_called()
        self.assertEqual([a[1].name for a in commands if a[0] == 'umount'], ['home', 'root', 'boot'])

    @unittest.skipUnless(os.uname().sysname == 'Linux', 'Linux metadata inventory required')
    def test_delta_refuses_changed_accepted_payload_and_dropped_metadata(self):
        root = self.folder / 'root'; (root / 'usr').mkdir(parents=True)
        accepted = root / 'usr/accepted'; accepted.write_bytes(b'accepted'); accepted.chmod(0o755)
        before = builder.tree_inventory(root)
        accepted.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'accepted payload'):
            builder.assert_delta(before, builder.tree_inventory(root))
        accepted.chmod(0o755); accepted.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'accepted payload'):
            builder.assert_delta(before, builder.tree_inventory(root))

    @unittest.skipUnless(os.uname().sysname == 'Linux', 'Linux xattrs required')
    def test_inventory_detects_lost_xattrs(self):
        root = self.folder / 'root'; root.mkdir(); p = root / 'file'; p.write_bytes(b'payload')
        os.setxattr(p, 'user.fixture', b'preserved')
        before = builder.tree_inventory(root)
        os.removexattr(p, 'user.fixture')
        with self.assertRaisesRegex(ValueError, 'accepted payload'):
            builder.assert_delta(before, builder.tree_inventory(root))


if __name__ == '__main__': unittest.main()
