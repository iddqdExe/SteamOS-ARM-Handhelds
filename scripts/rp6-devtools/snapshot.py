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


def run(args, timeout=10, deadline=None):
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
        if timeout <= 0: return {'error': 'Snapshot deadline exhausted'}
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {'exit': p.returncode, 'stdout': p.stdout[-16000:], 'stderr': p.stderr[-1200:]}
    except (OSError, subprocess.TimeoutExpired) as exc: return {'error': str(exc)}


def properties(unit, user=False, deadline=None):
    command = ['/usr/bin/systemctl'] + (['--user'] if user else [])
    output = run(command + ['show', unit, '-p', 'ActiveState', '-p', 'SubState', '-p', 'UnitFileState', '-p', 'MainPID', '-p', 'Result'], deadline=deadline)
    return dict(line.split('=', 1) for line in output.get('stdout', '').splitlines() if '=' in line)


def collect(deadline=None):
    model = Path('/sys/firmware/devicetree/base/model').read_text().rstrip('\x00\n')
    if model != 'Retroid Pocket 6': raise ValueError('Retroid Pocket 6 required')
    os.environ.setdefault('XDG_RUNTIME_DIR', '/run/user/1000')
    os.environ.setdefault('DBUS_SESSION_BUS_ADDRESS', 'unix:path=/run/user/1000/bus')
    mounts = run(['/usr/bin/findmnt', '--json', '-t', 'ext4,overlay,vfat', '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS'], deadline=deadline)
    processes = run(['/usr/bin/ps', '-C', 'PluginLoader,gamescope,gamescope-wl,konkr-focusfix', '-o', 'pid=,comm='], deadline=deadline)
    data = {'model': model, 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'collected_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'uptime_seconds': float(Path('/proc/uptime').read_text().split()[0]),
            'mem_total_kib': int(Path('/proc/meminfo').read_text().splitlines()[0].split()[1]),
            'kernel_release': run(['/usr/bin/uname', '-r'], deadline=deadline).get('stdout', '').strip(),
            'mounts': json.loads(mounts.get('stdout', '{}')), 'units': {},
            'processes': [{'pid': int(p.split()[0]), 'comm': p.split()[1]} for p in processes.get('stdout', '').splitlines() if len(p.split()) == 2],
            'root': {'status': 'unavailable'}, 'wifi': run(['/usr/bin/nmcli', 'radio', 'wifi'], deadline=deadline),
            'failed_system_units': run(['/usr/bin/systemctl', '--failed', '--no-pager'], deadline=deadline),
            'decky_journal': run(['/usr/bin/journalctl', '-b', '-u', 'plugin_loader.service', '-n', '60', '--no-pager', '-o', 'short-monotonic'], deadline=deadline)}
    for name in ['sshd.service', 'inputplumber.service', 'konkrd.service', 'sddm.service', 'sm8550-fixpad.service', 'plugin_loader.service']:
        data['units'][name] = properties(name, deadline=deadline)
    data['user_focusfix'] = properties('konkr-focusfix.service', user=True, deadline=deadline)
    helper = Path('/usr/local/libexec/rp6-devtools-root')
    if helper.is_file():
        root = run(['/usr/bin/sudo', '-n', '-k', str(helper), 'snapshot'], timeout=15, deadline=deadline)
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


def collect_startup(probe, timeout=90, delay=2):
    started = time.monotonic(); deadline = started + timeout
    data = probe(deadline); initial = None
    while True:
        waiting = [name for name, unit in data['units'].items() if unit.get('ActiveState') != 'active']
        if sum(p['comm'] == 'PluginLoader' for p in data['processes']) != 1:
            waiting.append('one_loader')
        if any(p['comm'] in ('gamescope', 'gamescope-wl') for p in data['processes']):
            if data['user_focusfix'].get('ActiveState') != 'active': waiting.append('focusfix_in_game_mode')
        if initial is None: initial = list(waiting)
        if not waiting or time.monotonic() >= deadline: break
        time.sleep(min(delay, max(0, deadline - time.monotonic())))
        data = probe(deadline)
    data['startup_wait'] = {'status': 'timeout' if waiting else 'ready',
                            'elapsed_seconds': round(time.monotonic() - started, 2),
                            'initial_not_ready': initial, 'final_not_ready': waiting}
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--save', action='store_true')
    args = parser.parse_args(); data = collect_startup(collect) if args.save else collect()
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
