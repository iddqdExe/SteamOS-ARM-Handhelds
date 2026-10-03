"""Release evidence and refusal paths, using real git repos and boot images."""
import copy
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tarfile
import unittest

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / 'scripts/build-rp6-release-manifest.py'


class ReleaseManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / 'repo'; self.repo.mkdir()
        self.git('init', '-q')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'user.name', 'Fixture')
        (self.repo / 'fix.patch').write_text('fixture patch\n')
        self.git('add', '.'); self.git('commit', '-qm', 'fixture')
        self.root = self.base / 'root'
        for rel in ('usr/lib/modules/7.0.14-fixture', 'usr/lib/firmware/qcom',
                    'usr/bin', 'usr/lib/steamos', 'usr/share/steamos-arm'):
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / 'usr/lib/modules/7.0.14-fixture/probe.ko').write_bytes(b'module')
        (self.root / 'usr/lib/firmware/qcom/probe.fw').write_bytes(b'firmware')
        (self.root / 'usr/bin/inputplumber').write_bytes(b'input binary')
        (self.root / 'usr/bin/inputplumber').chmod(0o755)
        payload = self.base / 'Image.gz'
        payload.write_bytes(gzip.compress(b'Linux version 7.0.14-fixture (builder)\0', mtime=0))
        ramdisk = self.base / 'ramdisk'; ramdisk.write_bytes(b'fixture')
        self.kernel = self.base / 'KERNEL'
        subprocess.run(['python3', str(REPO / 'external-and-mods/kernel-common/mkbootimg-v0.py'),
                        '--kernel', str(payload), '--ramdisk', str(ramdisk),
                        '--cmdline', 'root=PARTUUID=fixture-02 quiet', '--out', str(self.kernel)],
                       check=True, capture_output=True)
        self.download = self.base / 'rootfs.img'; self.download.write_bytes(b'fixed upstream rootfs')
        self.recipe = self.base / 'recipe.json'
        self.data = {
            'module': 'UP-08', 'tasks': ['UP-08.1'],
            'donors': [{'url': 'https://github.com/example/donor', 'sha': 'a' * 40,
                        'authors': ['Example Author'], 'license': 'GPL-2.0',
                        'adaptation': 'release checklist only'}],
            'components': {'frame': '20260925.6175226 / 0.5.0'},
            'inputs': [{'id': 'frame-rootfs', 'path': str(self.download),
                        'url': 'https://example.invalid/20260925/rootfs.img',
                        'sha256': hashlib.sha256(self.download.read_bytes()).hexdigest()}],
            'transfers': [{'module': 'UP-01', 'decision': 'untested'}],
            'validation': {'source': 'not-run', 'ci': 'not-run', 'device': 'not-run',
                           'fresh_image': 'not-run', 'update': 'not-run', 'rollback': 'not-run'},
            'rollback': {'backup_id': None, 'procedure': 'rollback.md'},
        }
        self.output = self.base / 'manifest.json'

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True).strip()

    def create(self, *extra):
        self.recipe.write_text(json.dumps(self.data))
        return subprocess.run(['python3', str(TOOL), 'create', '--repo', str(self.repo),
                               '--rootfs', str(self.root), '--kernel', str(self.kernel),
                               '--recipe', str(self.recipe), '--output', str(self.output), *extra],
                              capture_output=True, text=True)

    def test_records_actual_source_kernel_modules_firmware_modes_and_download_checksums(self):
        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(self.output.read_text())
        self.assertEqual(manifest['source']['sha'], self.git('rev-parse', 'HEAD'))
        self.assertFalse(manifest['source']['dirty'])
        self.assertEqual(manifest['kernel']['release'], '7.0.14-fixture')
        self.assertEqual(manifest['kernel']['sha256'], hashlib.sha256(self.kernel.read_bytes()).hexdigest())
        self.assertEqual(manifest['modules']['probe.ko']['sha256'], hashlib.sha256(b'module').hexdigest())
        self.assertEqual(manifest['firmware']['qcom/probe.fw']['sha256'], hashlib.sha256(b'firmware').hexdigest())
        self.assertEqual(manifest['runtime']['usr/bin/inputplumber']['mode'], '0755')
        self.assertEqual(manifest['patches']['fix.patch']['sha256'], hashlib.sha256(b'fixture patch\n').hexdigest())
        self.assertEqual(manifest['decision'], 'untested')
        self.assertEqual(manifest['channel'], 'beta-opt-in')
        self.assertEqual(manifest['target']['ram_gib'], 12)
        self.assertEqual(manifest['target']['media'], 'microSD')
        self.assertIn('python', manifest['toolchain'])

    def test_rejects_dirty_source_without_writing_manifest(self):
        (self.repo / 'fix.patch').write_text('unrecorded change')
        result = self.create()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('dirty', result.stderr)
        self.assertFalse(self.output.exists())

    def test_candidate_records_dirty_content_and_cannot_become_default(self):
        (self.repo / 'fix.patch').write_text('local adaptation')
        result = self.create('--allow-dirty')
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads(self.output.read_text())
        self.assertTrue(manifest['source']['dirty'])
        self.assertEqual(manifest['source']['changes']['fix.patch']['sha256'], hashlib.sha256(b'local adaptation').hexdigest())
        self.output.unlink()
        result = self.create('--allow-dirty', '--channel', 'default')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_candidate_records_staged_add_modify_delete_against_the_declared_head(self):
        (self.repo / 'remove.txt').write_bytes(b'base file')
        self.git('add', '.'); self.git('commit', '-qm', 'base with removal')
        (self.repo / 'fix.patch').write_bytes(b'staged adaptation')
        (self.repo / 'added.txt').write_bytes(b'staged addition')
        (self.repo / 'remove.txt').unlink()
        self.git('add', '-A')
        result = self.create('--allow-dirty')
        self.assertEqual(result.returncode, 0, result.stderr)
        changes = json.loads(self.output.read_text())['source']['changes']
        self.assertEqual(set(changes), {'fix.patch', 'added.txt', 'remove.txt'})
        self.assertEqual(changes['fix.patch']['sha256'], hashlib.sha256(b'staged adaptation').hexdigest())
        self.assertEqual(changes['added.txt']['sha256'], hashlib.sha256(b'staged addition').hexdigest())
        self.assertEqual(changes['remove.txt'], {'deleted': True})

    def test_rejects_moving_donor_refs_and_downloads(self):
        original = copy.deepcopy(self.data)
        for kind in ('donor', 'download'):
            self.data = copy.deepcopy(original)
            if kind == 'donor': self.data['donors'][0]['sha'] = 'main'
            else: self.data['inputs'][0]['url'] = 'https://example.invalid/releases/latest/rootfs.img'
            with self.subTest(kind=kind):
                result = self.create()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.output.exists())

    def test_rejects_wrong_download_checksum_before_output(self):
        self.download.write_bytes(b'changed download')
        result = self.create()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('checksum', result.stderr)
        self.assertFalse(self.output.exists())

    def test_records_sealed_local_artifact_without_inventing_a_download_url(self):
        item = self.data['inputs'][0]
        item.pop('url')
        item.update(kind='local-artifact', source_sha=self.git('rev-parse', 'HEAD'),
                    artifact_name=self.download.name)
        result = self.create()
        self.assertEqual(result.returncode, 0, result.stderr)
        recorded = json.loads(self.output.read_text())['inputs'][0]
        self.assertEqual(recorded['kind'], 'local-artifact')
        self.assertEqual(recorded['source_sha'], item['source_sha'])
        self.assertEqual(recorded['artifact_name'], self.download.name)
        self.assertNotIn('path', recorded)
        self.assertNotIn('url', recorded)

    def test_local_artifact_requires_source_sha_and_regular_file(self):
        item = self.data['inputs'][0]
        item.pop('url'); item.update(kind='local-artifact', artifact_name=self.download.name)
        result = self.create()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('source SHA', result.stderr)
        item['source_sha'] = self.git('rev-parse', 'HEAD')
        link = self.base / 'link.img'; link.symlink_to(self.download)
        item['path'] = str(link)
        result = self.create()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('regular', result.stderr)
        self.assertFalse(self.output.exists())

    def test_rejects_kernel_without_matching_modules(self):
        (self.root / 'usr/lib/modules/7.0.14-fixture').rename(self.root / 'usr/lib/modules/other-release')
        result = self.create()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('modules', result.stderr)
        self.assertFalse(self.output.exists())

    def test_default_requires_hardware_fresh_image_update_and_rollback_evidence(self):
        self.data['validation']['source'] = 'passed'
        self.data['validation']['ci'] = 'passed'
        result = self.create('--channel', 'default')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    def test_accepted_default_requires_each_checksummed_evidence_file(self):
        self.data['transfers'][0]['decision'] = 'accepted'
        self.data['rollback']['backup_id'] = 'fixture-card-backup'
        proof = self.base / 'validation.log'; proof.write_bytes(b'fixture evidence')
        checks = ('source', 'ci', 'device', 'fresh_image', 'update', 'rollback')
        self.data['validation'] = {name: 'passed' for name in checks}
        self.data['evidence'] = {name: {'path': str(proof), 'sha256': hashlib.sha256(b'fixture evidence').hexdigest()} for name in checks}
        result = self.create('--channel', 'default')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.output.read_text())['decision'], 'accepted')
        self.output.unlink()
        self.data['evidence'].pop('rollback')
        result = self.create('--channel', 'default')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.output.exists())

    @unittest.skipUnless(os.uname().sysname == 'Linux', 'GNU cp/tar package builder required')
    def test_real_package_builder_records_manifest_and_rejects_wrong_kernel_without_output(self):
        result = self.create(); self.assertEqual(result.returncode, 0, result.stderr)
        marker = self.root / 'usr/share/steamos-arm/release-manifest.json'
        marker.write_bytes(self.output.read_bytes())
        before = marker.read_bytes()
        (self.root / 'usr/lib/liblsfg-vk-layer-arm64.so').write_bytes(b'fixture layer')
        (self.root / 'etc').mkdir(); (self.root / 'opt').mkdir()
        for plugin in ('konkr-control', 'decky-lsfg-vk'):
            (self.root / 'home/steamos/homebrew/plugins' / plugin).mkdir(parents=True)
        package = self.base / 'update.tar.gz'
        command = ['python3', str(REPO / 'scripts/build-update-package.py'), '--rootfs', str(self.root),
                   '--kernel', str(self.kernel), '--soc', 'sm8550', '--device', 'Retroid Pocket 6',
                   '--version', 'fixture-up08', '--output', str(package)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(marker.read_bytes(), before, 'hardlink packaging must leave source marker untouched')
        with tarfile.open(package) as archive:
            metadata = json.load(archive.extractfile('manifest.json'))
        self.assertEqual(metadata['release'], json.loads(before))
        self.assertEqual(metadata['devices'], ['Retroid Pocket 6'])
        self.kernel.write_bytes(b'wrong kernel')
        bad_package = self.base / 'bad.tar.gz'
        command[-1] = str(bad_package)
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('KERNEL', result.stderr)
        self.assertFalse(bad_package.exists())

    def test_image_builder_rejects_unverified_recipe_before_allocating_an_image(self):
        source = (REPO / 'make-steamos-sm8650.sh').read_text()
        body = source.split('build_image() {', 1)[1].split('  command -v sfdisk', 1)[0]
        scripts = self.base / 'scripts'; scripts.mkdir()
        (scripts / 'check-rp6-input.sh').write_text('#!/bin/sh\nexit 0\n')
        (scripts / 'check-rp6-input.sh').chmod(0o755)
        os.symlink(TOOL, scripts / TOOL.name)
        self.data['inputs'][0]['sha256'] = '0' * 64
        self.recipe.write_text(json.dumps(self.data))
        env = {**os.environ, 'SOC': 'sm8550', 'R': str(self.root), 'ROOT': str(self.repo),
               'SCRIPTS': str(scripts), 'KOUT': str(self.base), 'WORKDIR': str(self.base),
               'RP6_RELEASE_RECIPE': str(self.recipe), 'RP6_RELEASE_CHANNEL': 'beta-opt-in'}
        result = subprocess.run(['bash', '-ec', 'build_image() {' + body + '\n}\nbuild_image'],
                                env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('input checksum mismatch', result.stderr)

    def test_final_image_and_package_checksums_are_external_to_embedded_manifest(self):
        result = self.create(); self.assertEqual(result.returncode, 0, result.stderr)
        before = self.output.read_bytes()
        image = self.base / 'candidate.img'; image.write_bytes(b'complete image')
        package = self.base / 'candidate.tar.gz'; package.write_bytes(b'complete package')
        final = self.base / 'final.json'
        result = subprocess.run(['python3', str(TOOL), 'finalize', '--manifest', str(self.output),
                                 '--image', str(image), '--package', str(package), '--output', str(final)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.output.read_bytes(), before)
        data = json.loads(final.read_text())
        self.assertEqual(data['outputs']['image']['sha256'], hashlib.sha256(b'complete image').hexdigest())
        self.assertEqual(data['outputs']['package']['sha256'], hashlib.sha256(b'complete package').hexdigest())
        self.assertEqual(data['build_manifest_sha256'], hashlib.sha256(before).hexdigest())

    def test_finalize_rejects_symlink_image_or_package_without_publishing_manifest(self):
        result = self.create(); self.assertEqual(result.returncode, 0, result.stderr)
        real_image = self.base / 'real.img'; real_image.write_bytes(b'image')
        real_package = self.base / 'real.tar.gz'; real_package.write_bytes(b'package')
        image_link = self.base / 'linked.img'; image_link.symlink_to(real_image)
        package_link = self.base / 'linked.tar.gz'; package_link.symlink_to(real_package)
        for image, package in ((image_link, real_package), (real_image, package_link)):
            with self.subTest(image=image.name, package=package.name):
                output = self.base / 'final.json'
                result = subprocess.run(['python3', str(TOOL), 'finalize', '--manifest', str(self.output),
                                         '--image', str(image), '--package', str(package), '--output', str(output)],
                                        capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())


if __name__ == '__main__': unittest.main()
