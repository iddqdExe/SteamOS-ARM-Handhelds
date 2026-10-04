"""Keep sealed userspace protected when assembling a new kernel image."""
import importlib.util
from pathlib import Path
import unittest

REPO = Path(__file__).resolve().parents[2]


class KernelReleasePolicyTests(unittest.TestCase):
    def setUp(self):
        path = REPO / 'scripts/prepare-rp6-kernel-release.py'
        self.assertTrue(path.is_file(), 'kernel image assembler is missing')
        spec = importlib.util.spec_from_file_location('kernel_release', path)
        self.tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.tool)

    def test_matching_modules_and_firmware_are_allowed(self):
        before = {'usr/lib/modules/old/one.ko': {'sha256': 'old'}, 'usr/bin/gamescope': {'sha256': 'fixed'}}
        after = {'usr/lib/modules/new/two.ko': {'sha256': 'new'}, 'usr/bin/gamescope': {'sha256': 'fixed'},
                 'usr/lib/firmware/qcom/a740_sqe.fw': {'sha256': 'new'}}
        self.assertEqual(len(self.tool.assert_root_delta(before, after)), 3)

    def test_runtime_settings_and_metadata_changes_are_rejected(self):
        for path in ('usr/bin/gamescope', 'usr/lib/libvulkan_freedreno.so', 'opt/fex/bin/FEXInterpreter',
                     'var/lib/overlays/etc/upper/konkrd.conf', 'usr/lib/konkr/konkr-standby', 'usr/lib'):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, 'userspace'):
                    self.tool.assert_root_delta({path: {'uid': 0}}, {path: {'uid': 1000}})

    def test_boot_replacement_preserves_other_files(self):
        before = {'KERNEL': {'sha256': 'old'}, 'KERNEL.md5': {'sha256': 'old'}, 'boot.ini': {'sha256': 'fixed'}}
        after = {'KERNEL': {'sha256': 'new'}, 'KERNEL.md5': {'sha256': 'new'}, 'boot.ini': {'sha256': 'fixed'}}
        self.assertEqual(set(self.tool.assert_boot_delta(before, after)), {'KERNEL', 'KERNEL.md5'})
        after['boot.ini'] = {'sha256': 'changed'}
        with self.assertRaisesRegex(ValueError, 'BOOT'):
            self.tool.assert_boot_delta(before, after)


if __name__ == '__main__': unittest.main()
