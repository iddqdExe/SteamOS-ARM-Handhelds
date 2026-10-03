"""UP-01: exercise startup, staged delivery and early /etc failure paths."""
from pathlib import Path
import os
import subprocess
import tempfile
import threading
import time
import unittest

REPO = Path(__file__).resolve().parents[2]
SESSION = REPO / 'steamos-overlay/usr/lib/steamos/gamescope-session'
WAIT = REPO / 'steamos-overlay/usr/lib/steamos/wait-gamescope-env'
ETC = REPO / 'external-and-mods/kernel-common/initramfs/mount-etc-overlay'


class MangoStartupTests(unittest.TestCase):
    def configure(self, runtime):
        # Run the real config block without starting a compositor on the host.
        text = SESSION.read_text()
        block = text.split('if [[ "$MANGOAPP" == 1 ]]; then', 1)[1].split('\nelse\n', 1)[0]
        return subprocess.run(['bash', '-ec', block + '\nprintf "%s" "$MANGOHUD_CONFIGFILE"'],
                              env={**os.environ, 'XDG_RUNTIME_DIR': str(runtime)},
                              capture_output=True, text=True, check=True).stdout

    def test_preset_survives_session_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(self.configure(tmp))
            first.write_text('fps,frametime\n')
            second = Path(self.configure(tmp))
            self.assertEqual(second, first)
            self.assertEqual(second.read_text(), 'fps,frametime\n')

    def test_first_start_has_hidden_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(Path(self.configure(tmp)).read_text(), 'no_display\n')

    def test_slow_environment_publication_is_waited_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / 'gamescope-steam.env'
            def publish():
                time.sleep(.25)
                env.write_text('STEAM_USE_MANGOAPP=1\n')
            thread = threading.Thread(target=publish); thread.start()
            result = subprocess.run(['sh', str(WAIT), str(env), '2'], capture_output=True, text=True)
            thread.join()
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_environment_fails_with_bounded_diagnostic(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = time.monotonic()
            result = subprocess.run(['sh', str(WAIT), str(Path(tmp) / 'absent'), '0'],
                                    capture_output=True, text=True, timeout=2)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('gamescope environment', result.stderr)
            self.assertLess(time.monotonic() - start, 1)

    def test_empty_environment_does_not_count_as_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / 'gamescope-steam.env'; env.touch()
            result = subprocess.run(['sh', str(WAIT), str(env), '0'], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)


class EarlyEtcTests(unittest.TestCase):
    def run_mount(self, *, mounted=False, fail=False, overlay=True,
                  modular=False, module_load_fails=False, log_unavailable=False):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp); root = base / 'root'; (root / 'etc').mkdir(parents=True)
            etc = root / 'var/lib/overlays/etc'
            if overlay:
                (etc / 'upper').mkdir(parents=True)
                (etc / 'upper/custom.conf').write_text('keep\n')
            mounts = base / 'mounts'; mounts.write_text(f'overlay {root}/etc overlay rw 0 0\n' if mounted else '')
            filesystems = base / 'filesystems'
            filesystems.write_text('nodev\toverlay\n' if not modular else 'nodev\ttmpfs\n')
            commands = base / 'commands'; commands.mkdir()
            log = base / 'mount.log'
            (commands / 'mount').write_text(
                '#!/bin/sh\n'
                'grep -qw overlay "$TEST_FILESYSTEMS" || { echo "unknown filesystem type overlay" >&2; exit 1; }\n'
                'printf "%s\\n" "$*" >>"$TEST_MOUNT_LOG"\nexit ' + ('1' if fail else '0') + '\n')
            (commands / 'mount').chmod(0o755)
            # The target kernel cannot be loaded into a unit-test host. Model
            # only that external boundary; the real helper must make mount work.
            (commands / 'chroot').write_text(
                '#!/bin/sh\n'
                '[ "$#" = 3 ] && [ "$1" = "$TEST_ROOT" ] && '
                '[ "$2" = /usr/bin/modprobe ] && [ "$3" = overlay ] || exit 97\n' +
                ('exit 1\n' if module_load_fails else
                 'printf "nodev\\toverlay\\n" >>"$TEST_FILESYSTEMS"\n'))
            (commands / 'chroot').chmod(0o755)
            invocation = ('. "$1" && mount_etc_overlay_logged "$2" "$5" "$3" "$4"' if log_unavailable else
                          '. "$1" && mount_etc_overlay "$2" "$3" "$4"')
            result = subprocess.run(['sh', '-c', invocation,
                                     'test', str(ETC), str(root), str(mounts), str(filesystems), str(base / 'absent/early-etc.log')],
                                    env={**os.environ, 'PATH': str(commands) + ':' + os.environ['PATH'],
                                         'TEST_MOUNT_LOG': str(log), 'TEST_ROOT': str(root),
                                         'TEST_FILESYSTEMS': str(filesystems)}, capture_output=True, text=True)
            saved = (etc / 'upper/custom.conf').read_text() if overlay else None
            return result, log.read_text() if log.exists() else '', saved

    def test_mount_uses_persistent_upper_and_preserves_custom_settings(self):
        result, log, saved = self.run_mount()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('-t overlay', log)
        self.assertIn('lowerdir=', log)
        self.assertIn('/var/lib/overlays/etc/upper', log)
        self.assertIn('/var/lib/overlays/etc/work', log)
        self.assertEqual(saved, 'keep\n')

    def test_already_mounted_overlay_is_left_alone(self):
        result, log, _ = self.run_mount(mounted=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log, '')

    def test_non_frame_root_without_overlay_is_left_alone(self):
        result, log, _ = self.run_mount(overlay=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log, '')

    def test_mount_failure_is_not_hidden_by_late_systemd_mount(self):
        result, _, saved = self.run_mount(fail=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('/etc overlay failed', result.stderr)
        self.assertEqual(saved, 'keep\n')

    def test_modular_overlay_is_loaded_before_early_mount(self):
        result, log, saved = self.run_mount(modular=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('-t overlay', log)
        self.assertEqual(saved, 'keep\n')

    def test_module_load_failure_stops_boot_with_a_diagnostic(self):
        result, log, saved = self.run_mount(modular=True, module_load_fails=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('load OverlayFS', result.stderr)
        self.assertEqual(log, '')
        self.assertEqual(saved, 'keep\n')

    def test_builtin_overlay_does_not_need_a_module_loader(self):
        result, log, _ = self.run_mount(module_load_fails=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('-t overlay', log)

    def test_unwritable_boot_log_does_not_stop_a_valid_overlay_mount(self):
        result, log, saved = self.run_mount(modular=True, log_unavailable=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('-t overlay', log)
        self.assertEqual(saved, 'keep\n')


class SessionDeliveryTests(unittest.TestCase):
    def test_staged_delivery_replaces_stale_standby_with_executable_current_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            standby = root / 'usr/lib/konkr/konkr-standby'
            standby.parent.mkdir(parents=True)
            standby.write_text('stale standby payload\n')
            standby.chmod(0o644)
            for _ in range(2):
                result = subprocess.run(['bash', str(REPO / 'scripts/install-rp6-session.sh'), str(root)],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(standby.read_bytes(),
                                 (REPO / 'sm8650-overlay/usr/lib/konkr/konkr-standby').read_bytes())
                self.assertEqual(standby.stat().st_mode & 0o777, 0o755)

    def test_staged_delivery_is_idempotent_and_preserves_other_vulkan_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layers = root / 'usr/share/vulkan/explicit_layer.d'; layers.mkdir(parents=True)
            for name in ('VkLayer_VALVE_rpo.json', 'VkLayer_VALVE_fdm_injection.json', 'VkLayer_MangoHud.json', 'VkLayer_LS_frame_generation.json'):
                (layers / name).write_text(name)
            custom = root / 'var/lib/overlays/etc/upper/custom.conf'; custom.parent.mkdir(parents=True)
            custom.write_text('keep')
            for _ in range(2):
                result = subprocess.run(['bash', str(REPO / 'scripts/install-rp6-session.sh'), str(root)],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            for name in ('VkLayer_VALVE_rpo.json', 'VkLayer_VALVE_fdm_injection.json'):
                self.assertFalse((layers / name).exists())
                self.assertEqual((layers.with_name('explicit_layer.d.frame') / name).read_text(), name)
            for name in ('VkLayer_MangoHud.json', 'VkLayer_LS_frame_generation.json'):
                self.assertEqual((layers / name).read_text(), name)
            self.assertEqual(custom.read_text(), 'keep')
            wait = root / 'usr/lib/steamos/wait-gamescope-env'
            self.assertTrue(os.access(wait, os.X_OK))
            dropin = root / 'usr/lib/systemd/user/steam.service.d/61-gamescope-env-wait.conf'
            self.assertIn('/usr/lib/steamos/wait-gamescope-env', dropin.read_text())
            unit = root / 'usr/lib/systemd/system/plugin_loader.service'
            self.assertIn('Wants=network-online.target systemd-binfmt.service', unit.read_text())
            self.assertFalse((root / 'usr/lib/systemd/system/multi-user.target.wants/plugin_loader.service').is_symlink())


if __name__ == '__main__': unittest.main()
