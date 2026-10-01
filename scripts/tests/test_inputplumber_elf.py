"""Check failure paths at the boundary with the external ELF analyzer."""
import os
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / 'scripts/check-inputplumber-elf.py'


def elf(machine=183):
    return b'\x7fELF' + bytes([2, 1, 1]) + bytes(9) + struct.pack('<HHIQQQIHHHHHH',
        3, machine, 1, 0, 0, 0, 0, 64, 0, 0, 0, 0, 0)


class ElfChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'
        self.binary = self.root / 'usr/bin/inputplumber'
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(elf())
        lib = self.root / 'usr/lib'
        lib.mkdir()
        (lib / 'libok.so.1').write_bytes(elf())
        (lib / 'ld-linux-aarch64.so.1').write_bytes(elf())
        (self.root / 'lib').symlink_to('/usr/lib')
        self.tools = Path(self.temp.name) / 'tools'
        self.tools.mkdir()
        self.analyzer = self.tools / 'readelf'
        self.analyzer.write_text('''#!/bin/sh
case "$1" in
-dW) echo 'Dynamic section at offset 0x200 contains 2 entries:'
     echo ' 0x0000000000000001 (NEEDED) Shared library: [libok.so.1]';;
-lW) echo ' [Requesting program interpreter: /lib/ld-linux-aarch64.so.1]';;
*) exit 2;;
esac
''')
        self.analyzer.chmod(0o755)

    def run_check(self):
        return subprocess.run([sys.executable, str(TOOL), str(self.binary), str(self.root)],
                              env={**os.environ, 'PATH': str(self.tools), 'LC_ALL': 'C'},
                              capture_output=True, text=True)

    def test_accepts_absolute_library_symlink_inside_target_root(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('libok.so.1', result.stdout)

    def test_rejects_unavailable_analyzer(self):
        self.analyzer.unlink()
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('readelf', result.stderr)

    def test_rejects_analyzer_failure(self):
        self.analyzer.write_text('#!/bin/sh\nexit 3\n')
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('readelf', result.stderr)

    def test_rejects_missing_library_and_loader(self):
        for name in ['libok.so.1', 'ld-linux-aarch64.so.1']:
            with self.subTest(name=name):
                path = self.root / 'usr/lib' / name
                data = path.read_bytes(); path.unlink()
                result = self.run_check()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(name, result.stderr)
                path.write_bytes(data)

    def test_rejects_wrong_architecture(self):
        self.binary.write_bytes(elf(62))
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('AArch64', result.stderr)

    def test_rejects_wrong_architecture_in_loader_and_direct_libraries(self):
        for name in ('ld-linux-aarch64.so.1', 'libok.so.1'):
            with self.subTest(name=name):
                path = self.root / 'usr/lib' / name
                path.write_bytes(elf(62))
                result = self.run_check()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('AArch64', result.stderr)
                self.assertIn(name, result.stderr)
                path.write_bytes(elf())

    def test_rejects_invalid_dynamic_analysis(self):
        self.analyzer.write_text('#!/bin/sh\necho "There is no dynamic section in this file."\n')
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('dynamic', result.stderr)

    def test_rejects_symlink_escape_even_when_host_file_exists(self):
        path = self.root / 'usr/lib/libok.so.1'
        path.unlink()
        outside = Path(self.temp.name) / 'host-lib.so.1'
        outside.write_bytes(elf())
        path.symlink_to('../../../host-lib.so.1')
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('rootfs', result.stderr)


if __name__ == '__main__':
    unittest.main()
