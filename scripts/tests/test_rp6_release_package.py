"""New release contract is enforced before updater accepts a package."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('release_update', REPO / 'external-and-mods/konkr-update/konkr-update.py')
updater = importlib.util.module_from_spec(spec); spec.loader.exec_module(updater)


class PackageReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.stage = Path(self.temp.name) / 'stage'
        for rel in ('root/usr/lib/modules/fixture', 'root/opt', 'root/etc', 'boot'):
            (self.stage / rel).mkdir(parents=True, exist_ok=True)
        (self.stage / 'boot/KERNEL').write_bytes(b'kernel')
        module = self.stage / 'root/usr/lib/modules/fixture/probe.ko'; module.write_bytes(b'module')
        self.release = {'format': 'rp6-release-1', 'module': 'UP-08',
                        'target': {'model': 'Retroid Pocket 6', 'soc': 'SM8550', 'ram_gib': 12, 'media': 'microSD'},
                        'source': {'sha': 'a' * 40, 'dirty': False}, 'channel': 'beta-opt-in', 'decision': 'untested',
                        'kernel': {'release': 'fixture', 'sha256': hashlib.sha256(b'kernel').hexdigest()},
                        'modules': {'probe.ko': {'mode': '0644', 'bytes': 6, 'sha256': hashlib.sha256(b'module').hexdigest()}},
                        'firmware': {}, 'runtime': {}, 'transfers': [{'module': 'UP-01', 'decision': 'untested'}]}

    def package(self):
        marker = self.stage / 'root/usr/share/steamos-arm/release-manifest.json'
        marker.parent.mkdir(parents=True, exist_ok=True); marker.write_text(json.dumps(self.release))
        files = {str(p.relative_to(self.stage)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in self.stage.rglob('*') if p.is_file()}
        manifest = {'format': 1, 'architecture': 'aarch64', 'devices': ['Retroid Pocket 6'],
                    'version': 'fixture', 'files': files, 'release': self.release}
        (self.stage / 'manifest.json').write_text(json.dumps(manifest))
        package = self.stage.parent / 'package.tar.gz'
        with tarfile.open(package, 'w:gz') as archive:
            for rel in ('manifest.json', 'root', 'boot'): archive.add(self.stage / rel, arcname=rel)
        return package, manifest

    def test_legacy_package_still_works_and_release_kernel_mismatch_is_rejected(self):
        self.release['kernel']['sha256'] = '0' * 64
        package, _ = self.package()
        with self.assertRaisesRegex(ValueError, 'KERNEL'): updater.validate_archive(package)

    def test_missing_matching_modules_is_rejected_before_extraction(self):
        (self.stage / 'root/usr/lib/modules/fixture/probe.ko').unlink()
        package, _ = self.package()
        with self.assertRaisesRegex(ValueError, 'modules'): updater.validate_archive(package)

    def test_default_channel_cannot_claim_acceptance_from_source_tests_alone(self):
        self.release.update(channel='default', decision='accepted', validation={'source': 'passed', 'ci': 'passed'})
        package, _ = self.package()
        with self.assertRaisesRegex(ValueError, 'default'): updater.validate_archive(package)

    def test_metadata_and_embedded_release_must_agree(self):
        package, manifest = self.package()
        (self.stage / 'root/usr/share/steamos-arm/release-manifest.json').write_text('{}')
        # Keep payload SHA accurate; the semantic mismatch must still be refused.
        name = 'root/usr/share/steamos-arm/release-manifest.json'
        manifest['files'][name] = hashlib.sha256(b'{}').hexdigest()
        with self.assertRaisesRegex(ValueError, 'release manifest'): updater.verify_payload(self.stage, manifest)

    def test_modules_keep_recorded_modes_and_symlinks(self):
        _, manifest = self.package()
        (self.stage / 'root/usr/lib/modules/fixture/probe.ko').chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'mode'): updater.verify_payload(self.stage, manifest)

    def test_well_formed_beta_contract_and_payload_are_accepted(self):
        package, manifest = self.package()
        parsed, _ = updater.validate_archive(package)
        self.assertEqual(parsed['release'], self.release)
        updater.verify_payload(self.stage, manifest)


if __name__ == '__main__': unittest.main()
