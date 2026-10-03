"""Run actual focusfix against Xvfb, including the Wine stale-Normal case."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('Xvfb') and shutil.which('cc'), 'Linux Xvfb and X11 build dependencies required')
class FocusRestoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.tmp.cleanup)
        cls.binary, cls.scenario = [Path(cls.tmp.name) / n for n in ('focusfix', 'scenario')]
        for source, target in ((REPO / 'sm8650-overlay/usr/src/konkr-focusfix/konkr-focusfix.c', cls.binary),
                               (REPO / 'scripts/tests/focusfix-scenario.c', cls.scenario)):
            subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', str(source), '-lX11', '-o', str(target)], check=True)

    def run_scenario(self, number):
        read, write = os.pipe()
        xvfb = subprocess.Popen(['Xvfb', '-displayfd', str(write), '-screen', '0', '640x480x24'],
                                pass_fds=(write,), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        os.close(write)
        try:
            display = ':' + os.read(read, 100).decode().strip()
            daemon = subprocess.Popen([str(self.binary), display], stderr=subprocess.PIPE)
            try:
                result = subprocess.run([str(self.scenario), display, str(number)], capture_output=True, text=True, timeout=12)
                self.assertEqual(result.returncode, 0, result.stderr)
            finally:
                daemon.terminate(); daemon.communicate(timeout=3)
        finally:
            os.close(read); xvfb.terminate(); xvfb.communicate(timeout=3)

    def test_iconic_game_restores_only_after_qam_closes_and_is_rate_limited(self): self.run_scenario(0)
    def test_wine_stale_normal_state_still_receives_restore_transition(self): self.run_scenario(1)
    def test_steam_window_is_never_restored(self): self.run_scenario(2)
    def test_minimized_game_restores_behind_active_overlay_without_raising_or_focus(self): self.run_scenario(3)
    def test_overlay_restore_is_once_per_open_and_rearms_after_close(self): self.run_scenario(4)
    def test_steam_focus_without_an_active_overlay_does_not_restore(self): self.run_scenario(5)
    def test_overlay_graphics_app_must_match_the_game(self): self.run_scenario(6)
    def test_overlay_cannot_restore_a_steam_window(self): self.run_scenario(7)
    def test_hidden_overlay_does_not_restore_the_game(self): self.run_scenario(8)
    def test_focus_bounce_does_not_rearm_a_continuous_overlay(self): self.run_scenario(9)
    def test_subsequent_minimization_retains_stale_normal_fallback_after_close(self): self.run_scenario(10)
    def test_game_focus_bounce_cannot_raise_or_activate_over_visible_overlay(self): self.run_scenario(11)
    def test_overlay_reopened_during_restore_delay_blocks_raise_and_activation(self): self.run_scenario(12)
    def test_overlay_close_delivers_deferred_activation_without_another_focus_change(self): self.run_scenario(13)


if __name__ == '__main__': unittest.main()
