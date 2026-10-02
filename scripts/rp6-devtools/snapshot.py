#!/usr/bin/env python3
"""RP6 development snapshot: bounded diagnostics without process arguments/secrets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time


def run(args, timeout=10):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {'exit': p.returncode, 'stdout': p.stdout[-16000:], 'stderr': p.stderr[-1200:]}
    except (OSError, subprocess.TimeoutExpired) as exc: return {'error': str(exc)}


def properties(unit, user=False):
    command = ['/usr/bin/systemctl'] + (['--user'] if user else [])
    output = run(command + ['show', unit, '-p', 'ActiveState', '-p', 'SubState', '-p', 'UnitFileState', '-p', 'MainPID', '-p', 'Result'])
    return dict(line.split('=', 1) for line in output.get('stdout', '').splitlines() if '=' in line)


def collect():
    model = Path('/sys/firmware/devicetree/base/model').read_text().rstrip('\x00\n')
    if model != 'Retroid Pocket 6': raise ValueError('Retroid Pocket 6 required')
    os.environ.setdefault('XDG_RUNTIME_DIR', '/run/user/1000')
    os.environ.setdefault('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/1000/bus')
    mounts = run(['/usr/bin/findmnt', '--json', '-t', 'ext4,overlay,vfat', '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS'])
    processes = run(['/usr/bin/ps', '-C', 'PluginLoader,gamescope,gamescope-wl,konkr-focusfix', '-o', 'pid=,comm='])
    data = {'model': model, 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'collected_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'uptime_seconds': float(Path('/proc/uptime').read_text().split()[0]),
            'mem_total_kib': int(Path('/proc/meminfo').read_text().splitlines()[0].split()[1]),
            'kernel_release': run(['/usr/bin/uname', '-r']).get('stdout', '').strip(),
            'mounts': json.loads(mounts.get('stdout', '{}')), 'units': {},
            'processes': [{'pid': int(p.split()[0]), 'comm': p.split()[1]} for p in processes.get('stdout', '').splitlines() if len(p.split()) == 2],
            'root': {'status': 'unavailable'}, 'wifi': run(['/usr/bin/nmcli', 'radio', 'wifi']),
            'failed_system_units': run(['/usr/bin/systemctl', '--failed', '--no-pager']),
            'decky_journal': run(['/usr/bin/journalctl', '-b', '-u', 'plugin_loader.service', '-n', '60', '--no-pager', '-o', 'short-monotonic'])}
    for name in ['sshd.service', 'inputplumber.service', 'konkrd.service', 'sddm.service', 'sm8550-fixpad.service', 'plugin_loader.service']:
        data['units'][name] = properties(name)
    data['user_focusfix'] = properties('konkr-focusfix.service', user=True)
    helper = Path('/usr/local/libexec/rp6-devtools-root')
    if helper.is_file():
        root = run(['/usr/bin/sudo', '-n', str(helper), 'snapshot'], timeout=15)
        if root.get('exit') == 0:
            try: data['root'] = json.loads(root['stdout'])
            except ValueError: data['root']['detail'] = 'invalid privileged snapshot'
        else: data['root']['detail'] = root.get('stderr', root.get('error', 'unavailable'))
    data['etc_ssh_enabled_link'] = os.path.islink('/var/lib/overlays/etc/upper/systemd/system/multi-user.target.wants/sshd.service')
    config = Path('/run/user/1000/mangohud-config')
    if config.is_file():
        data['mangohud'] = {'inode': config.stat().st_ino, 'sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
                            'preset': [line for line in config.read_text().splitlines() if line.startswith('preset=')]}
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--save', action='store_true')
    args = parser.parse_args(); data = collect()
    raw = (json.dumps(data, indent=2) + '\n').encode()
    if args.save:
        folder = Path.home()/'.local/state/rp6-devtools'; folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in (data['boot_id'] + '.json', 'latest.json'):
            fd, temp = tempfile.mkstemp(prefix='.snapshot-', dir=folder)
            try:
                with os.fdopen(fd, 'wb') as stream: stream.write(raw)
                os.replace(temp, folder/name)
            finally:
                if os.path.exists(temp): os.unlink(temp)
    print(raw.decode(), end='')


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError) as exc: raise SystemExit(str(exc))
