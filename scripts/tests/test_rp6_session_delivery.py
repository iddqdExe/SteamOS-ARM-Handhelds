"""Candidate preparation refuses unsafe outputs and mismatched root/BOOT."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


class CandidateSafetyTests(unittest.TestCase):
    def staged_root(self, folder):
        root = folder / 'root'; root.mkdir()
        subprocess.run(['bash', str(REPO / 'scripts/install-rp6-session.sh'), str(root)], check=True)
        wants = root / 'usr/lib/systemd/system/multi-user.target.wants'; wants.mkdir(parents=True)
        (wants / 'plugin_loader.service').symlink_to('../plugin_loader.service')
        return root

    def check_root(self, root):
        return subprocess.run(['python3', str(REPO / 'scripts/check-rp6-session.py'), str(root), str(root / 'absent-KERNEL')],
                              capture_output=True, text=True)

    def test_focusfix_unit_is_required_for_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.staged_root(Path(tmp))
            (root / 'usr/lib/systemd/user/konkr-focusfix.service').unlink()
            self.assertIn('missing UP-01 session file: usr/lib/systemd/user/konkr-focusfix.service', self.check_root(root).stderr)

    def test_preflight_rejects_missing_stale_and_nonexecutable_standby(self):
        cases = [('missing', 'missing UP-01 session file'),
                 ('stale', 'UP-01 staged content differs'),
                 ('not_executable', 'UP-01 file is not executable')]
        for case, message in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = self.staged_root(Path(tmp))
                standby = root / 'usr/lib/konkr/konkr-standby'
                standby.write_bytes((REPO / 'sm8650-overlay/usr/lib/konkr/konkr-standby').read_bytes())
                standby.chmod(0o755)
                if case == 'missing':
                    standby.unlink()
                elif case == 'stale':
                    standby.write_text('stale standby payload\n')
                else:
                    standby.chmod(0o644)
                result = self.check_root(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message + ': usr/lib/konkr/konkr-standby', result.stderr)

    def test_focusfix_enable_link_is_required_for_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.staged_root(Path(tmp))
            (root / 'usr/lib/systemd/user/gamescope-session.target.wants/konkr-focusfix.service').unlink()
            self.assertIn('invalid UP-01 enable link', self.check_root(root).stderr)

    def test_decky_enable_link_is_required_for_delivery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.staged_root(Path(tmp))
            (root / 'usr/lib/systemd/system/multi-user.target.wants/plugin_loader.service').unlink()
            self.assertIn('invalid UP-01 enable link', self.check_root(root).stderr)

    def test_decky_loader_requires_executable_mode_before_crypto_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.staged_root(Path(tmp))
            loader = root / 'home/steamos/homebrew/services/PluginLoader'; loader.parent.mkdir(parents=True)
            loader.write_bytes(b'placeholder'); loader.chmod(0o644)
            self.assertIn('Decky loader is not executable', self.check_root(root).stderr)

    def test_clean_image_builder_rejects_old_boot_before_image_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp); root = folder / 'root'; scripts = folder / 'scripts'
            scripts.mkdir(); (root / 'usr/lib/steamos').mkdir(parents=True)
            (root / 'usr/lib/steamos/wait-gamescope-env').touch()
            (scripts / 'check-rp6-input.sh').write_text('#!/bin/sh\nexit 0\n')
            (scripts / 'check-rp6-input.sh').chmod(0o755)
            (scripts / 'check-rp6-session.py').write_text('raise SystemExit("BOOT lacks matching UP-01 initramfs")\n')
            # Execute the real preflight portion before image allocation.
            source = (REPO / 'make-steamos-sm8650.sh').read_text()
            prefix = source.split('build_image() {', 1)[1].split('  command -v sfdisk', 1)[0]
            result = subprocess.run(['bash', '-ec', 'build_image() {' + prefix + '\n}\nbuild_image'],
                                    env={**os.environ, 'SOC': 'sm8550', 'R': str(root), 'SCRIPTS': str(scripts), 'KOUT': str(folder / 'kout')},
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('BOOT lacks matching UP-01', result.stderr)

    def test_existing_output_is_preserved_before_any_mount_or_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); output = root / 'candidate.img'; output.write_bytes(b'keep')
            result = subprocess.run(['python3', str(REPO / 'scripts/prepare-rp6-session-test.py'),
                                     str(root / 'missing.img'), str(output), '--expected-sha256', '0' * 64],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('output already exists', result.stderr)
            self.assertEqual(output.read_bytes(), b'keep')

    def test_incomplete_rootfs_fails_before_boot_artifact_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(['python3', str(REPO / 'scripts/check-rp6-session.py'), tmp, str(Path(tmp) / 'KERNEL')],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('missing UP-01 session file', result.stderr)


if __name__ == '__main__': unittest.main()

class AcceptedBaseSessionTests(unittest.TestCase):
    def test_old_standby_is_checked_against_explicit_baseline_hash(self):
        import hashlib, importlib.util
        spec=importlib.util.spec_from_file_location('base_session', REPO/'scripts/check-rp6-session.py')
        tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory() as tmp:
            root=CandidateSafetyTests().staged_root(Path(tmp));standby=root/'usr/lib/konkr/konkr-standby'
            standby.write_text('accepted baseline standby');standby.chmod(0o755)
            old=hashlib.sha256(standby.read_bytes()).hexdigest()
            # The fixture deliberately lacks Decky/kernel; a verified old
            # standby must pass the content gate and reach the missing artifact.
            with self.assertRaises(FileNotFoundError):tool.check(root,root/'absent-KERNEL',standby_sha256=old)
            standby.write_text('corrupt baseline standby')
            with self.assertRaisesRegex(ValueError,'staged content differs'):
                tool.check(root,root/'absent-KERNEL',standby_sha256=old)
