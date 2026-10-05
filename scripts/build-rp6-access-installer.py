#!/usr/bin/env python3
"""Produce a self-contained, public-key-only installer for a verified RP6."""
import argparse
import base64
import hashlib
import importlib.util
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[1]


def build(public_key, fingerprint=None, *, kernel_sha256=None):
    spec = importlib.util.spec_from_file_location('access_restore', REPO / 'scripts/rp6-access-restore.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    key = module.validate_key(public_key)
    if (fingerprint is None) == (kernel_sha256 is None):
        raise ValueError('choose a pinned host fingerprint or a fresh-install kernel SHA256')
    if fingerprint is not None and not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', fingerprint):
        raise ValueError('invalid host fingerprint')
    if kernel_sha256 is not None and not re.fullmatch(r'[0-9a-f]{64}', kernel_sha256):
        raise ValueError('invalid fresh-install kernel SHA256')
    payload = {
        '/usr/lib/steamos-arm/rp6-access-restore.py': ((REPO / 'scripts/rp6-access-restore.py').read_bytes(), '0755'),
        '/usr/share/steamos-arm/access/codex.pub': ((key + '\n').encode(), '0644'),
        '/usr/lib/systemd/system/rp6-codex-access.service': ((REPO / 'sm8550-overlay/usr/lib/systemd/system/rp6-codex-access.service').read_bytes(), '0644'),
        '/usr/lib/systemd/system/rp6-codex-access.timer': ((REPO / 'sm8550-overlay/usr/lib/systemd/system/rp6-codex-access.timer').read_bytes(), '0644'),
        '/etc/systemd/system/sshd.service.d/30-rp6-recovery.conf': (b'[Service]\nRestart=on-failure\nRestartSec=3s\n', '0644'),
        '/etc/systemd/journald.conf.d/zz-rp6-debug.conf': (b'[Journal]\nStorage=persistent\nSystemMaxUse=96M\nRuntimeMaxUse=32M\n', '0644'),
        '/usr/lib/steamos-arm/measure-rp6-touch.py': ((REPO / 'scripts/measure-rp6-touch.py').read_bytes(), '0755'),
        '/etc/systemd/system/rp6-touch-debug.service': (b'[Unit]\nDescription=RP6 touch timing (no input grab)\nConditionPathIsMountPoint=/boot\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 -I /usr/lib/steamos-arm/measure-rp6-touch.py --seconds 30 --output /boot/debug-logs/up02-touch.json\nTimeoutStartSec=45\nNice=10\n', '0644'),
        '/etc/systemd/system/rp6-touch-debug.timer': (b'[Unit]\nDescription=Periodic RP6 touch diagnostics\n[Timer]\nOnBootSec=90\nOnUnitInactiveSec=5min\n[Install]\nWantedBy=timers.target\n', '0644'),
    }
    script = '''#!/usr/bin/env bash
# RP6 SSH access installer. Contains a PUBLIC client key, never a password.
set -euo pipefail
if (( EUID != 0 )); then exec sudo -- bash "$0" "$@"; fi
for tool in python3 systemctl ssh-keygen runuser nmcli hostnamectl findmnt base64 install sha256sum mktemp awk tr hostname mountpoint mount touch journalctl; do
    command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done
model="$(tr -d '\\000\\n' </proc/device-tree/model)"
case "$model" in 'Retroid Pocket 6'|'Retroid Pocket 6 TOP-DPAD') ;; *) echo "Unsupported device: $model" >&2; exit 1;; esac
@IDENTITY_GATE@
restore_readonly=0
finish() {
    status=$?
    if (( restore_readonly )); then
        steamos-readonly enable || { echo 'Failed to restore read-only state.' >&2; status=1; }
    fi
    exit "$status"
}
trap finish EXIT
mountopts="$(findmnt -n -o OPTIONS -T /usr)"
if [[ ",$mountopts," == *,ro,* ]]; then
    command -v steamos-readonly >/dev/null || { echo 'Cannot unlock read-only system.' >&2; exit 1; }
    restore_readonly=1
    steamos-readonly disable
fi
workspace="$(mktemp -d /run/rp6-access.XXXXXXXX)"
trap 'rm -rf -- "$workspace"; finish' EXIT
'''
    if fingerprint is not None:
        gate = '''[[ -f /etc/ssh/ssh_host_ed25519_key.pub ]] || { echo 'Enable SSH in SteamOS first.' >&2; exit 1; }
actual="$(ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256 | awk '{print $2}')"
expected='@FINGERPRINT@'
printf 'RP6 SSH host fingerprint: %s\\n' "$actual"
[[ "$actual" == "$expected" ]] || { echo 'Host identity differs. Send the fingerprint above before continuing.' >&2; exit 1; }
'''.replace('@FINGERPRINT@', fingerprint)
    else:
        gate = '''mountpoint -q /boot || mount /boot
printf '%s  %s\\n' '@KERNEL_SHA256@' /boot/KERNEL | sha256sum -c -
echo 'Fresh-install image matched. The new SSH fingerprint will be shown below.'
'''.replace('@KERNEL_SHA256@', kernel_sha256)
    script = script.replace('@IDENTITY_GATE@', gate)
    for index, (target, (data, mode)) in enumerate(payload.items()):
        encoded = base64.b64encode(data).decode()
        parent = str(Path(target).parent)
        script += f'''mkdir -p '{parent}'
[[ ! -L '{parent}' && ! -L '{target}' ]] || {{ echo 'Refusing symbolic link: {target}' >&2; exit 1; }}
base64 -d >"$workspace/{index}" <<'RP6_PAYLOAD_{index}'
{encoded}
RP6_PAYLOAD_{index}
printf '%s  %s\\n' '{hashlib.sha256(data).hexdigest()}' "$workspace/{index}" | sha256sum -c - >/dev/null
install -o root -g root -m {mode} "$workspace/{index}" '{target}'
'''
    script += '''mkdir -p /var/log/journal
systemctl daemon-reload
/usr/bin/python3 -I /usr/lib/steamos-arm/rp6-access-restore.py --configure
systemctl enable --now rp6-codex-access.service rp6-codex-access.timer
systemctl enable --now rp6-touch-debug.timer
systemctl restart systemd-journald.service
journalctl --flush
systemctl is-active --quiet sshd.service
mountpoint -q /boot || mount /boot
touch /boot/debug
if systemctl cat steamos-arm-bootdebug.service >/dev/null 2>&1; then
    systemctl start steamos-arm-bootdebug.service
else
    systemctl start steamos-arm-bootdebug-file.service
fi
actual="$(ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256 | awk '{print $2}')"
echo
echo 'READY: SSH access and automatic recovery enabled; diagnostics remain enabled.'
echo 'Address: rp6-steamos.local (same local network).'
printf 'SSH fingerprint to verify from this device: %s\\n' "$actual"
echo 'Send this fingerprint to Codex to pin the fresh SSH connection.'
echo 'Automatic debug: /boot/debug-logs; persistent journal: 96 MiB maximum.'
'''
    return script


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-key', type=Path, required=True)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument('--host-fingerprint')
    identity.add_argument('--fresh-kernel-sha256')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    script = build(args.public_key.read_text(), args.host_fingerprint, kernel_sha256=args.fresh_kernel_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(script); args.output.chmod(0o755)
    digest = hashlib.sha256(args.output.read_bytes()).hexdigest()
    args.output.with_suffix(args.output.suffix + '.sha256').write_text(digest + '  ' + args.output.name + '\n')
    print(str(args.output)); print('SHA256: ' + digest)


if __name__ == '__main__': main()
