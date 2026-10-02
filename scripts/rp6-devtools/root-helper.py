#!/usr/bin/python3 -I
# RP6 development helper: fixed actions only, installed root-owned.
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess

ACTIONS = {'enable-ssh': ['/usr/bin/systemctl', 'enable', '--now', 'sshd.service'],
           'restart-decky': ['/usr/bin/systemctl', 'restart', 'plugin_loader.service'],
           'restart-konkrd': ['/usr/bin/systemctl', 'restart', 'konkrd.service'],
           'reboot': ['/usr/bin/systemctl', 'reboot']}


def main():
    parser = argparse.ArgumentParser(description='Restricted RP6 development actions')
    parser.add_argument('action', choices=['snapshot', *ACTIONS]); args = parser.parse_args()
    if os.geteuid() != 0: raise ValueError('Root installation/authentication required')
    if Path('/sys/firmware/devicetree/base/model').read_text().rstrip('\x00\n') != 'Retroid Pocket 6':
        raise ValueError('Retroid Pocket 6 required')
    root_device = subprocess.check_output(['/usr/bin/findmnt', '-n', '-o', 'SOURCE', '/'], text=True).strip()
    if not root_device.startswith('/dev/mmcblk'): raise ValueError('microSD root required')
    lock = os.open('/run/lock/rp6-devtools.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'snapshot':
            with Path('/boot/KERNEL').open('rb') as stream: kernel = hashlib.file_digest(stream, 'sha256').hexdigest()
            log = Path('/boot/early-etc.log')
            result = {'status': 'available', 'kernel_sha256': kernel, 'root_device': root_device,
                      'early_etc_log': log.read_text(errors='replace')[-12000:] if log.is_file() else None}
        else:
            p = subprocess.run(ACTIONS[args.action], capture_output=True, text=True, timeout=25)
            result = {'action': args.action, 'exit': p.returncode, 'stdout': p.stdout[-2000:], 'stderr': p.stderr[-2000:]}
            if p.returncode:
                print(json.dumps(result)); raise SystemExit(p.returncode)
        print(json.dumps(result))
    finally: os.close(lock)


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, subprocess.SubprocessError) as exc: raise SystemExit(str(exc))
