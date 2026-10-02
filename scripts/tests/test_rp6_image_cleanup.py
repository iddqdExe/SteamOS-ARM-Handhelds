"""A failed unmount must never recursively delete a still-mounted filesystem."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('image_builder', REPO / 'scripts/prepare-rp6-beta8-test.py')
builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)


class ImageCleanupTests(unittest.TestCase):
    def test_missing_optional_power_sources_fail_before_copying_or_mounting(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(builder, 'REPO', Path(temporary)), \
                 patch.object(builder.sys, 'platform', 'linux'), \
                 patch.object(builder.os, 'geteuid', return_value=0), \
                 patch.object(builder, 'validate_base') as validate, \
                 patch.object(builder, 'run') as run:
                with self.assertRaisesRegex(ValueError, 'module2 source missing'):
                    builder.build(Path('/missing/base.img'), Path(temporary) / 'test.img', False, True)
                validate.assert_not_called()
                run.assert_not_called()
                self.assertFalse((Path(temporary) / 'test.img.partial').exists())

    def test_failed_unmount_attempts_other_mounts_and_retains_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / 'mounts'; folder.mkdir()
            commands = []
            def run(*args, **kwargs):
                commands.append(args)
                if args[0] == 'umount' and args[1].name == 'root':
                    raise subprocess.CalledProcessError(32, args)
            with patch.object(builder.tempfile, 'mkdtemp', return_value=str(folder)), \
                 patch.object(builder, 'run', run), patch.object(builder.shutil, 'rmtree') as remove:
                with self.assertRaisesRegex(ValueError, 'retained'):
                    with builder.image_mounts(Path('/tmp/copied.img')): pass
                self.assertEqual([args[1].name for args in commands if args[0] == 'umount'], ['root', 'boot'])
                remove.assert_not_called()
                self.assertTrue(folder.exists())

    def test_successful_unmount_removes_only_temporary_mount_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / 'mounts'; folder.mkdir()
            with patch.object(builder.tempfile, 'mkdtemp', return_value=str(folder)), patch.object(builder, 'run'):
                with builder.image_mounts(Path('/tmp/copied.img')): pass
                self.assertFalse(folder.exists())


if __name__ == '__main__': unittest.main()
