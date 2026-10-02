"""Pinned Decky must work offline and reject corrupt or wrong-ABI caches."""
from pathlib import Path
import hashlib
import json
import struct
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


class DeckyArtifactTests(unittest.TestCase):
    def fetch(self, *, corrupt=False, present=True, machine=62):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = b'\x7fELF' + bytes((2, 1, 1)) + b'\0' * 11 + struct.pack('<H', machine) + b'test artifact'
            meta = root / 'loader.json'
            meta.write_text(json.dumps({'version': 'test', 'sha256': hashlib.sha256(data).hexdigest(),
                                        'url': 'https://example.invalid/PluginLoader', 'architecture': 'x86_64'}))
            cached = root / 'PluginLoader-test'
            if present: cached.write_bytes(b'bad' if corrupt else data)
            result = subprocess.run(['python3', str(REPO / 'scripts/fetch-decky-loader.py'),
                                     '--metadata', str(meta), '--cache-dir', str(root), '--offline'],
                                    capture_output=True, text=True)
            return result, cached.exists()

    def test_verified_cache_needs_no_network(self):
        result, _ = self.fetch()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PluginLoader-test', result.stdout)

    def test_corrupt_cache_is_rejected_without_publishing_replacement(self):
        result, exists = self.fetch(corrupt=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA256 mismatch', result.stderr)
        self.assertTrue(exists)

    def test_missing_cache_fails_clearly_offline(self):
        result, exists = self.fetch(present=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('offline', result.stderr)
        self.assertFalse(exists)

    def test_arm_binary_cannot_replace_box64_loader(self):
        result, _ = self.fetch(machine=183)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('x86-64 ELF', result.stderr)


if __name__ == '__main__': unittest.main()
