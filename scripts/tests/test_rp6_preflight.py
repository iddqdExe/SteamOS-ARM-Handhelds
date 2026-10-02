"""Ensure packaging cannot accept stale RP6 input files or a broken boot DTB."""
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_rp6_paddles import dtb, IMAGE, TOOL
from test_rp6_touch import boot as boot_image, BUS, TOUCH

REPO = Path(__file__).resolve().parents[2]


class PreflightTests(unittest.TestCase):
    def test_preflight_checks_persistent_map_and_boot_before_packaging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'rootfs'
            (root / 'usr').mkdir(parents=True)
            (root / 'var/lib/overlays/etc/upper').mkdir(parents=True)
            subprocess.run(['bash', str(REPO / 'scripts/install-inputplumber-sm8550.sh'),
                            str(root), '--config-only'], check=True, capture_output=True)
            gdbus = root / 'usr/bin/gdbus'
            gdbus.parent.mkdir(parents=True)
            gdbus.write_text('#!/bin/sh\nexit 0\n')
            gdbus.chmod(0o755)
            source, fixed, boot = [Path(tmp) / p for p in ['payload', 'fixed', 'KERNEL']]
            source.write_bytes(IMAGE + dtb())
            subprocess.run(['python3', str(TOOL), str(source), str(fixed)],
                           check=True, capture_output=True)

            def write_boot(payload):
                boot.write_bytes(boot_image(payload))

            def check():
                return subprocess.run(['bash', str(REPO / 'scripts/check-rp6-input.sh'),
                                       str(root), str(boot)], capture_output=True, text=True)

            write_boot(fixed.read_bytes())
            result = check()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            tree = Path(tmp) / 'tree.dtb'
            for args in (['-t', 'i', str(tree), BUS, 'clock-frequency', '100000'],
                         [str(tree), TOUCH, 'no-regmap-bulk-read']):
                tree.write_bytes(fixed.read_bytes()[len(IMAGE):])
                subprocess.run(['fdtput', *args], check=True)
                write_boot(IMAGE + tree.read_bytes())
                self.assertNotEqual(check().returncode, 0, 'touch regression accepted by input preflight')
            write_boot(fixed.read_bytes())
            gdbus.chmod(0o644)
            self.assertNotEqual(check().returncode, 0, 'missing volume signal runtime was accepted')
            gdbus.chmod(0o755)
            volume = root / 'usr/lib/steamos/sm8550-volume-keys'
            volume_bytes = volume.read_bytes()
            volume.write_text('stale volume handler')
            self.assertNotEqual(check().returncode, 0, 'stale volume handler was accepted')
            volume.write_bytes(volume_bytes)
            map_path = root / 'var/lib/overlays/etc/upper/inputplumber/capability_maps.d/retroid_mcu.yaml'
            good = map_path.read_bytes()
            map_path.write_text('stale override')
            self.assertNotEqual(check().returncode, 0)
            map_path.write_bytes(good)
            profile = root / 'etc/inputplumber/devices.d/02-retroid-pocket.yaml'
            profile.unlink()
            self.assertNotEqual(check().returncode, 0)
            profile.write_bytes((root / 'var/lib/overlays/etc/upper/inputplumber/devices.d/02-retroid-pocket.yaml').read_bytes())
            calibration = root / 'usr/lib/steamos/sm8550-fixpad'
            calibration_bytes = calibration.read_bytes()
            calibration.write_text('stale axis calibration')
            self.assertNotEqual(check().returncode, 0, 'stale trigger calibration was accepted')
            calibration.write_bytes(calibration_bytes)
            write_boot(source.read_bytes())
            result = check()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('paddle definitions missing', result.stderr)


if __name__ == '__main__':
    unittest.main()
