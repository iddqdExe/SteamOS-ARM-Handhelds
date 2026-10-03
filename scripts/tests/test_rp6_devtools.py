import importlib.util
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
RUNNER = REPO / 'scripts/rp6-devtools.py'
ROOT_HELPER = REPO / 'scripts/rp6-devtools/root-helper.py'


def load(path):
    spec = importlib.util.spec_from_file_location('devtools', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def snapshot():
    return {'model': 'Retroid Pocket 6', 'mem_total_kib': 11771268,
            'mounts': {'filesystems': [{'target': '/etc', 'fstype': 'overlay'}]},
            'units': {n: {'ActiveState': 'active', 'UnitFileState': 'enabled'} for n in
                      ['sshd.service', 'inputplumber.service', 'konkrd.service',
                       'sddm.service', 'sm8550-fixpad.service', 'plugin_loader.service']},
            'processes': [{'pid': 50, 'comm': 'PluginLoader'}],
            'root': {'status': 'available', 'kernel_sha256': 'a' * 64}}


class DevtoolsTests(unittest.TestCase):
    def runner(self):
        self.assertTrue(RUNNER.is_file(), 'RP6 development runner is missing')
        return load(RUNNER)

    def test_reports_missing_privileged_coverage_as_limited(self):
        mod = self.runner()
        data = snapshot(); data['root'] = {'status': 'unavailable'}
        self.assertEqual(mod.assess(data)['status'], 'limited')

    def test_wrong_model_cannot_pass_system_checks(self):
        mod = self.runner()
        data = snapshot(); data['model'] = 'Retroid Pocket 5'
        self.assertEqual(mod.assess(data)['status'], 'fail')

    def test_duplicate_loader_is_a_failure(self):
        mod = self.runner()
        data = snapshot(); data['processes'].append({'pid': 51, 'comm': 'PluginLoader'})
        self.assertEqual(mod.assess(data)['status'], 'fail')

    def test_wrong_kernel_hash_fails_instead_of_accepting_old_boot(self):
        mod = self.runner()
        self.assertEqual(mod.assess(snapshot(), 'b' * 64)['status'], 'fail')

    def test_malformed_remote_json_cannot_pass(self):
        mod = self.runner()
        for data in ({}, {'model': 'Retroid Pocket 6'}, [], None):
            with self.subTest(data=data):
                self.assertEqual(mod.assess(data)['status'], 'fail')

    def test_host_option_injection_is_rejected_before_ssh(self):
        mod = self.runner()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'key').touch(); (root/'hosts').touch()
            for host in ['-oProxyCommand=touch /tmp/injected', 'host;echo bad', 'host\nother']:
                with self.subTest(host=host), self.assertRaises(ValueError):
                    mod.ssh_command({'host':host,'user':'steamos','key':str(root/'key'),'known_hosts':str(root/'hosts')})
            argv = mod.ssh_command({'host':'192.168.31.125','user':'steamos','key':str(root/'key'),'known_hosts':str(root/'hosts')})
            self.assertIn('StrictHostKeyChecking=yes', argv)
            self.assertIn('BatchMode=yes', argv)

    def test_root_helper_rejects_arbitrary_commands(self):
        self.assertTrue(ROOT_HELPER.is_file(), 'Restricted root helper is missing')
        result = subprocess.run([sys.executable,str(ROOT_HELPER),'snapshot; touch /tmp/rp6-bad'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('invalid choice', result.stderr)

    def test_atomic_stage_refuses_symlink_and_preserves_target(self):
        mod = self.runner()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); target=root/'original'; target.write_bytes(b'private')
            link=root/'link'; link.symlink_to(target)
            with self.assertRaises(ValueError): mod.write_owned(link,b'replacement',0o600)
            self.assertEqual(target.read_bytes(),b'private')

    def test_restaging_identical_file_removes_world_write_permission(self):
        mod = self.runner()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve()/'root-helper.py'; path.write_bytes(b'helper'); path.chmod(0o666)
            mod.write_owned(path,b'helper',0o600)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)

    def test_current_boot_read_rejects_previous_boot_snapshot(self):
        mod = self.runner()
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'latest.json'
            path.write_text(json.dumps({'boot_id':'previous',**snapshot()}))
            self.assertTrue(hasattr(mod,'load_boot_report'),'Boot-report freshness guard is missing')
            with self.assertRaises(ValueError): mod.load_boot_report(path,'current')
            self.assertEqual(mod.load_boot_report(path,'previous')['boot_id'],'previous')

    def test_reboot_waits_for_new_boot_instead_of_accepting_old_connection(self):
        mod=self.runner()
        self.assertTrue(hasattr(mod,'wait_for_new_boot'),'Reboot reconnection verification is missing')
        replies=iter([{'boot_id':'previous'},{'boot_id':'current'}])
        result=mod.wait_for_new_boot('previous',lambda:next(replies),timeout=1,delay=0)
        self.assertEqual(result['boot_id'],'current')

    def test_reboot_cannot_succeed_when_boot_id_does_not_change(self):
        mod=self.runner()
        self.assertTrue(hasattr(mod,'wait_for_new_boot'),'Reboot reconnection verification is missing')
        with self.assertRaises(TimeoutError):
            mod.wait_for_new_boot('previous',lambda:{'boot_id':'previous'},timeout=0.01,delay=0.002)

    def test_boot_capture_waits_for_game_session_focusfix(self):
        mod=load(REPO/'scripts/rp6-devtools/snapshot.py')
        self.assertTrue(hasattr(mod,'collect_startup'),'Boot capture readiness wait is missing')
        starting=snapshot(); starting['processes'].append({'pid':52,'comm':'gamescope'})
        starting['user_focusfix']={'ActiveState':'inactive'}
        ready=snapshot(); ready['processes'].append({'pid':53,'comm':'gamescope-wl'})
        ready['user_focusfix']={'ActiveState':'active'}; ready['root']={'status':'unavailable'}
        replies=iter([starting,ready])
        result=mod.collect_startup(lambda deadline:next(replies),timeout=1,delay=0)
        self.assertEqual(result['user_focusfix']['ActiveState'],'active')
        self.assertEqual(result['startup_wait']['status'],'ready')
        self.assertIn('focusfix_in_game_mode',result['startup_wait']['initial_not_ready'])
        self.assertEqual(self.runner().assess(result)['status'],'limited')

    def test_boot_capture_preserves_failure_when_session_never_becomes_ready(self):
        mod=load(REPO/'scripts/rp6-devtools/snapshot.py')
        self.assertTrue(hasattr(mod,'collect_startup'),'Boot capture readiness wait is missing')
        data=snapshot(); data['processes'].append({'pid':52,'comm':'gamescope'})
        data['user_focusfix']={'ActiveState':'inactive'}
        result=mod.collect_startup(lambda deadline:dict(data),timeout=0.01,delay=0.002)
        self.assertEqual(result['startup_wait']['status'],'timeout')
        self.assertEqual(result['user_focusfix']['ActiveState'],'inactive')
        self.assertEqual(self.runner().assess(result)['status'],'fail')

    def test_command_timeout_uses_remaining_boot_capture_budget(self):
        mod=load(REPO/'scripts/rp6-devtools/snapshot.py')
        self.assertIn('deadline',inspect.signature(mod.run).parameters,'Command budget is missing')
        started=time.monotonic(); deadline=started+0.03
        result=mod.run([sys.executable,'-c','import time; time.sleep(2)'],timeout=2,deadline=deadline)
        self.assertIn('error',result)
        self.assertLess(time.monotonic()-started,1)
        expired=mod.run([sys.executable,'-c','print("late-command-ran")'],deadline=deadline)
        self.assertIn('error',expired)
        self.assertNotIn('late-command-ran',expired.get('stdout',''))

    def test_boot_capture_passes_one_deadline_to_the_last_slow_probe(self):
        mod=load(REPO/'scripts/rp6-devtools/snapshot.py')
        self.assertIn('deadline',inspect.signature(mod.collect).parameters,'Collection budget is missing')
        tick=[0.0]; seen=[]
        data=snapshot(); data['processes'].append({'pid':52,'comm':'gamescope'})
        data['user_focusfix']={'ActiveState':'inactive'}
        def probe(deadline):
            seen.append(deadline)
            tick[0]+=min(0.5 if len(seen)==1 else 145,deadline-tick[0])
            return dict(data)
        with patch.object(mod.time,'monotonic',side_effect=lambda:tick[0]):
            result=mod.collect_startup(probe,timeout=90,delay=0)
        self.assertEqual(seen,[90,90])
        self.assertEqual(result['startup_wait']['elapsed_seconds'],90)
        self.assertEqual(result['startup_wait']['status'],'timeout')


if __name__ == '__main__': unittest.main()
