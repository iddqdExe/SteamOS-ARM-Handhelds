"""Exercise the sealed daemon's power loop after installing UP04 runtime."""
import ast
import hashlib
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / 'scripts/tests/fixtures/rp6-up03-konkrd.py'

class EndInput(Exception): pass

def power_decisions(source, polls):
    tree = ast.parse(source)
    daemon = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Daemon')
    run = next(n for n in daemon.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
    cls = ast.ClassDef(name='Loop', bases=[], keywords=[], body=[run], decorator_list=[])
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    clock = {'mono': 100.0, 'boot': 100.0}
    actions = []
    queue = iter(polls)
    def poll(*args):
        try: mono, boot, keys = next(queue)
        except StopIteration: raise EndInput()
        clock.update(mono=mono, boot=boot)
        return keys
    no_op = lambda *a: None
    device = SimpleNamespace(tick=no_op, apply_sticks=no_op)
    namespace = {'time': SimpleNamespace(monotonic=lambda: clock['mono'], CLOCK_BOOTTIME=7,
                                         clock_gettime=lambda kind: clock['boot']),
                 'os': __import__('os'), 'STANDBY_FLAG': '/nonexistent-rp6-test-standby',
                 'KEY_POWER': 116, 'KEY_F13': 183, 'KEY_F14': 184, 'KEY_F15': 185, 'KEY_F24': 194,
                 'WAKE_GRACE_S': 2.5, 'LONG_PRESS_S': 1.0,
                 'power_press': lambda long: actions.append(long),
                 'ensure_webhelper_vulkan': no_op, 'pin_gpu_irqs': no_op,
                 'ensure_gamepad_mode': no_op, 'REQUEST_ACTIONS': (), 'log': no_op}
    exec(compile(module, '<delivered-daemon-loop>', 'exec'), namespace)
    loop = namespace['Loop']()
    loop.touch = SimpleNamespace(active=False, tick=no_op)
    loop.keys = SimpleNamespace(poll=poll)
    loop.requests = None; loop.reload = False; loop.conf = None
    loop.st = {'profile': 'balanced', 'fan': {}, 'power_led': True}
    loop.fan = device; loop.leds = device; loop.games = device
    try: loop.run()
    except EndInput: pass
    return actions

class WakeGuardDeliveryTests(unittest.TestCase):
    def installed_source(self):
        spec = importlib.util.spec_from_file_location('wakeguard_assembly', REPO/'scripts/prepare-rp6-kernel-release.py')
        tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); target=root/'usr/lib/konkr/konkrd'
            target.parent.mkdir(parents=True); target.write_bytes(BASE.read_bytes()); target.chmod(0o755)
            tool.install_power_runtime(root)
            self.assertEqual(target.stat().st_mode & 0o777, 0o755)
            return target.read_text()

    def test_s2idle_wake_button_does_not_send_a_new_sleep_request(self):
        source=self.installed_source()
        self.assertEqual(power_decisions(source, [(100.0, 160.0, [(116,1),(116,0)])]), [])

    def test_intentional_power_press_after_resume_grace_still_sleeps(self):
        source=self.installed_source()
        self.assertEqual(power_decisions(source, [(100.0,160.0,[(116,1),(116,0)]),
                                                 (104.0,164.0,[(116,1),(116,0)])]), [False])

    def test_awake_short_and_long_press_keep_existing_behavior(self):
        source=self.installed_source()
        self.assertEqual(power_decisions(source, [(100.0,100.0,[(116,1),(116,0)])]), [False])
        self.assertEqual(power_decisions(source, [(100.0,100.0,[(116,1)]),
                                                 (101.1,101.1,[]), (101.2,101.2,[(116,0)])]), [True])

class WakeGuardRefusalTests(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location('wakeguard',REPO/'scripts/fix-rp6-s2idle-wake.py')
        self.tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.tool)

    def test_unknown_daemon_is_refused_without_changing_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'daemon';file.write_bytes(b'unknown daemon');file.chmod(0o755)
            with self.assertRaisesRegex(ValueError,'SHA256 mismatch'):self.tool.apply(file)
            self.assertEqual(file.read_bytes(),b'unknown daemon')

    def test_symlink_is_refused_and_xattrs_mode_survive_a_real_update(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'daemon';file.write_bytes(BASE.read_bytes());file.chmod(0o755)
            os.setxattr(file,'user.fixture',b'keep')
            link=Path(tmp)/'link';link.symlink_to(file)
            with self.assertRaises(OSError):self.tool.apply(link)
            result=self.tool.apply(file)
            self.assertTrue(result['changed']);self.assertEqual(os.getxattr(file,'user.fixture'),b'keep')
            self.assertEqual(file.stat().st_mode & 0o777,0o755)
            self.assertFalse(self.tool.apply(file)['changed'])

if __name__ == '__main__': unittest.main()
