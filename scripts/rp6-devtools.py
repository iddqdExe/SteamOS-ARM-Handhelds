#!/usr/bin/env python3
"""Opt-in RP6 development tools over an explicitly pinned SSH connection."""
import argparse
import base64
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

FILES = Path(__file__).with_name('rp6-devtools')
ACTIONS = ('snapshot', 'enable-ssh', 'restart-decky', 'restart-konkrd', 'reboot')


def ssh_command(profile):
    host, user = profile['host'], profile.get('user', 'steamos')
    if not isinstance(host, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', host):
        raise ValueError('Invalid SSH host')
    if user != 'steamos': raise ValueError('Only steamos development account is supported')
    key = Path(profile['key']).expanduser().resolve()
    hosts = Path(profile['known_hosts']).expanduser().resolve()
    if not key.is_file() or not hosts.is_file(): raise ValueError('Key and pinned known_hosts files are required')
    return ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
            '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={hosts}',
            '-o', 'IdentitiesOnly=yes', '-i', str(key), f'{user}@{host}', 'python3', '-']


def remote(profile, source):
    result = subprocess.run(ssh_command(profile), input=source, text=True,
                            capture_output=True, timeout=60)
    if result.returncode: raise ValueError(f'SSH operation failed ({result.returncode}): {result.stderr[-1500:]}')
    return json.loads(result.stdout)


