"""Upgrade managed defaults while leaving administrator remaps active."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / 'steamos-overlay/usr/lib/steamos/rp6-input-config.py'
MAP = 'etc/inputplumber/capability_maps.d/retroid_mcu.yaml'
PROFILE = 'etc/inputplumber/devices.d/02-retroid-pocket.yaml'
UPPER = 'var/lib/overlays/etc/upper'


class ConfigUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'; self.root.mkdir()
        self.source = Path(self.temp.name) / 'defaults'
        for folder, name, body in [('devices.d', '02-retroid-pocket.yaml', 'new profile\n'),
                                    ('capability_maps.d', 'retroid_mcu.yaml', 'new map\n')]:
            p = self.source / folder / name; p.parent.mkdir(parents=True); p.write_text(body)

    def put(self, path, text):
        p = self.root / path; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(text)
        return p

    def run_tool(self, rollback=False):
        args = [sys.executable, str(TOOL), str(self.root)]
        args += ['--rollback'] if rollback else ['--source', str(self.source)]
        return subprocess.run(args, capture_output=True, text=True)

    def receipt(self, values):
        self.put('var/lib/rp6-input/managed.json', json.dumps({'format': 1, 'defaults': values}))

    def test_installs_fresh_defaults_and_rolls_back_created_files(self):
        result = self.run_tool(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / MAP).read_text(), 'new map\n')
        self.assertEqual((self.root / PROFILE).read_text(), 'new profile\n')
        again = self.run_tool(); self.assertEqual(again.returncode, 0, again.stderr)
        rolled = self.run_tool(True); self.assertEqual(rolled.returncode, 0, rolled.stderr)
        self.assertFalse((self.root / MAP).exists())
        self.assertFalse((self.root / PROFILE).exists())

    def test_updates_known_old_defaults_but_preserves_custom_upper_map(self):
        self.put(MAP, 'old vendor map\n')
        self.put(PROFILE, 'old vendor profile\n')
        upper_map = UPPER + '/inputplumber/capability_maps.d/retroid_mcu.yaml'
        upper = self.put(upper_map, 'my custom map\n')
        self.receipt({MAP: hashlib.sha256(b'old vendor map\n').hexdigest(),
                      PROFILE: hashlib.sha256(b'old vendor profile\n').hexdigest(),
                      upper_map: hashlib.sha256(b'old vendor map\n').hexdigest()})
        steam = self.put('home/steamos/.steam/steam/userdata/42/config/localconfig.vdf', 'my Steam Input binds')
        extra = self.put('etc/inputplumber/profiles.d/my-game.yaml', 'my profile')
        result = self.run_tool(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / MAP).read_text(), 'new map\n')
        self.assertEqual(upper.read_text(), 'my custom map\n')
        self.assertEqual(extra.read_text(), 'my profile')
        self.assertEqual(steam.read_text(), 'my Steam Input binds')
        self.assertEqual((self.root / 'usr/share/rp6-input/defaults/capability_maps.d/retroid_mcu.yaml').read_text(), 'new map\n')
        rolled = self.run_tool(True); self.assertEqual(rolled.returncode, 0, rolled.stderr)
        self.assertEqual((self.root / MAP).read_text(), 'old vendor map\n')
        self.assertEqual(upper.read_text(), 'my custom map\n')

    def test_preserves_unknown_legacy_customizations_without_a_receipt(self):
        self.put(MAP, 'unknown remap\n'); self.put(PROFILE, 'unknown device profile\n')
        result = self.run_tool(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / MAP).read_text(), 'unknown remap\n')
        self.assertEqual((self.root / PROFILE).read_text(), 'unknown device profile\n')
        self.assertIn('preserved', result.stdout)

    def test_does_not_shadow_custom_lower_config_with_a_new_upper_default(self):
        self.put(MAP, 'custom lower map\n')
        (self.root / UPPER).mkdir(parents=True)
        result = self.run_tool(); self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / MAP).read_text(), 'custom lower map\n')
        self.assertFalse((self.root / UPPER / 'inputplumber/capability_maps.d/retroid_mcu.yaml').exists())

    def test_rollback_refuses_to_overwrite_a_later_user_edit(self):
        result = self.run_tool(); self.assertEqual(result.returncode, 0, result.stderr)
        self.put(MAP, 'edited after upgrade')
        result = self.run_tool(True); self.assertNotEqual(result.returncode, 0)
        self.assertIn('changed since', result.stderr)
        self.assertEqual((self.root / MAP).read_text(), 'edited after upgrade')

    def test_refuses_symlink_destination_without_changing_other_files(self):
        other = Path(self.temp.name) / 'outside'; other.write_text('outside')
        path = self.root / MAP; path.parent.mkdir(parents=True); path.symlink_to(other)
        result = self.run_tool(); self.assertNotEqual(result.returncode, 0)
        self.assertIn('symlink', result.stderr)
        self.assertEqual(other.read_text(), 'outside')
        self.assertFalse((self.root / PROFILE).exists())


if __name__ == '__main__':
    unittest.main()
