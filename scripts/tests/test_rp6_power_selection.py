"""Reproduce selector false success without running a real service."""
import asyncio
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    loader = importlib.machinery.SourceFileLoader('profile_test_' + path.name.replace('.', '_'), str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ProfileSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'state.json'
        self.state.write_text('{"profile":"balanced"}')
        with patch.dict(sys.modules, {'decky': types.ModuleType('decky')}):
            plugin = load(ROOT / 'external-and-mods/Decky/sm8650/konkr-control/main.py')
        cli = load(ROOT / 'sm8650-overlay/usr/bin/konkrctl')
        self.modules = [cli, plugin]
        for module in self.modules:
            module.STATE = str(self.state)

    def probe(self, argv, **kwargs):
        failed = ('is-active' in argv and self.fail_active) or ('kill' in argv and self.fail_signal)
        if failed and kwargs.get('check'):
            raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 1 if failed else 0)

    def test_inactive_daemon_rejects_preset_before_changing_state(self):
        self.fail_active, self.fail_signal = True, False
        for module in self.modules:
            with self.subTest(module=module.__file__), patch.object(module.subprocess, 'run', self.probe):
                with self.assertRaises(subprocess.CalledProcessError):
                    module.save({'profile': 'turbo'})
                self.assertEqual(json.loads(self.state.read_text())['profile'], 'balanced')

    def test_failed_signal_is_reported_to_caller(self):
        self.fail_active, self.fail_signal = False, True
        for module in self.modules:
            with self.subTest(module=module.__file__), patch.object(module.subprocess, 'run', self.probe):
                with self.assertRaises(subprocess.CalledProcessError):
                    module.save({'profile': 'turbo'})

    def test_valid_presets_are_persisted_and_daemon_notified(self):
        self.fail_active, self.fail_signal = False, False
        for module in self.modules:
            for profile in ('silent', 'balanced', 'turbo'):
                with self.subTest(module=module.__file__, profile=profile), patch.object(module.subprocess, 'run', self.probe):
                    module.save({'profile': profile})
                    self.assertEqual(json.loads(self.state.read_text())['profile'], profile)

    def test_plugin_does_not_return_success_on_failed_signal(self):
        self.fail_active, self.fail_signal = False, True
        module = self.modules[1]
        with patch.object(module.subprocess, 'run', self.probe):
            with self.assertRaises(subprocess.CalledProcessError):
                asyncio.run(module.Plugin().set_profile('turbo'))


if __name__ == '__main__':
    unittest.main()
