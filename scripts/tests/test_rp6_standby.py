import errno
import io
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch


STANDBY = Path(__file__).resolve().parents[2] / 'sm8650-overlay/usr/lib/konkr/konkr-standby'


class PanelWrite:
    """A sysfs write caches brightness even when the DCS transfer fails."""
    def __init__(self, stream, panel):
        self.stream, self.panel = stream, panel

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        return self.stream.__exit__(*args)

    def write(self, value):
        self.stream.write(value)
        self.stream.flush()
        if int(value) and (self.panel.fail_write or (
                self.panel.model == 'Retroid Pocket 6' and
                (self.panel.dsi / 'bl_power').read_text() != '0')):
            self.panel.failed_writes += 1
            raise OSError(errno.EPROTO, 'Protocol error')
        self.panel.physical_brightness = int(value)


class StandbyFixture:
    def __init__(self, folder, model='Retroid Pocket 6', ready=True, fail_write=False):
        self.model, self.ready, self.fail_write = model, ready, fail_write
        self.now, self.ready_at = 0., None
        self.physical_brightness, self.failed_writes = 1425, 0
        self.commands, self.signals, self.messages = [], [], []
        self.dsi = Path(folder) / 'ae94000.dsi.0'
        self.pwm = Path(folder) / 'backlight'
        for path, value, power in [(self.dsi, '1425', '0'), (self.pwm, '600', '4')]:
            path.mkdir()
            (path / 'brightness').write_text(value)
            (path / 'bl_power').write_text(power)
        self.flag = str(Path(folder) / 'standby-flag')
        self.real_open = open

    def open(self, path, mode='r', *args, **kwargs):
        if str(path) == '/sys/firmware/devicetree/base/model':
            return io.StringIO(self.model + '\0')
        if str(path).endswith('/actual_brightness'):
            raise AssertionError('Do not query DCS brightness while the panel may be off')
        stream = self.real_open(path, mode, *args, **kwargs)
        if str(path) == str(self.dsi / 'brightness') and mode == 'w':
            return PanelWrite(stream, self)
        return stream

    def glob(self, pattern):
        if pattern == '/sys/class/backlight/*':
            return [str(self.dsi), str(self.pwm)]
        return []

    def run(self, *cmd):
        self.commands.append(cmd)
        if cmd[-1] == 'standby-pre':
            (self.dsi / 'bl_power').write_text('4')
        elif cmd[-1] == 'standby-screen-on':
            self.ready_at = self.now + .4 if self.ready else None
        return 0

    def sleep(self, seconds):
        self.now += seconds
        if self.ready_at is not None and self.now >= self.ready_at:
            (self.dsi / 'bl_power').write_text('0')

    def execute(self):
        namespace = {'__name__': 'standby_test'}
        exec(compile(STANDBY.read_text(), str(STANDBY), 'exec'), namespace)
        fd = os.open(os.devnull, os.O_RDONLY)
        replacements = {
            'FLAG': self.flag, 'power_key_fd': lambda: fd,
            'game_pids': lambda: [1234567], 'freeze_targets': lambda: [],
            'wait_power_press': lambda _fd: None,
            'run': self.run, 'log': self.messages.append,
        }
        try:
            with patch.dict(namespace, replacements), patch('builtins.open', self.open), \
                    patch('glob.glob', self.glob), patch('time.monotonic', lambda: self.now), \
                    patch('time.sleep', self.sleep), patch('signal.signal'), \
                    patch('os.kill', lambda pid, sig: self.signals.append((pid, sig))), \
                    patch('os.system', return_value=0):
                return namespace['main']()
        finally:
            for pipe in (namespace['WAKE_R'], namespace['WAKE_W']):
                os.close(pipe)
            try:
                os.close(fd)
            except OSError:
                pass


class RP6StandbyTests(unittest.TestCase):
    def test_restores_physical_brightness_only_after_delayed_panel_unblank(self):
        # Removing the readiness wait reproduces the observed EPROTO/black panel.
        with tempfile.TemporaryDirectory() as folder:
            fixture = StandbyFixture(folder)
            status = fixture.execute()
            self.assertEqual(fixture.physical_brightness, 1425)
            self.assertEqual(fixture.failed_writes, 0)
            self.assertEqual(status, 0)
            # The unrelated PWM device remains power=4 even in healthy Game Mode.
            self.assertEqual((fixture.pwm / 'brightness').read_text(), '600')

    def test_panel_timeout_reports_failure_and_still_restores_game_and_other_devices(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = StandbyFixture(folder, ready=False)
            self.assertNotEqual(fixture.execute(), 0)
            self.assertEqual(fixture.failed_writes, 0)
            self.assertLess(fixture.now, 6)
            self.assertIn((1234567, signal.SIGCONT), fixture.signals)
            self.assertIn(('/usr/lib/konkr/konkr-sleep', 'standby-post'), fixture.commands)
            self.assertEqual((fixture.pwm / 'brightness').read_text(), '600')
            self.assertFalse(Path(fixture.flag).exists())
            self.assertTrue(fixture.messages)

    def test_ready_panel_write_failure_is_not_hidden_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = StandbyFixture(folder, fail_write=True)
            self.assertNotEqual(fixture.execute(), 0)
            self.assertEqual(fixture.physical_brightness, 0)
            self.assertIn((1234567, signal.SIGCONT), fixture.signals)
            self.assertFalse(Path(fixture.flag).exists())
            self.assertTrue(any('brightness' in message for message in fixture.messages))

    def test_other_model_keeps_legacy_restore_without_waiting_for_rp6_panel(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = StandbyFixture(folder, model='KONKR Pocket FIT', ready=False)
            self.assertEqual(fixture.execute(), 0)
            self.assertEqual(fixture.physical_brightness, 1425)
            self.assertLess(fixture.now, 2)


if __name__ == '__main__':
    unittest.main()