def write_owned(path, data, mode):
    path = Path(path)
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError(f'Refusing symlinked path: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.stat().st_uid != os.getuid() or path.read_bytes() != data:
            raise ValueError(f'Existing file differs; inspect it before replacement: {path}')
        os.chmod(path, mode)
        return
    fd, temporary = tempfile.mkstemp(prefix='.rp6-devtools-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def load_boot_report(path, current_boot_id):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or not current_boot_id or data.get('boot_id') != current_boot_id:
        raise ValueError('Saved boot report is stale; inspect the snapshot timer in the current boot')
    return data


def wait_for_new_boot(previous, probe, timeout=90, delay=2):
    deadline = time.monotonic() + timeout
    last_error = ''
    while time.monotonic() < deadline:
        try:
            data = probe()
            if isinstance(data, dict) and data.get('boot_id') and data['boot_id'] != previous:
                return data
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            last_error = str(exc)
        time.sleep(min(delay, max(0, deadline - time.monotonic())))
    raise TimeoutError(f'No new boot ID observed after reboot: {last_error}')


def reboot(profile):
    probe_source = 'import json\nfrom pathlib import Path\nprint(json.dumps({"boot_id":Path("/proc/sys/kernel/random/boot_id").read_text().strip(),"model":Path("/sys/firmware/devicetree/base/model").read_text().rstrip("\\x00\\n")}))\n'
    before = remote(profile, probe_source)
    if before.get('model') != 'Retroid Pocket 6' or not before.get('boot_id'):
        raise ValueError('RP6 identity and boot ID required before reboot')
    source = 'import subprocess,sys\np=subprocess.run(["sudo","-n","-k","/usr/local/libexec/rp6-devtools-root","reboot"],capture_output=True,text=True,timeout=30)\nprint(p.stdout,end="")\nprint(p.stderr,end="",file=sys.stderr)\nraise SystemExit(p.returncode)\n'
    request = subprocess.run(ssh_command(profile), input=source, text=True, capture_output=True, timeout=40)
    if request.returncode not in (0, 255):
        raise ValueError(f'Reboot request failed: {request.stderr[-1500:]}')
    after = wait_for_new_boot(before['boot_id'], lambda: remote(profile, probe_source))
    if after.get('model') != 'Retroid Pocket 6': raise ValueError('Unexpected device after reboot')
    return {'action': 'reboot', 'status': 'verified_new_boot',
            'previous_boot_id': before['boot_id'], 'boot_id': after['boot_id']}


def assess(data, expected_kernel=None):
    checks = {}
    try:
        checks['rp6_identity'] = data['model'] == 'Retroid Pocket 6' and data['mem_total_kib'] >= 11 * 1024 * 1024
        mounts = data['mounts']['filesystems']
        def has_etc(entries):
            return any((m.get('target') == '/etc' and m.get('fstype') == 'overlay') or has_etc(m.get('children', [])) for m in entries)
        checks['etc_overlay_mounted'] = has_etc(mounts)
        for unit in ['sshd.service', 'inputplumber.service', 'konkrd.service',
                     'sddm.service', 'sm8550-fixpad.service', 'plugin_loader.service']:
            checks[unit] = data['units'][unit]['ActiveState'] == 'active'
        checks['ssh_enabled'] = data['units']['sshd.service']['UnitFileState'] == 'enabled'
        checks['one_loader'] = sum(p['comm'] == 'PluginLoader' for p in data['processes']) == 1
        if any(p['comm'] in ('gamescope', 'gamescope-wl') for p in data['processes']):
            checks['focusfix_in_game_mode'] = data['user_focusfix']['ActiveState'] == 'active'
        privileged = data.get('root', {}).get('status') == 'available'
        if privileged:
            checks['boot_readable'] = bool(re.fullmatch(r'[0-9a-f]{64}', data['root'].get('kernel_sha256', '')))
            if expected_kernel: checks['expected_kernel'] = data['root'].get('kernel_sha256') == expected_kernel
        status = 'fail' if not all(checks.values()) else ('pass_system_checks' if privileged else 'limited')
    except (KeyError, TypeError, AttributeError):
        status = 'fail'; checks['valid_snapshot'] = False
    return {'status': status, 'checks': checks,
            'scope': 'System observations only; visual/game/input/suspend acceptance remains separate.'}


def stage(profile):
    files = {f.name: base64.b64encode(f.read_bytes()).decode() for f in FILES.iterdir() if f.is_file()}
    service = '[Unit]\nDescription=RP6 development boot snapshot\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 -I %h/.local/lib/rp6-devtools/snapshot.py --save\nTimeoutStartSec=180\n'
    timer = '[Unit]\nDescription=Capture RP6 diagnostics once after user manager starts\n[Timer]\nOnStartupSec=45\nAccuracySec=5\nUnit=rp6-devtools-snapshot.service\n[Install]\nWantedBy=timers.target\n'
    source = 'import base64,json,os,tempfile,subprocess\nfrom pathlib import Path\n' + inspect.getsource(write_owned)
    source += '\nmodel=Path("/sys/firmware/devicetree/base/model").read_text().rstrip("\\x00\\n")\n'
    source += 'if model != "Retroid Pocket 6" or os.getuid()!=1000 or Path.home()!=Path("/home/steamos"): raise SystemExit("RP6 steamos account required")\n'
    source += f'files=json.loads({json.dumps(json.dumps(files))})\n'
    source += 'folder=Path.home()/".local/lib/rp6-devtools"\n'
    source += 'for name,data in files.items(): write_owned(folder/name,base64.b64decode(data),0o700 if name.endswith(".sh") else 0o600)\n'
    for name, content in [('service', service), ('timer', timer)]:
        source += f'write_owned(Path.home()/".config/systemd/user/rp6-devtools-snapshot.{name}",{content.encode()!r},0o600)\n'
    source += 'os.environ["XDG_RUNTIME_DIR"]="/run/user/1000"\nos.environ["DBUS_SESSION_BUS_ADDRESS"]="unix:path=/run/user/1000/bus"\n'
    source += 'subprocess.run(["systemd-analyze","--user","verify",str(Path.home()/".config/systemd/user/rp6-devtools-snapshot.service"),str(Path.home()/".config/systemd/user/rp6-devtools-snapshot.timer")],check=True,stdout=subprocess.DEVNULL)\n'
    source += 'subprocess.run(["systemctl","--user","daemon-reload"],check=True)\nsubprocess.run(["systemctl","--user","enable","--now","rp6-devtools-snapshot.timer"],check=True,stdout=subprocess.DEVNULL)\n'
    source += 'print(json.dumps({"staged":str(folder),"user_timer":"enabled","root_install":"sudo /usr/bin/bash /home/steamos/.local/lib/rp6-devtools/install-root.sh"}))\n'
    return remote(profile, source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--output', type=Path)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('snapshot'); sub.add_parser('stage'); sub.add_parser('boot-report')
    sub.add_parser('action').add_argument('action', choices=ACTIONS)
    sub.add_parser('report').add_argument('file', type=Path)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text()) if args.profile else {}
    if args.command == 'report':
        result = assess(json.loads(args.file.read_text()), profile.get('expected_kernel_sha256'))
    else:
        if not profile: parser.error('--profile is required for SSH operations')
        if args.command == 'stage': result = stage(profile)
        elif args.command == 'snapshot':
            result = remote(profile, (FILES/'snapshot.py').read_text())
            result['assessment'] = assess(result, profile.get('expected_kernel_sha256'))
        elif args.command == 'boot-report':
            source = 'import json\nfrom pathlib import Path\n' + inspect.getsource(load_boot_report)
            source += '\nboot=Path("/proc/sys/kernel/random/boot_id").read_text().strip()\n'
            source += 'print(json.dumps(load_boot_report(Path.home()/".local/state/rp6-devtools/latest.json",boot)))\n'
            result = remote(profile, source)
            result['assessment'] = assess(result, profile.get('expected_kernel_sha256'))
        elif args.command == 'action' and args.action == 'reboot':
            result = reboot(profile)
        else:
            source = f'import subprocess\np=subprocess.run(["sudo","-n","-k","/usr/local/libexec/rp6-devtools-root",{args.action!r}],text=True,capture_output=True,timeout=30)\n'
            source += 'print(p.stdout,end="")\nraise SystemExit(p.returncode)\n'
            result = remote(profile, source)
    encoded = (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode()
    if args.output: write_owned(args.output, encoded, 0o600)
    print(encoded.decode(), end='')
    if result.get('status', result.get('assessment', {}).get('status')) == 'fail': raise SystemExit(1)


if __name__ == '__main__':
    try: main()
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc: raise SystemExit(str(exc))
