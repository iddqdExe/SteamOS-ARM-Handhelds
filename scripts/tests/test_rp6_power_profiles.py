"""Exercise clock control against files with the kernel's min/max contract."""
import glob
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CPU = '/sys/devices/system/cpu/cpufreq'
GPU = '/sys/class/devfreq/3d00000.gpu'
OPPS = {
    0: '307200 441600 556800 672000 787200 902400 1017600 1113600 1228800 1344000 1459200 1555200 1670400 1785600 1900800 2016000',
    3: '499200 614400 729600 844800 940800 1056000 1171200 1286400 1401600 1536000 1651200 1785600 1920000 2054400 2188800 2323200 2457600 2592000 2707200 2803200',
    7: '595200 729600 864000 998400 1132800 1248000 1363200 1478400 1593600 1708800 1843200 1977600 2092800 2227200 2342400 2476800 2592000 2726400 2841600 2956800',
}


def load_daemon():
    loader = importlib.machinery.SourceFileLoader('power_profiles', str(ROOT / 'sm8650-overlay/usr/lib/konkr/konkrd'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ClockTests(unittest.TestCase):
    def setUp(self):
        self.module = load_daemon()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.module.STANDBY_FLAG = str(self.root / 'standby')
        self.put('/sys/firmware/devicetree/base/model', 'Retroid Pocket 6\0')
        self.put('/sys/firmware/devicetree/base/compatible', 'retroidpocket,rp6\0qcom,sm8550\0')
        for policy, cpus in ((0, '0 1 2'), (3, '3 4 5 6'), (7, '7')):
            freqs = OPPS[policy].split()
            for name, value in {
                'related_cpus': cpus, 'scaling_available_frequencies': OPPS[policy],
                'cpuinfo_min_freq': freqs[0], 'cpuinfo_max_freq': freqs[-1],
                'scaling_min_freq': freqs[0], 'scaling_max_freq': freqs[-1],
                'scaling_available_governors': 'ondemand powersave performance schedutil',
                'scaling_governor': 'performance', 'schedutil/rate_limit_us': '1000',
            }.items():
                self.put(f'{CPU}/policy{policy}/{name}', value)
            for cpu in cpus.split():
                self.put(f'/sys/devices/system/cpu/cpu{cpu}/cpu_capacity', '200' if policy == 0 else '900')
        for name, value in {
            'available_frequencies': '220000000 295000000 348000000 401000000 475000000 550000000 615000000 680000000',
            'min_freq': '220000000', 'max_freq': '680000000', 'polling_interval': '50',
        }.items():
            self.put(f'{GPU}/{name}', value)
        self.rejected = set()
        self.ignored = set()
        self.messages = []
        real_read, real_write, real_glob = self.module.rd, self.module.wr, glob.glob

        def write(path, value):
            if path in self.rejected:
                return False
            if path in self.ignored:
                return True  # accepted write but driver did not apply it
            name = Path(path).name
            siblings = {'scaling_min_freq': 'scaling_max_freq', 'scaling_max_freq': 'scaling_min_freq',
                        'min_freq': 'max_freq', 'max_freq': 'min_freq'}
            if name in siblings:
                other = int(self.get(str(Path(path).with_name(siblings[name]))))
                if ('min' in name and int(value) > other) or ('max' in name and int(value) < other):
                    return False
            return real_write(str(self.root / path.lstrip('/')), value)

        for name, value in {
            'rd': lambda path, default='': real_read(str(self.root / path.lstrip('/')), default),
            'wr': write, 'log': self.messages.append,
        }.items():
            p = patch.object(self.module, name, value)
            p.start(); self.addCleanup(p.stop)
        p = patch.object(self.module.glob, 'glob', lambda pattern: [str(p).removeprefix(str(self.root)) for p in real_glob(str(self.root / pattern.lstrip('/')))])
        p.start(); self.addCleanup(p.stop)

    def put(self, path, value):
        file = self.root / path.lstrip('/')
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(str(value))

    def get(self, path):
        return (self.root / path.lstrip('/')).read_text().strip()

    def test_presets_apply_distinct_supported_cpu_caps(self):
        for profile, expected in (
            ('silent', ('1459200', '1785600', '1843200')),
            ('balanced', ('1670400', '2188800', '2342400')),
            ('turbo', ('2016000', '2803200', '2956800')),
        ):
            with self.subTest(profile=profile):
                self.module.apply_cpu(profile)
                self.assertEqual(tuple(self.get(f'{CPU}/policy{p}/scaling_max_freq') for p in (0, 3, 7)), expected)

    def test_turbo_can_downclock_every_cluster_at_idle(self):
        self.module.apply_cpu('turbo')
        self.assertEqual([self.get(f'{CPU}/policy{p}/scaling_governor') for p in (0, 3, 7)], ['schedutil'] * 3)

    def test_profile_change_lowers_touch_min_before_cpu_max(self):
        for policy, value in ((0, 1555200), (3, 1920000), (7, 1843200)):
            self.put(f'{CPU}/policy{policy}/scaling_min_freq', value)
        self.module.apply_cpu('silent')
        self.assertEqual(self.get(f'{CPU}/policy3/scaling_max_freq'), '1785600')

    def test_all_rp6_presets_leave_gpu_full_dynamic_range(self):
        for profile in ('silent', 'balanced', 'turbo'):
            self.put(f'{GPU}/min_freq', '401000000')
            self.put(f'{GPU}/max_freq', '550000000')
            self.module.apply_gpu(profile)
            self.assertEqual((self.get(f'{GPU}/min_freq'), self.get(f'{GPU}/max_freq')), ('220000000', '680000000'))

    def test_other_board_retains_legacy_profile_behavior(self):
        self.put('/sys/firmware/devicetree/base/model', 'KONKR Pocket FIT\0')
        self.module.apply_cpu('turbo')
        self.module.apply_gpu('silent')
        self.assertEqual(self.get(f'{CPU}/policy3/scaling_governor'), 'performance')
        self.assertEqual(self.get(f'{GPU}/max_freq'), '550000000')

    def test_cpu_write_failure_is_reported(self):
        self.rejected.add(f'{CPU}/policy3/scaling_max_freq')
        self.assertIs(self.module.apply_cpu('silent'), False)
        self.assertTrue(any('policy3' in m for m in self.messages))

    def test_readback_detects_driver_ignoring_cpu_cap(self):
        self.ignored.add(f'{CPU}/policy7/scaling_max_freq')
        self.assertIs(self.module.apply_cpu('silent'), False)

    def test_delayed_cpu_policy_update_is_verified(self):
        real_write = self.module.wr

        def queued_write(path, value):
            if path.endswith('/scaling_max_freq'):
                timer = threading.Timer(.01, lambda: real_write(path, value))
                timer.start()
                self.addCleanup(timer.join)
                return True
            return real_write(path, value)

        with patch.object(self.module, 'wr', queued_write):
            self.assertIs(self.module.apply_cpu('silent'), True)
        self.assertEqual(self.get(f'{CPU}/policy3/scaling_max_freq'), '1785600')

    def test_gpu_kernel_qos_floor_does_not_reject_unrestricted_request(self):
        real_read = self.module.rd
        # devfreq reports all QoS constraints, not just the user's own floor.
        with patch.object(self.module, 'rd', lambda path, default='': '680000000' if path == f'{GPU}/min_freq' else real_read(path, default)):
            self.assertIs(self.module.apply_gpu('silent'), True)
        self.assertEqual(self.get(f'{GPU}/min_freq'), '220000000')
        self.assertEqual(self.get(f'{GPU}/max_freq'), '680000000')

    def test_gpu_kernel_cooling_ceiling_does_not_reject_unrestricted_request(self):
        real_read = self.module.rd
        with patch.object(self.module, 'rd', lambda path, default='': '615000000' if path == f'{GPU}/max_freq' else real_read(path, default)):
            self.assertIs(self.module.apply_gpu('balanced'), True)
        self.assertEqual(self.get(f'{GPU}/max_freq'), '680000000')

    def test_absent_requested_opp_uses_next_lower_supported_frequency(self):
        self.put(f'{CPU}/policy3/scaling_available_frequencies', OPPS[3].replace('1785600 ', ''))
        self.module.apply_cpu('silent')
        self.assertEqual(self.get(f'{CPU}/policy3/scaling_max_freq'), '1651200')

    def test_bad_opp_data_rejects_profile_before_mutating_any_cluster(self):
        self.put(f'{CPU}/policy7/scaling_available_frequencies', '')
        self.assertIs(self.module.apply_cpu('silent'), False)
        self.assertEqual(self.get(f'{CPU}/policy0/scaling_governor'), 'performance')

    def test_touch_boost_respects_cap_and_refreshes_while_still_active(self):
        touch = self.module.TouchBoost()
        touch.last_touch = time.monotonic()
        touch.tick(False)
        self.module.apply_cpu('silent')
        touch.tick(False)
        self.assertEqual(self.get(f'{CPU}/policy0/scaling_min_freq'), '1459200')
        self.assertEqual(self.get(f'{CPU}/policy3/scaling_min_freq'), '1785600')
        touch.tick(True)
        self.assertEqual(self.get(f'{CPU}/policy3/scaling_min_freq'), '499200')

    def daemon(self):
        daemon = self.module.Daemon.__new__(self.module.Daemon)
        daemon.st = {'profile': 'silent'}
        daemon.games = types.SimpleNamespace(done=set())
        flashes = []
        daemon.leds = types.SimpleNamespace(flash=flashes.append)
        return daemon, flashes

    def test_failed_profile_does_not_flash_or_log_success(self):
        self.rejected.add(f'{CPU}/policy3/scaling_max_freq')
        daemon, flashes = self.daemon()
        self.assertIs(daemon.apply_profile(), False)
        self.assertEqual(flashes, [])
        self.assertNotIn('profile silent', self.messages)

    def test_profile_request_during_standby_does_not_raise_clock_caps(self):
        Path(self.module.STANDBY_FLAG).write_text('1')
        self.put(f'{CPU}/policy3/scaling_max_freq', '499200')
        daemon, _ = self.daemon()
        daemon.apply_profile()
        self.assertEqual(self.get(f'{CPU}/policy3/scaling_max_freq'), '499200')


if __name__ == '__main__':
    unittest.main()
