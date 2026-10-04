"""Keep sealed userspace protected when assembling a new kernel image."""
import importlib.util
from pathlib import Path
import unittest
import tempfile

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

    def test_existing_bluetooth_firmware_cannot_disappear(self):
        before = {'usr/lib/firmware/qca/hmtbtfw20.tlv': {'kind': 'file', 'sha256': 'accepted-bt'},
                  'usr/lib/firmware/qcom/a740_sqe.fw': {'kind': 'file', 'sha256': 'old-gpu'}}
        after = {'usr/lib/firmware/qcom/a740_sqe.fw': {'kind': 'file', 'sha256': 'new-gpu'}}
        with self.assertRaisesRegex(ValueError, 'firmware removed'):
            self.tool.assert_root_delta(before, after)

    def test_firmware_overlay_may_update_gpu_while_preserving_bluetooth(self):
        before = {'usr/lib/firmware/qca/hmtbtfw20.tlv': {'kind': 'file', 'sha256': 'accepted-bt'},
                  'usr/lib/firmware/qcom/a740_sqe.fw': {'kind': 'file', 'sha256': 'old-gpu'}}
        after = {'usr/lib/firmware/qca/hmtbtfw20.tlv': {'kind': 'file', 'sha256': 'accepted-bt'},
                 'usr/lib/firmware/qcom/a740_sqe.fw': {'kind': 'file', 'sha256': 'new-gpu'}}
        self.assertEqual(self.tool.assert_root_delta(before, after), ['usr/lib/firmware/qcom/a740_sqe.fw'])

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

    def test_power_runtime_allows_only_explicit_payload(self):
        path='usr/lib/konkr/konkr-sleep-state'
        self.assertEqual(self.tool.assert_root_delta({}, {path: {'kind':'file'}}, power_runtime=True), [path])
        for forbidden in ('usr/lib/konkr/konkrd','usr/bin/gamescope','etc/konkrd.conf','usr/lib/systemd/system/arbitrary.service'):
            with self.assertRaisesRegex(ValueError,'userspace'):
                self.tool.assert_root_delta({}, {forbidden:{'kind':'file'}}, power_runtime=True)

    def test_late_failure_leaves_no_published_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / 'candidate.tar.gz'
            with self.assertRaisesRegex(ValueError, 'late filesystem failure'):
                with self.tool.package_staging(final) as staged:
                    staged.write_bytes(b'checked package')
                    staged.with_name(staged.name+'.sha256').write_text('staged checksum')
                    raise ValueError('late filesystem failure')
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_package_is_published_after_validation_with_final_checksum_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / 'candidate.tar.gz'
            with self.tool.package_staging(final) as staged:
                staged.write_bytes(b'validated package')
                self.assertFalse(final.exists())
                self.tool.publish_staged_package(staged, final)
            self.assertEqual(final.read_bytes(), b'validated package')
            self.assertTrue(final.with_name(final.name+'.sha256').read_text().endswith('  candidate.tar.gz\n'))


if __name__ == '__main__': unittest.main()
