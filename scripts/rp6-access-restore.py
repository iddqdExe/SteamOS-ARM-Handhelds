#!/usr/bin/env python3
"""Restore explicitly provisioned RP6 SSH access without passwords or root login."""
import argparse
import base64
import os
from pathlib import Path
import pwd
import secrets
import shutil
import stat
import struct
import subprocess

KEYFILE = Path('/usr/share/steamos-arm/access/codex.pub')
HELPER = '/usr/lib/steamos-arm/rp6-access-restore.py'
CONFIGURED = Path('/var/lib/steamos-arm/access-configured')
OPTIONS = 'no-agent-forwarding,no-X11-forwarding,no-port-forwarding'


def validate_key(key):
    if '\n' in key.strip() or '\r' in key or '\x00' in key:
        raise ValueError('one public key required')
    parts = key.strip().split()
    if len(parts) < 2 or parts[0] != 'ssh-ed25519':
        raise ValueError('plain Ed25519 public key required')
    try:
        raw = base64.b64decode(parts[1], validate=True)
        if len(raw) != 51 or raw[:19] != struct.pack('>I', 11) + b'ssh-ed25519' + struct.pack('>I', 32):
            raise ValueError('invalid Ed25519 public key')
    except (ValueError, __import__('binascii').Error) as exc:
        raise ValueError('invalid Ed25519 public key') from exc
    return ' '.join(parts)


def install_key(home, key):
    key = validate_key(key)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    homefd = os.open(home, flags)
    folderfd = None
    temporary = None
    try:
        try: os.mkdir('.ssh', 0o700, dir_fd=homefd)
        except FileExistsError: pass
        folderfd = os.open('.ssh', flags, dir_fd=homefd)
        os.fchmod(folderfd, 0o700)
        existing = b''
        try:
            fd = os.open('authorized_keys', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folderfd)
        except FileNotFoundError: fd = None
        if fd is not None:
            with os.fdopen(fd, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError('authorized_keys must be a regular file')
                os.fchmod(stream.fileno(), 0o600)
                existing = stream.read(1024 * 1024 + 1)
            if len(existing) > 1024 * 1024: raise ValueError('authorized_keys too large')
        line = (OPTIONS + ' ' + key).encode()
        # Match the whole provisioned line; unrelated user keys are preserved.
        if line in existing.splitlines(): return
        content = existing + (b'\n' if existing and not existing.endswith(b'\n') else b'') + line + b'\n'
        temporary = '.rp6-key-' + secrets.token_hex(12)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folderfd)
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, 'authorized_keys', src_dir_fd=folderfd, dst_dir_fd=folderfd)
        temporary = None
        os.fsync(folderfd)
    finally:
        if temporary is not None and folderfd is not None: os.unlink(temporary, dir_fd=folderfd)
        if folderfd is not None: os.close(folderfd)
        os.close(homefd)


def run(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True, timeout=20)


def protected_write(path, text):
    """Write this service's own root configuration, rejecting redirected paths."""
    path = Path(path)
    # Create each missing parent only below a verified root-owned directory.
    current = Path('/')
    for part in path.parent.parts[1:]:
        current /= part
        current.mkdir(exist_ok=True)
        if current.is_symlink() or current.stat().st_uid != 0 or current.stat().st_mode & 0o022:
            raise ValueError('unsafe system directory: ' + str(current))
    if path.is_symlink(): raise ValueError('unsafe system file: ' + str(path))
    if path.exists() and (not path.is_file() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022):
        raise ValueError('unsafe system file: ' + str(path))
    if path.exists() and path.read_text() == text: return
    temporary = path.with_name('.rp6-' + secrets.token_hex(12))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), 0o644); stream.write(text)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists(): temporary.unlink()


def restore(configure=False):
    if os.geteuid() != 0: raise ValueError('root required for system configuration')
    model = Path('/proc/device-tree/model').read_text().rstrip('\x00\n')
    if model not in ('Retroid Pocket 6', 'Retroid Pocket 6 TOP-DPAD'):
        raise ValueError('this installer supports Retroid Pocket 6 only: ' + model)
    user = pwd.getpwnam('steamos')
    if user.pw_uid == 0 or user.pw_dir != '/home/steamos': raise ValueError('unexpected steamos account')
    if KEYFILE.is_symlink() or not KEYFILE.is_file() or KEYFILE.stat().st_uid != 0 or KEYFILE.stat().st_mode & 0o022:
        raise ValueError('public key must be a protected root-owned regular file')
    key = validate_key(KEYFILE.read_text())
    # User-controlled HOME is written with that user's permissions, never root's.
    run('runuser', '-u', 'steamos', '--', '/usr/bin/python3', '-I', HELPER, '--install-key', key)
    sshd = shutil.which('sshd')
    if not sshd: raise ValueError('OpenSSH server is missing')
    # Fresh images have no host keys; -A preserves every existing server key.
    run('ssh-keygen', '-A')
    run(sshd, '-t')
    configure = configure or not CONFIGURED.exists()
    if configure:
        protected_write('/etc/systemd/system/sshd.service.d/30-rp6-recovery.conf', '[Service]\nRestart=on-failure\nRestartSec=3s\n')
        protected_write('/etc/systemd/journald.conf.d/30-rp6-debug.conf', '[Journal]\nStorage=persistent\nSystemMaxUse=96M\nRuntimeMaxUse=32M\n')
        run('systemctl', 'daemon-reload')
        run('hostnamectl', 'set-hostname', 'rp6-steamos')
        run('systemctl', 'enable', 'sshd.service')
        if run('systemctl', 'cat', 'avahi-daemon.service', check=False).returncode == 0:
            run('systemctl', 'enable', 'avahi-daemon.service')
        # Keep the existing Wi-Fi credentials and reconnect only its current profile.
        active = run('nmcli', '-t', '-f', 'UUID,TYPE', 'connection', 'show', '--active')
        for line in active.stdout.splitlines():
            uuid, kind = line.split(':', 1)
            if kind in ('802-11-wireless', 'wifi'):
                run('nmcli', 'connection', 'modify', uuid, 'connection.autoconnect', 'yes')
        run('systemctl', 'restart', 'systemd-journald.service')
        run('journalctl', '--flush')
        protected_write(CONFIGURED, 'RP6 SSH access configured\n')
    for unit in ('sshd.service', 'avahi-daemon.service'):
        if run('systemctl', 'cat', unit, check=False).returncode != 0: continue
        if run('systemctl', 'is-active', '--quiet', unit, check=False).returncode != 0:
            run('systemctl', 'reset-failed', unit, check=False)
            run('systemctl', 'start', '--no-block', unit)
    fingerprint = run('ssh-keygen', '-lf', '/etc/ssh/ssh_host_ed25519_key.pub', '-E', 'sha256').stdout.strip()
    addresses = run('hostname', '-I', check=False).stdout.strip()
    print('RP6 access restored; hostname=rp6-steamos.local; addresses=' + addresses)
    print('SSH host key: ' + fingerprint)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-key'); parser.add_argument('--configure', action='store_true')
    args = parser.parse_args()
    if args.install_key:
        user = pwd.getpwnam('steamos')
        if os.geteuid() != user.pw_uid or user.pw_uid == 0: raise ValueError('key installation must run as steamos')
        install_key(Path(user.pw_dir), args.install_key)
    else: restore(args.configure)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc: raise SystemExit(str(exc))
