"""UP-04 recovery tests use an offline sysfs fixture and actual state transitions."""
import importlib.machinery
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[2]
SCRIPT=REPO/'sm8650-overlay/usr/lib/konkr/konkr-sleep-state'

def load():
    loader=importlib.machinery.SourceFileLoader('sleep_state',str(SCRIPT))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    m=importlib.util.module_from_spec(spec);loader.exec_module(m);return m

class SleepRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(),'UP-04 sleep state helper missing')
        self.m=load();self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.sys=self.root/'sys';self.proc=self.root/'proc';self.run=self.root/'run'
        self.write('power/mem_sleep','[s2idle]')
        self.write('power/suspend_stats/success','5');self.write('power/suspend_stats/fail','2')
        self.write('bus/pci/devices/0000:01:00.0/power/wakeup','enabled')
        self.write('module/ath12k/placeholder','');self.write('module/ath12k_wifi7/placeholder','')
        self.proc.mkdir();(self.proc/'interrupts').write_text(' CPU0 CPU1\n 10: 1 2 GIC pwrkey\n')
        self.calls=[];self.fail=None
        self.s=self.m.SleepState(self.sys,self.proc,self.run)
        self.s.command=self.command
    def write(self,p,v):
        f=self.sys/p;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(v);return f
    def command(self,*args):
        self.calls.append(args)
        if self.fail and self.fail in args: raise OSError('injected '+self.fail)
    def test_timeout_reaps_descendants_before_recovery(self):
        import subprocess, time
        marker=self.root/'late-audio-change'
        self.s.command=self.m.SleepState.command.__get__(self.s)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.s.command('/bin/sh','-c',f'(sleep 0.25; echo changed > "{marker}") & wait',timeout=0.05)
        time.sleep(0.35)
        self.assertFalse(marker.exists(),'late child modified devices after recovery')

    def test_readiness_is_cleared_after_failed_resume(self):
        self.s.prepare();self.assertTrue(self.s.ready_path.exists())
        self.fail='ath12k_wifi7';self.assertFalse(self.s.recover())
        self.assertFalse(self.s.ready_path.exists())
        self.assertTrue(self.s.state_path.exists())

    def test_failure_preparing_audio_recovers_wake_wifi_and_audio(self):
        self.fail='audio-off'
        with self.assertRaisesRegex(OSError,'audio-off'): self.s.prepare()
        self.assertIn(('/usr/lib/konkr/konkr-sleep','audio-on'),self.calls)
        self.assertFalse(self.s.state_path.exists())
        self.assertEqual((self.sys/'bus/pci/devices/0000:01:00.0/power/wakeup').read_text(),'enabled')
    def test_wifi_unload_failure_restores_only_original_modules(self):
        self.fail='-r'
        with self.assertRaisesRegex(OSError,'-r'):self.s.prepare()
        self.assertIn(('modprobe','ath12k_wifi7'),self.calls)
        self.assertIn(('modprobe','ath12k'),self.calls)
        self.assertNotIn(('modprobe','ath12k_pci'),self.calls)
        self.assertFalse(self.s.state_path.exists())
    def test_resume_failure_attempts_all_and_retains_retry_record(self):
        self.s.prepare();self.fail='ath12k_wifi7'
        self.assertFalse(self.s.recover())
        self.assertTrue(self.s.state_path.exists())
        self.assertIn(('/usr/lib/konkr/konkr-sleep','audio-on'),self.calls)
        self.fail=None;self.assertTrue(self.s.recover());self.assertFalse(self.s.state_path.exists())
    def test_reentry_does_not_overwrite_original_recovery(self):
        self.s.prepare();old=self.s.state_path.read_bytes();calls=len(self.calls)
        with self.assertRaisesRegex(RuntimeError,'pending'):self.s.prepare()
        self.assertEqual(self.s.state_path.read_bytes(),old);self.assertEqual(len(self.calls),calls)
        self.assertTrue(self.s.recover())
    def test_disabled_wifi_is_not_enabled_by_resume(self):
        import shutil
        shutil.rmtree(self.sys/'module')
        self.s.prepare();self.assertTrue(self.s.recover())
        self.assertFalse(any(c[0]=='modprobe' for c in self.calls))
    def test_rejects_missing_s2idle_before_audio_or_wifi(self):
        self.write('power/mem_sleep','[deep]')
        with self.assertRaisesRegex(RuntimeError,'s2idle'):self.s.prepare()
        self.assertEqual(self.calls,[])
    def test_corrupt_record_cannot_request_arbitrary_modules_or_paths(self):
        self.run.mkdir();self.s.state_path.write_text('{"format": "wrong"}')
        self.assertFalse(self.s.recover());self.assertEqual(self.calls,[])
        self.assertTrue(self.s.state_path.exists())
    def test_report_omits_energy_estimate_while_charging(self):
        start={'pct':'70','energy_now':'7000000','status':'Charging'}
        end={'pct':'68','energy_now':'6800000','status':'Discharging'}
        report=self.m.drain_report(3600,start,end)
        self.assertNotIn('Wh/h',report);self.assertIn('charging',report.lower())
    def test_report_real_energy_units_and_missing_battery(self):
        start={'pct':'70','energy_now':'7000000','status':'Discharging'}
        end={'pct':'68','energy_now':'6800000','status':'Discharging'}
        self.assertIn('0.200 Wh/h',self.m.drain_report(3600,start,end))
        self.assertIn('2.00 %/h',self.m.drain_report(3600,start,end))
        self.assertNotIn('%/h',self.m.drain_report(3600,{},{}))

if __name__=='__main__': unittest.main()

class SuspendDispatcherTests(unittest.TestCase):
    def test_failed_preparation_blocks_suspend_but_standby_remains_default(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'var/lib/konkrd').mkdir(parents=True);(root/'run/konkr').mkdir(parents=True)
            marker=root/'entered'
            standby=root/'standby';standby.write_text(f'#!/bin/sh\necho standby > "{marker}"\n');standby.chmod(0o755)
            suspend=root/'suspend';suspend.write_text(f'#!/bin/sh\necho s2idle > "{marker}"\n');suspend.chmod(0o755)
            script=(REPO/'sm8650-overlay/usr/lib/konkr/konkr-suspend').read_text()
            script=script.replace('/var/lib/konkrd',str(root/'var/lib/konkrd')).replace('/run/konkr',str(root/'run/konkr'))
            script=script.replace('/usr/lib/konkr/konkr-standby',str(standby)).replace('/usr/lib/systemd/systemd-sleep',str(suspend))
            dispatch=root/'dispatch';dispatch.write_text(script)
            result=subprocess.run(['sh',str(dispatch)],capture_output=True)
            self.assertEqual(result.returncode,0);self.assertEqual(marker.read_text().strip(),'standby');marker.unlink()
            (root/'run/konkr/s2idle').touch()
            result=subprocess.run(['sh',str(dispatch)],capture_output=True)
            self.assertNotEqual(result.returncode,0);self.assertFalse(marker.exists())
            (root/'run/konkr/sleep-ready').touch();(root/'run/konkr/sleep-state.json').write_text('{}')
            result=subprocess.run(['sh',str(dispatch)],capture_output=True)
            self.assertEqual(result.returncode,0);self.assertEqual(marker.read_text().strip(),'s2idle');marker.unlink()
            (root/'var/lib/konkrd/sleep-standby').touch()
            result=subprocess.run(['sh',str(dispatch)],capture_output=True)
            self.assertEqual(result.returncode,0);self.assertEqual(marker.read_text().strip(),'standby')
