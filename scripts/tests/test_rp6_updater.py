"""Real rsync upgrade/restore against temporary roots; never touches a device."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import subprocess
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('updater', REPO / 'external-and-mods/konkr-update/konkr-update.py')
updater = importlib.util.module_from_spec(spec); spec.loader.exec_module(updater)
MAP = 'etc/inputplumber/capability_maps.d/retroid_mcu.yaml'
UPPER_MAP = updater.UPPER + '/inputplumber/capability_maps.d/retroid_mcu.yaml'
RECEIPT = 'var/lib/rp6-input/managed.json'


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('rsync'), 'Linux rsync -aHAX required')
class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.root, self.home, self.boot, self.work = [base / name for name in ('root', 'home', 'boot', 'work')]
        for path in (self.root, self.home, self.boot, self.work): path.mkdir()
        self.payload = self.work / 'payload'
        for rel in ('usr', 'opt', 'etc'): (self.root / rel).mkdir()
        for rel in ('root/usr', 'root/opt', 'root/etc', 'boot'):
            (self.payload / rel).mkdir(parents=True)
        for rel in updater.HOME_DIRS: (self.payload / 'home/steamos' / rel).mkdir(parents=True)
        self.put(self.work, 'previous-KERNEL', 'old kernel')
        self.put(self.work, 'next-KERNEL', 'new kernel')
        self.put(self.boot, 'KERNEL', 'old kernel')
        self.put(self.payload / 'root', MAP, 'new map\n')
        self.put(self.payload / 'root', UPPER_MAP, 'new map\n')
        self.put(self.payload / 'root', 'usr/share/rp6-input/defaults/capability_maps.d/retroid_mcu.yaml', 'new map\n')
        self.put(self.payload / 'root', 'usr/share/rp6-input/defaults/devices.d/02-retroid-pocket.yaml', 'new profile\n')
        helper = self.payload / 'root/usr/lib/steamos/rp6-input-config.py'
        helper.parent.mkdir(parents=True)
        shutil.copyfile(REPO / 'steamos-overlay/usr/lib/steamos/rp6-input-config.py', helper)
        self.manifest = {'files': {str(p.relative_to(self.payload)): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in self.payload.rglob('*') if p.is_file()}}
        original = updater.run
        def run(*args, **kwargs):
            if args[0] == 'chown': return None  # Ownership is outside this non-root fixture.
            return original(*args, **kwargs)
        self.mock = patch.object(updater, 'run', run); self.mock.start(); self.addCleanup(self.mock.stop)

    def put(self, root, rel, body):
        p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(body); return p

    def test_upgrade_preserves_remaps_and_steam_data_and_restore_recovers_receipt(self):
        self.put(self.root, MAP, 'old map\n')
        custom = self.put(self.root, UPPER_MAP, 'custom upper remap\n')
        receipt = self.put(self.root, RECEIPT, json.dumps({'format': 1, 'defaults': {
            MAP: hashlib.sha256(b'old map\n').hexdigest(),
            UPPER_MAP: hashlib.sha256(b'old map\n').hexdigest()}}))
        original_receipt = receipt.read_bytes()
        steam = self.put(self.home, 'steamos/.steam/steam/userdata/42/config/localconfig.vdf', 'user assignments')
        extra = self.put(self.root, 'etc/inputplumber/profiles.d/my-game.yaml', 'my profile')
        updater.snapshot(self.root, self.home, self.work)
        updater.apply(self.root, self.boot, self.home, self.work, self.manifest)
        self.assertEqual((self.root / MAP).read_text(), 'new map\n')
        self.assertEqual(custom.read_text(), 'custom upper remap\n')
        self.assertEqual(extra.read_text(), 'my profile')
        self.assertEqual(steam.read_text(), 'user assignments')
        updater.restore(self.root, self.boot, self.home, self.work)
        self.assertEqual((self.root / MAP).read_text(), 'old map\n')
        self.assertEqual(receipt.read_bytes(), original_receipt)
        self.assertEqual(custom.read_text(), 'custom upper remap\n')
        self.assertFalse((self.root / 'var/lib/rp6-input/last-update.json').exists())
        self.assertEqual((self.boot / 'KERNEL').read_text(), 'old kernel')

    def test_upgrade_preserves_legacy_custom_map_and_restore_removes_new_receipt(self):
        custom = self.put(self.root, MAP, 'legacy customization\n')
        updater.snapshot(self.root, self.home, self.work)
        updater.apply(self.root, self.boot, self.home, self.work, self.manifest)
        self.assertEqual(custom.read_text(), 'legacy customization\n')
        self.assertFalse((self.root / UPPER_MAP).exists(), 'new upper must not shadow the active user map')
        self.assertTrue((self.root / RECEIPT).exists())
        updater.restore(self.root, self.boot, self.home, self.work)
        self.assertFalse((self.root / 'var/lib/rp6-input').exists())
        self.assertEqual(custom.read_text(), 'legacy customization\n')

    def test_decky_loader_upgrade_and_rollback_preserve_plugin_settings(self):
        old = self.put(self.home, 'steamos/homebrew/services/PluginLoader', 'old loader')
        settings = self.put(self.home, 'steamos/homebrew/settings/konkr-control.json', 'custom settings')
        self.put(self.payload, 'home/steamos/homebrew/services/PluginLoader', 'new loader')
        self.manifest['files']['home/steamos/homebrew/services/PluginLoader'] = hashlib.sha256(b'new loader').hexdigest()
        updater.snapshot(self.root, self.home, self.work)
        updater.apply(self.root, self.boot, self.home, self.work, self.manifest)
        self.assertEqual(old.read_text(), 'new loader')
        self.assertEqual(settings.read_text(), 'custom settings')
        updater.restore(self.root, self.boot, self.home, self.work)
        self.assertEqual(old.read_text(), 'old loader')
        self.assertEqual(settings.read_text(), 'custom settings')

    def test_restore_older_snapshot_without_decky_service_receipt(self):
        loader = self.put(self.home, 'steamos/homebrew/services/PluginLoader', 'untouched loader')
        updater.snapshot(self.root, self.home, self.work)
        receipt = self.work / 'backup/home-presence.json'
        previous = json.loads(receipt.read_text()); previous.pop('homebrew/services', None)
        receipt.write_text(json.dumps(previous))
        updater.restore(self.root, self.boot, self.home, self.work)
        self.assertEqual(loader.read_text(), 'untouched loader')

    def test_bootstrap_replaces_the_old_updater_before_the_first_upgrade(self):
        custom = self.put(self.root, MAP, 'legacy assignments\n')
        path = self.put(self.root, 'usr/share/konkr-update/konkr-update.py', '# old deployed updater\n')
        result = subprocess.run(['bash', str(REPO / 'scripts/install-inputplumber-sm8550.sh'),
                                 str(self.root), '--config-only'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_bytes(), (REPO / 'external-and-mods/konkr-update/konkr-update.py').read_bytes())
        installed_spec = importlib.util.spec_from_file_location('installed_updater', path)
        installed = importlib.util.module_from_spec(installed_spec); installed_spec.loader.exec_module(installed)
        installed.run = updater.run
        # Staging copies installed.__file__, so its recovery executes this same code.
        self.assertEqual(Path(installed.__file__), path)
        installed.snapshot(self.root, self.home, self.work)
        installed.apply(self.root, self.boot, self.home, self.work, self.manifest)
        self.assertEqual(custom.read_text(), 'legacy assignments\n')
        self.assertFalse((self.root / UPPER_MAP).exists())


if __name__ == '__main__': unittest.main()
