"""Kernel input corruption and real recipe selection must stop before building."""
import hashlib
import importlib.util
import json
import os
import platform
from pathlib import Path
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / 'scripts/check-rp6-kernel.py'


class KernelInputsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.cache = self.folder / 'cache'; self.cache.mkdir()
        self.frame = self.folder / 'frame'; self.frame.mkdir()
        self.rocknix = self.folder / 'rocknix'; self.rocknix.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.rocknix)], check=True)
        (self.rocknix / 'donor.patch').write_text('accepted donor')
        subprocess.run(['git', '-C', str(self.rocknix), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.rocknix), '-c', 'user.name=Fixture',
                        '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture'], check=True)
        sha = subprocess.check_output(['git', '-C', str(self.rocknix), 'rev-parse', 'HEAD'], text=True).strip()
        self.lock = {'format': 'rp6-kernel-inputs-1', 'kernel': '7.2.8', 'recipe': '7.2',
                     'rocknix_sha': sha, 'inputs': []}
        for name, location in [('linux', 'cache'), ('extra-firmware', 'cache'), ('chipone', 'cache'),
                               ('regdb', 'cache'), ('regdb-signature', 'cache'), ('gpu-sqe', 'cache'),
                               ('gpu-gmu', 'cache'), ('gpu-zap', 'cache'), ('wifi-amss', 'frame'),
                               ('wifi-m3', 'frame'), ('wifi-board', 'frame')]:
            data = ('locked ' + name).encode(); folder = self.cache if location == 'cache' else self.frame
            (folder / name).write_bytes(data)
            self.lock['inputs'].append({'id': name, 'location': location, 'path': name,
                                       'sha256': hashlib.sha256(data).hexdigest(),
                                       'url': 'https://example.invalid/pinned/' + name})
        self.lockfile = self.folder / 'lock.json'

    def invoke(self, *extra):
        self.lockfile.write_text(json.dumps(self.lock))
        return subprocess.run(['python3', str(TOOL), 'inputs', '--lock', str(self.lockfile),
                               '--cache', str(self.cache), '--frame', str(self.frame),
                               '--rocknix', str(self.rocknix), *extra], capture_output=True, text=True)

    def test_rejects_wrong_toolchain_or_busybox(self):
        bb = self.folder / 'busybox'; bb.write_bytes(b'static fixture')
        expected = 'sha256:' + 'a' * 64
        self.lock['toolchain'] = {'image': expected, 'busybox_sha256': hashlib.sha256(bb.read_bytes()).hexdigest()}
        args = ['--toolchain-id', expected, '--busybox', str(bb)]
        self.assertEqual(self.invoke(*args).returncode, 0)
        bb.write_bytes(b'changed binary')
        r = self.invoke(*args); self.assertNotEqual(r.returncode, 0); self.assertIn('BusyBox', r.stderr)
        args[1] = 'sha256:' + 'b' * 64
        r = self.invoke(*args); self.assertNotEqual(r.returncode, 0); self.assertIn('toolchain', r.stderr)

    def test_exact_locked_inputs_pass(self):
        r = self.invoke(); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)['kernel'], '7.2.8')

    def test_rejects_cached_archive_hash_mismatch(self):
        (self.cache / 'linux').write_bytes(b'corrupted')
        r = self.invoke(); self.assertNotEqual(r.returncode, 0); self.assertIn('SHA256', r.stderr)

    def test_rejects_dirty_or_wrong_rocknix(self):
        (self.rocknix / 'donor.patch').write_text('uncommitted edit')
        r = self.invoke(); self.assertNotEqual(r.returncode, 0); self.assertIn('dirty', r.stderr)
        subprocess.run(['git', '-C', str(self.rocknix), 'checkout', '--', 'donor.patch'], check=True)
        self.lock['rocknix_sha'] = '1' * 40
        r = self.invoke(); self.assertNotEqual(r.returncode, 0); self.assertIn('ROCKNIX', r.stderr)

    def test_rejects_missing_frame_blob(self):
        (self.frame / 'wifi-board').unlink()
        r = self.invoke(); self.assertNotEqual(r.returncode, 0); self.assertIn('wifi-board', r.stderr)

    def test_rejects_incomplete_lock_or_escaping_path(self):
        self.lock['inputs'][0]['path'] = '../outside'
        r = self.invoke(); self.assertNotEqual(r.returncode, 0); self.assertIn('path', r.stderr)
        self.lock['inputs'].pop(0)
        r = self.invoke(); self.assertNotEqual(r.returncode, 0); self.assertIn('incomplete', r.stderr)

    def test_invalid_recipe_is_rejected(self):
        r = subprocess.run(['bash', '-c', 'SM8550_RECIPE=typo; source "$1"', 'fixture',
                            str(REPO / 'external-and-mods/kernel-sm8550/soc.env')], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)

    def test_recipe_7_2_defaults_to_both_rp6_trees(self):
        r = subprocess.run(['bash', '-c', 'SM8550_RECIPE=7.2; unset DTBS_OVERRIDE SM8550_KERNEL; source "$1"; printf "%s" "$DTBS"',
                            'fixture', str(REPO / 'external-and-mods/kernel-sm8550/soc.env')],
                           capture_output=True, text=True, check=True)
        self.assertEqual(r.stdout.split(), ['qcs8550-retroidpocket-rp6', 'qcs8550-retroidpocket-rp6-top-dpad'])

    def test_recipe_7_2_defaults_to_rocknix_cmdline(self):
        r = subprocess.run(['bash', '-c', 'SM8550_RECIPE=7.2; unset SM8550_KERNEL; source "$1"; printf "%s" "$SM8550_KERNEL"',
                            'fixture', str(REPO / 'external-and-mods/kernel-sm8550/soc.env')],
                           capture_output=True, text=True, check=True)
        self.assertEqual(r.stdout, 'rocknix')

    def test_rejects_chipone_ref_override(self):
        self.lock['inputs'][2]['path'] = 'chipone_tddi-' + 'a'*40 + '.tar.gz'
        (self.cache / 'chipone').rename(self.cache / self.lock['inputs'][2]['path'])
        r = self.invoke('--chipone-ref', 'b'*40)
        self.assertNotEqual(r.returncode, 0); self.assertIn('chipone ref', r.stderr)
        self.assertEqual(self.invoke('--chipone-ref', 'a'*40).returncode, 0)

    @unittest.skipUnless(platform.system() == 'Linux' and platform.machine() == 'aarch64', 'needs ARM64 Linux builder')
    def test_repack_refuses_to_mix_an_old_bundle(self):
        r = subprocess.run(['bash', str(REPO / 'external-and-mods/kernel-common/build.sh'), 'sm8550', '--repack-boot'],
                           env={**os.environ, 'SM8550_RECIPE': '7.2', 'SM8550_KERNEL': 'rocknix'},
                           capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0); self.assertIn('full rebuild', r.stderr)

    def test_donor_patch_change_invalidates_source_marker(self):
        self.assertTrue(TOOL.is_file(), 'input checker/fingerprint not implemented')
        spec = importlib.util.spec_from_file_location('kernel_inputs', TOOL)
        tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        soc = self.folder / 'soc'; common = self.folder / 'common'
        (soc / 'patches').mkdir(parents=True); (common / 'initramfs').mkdir(parents=True)
        (self.rocknix / 'patches').mkdir(); p = self.rocknix / 'patches/one.patch'; p.write_text('first')
        args = (soc, common, self.rocknix, ['patches'], [], ['rp6'])
        before = tool.fingerprint(*args); p.write_text('changed donor')
        self.assertNotEqual(tool.fingerprint(*args), before)
        before = tool.fingerprint(*args); (common / 'initramfs/init').write_text('new early /etc')
        self.assertNotEqual(tool.fingerprint(*args), before)


if __name__ == '__main__': unittest.main()
