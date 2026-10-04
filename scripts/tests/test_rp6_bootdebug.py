"""Persistent RP6 collection must survive the initial boot window."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


@unittest.skipUnless(platform.system() == 'Linux', 'requires Linux procfs')
class BootDebugTests(unittest.TestCase):
    def test_keeps_collecting_after_initial_boot_and_records_boot_storage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); out = root / 'logs'; tools = root / 'tools'; tools.mkdir()
            # Accelerate waits, then stop the real collector after eleven waits.
            sleep = tools / 'sleep'
            sleep.write_text('#!/bin/sh\nn=$(cat "$WAIT_COUNT" 2>/dev/null || echo 0)\nn=$((n+1)); echo "$n" > "$WAIT_COUNT"\n[ "$n" -lt 11 ] || kill -TERM "$PPID"\n')
            sleep.chmod(0o755)
            script = (REPO / 'external-and-mods/kernel-common/initramfs/bootdebug').read_text()
            script = script.replace('out=/boot/debug-logs', 'out="$TEST_OUTPUT"')
            env = dict(os.environ, PATH=str(tools) + ':' + os.environ['PATH'],
                       TEST_OUTPUT=str(out), WAIT_COUNT=str(root / 'waits'))
            result = subprocess.run(['sh', '-c', script], env=env, capture_output=True, timeout=30)
            self.assertEqual((root / 'waits').read_text().strip(), '11')
            self.assertEqual(result.returncode, -15)
            summary = (out / 'summary.txt').read_text()
            self.assertIn(Path('/proc/cmdline').read_text().strip(), summary)
            devices = (out / 'devices.txt').read_text()
            self.assertIn(Path('/proc/partitions').read_text().strip(), devices)


if __name__ == '__main__': unittest.main()
