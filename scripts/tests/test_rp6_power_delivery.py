"""Power scripts must reach reused rootfs and optional beta8 test images."""
import importlib.util
import subprocess
import shlex
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / 'scripts/install-rp6-power.sh'
SOURCES = ROOT / 'sm8650-overlay/usr/lib/konkr'


class PowerDeliveryTests(unittest.TestCase):
    def test_cpu_profile_runtime_replaces_stale_daemon_and_cli(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'usr').mkdir()
            result = subprocess.run(['bash', str(INSTALL), str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for rel in ('usr/lib/konkr/konkrd', 'usr/bin/konkrctl'):
                self.assertTrue((root / rel).is_file(), f'CPU preset runtime missing: {rel}')
                self.assertEqual((root / rel).read_bytes(), (ROOT / 'sm8650-overlay' / rel).read_bytes())

    def test_installs_both_scripts_over_stale_reused_rootfs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'usr/lib/konkr'
            target.mkdir(parents=True)
            for name in ('konkr-standby', 'konkr-sleep'):
                (target / name).write_text('old script')
            result = subprocess.run(['bash', str(INSTALL), str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name in ('konkr-standby', 'konkr-sleep'):
                self.assertEqual((target / name).read_bytes(), (SOURCES / name).read_bytes())
                self.assertEqual((target / name).stat().st_mode & 0o777, 0o755)
            again = subprocess.run(['bash', str(INSTALL), str(root)], capture_output=True, text=True)
            self.assertEqual(again.returncode, 0, again.stderr)

    def test_refuses_live_root(self):
        result = subprocess.run(['bash', str(INSTALL), '/'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('offline rootfs', result.stderr)

    def test_refuses_symlinked_destination_before_changing_pair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'rootfs'
            target = root / 'usr/lib/konkr'
            target.mkdir(parents=True)
            outside = Path(temp) / 'outside'
            outside.write_text('keep outside')
            (target / 'konkr-sleep').symlink_to(outside)
            (target / 'konkr-standby').write_text('keep first script')
            result = subprocess.run(['bash', str(INSTALL), str(root)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(outside.read_text(), 'keep outside')
            self.assertEqual((target / 'konkr-standby').read_text(), 'keep first script')

    def test_packaging_runtime_refreshes_power_without_full_overlay(self):
        script = (ROOT / 'make-steamos-sm8650.sh').read_text()
        start = script.index('prepare_runtime() {')
        end = script.index('\n}\n', start) + 3
        function = script[start:end]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'rootfs'
            (root / 'usr').mkdir(parents=True)
            commands = Path(temp) / 'scripts'
            commands.mkdir()
            for name, body in {
                'install-inputplumber-sm8550.sh': '#!/bin/bash\nexit 0\n',
                'install-rp6-power.sh': '#!/bin/bash\nexec bash ' + shlex.quote(str(INSTALL)) + ' "$@"\n',
            }.items():
                (commands / name).write_text(body)
                (commands / name).chmod(0o755)
            # Exercise the real packaging function, isolating unrelated
            # runtime installation and InputPlumber downloads.
            harness = 'set -e\nR=' + shlex.quote(str(root)) + '\nOVL=' + shlex.quote(str(ROOT / 'steamos-overlay'))
            harness += '\nSCRIPTS=' + shlex.quote(str(commands)) + '\ninstall() { :; }\nlog() { :; }\n'
            result = subprocess.run(['bash', '-c', harness + function + '\nprepare_runtime'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for name in ('konkr-standby', 'konkr-sleep'):
                self.assertTrue((root / 'usr/lib/konkr' / name).is_file(), 'packaging skipped power delivery')
                self.assertEqual((root / 'usr/lib/konkr' / name).read_bytes(), (SOURCES / name).read_bytes())

    def test_test_image_option_delivers_same_pair(self):
        spec = importlib.util.spec_from_file_location('module2_image', ROOT / 'scripts/prepare-rp6-beta8-test.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        self.assertTrue(hasattr(builder, 'install_power'), 'test image has no power delivery path')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'usr').mkdir()
            installed = builder.install_power(root)
            self.assertEqual(installed, ['usr/lib/konkr/konkr-standby', 'usr/lib/konkr/konkr-sleep',
                                         'usr/lib/konkr/konkrd', 'usr/bin/konkrctl'])
            for name in installed:
                self.assertEqual((root / name).read_bytes(), (ROOT / 'sm8650-overlay' / name).read_bytes())


if __name__ == '__main__':
    unittest.main()
