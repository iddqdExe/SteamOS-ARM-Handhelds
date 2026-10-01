"""Regression checks for delivering the RP6 input fixes in a fresh rootfs."""
import subprocess
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


class InputDeliveryTests(unittest.TestCase):
    def test_config_only_delivers_axis_calibration_before_inputplumber(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'usr').mkdir()
            result = subprocess.run(
                ['bash', str(REPO / 'scripts/install-inputplumber-sm8550.sh'),
                 str(root), '--config-only'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            for rel in ('usr/lib/steamos/sm8550-fixpad',
                        'usr/lib/systemd/system/sm8550-fixpad.service'):
                installed = root / rel
                self.assertTrue(installed.is_file(), f'missing axis calibration: {rel}')
                self.assertEqual(installed.read_bytes(), (REPO / 'steamos-overlay' / rel).read_bytes())
            self.assertTrue((root / 'usr/lib/steamos/sm8550-fixpad').stat().st_mode & 0o111)
            link = root / 'etc/systemd/system/multi-user.target.wants/sm8550-fixpad.service'
            self.assertTrue(link.is_symlink(), 'calibration service not enabled')
            self.assertEqual(str(link.readlink()), '/usr/lib/systemd/system/sm8550-fixpad.service')

    def test_config_install_retains_user_maps_and_mouse_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'usr').mkdir()
            files = ['etc/inputplumber/devices.d/my-mouse.yaml',
                     'etc/inputplumber/devices.d/02-ayn-odin.yaml',
                     'etc/inputplumber/capability_maps.d/ayn_mcu.yaml',
                     'etc/inputplumber/capability_maps.d/retroid_mcu.yaml']
            for rel in files:
                path = root / rel; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('custom ' + rel)
            result = subprocess.run(['bash', str(REPO / 'scripts/install-inputplumber-sm8550.sh'),
                                     str(root), '--config-only'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for rel in files: self.assertEqual((root / rel).read_text(), 'custom ' + rel)

    def test_config_only_installs_retroid_profile_and_map_into_persistent_etc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'usr').mkdir()
            upper = root / 'var/lib/overlays/etc/upper/inputplumber'
            (upper / 'capability_maps.d').mkdir(parents=True)
            (upper / 'capability_maps.d/retroid_mcu.yaml').write_text('stale map')
            receipt = root / 'var/lib/rp6-input/managed.json'
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({'format': 1, 'defaults': {
                'var/lib/overlays/etc/upper/inputplumber/capability_maps.d/retroid_mcu.yaml':
                    hashlib.sha256(b'stale map').hexdigest()}}))
            result = subprocess.run(
                ['bash', str(REPO / 'scripts/install-inputplumber-sm8550.sh'),
                 str(root), '--config-only'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            profile = root / 'etc/inputplumber/devices.d/02-retroid-pocket.yaml'
            self.assertTrue(profile.is_file(), 'RP6 profile missing from fresh rootfs')
            self.assertEqual(profile.read_bytes(), (REPO / 'sm8550-overlay' /
                             profile.relative_to(root)).read_bytes())
            expected = (REPO / 'steamos-overlay/etc/inputplumber/capability_maps.d/retroid_mcu.yaml').read_bytes()
            for destination in ['etc/inputplumber/capability_maps.d/retroid_mcu.yaml',
                                'usr/share/inputplumber/capability_maps/retroid_mcu.yaml',
                                'var/lib/overlays/etc/upper/inputplumber/capability_maps.d/retroid_mcu.yaml']:
                self.assertEqual((root / destination).read_bytes(), expected)
            self.assertEqual((upper / 'devices.d/02-retroid-pocket.yaml').read_bytes(), profile.read_bytes())
            # Repeated image-only builds must not leave stale persistent overrides.
            again = subprocess.run(['bash', str(REPO / 'scripts/install-inputplumber-sm8550.sh'),
                                    str(root), '--config-only'], capture_output=True, text=True)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertTrue((root / 'etc/inputplumber/devices.d/02-ayn-odin.yaml').is_file())

    def test_known_fixed_events_route_to_dpad_menus_and_independent_paddles(self):
        data = yaml.safe_load((REPO / 'steamos-overlay/etc/inputplumber/capability_maps.d/retroid_mcu.yaml').read_text())
        routes = {}
        for entry in data['mapping']:
            for source in entry['source_events']:
                event = source.get('evdev', {})
                if event.get('event_type') == 'KEY':
                    routes[event['event_code']] = entry['target_event'].get('gamepad', {}).get('button')
        for code, target in {
            'BTN_DPAD_LEFT': 'DPadLeft', 'BTN_DPAD_RIGHT': 'DPadRight',
            'BTN_DPAD_UP': 'DPadUp', 'BTN_DPAD_DOWN': 'DPadDown',
            'BTN_MODE': 'Guide', 'BTN_BACK': 'QuickAccess',
            'BTN_Z': 'LeftPaddle1', 'BTN_C': 'RightPaddle1',
            'BTN_SOUTH': 'East', 'BTN_EAST': 'South',
            'BTN_NORTH': 'North', 'BTN_WEST': 'West',
        }.items():
            self.assertEqual(routes[code], target, code)

    def test_retroid_sources_exclude_external_hid_and_the_virtual_pad(self):
        data = yaml.safe_load((REPO / 'sm8550-overlay/etc/inputplumber/devices.d/02-retroid-pocket.yaml').read_text())
        self.assertEqual(data['target_devices'], ['deck-uhid', 'keyboard'])
        self.assertFalse(data['single_source'])
        self.assertEqual([s['evdev']['phys_path'] for s in data['source_devices']],
                         ['rsinput-gamepad/input0', 'gpio-keys/input0'])
        self.assertTrue(all(s['capability_map_id'] == 'retroid_mcu' for s in data['source_devices']))
        self.assertEqual([m['udev']['attributes'][0]['value'] for m in data['matches']],
                         ['Retroid Pocket 6', 'Retroid Pocket 6 TOP-DPAD', 'Retroid Pocket Nova'])


if __name__ == '__main__':
    unittest.main()
