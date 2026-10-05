"""Access restoration preserves existing keys and refuses redirected files."""
import base64
import importlib.util
from pathlib import Path
import struct
import tempfile
import subprocess
import unittest

REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / 'scripts/rp6-access-restore.py'
KEY = 'ssh-ed25519 ' + base64.b64encode(struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 32) + bytes(range(32))).decode() + ' fixture'


class AccessTests(unittest.TestCase):
    def helper(self):
        self.assertTrue(HELPER.exists(), 'Access restoration helper is missing')
        spec = importlib.util.spec_from_file_location('access', HELPER)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_preserves_existing_keys_and_is_idempotent(self):
        tool = self.helper()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); folder = home / '.ssh'; folder.mkdir()
            existing = '# user keys\nssh-rsa existing-user-key\n'
            (folder / 'authorized_keys').write_text(existing)
            tool.install_key(home, KEY); first = (folder / 'authorized_keys').read_bytes()
            tool.install_key(home, KEY)
            self.assertEqual((folder / 'authorized_keys').read_bytes(), first)
            self.assertTrue(first.decode().startswith(existing))
            self.assertEqual(first.decode().count(KEY.split()[1]), 1)
            self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
            self.assertEqual((folder / 'authorized_keys').stat().st_mode & 0o777, 0o600)

    def test_rejects_symlinked_ssh_folder_and_authorized_keys(self):
        tool = self.helper()
        for target in ('folder', 'file'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); home = root / 'home'; home.mkdir(); outside = root / 'outside'; outside.mkdir()
                marker = outside / 'authorized_keys'; marker.write_text('keep')
                if target == 'folder': (home / '.ssh').symlink_to(outside, target_is_directory=True)
                else:
                    (home / '.ssh').mkdir(); (home / '.ssh/authorized_keys').symlink_to(marker)
                with self.assertRaises((ValueError, OSError)): tool.install_key(home, KEY)
                self.assertEqual(marker.read_text(), 'keep')

    def test_refuses_key_options_or_invalid_key_before_changes(self):
        tool = self.helper()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            for key in ('command="evil" ' + KEY, 'ssh-ed25519 invalid', KEY + '\n' + KEY):
                with self.assertRaises(ValueError): tool.install_key(home, key)
            self.assertFalse((home / '.ssh').exists())

    def test_installer_payloads_match_source_and_pass_bash_parser(self):
        spec = importlib.util.spec_from_file_location('installer', REPO / 'scripts/build-rp6-access-installer.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        script = module.build(KEY, 'SHA256:' + 'a' * 43)
        # Decode the actual standalone payload, not a parallel test implementation.
        encoded = script.split("<<'RP6_PAYLOAD_0'\n", 1)[1].split('\nRP6_PAYLOAD_0', 1)[0]
        self.assertEqual(base64.b64decode(encoded), HELPER.read_bytes())
        self.assertNotIn('PRIVATE KEY', script)
        result = subprocess.run(['bash', '-n'], input=script, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_repeated_restore_does_not_rewrite_key_file(self):
        tool = self.helper()
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); tool.install_key(home, KEY)
            path = home / '.ssh/authorized_keys'; original = path.stat().st_ino
            path.chmod(0o644)
            tool.install_key(home, KEY)
            self.assertEqual(path.stat().st_ino, original)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_fresh_install_requires_exact_kernel_before_any_configuration(self):
        spec = importlib.util.spec_from_file_location('installer', REPO / 'scripts/build-rp6-access-installer.py')
        tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory() as tmp:
            kernel = Path(tmp) / 'KERNEL'; kernel.write_bytes(b'wrong image')
            script = tool.build(KEY, kernel_sha256='a' * 64)
            # Stop the real generated installer at its read-only image gate.
            script = script.replace('/boot/KERNEL', str(kernel))
            script = script.replace('if (( EUID != 0 )); then exec sudo -- bash "$0" "$@"; fi', '')
            start = script.index('for tool in ')
            end = script.index('restore_readonly=0')
            gate = script[start:end]
            gate = gate[gate.index("printf '%s  %s\\n'"):]
            result = subprocess.run(['bash', '-euc', gate], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('FAILED', result.stdout)

    def test_installer_rejects_missing_or_ambiguous_identity_policy(self):
        spec = importlib.util.spec_from_file_location('installer', REPO / 'scripts/build-rp6-access-installer.py')
        tool = importlib.util.module_from_spec(spec); spec.loader.exec_module(tool)
        for options in ({}, {'kernel_sha256': 'bad'},
                        {'fingerprint': 'SHA256:' + 'a' * 43, 'kernel_sha256': 'b' * 64}):
            with self.subTest(options=options), self.assertRaises(ValueError): tool.build(KEY, **options)
