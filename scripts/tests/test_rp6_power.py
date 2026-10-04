"""Standby regression tests: no real sysfs, services or processes touched."""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'sm8650-overlay/usr/lib/konkr/konkr-standby'


def load_standby():
    loader = importlib.machinery.SourceFileLoader('standby_test', str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class StandbyTests(unittest.TestCase):
    def setUp(self):
        self.s = load_standby()
        self.addCleanup(os.close, self.s.WAKE_R)
        self.addCleanup(os.close, self.s.WAKE_W)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.s.FLAG = str(Path(self.tmp.name) / 'standby')
        self.policy = '/sys/devices/system/cpu/cpufreq/policy0'
        self.bl = '/sys/class/backlight/panel'
        self.cg = '/sys/fs/cgroup/user.slice/session.scope'
        self.values = {
            self.policy + '/scaling_min_freq': '600000',
            self.policy + '/scaling_max_freq': '1800000',
            self.policy + '/cpuinfo_min_freq': '300000',
            self.bl + '/brightness': '77',
            self.cg + '/cgroup.freeze': '0',
            self.cg + '/cgroup.events': 'populated 1\nfrozen 1',
        }
        self.writes = []
        self.helpers = []
        self.wait_fn = self.s.wait_power_press
        self.waited = False
        self.fail_write = None
        self.fail_helper = None
        self.wake_error = None
        self.output = io.StringIO()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for name, replacement in {
            'rd': lambda p, d='': self.values.get(p, d),
            'wr_ok': self.write,
            'run': self.helper,
            'power_key_fd': lambda: os.open(os.devnull, os.O_RDONLY),
            'game_pids': lambda: [43210],
            'freeze_targets': lambda: [self.cg],
            'is_sm8550': lambda: True,
            'wait_power_press': self.wake,
        }.items():
            self.stack.enter_context(patch.object(self.s, name, replacement))
        self.stack.enter_context(patch.object(self.s.glob, 'glob', self.glob))
        self.stack.enter_context(patch.object(self.s.time, 'sleep', lambda _: None))
        self.kills = []
        self.stack.enter_context(patch.object(self.s.os, 'kill', lambda p, s: self.kills.append((p, s))))
        self.stack.enter_context(contextlib.redirect_stdout(self.output))

    def glob(self, pattern):
        return {
            '/sys/class/backlight/*': [self.bl],
            '/sys/class/leds/*': [],
            '/sys/devices/system/cpu/cpufreq/policy*': [self.policy],
        }.get(pattern, [])

    def write(self, path, value):
        value = str(value)
        self.writes.append((path, value))
        if self.fail_write == (path, value):
            return False
        self.values[path] = value
        return True

    def helper(self, *args):
        self.helpers.append(args)
        return 1 if args[-1] == self.fail_helper else 0

    def wake(self, fd):
        self.waited = True
        if self.wake_error:
            raise self.wake_error

    def assert_restored(self):
        self.assertEqual(self.values[self.bl + '/brightness'], '77')
        self.assertEqual(self.values[self.cg + '/cgroup.freeze'], '0')
        self.assertFalse(Path(self.s.FLAG).exists())
        self.assertIn((43210, signal.SIGCONT), self.kills)

    def test_inputplumber_is_frozen_and_thawed_with_session(self):
        cg='/sys/fs/cgroup/system.slice/inputplumber.service'
        self.values[cg+'/cgroup.events']='frozen 1'
        with patch.object(self.s.os.path,'isdir',lambda p:p==cg):
            self.assertEqual(self.s.main(),0)
        self.assertIn((cg+'/cgroup.freeze','1'),self.writes)
        self.assertIn((cg+'/cgroup.freeze','0'),self.writes)
        self.assertTrue(self.waited)

    def test_failed_inputplumber_freeze_thaws_all_without_waiting(self):
        cg='/sys/fs/cgroup/system.slice/inputplumber.service'
        self.fail_write=(cg+'/cgroup.freeze','1')
        with patch.object(self.s.os.path,'isdir',lambda p:p==cg):
            self.assertNotEqual(self.s.main(),0)
        self.assertIn((cg+'/cgroup.freeze','0'),self.writes)
        self.assertFalse(self.waited)
        self.assert_restored()

    def test_restores_cpu_minimum_and_maximum(self):
        self.assertEqual(self.s.main(), 0)
        self.assert_restored()
        self.assertEqual(self.values[self.policy + '/scaling_min_freq'], '600000')
        self.assertEqual(self.values[self.policy + '/scaling_max_freq'], '1800000')
        max_restore = self.writes.index((self.policy + '/scaling_max_freq', '1800000'))
        min_restore = self.writes.index((self.policy + '/scaling_min_freq', '600000'))
        self.assertLess(max_restore, min_restore)
        self.assertFalse(any('/online' in p or '/devfreq/' in p for p, _ in self.writes))

    def test_other_sm8550_board_keeps_backlight_failure_visible(self):
        self.values['/sys/firmware/devicetree/base/model'] = 'AYN Thor\0'
        self.values[self.bl + '/device/of_node/compatible'] = 'retroid,pocket-6-panel\0'
        self.fail_write = (self.bl + '/brightness', '77')
        self.assertEqual(self.s.main(), 1)
        self.assertIn((self.bl + '/brightness', '77'), self.writes)

    def test_preparation_failure_aborts_and_restores(self):
        self.fail_helper = 'standby-pre'
        self.assertEqual(self.s.main(), 1)
        self.assertFalse(self.waited)
        self.assert_restored()

    def test_clock_write_failure_aborts_and_restores(self):
        self.fail_write = (self.policy + '/scaling_max_freq', '300000')
        self.assertEqual(self.s.main(), 1)
        self.assertFalse(self.waited)
        self.assert_restored()
        self.assertEqual(self.values[self.policy + '/scaling_min_freq'], '600000')

    def test_missing_clock_snapshot_does_not_write_that_clock(self):
        del self.values[self.policy + '/scaling_min_freq']
        self.assertEqual(self.s.main(), 1)
        self.assertNotIn((self.policy + '/scaling_min_freq', '300000'), self.writes)
        self.assert_restored()

    def test_failed_thaw_reports_failure_but_restores_screen_and_games(self):
        self.fail_write = (self.cg + '/cgroup.freeze', '0')
        self.assertEqual(self.s.main(), 1)
        self.assertEqual(self.values[self.bl + '/brightness'], '77')
        self.assertIn((43210, signal.SIGCONT), self.kills)
        self.assertFalse(Path(self.s.FLAG).exists())

    def test_resume_helper_failure_does_not_skip_other_restoration(self):
        self.fail_helper = 'standby-audio-on'
        self.assertEqual(self.s.main(), 1)
        self.assertIn(('/usr/lib/konkr/konkr-sleep', 'standby-screen-on'), self.helpers)
        self.assertIn(('/usr/lib/konkr/konkr-sleep', 'standby-post'), self.helpers)
        self.assert_restored()

    def test_disconnected_power_device_restores_instead_of_busy_loop(self):
        with patch.object(self.s.select, 'select', return_value=([9], [], [])), \
                patch.object(self.s.os, 'read', side_effect=[b'', RuntimeError('busy loop')]):
            try:
                with self.assertRaises(OSError):
                    self.wait_fn(9)
            except RuntimeError:
                self.fail('EOF from power key was ignored; standby would spin forever')

    def test_freeze_write_failure_still_attempts_thaw(self):
        self.fail_write = (self.cg + '/cgroup.freeze', '1')
        self.assertEqual(self.s.main(), 1)
        self.assertIn((self.cg + '/cgroup.freeze', '0'), self.writes)
        self.assertFalse(self.waited)
        self.assert_restored()

    def test_wake_io_error_still_restores(self):
        self.wake_error = OSError('power key disconnected')
        self.assertEqual(self.s.main(), 1)
        self.assert_restored()

    def test_freezer_timeout_aborts_and_thaws_accepted_groups(self):
        self.values[self.cg + '/cgroup.events'] = 'populated 1\nfrozen 0'
        ticks = iter(range(100))
        with patch.object(self.s.time, 'monotonic', side_effect=lambda: next(ticks)):
            self.assertEqual(self.s.main(), 1)
        self.assertFalse(self.waited)
        self.assert_restored()

    def test_termination_between_stop_and_tracking_resumes_game(self):
        def stop_then_interrupt(pid, sig):
            self.kills.append((pid, sig))
            if sig == signal.SIGSTOP:
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        with patch.object(self.s.os, 'kill', stop_then_interrupt):
            self.assertEqual(self.s.main(), 1)
        self.assertIn((43210, signal.SIGCONT), self.kills)
        self.assertFalse(Path(self.s.FLAG).exists())

    def test_termination_request_runs_cleanup(self):
        def terminate(_):
            handler = signal.getsignal(signal.SIGTERM)
            if not callable(handler):
                self.fail('standby has no termination recovery handler')
            handler(signal.SIGTERM, None)
        self.s.wait_power_press = terminate
        self.assertEqual(self.s.main(), 1)
        self.assert_restored()


class HelperProcessTests(unittest.TestCase):
    def setUp(self):
        self.s = load_standby()
        self.addCleanup(os.close, self.s.WAKE_R)
        self.addCleanup(os.close, self.s.WAKE_W)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.marker = Path(self.tmp.name) / 'late-write'
        child = "import time; from pathlib import Path; time.sleep(0.5); Path(%r).write_text('late')" % str(self.marker)
        parent = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',%r]); time.sleep(30)" % child
        self.command = [os.sys.executable, '-c', parent]

    def test_helper_timeout_stops_descendants_before_recovery(self):
        # Shorten only the external wait; exercise the real process tree.
        real_popen = subprocess.Popen
        class ShortWaitProcess(real_popen):
            def wait(self, timeout=None):
                return super().wait(timeout=0.2 if timeout is not None else None)
        # subprocess.run's old timeout path and the new managed-Popen path
        # both use this same real process boundary.
        with patch.object(subprocess, 'Popen', ShortWaitProcess):
            self.assertEqual(self.s.run(*self.command), 1)
        time.sleep(0.65)
        self.assertFalse(self.marker.exists(), 'helper descendant acted after timeout recovery')

    def test_helper_interruption_stops_descendants_before_recovery(self):
        def interrupted(*_):
            raise self.s.StandbyError('termination request')
        previous = signal.signal(signal.SIGTERM, interrupted)
        self.addCleanup(signal.signal, signal.SIGTERM, previous)
        timer = threading.Timer(0.15, lambda: os.kill(os.getpid(), signal.SIGTERM))
        timer.start()
        self.addCleanup(timer.cancel)
        with self.assertRaises(self.s.StandbyError):
            self.s.run(*self.command)
        timer.join()
        time.sleep(0.65)
        self.assertFalse(self.marker.exists(), 'helper descendant acted after interrupted recovery')


class SleepHelperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.module_root = Path(self.tmp.name) / 'modules'
        self.module_root.mkdir()
        self.wifi_state = Path(self.tmp.name) / 'wifi-state'

    def invoke(self, phase, injected):
        script = (ROOT / 'sm8650-overlay/usr/lib/konkr/konkr-sleep').read_text()
        script = script.replace('/sys/module/', str(self.module_root) + '/')
        functions, dispatch = script.split('case "${1:-}" in', 1)
        result = subprocess.run(['bash', '-c', functions + '\nSTANDBY_WIFI_STATE=' + str(self.wifi_state) + '\n' + injected +
                                 '\ncase "${1:-}" in' + dispatch, 'test', phase],
                                capture_output=True, text=True, timeout=5)
        return result

    def test_audio_preparation_failure_is_not_reported_as_success(self):
        result = self.invoke('standby-pre', 'audio() { return 9; }; gamescope_screen() { return 0; }')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('standby: prepared', result.stdout)

    def test_panel_preparation_failure_is_not_reported_as_success(self):
        result = self.invoke('standby-pre', 'audio() { return 0; }; gamescope_screen() { return 9; }')
        self.assertNotEqual(result.returncode, 0)

    def test_audio_resume_failure_propagates(self):
        result = self.invoke('standby-audio-on', 'audio() { return 9; }')
        self.assertNotEqual(result.returncode, 0)

    def test_panel_resume_failure_propagates(self):
        result = self.invoke('standby-screen-on', 'gamescope_screen() { return 9; }')
        self.assertNotEqual(result.returncode, 0)

    def test_audio_list_failure_propagates(self):
        result = self.invoke('standby-audio-on', 'as_user() { return 9; }')
        self.assertNotEqual(result.returncode, 0)

    def test_audio_suspend_failure_propagates(self):
        result = self.invoke('standby-audio-on', "as_user() { if [[ $2 == list ]]; then echo '0 speaker driver format state'; else return 9; fi; }")
        self.assertNotEqual(result.returncode, 0)

    def test_resume_does_not_load_modules_absent_before_standby(self):
        result = self.invoke('standby-post', 'modprobe() { echo unexpected-load; return 9; }')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('unexpected-load', result.stdout)

    def test_wifi_unload_failure_keeps_recovery_record(self):
        (self.module_root / 'ath12k_wifi7').mkdir()
        (self.module_root / 'ath12k').mkdir()
        result = self.invoke('standby-pre', 'audio() { return 0; }; gamescope_screen() { return 0; }; timeout() { return 9; }')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.wifi_state.read_text().splitlines(), ['ath12k_wifi7', 'ath12k'])

    def test_wifi_resume_reloads_only_saved_modules(self):
        self.wifi_state.write_text('ath12k\n')
        result = self.invoke('standby-post', 'modprobe() { echo "load:$1"; return 0; }')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'load:ath12k')
        self.assertFalse(self.wifi_state.exists())

    def test_wifi_record_without_final_newline_is_recovered(self):
        self.wifi_state.write_text('ath12k')
        result = self.invoke('standby-post', 'modprobe() { echo "load:$1"; return 0; }')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'load:ath12k')
        self.assertFalse(self.wifi_state.exists())

    def test_empty_wifi_record_is_not_silently_discarded(self):
        self.wifi_state.write_text('')
        result = self.invoke('standby-post', 'modprobe() { echo unexpected-load; return 0; }')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.wifi_state.exists())
        self.assertNotIn('unexpected-load', result.stdout)

    def test_invalid_wifi_record_does_not_partially_reload_modules(self):
        self.wifi_state.write_text('ath12k\nunknown-driver\n')
        result = self.invoke('standby-post', 'modprobe() { echo unexpected-load; return 0; }')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.wifi_state.exists())
        self.assertNotIn('unexpected-load', result.stdout)

    def test_wifi_record_read_failure_keeps_record(self):
        self.wifi_state.write_text('ath12k\n')
        result = self.invoke('standby-post', 'cat() { return 9; }; modprobe() { echo unexpected-load; return 0; }')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.wifi_state.exists())
        self.assertNotIn('unexpected-load', result.stdout)

    def test_failed_wifi_reload_keeps_recovery_record(self):
        self.wifi_state.write_text('ath12k\n')
        result = self.invoke('standby-post', 'modprobe() { return 9; }')
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(self.wifi_state.exists())

    def test_keep_wifi_never_unloads_or_records_modules(self):
        (self.module_root / 'ath12k_wifi7').mkdir()
        result = self.invoke('standby-pre', 'KONKR_STANDBY_KEEP_WIFI=1; audio() { return 0; }; gamescope_screen() { return 0; }; timeout() { echo unexpected-unload; return 9; }')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('unexpected-unload', result.stdout)
        self.assertFalse(self.wifi_state.exists())

    def test_successful_preparation_still_works(self):
        result = self.invoke('standby-pre', 'audio() { return 0; }; gamescope_screen() { return 0; }')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('standby: prepared', result.stdout)


if __name__ == '__main__':
    unittest.main()
