#!/usr/bin/env python3
"""Merge two RP6 defaults; retain remaps and offer guarded configuration rollback."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

FILES = ('devices.d/02-retroid-pocket.yaml', 'capability_maps.d/retroid_mcu.yaml')
# Exact defaults shipped before receipts were consistently available (c7a3a2b).
# Never normalize YAML here: even a comment edit remains a user customization.
LEGACY_DEFAULTS = {
    FILES[0]: {'2a6b339445efffb9f676472ed65aa3bf80b147ebe55a31810d5b4cf9a25f9539'},
    FILES[1]: {'b0eefc986b6b4e4011c137b1eb29ad3a3d7caefdd49f4a10b30262dff1e25e8b'},
}
UPPER = 'var/lib/overlays/etc/upper'
STATE = 'var/lib/rp6-input'
RECEIPT = STATE + '/managed.json'
BACKUP = STATE + '/last-update.json'
ACTIVE = tuple('etc/inputplumber/' + name for name in FILES) + tuple(
    UPPER + '/inputplumber/' + name for name in FILES)
CANONICAL = tuple('usr/share/rp6-input/defaults/' + name for name in FILES) + (
    'usr/share/inputplumber/capability_maps/retroid_mcu.yaml',)
ALLOWED = set(ACTIVE + CANONICAL + (RECEIPT,))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(root, relative):
    # Never follow target-root links using the host's filesystem semantics.
    path = root
    for part in Path(relative).parts:
        if part in ('..', '/', ''):
            raise ValueError('unsafe configuration path')
        path = path / part
        if path.is_symlink():
            raise ValueError(f'symlink configuration destination: {relative}')
        if path != root / relative and path.exists() and not path.is_dir():
            raise ValueError(f'configuration parent is not a directory: {relative}')
    if path.exists() and not path.is_file():
        raise ValueError(f'configuration destination is not a file: {relative}')
    return path


def current(path):
    return path.read_bytes() if path.exists() else None


def atomic(path, data, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(name, mode)
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(name): os.unlink(name)


def encoded(data):
    return None if data is None else base64.b64encode(data).decode('ascii')


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def install(root, source):
    # Validate every destination before changing any file, including state paths.
    paths = {rel: safe_path(root, rel) for rel in ALLOWED | {BACKUP}}
    prior = current(paths[RECEIPT])
    receipt = json.loads(prior) if prior else {'format': 1, 'defaults': {}}
    if receipt.get('format') != 1 or not isinstance(receipt.get('defaults'), dict):
        raise ValueError('unsupported RP6 configuration receipt')
    if paths[BACKUP].exists() and json.loads(paths[BACKUP].read_bytes()).get('phase') != 'complete':
        raise ValueError('unfinished configuration update; run --rollback first')
    defaults = {name: (source / name).read_bytes() for name in FILES}
    desired = {'usr/share/rp6-input/defaults/' + name: data for name, data in defaults.items()}
    desired[CANONICAL[-1]] = defaults[FILES[1]]
    managed = dict(receipt['defaults'])
    for rel in ACTIVE:
        if rel.startswith(UPPER + '/') and not (root / UPPER).exists(): continue
        name = rel.split('inputplumber/', 1)[1]
        data = defaults[name]; old = current(paths[rel])
        if rel.startswith(UPPER + '/') and old is None:
            lower = 'etc/inputplumber/' + name
            if lower not in desired:
                # An absent upper means the user's lower configuration is active.
                print(f'preserved customized lower configuration: /{lower}')
                continue
        old_hash = sha(old) if old is not None else None
        if old is None or old == data or old_hash == managed.get(rel) or old_hash in LEGACY_DEFAULTS[name]:
            desired[rel] = data
        else:
            print(f'preserved customized configuration: /{rel}')
        managed[rel] = sha(data)
    desired[RECEIPT] = json_bytes({'format': 1, 'defaults': managed})
    changes = []
    for rel, data in desired.items():
        old = current(paths[rel])
        if old == data: continue
        changes.append({'path': rel, 'before': encoded(old), 'after': sha(data),
                        'mode': paths[rel].stat().st_mode & 0o777 if old is not None else 0o644})
    if not changes:
        print('RP6 defaults already current'); return
    backup = {'format': 1, 'phase': 'prepared', 'changes': changes}
    paths[BACKUP].parent.mkdir(parents=True, exist_ok=True)
    os.chmod(paths[BACKUP].parent, 0o700)
    atomic(paths[BACKUP], json_bytes(backup), 0o600)
    for change in changes:
        rel = change['path']
        atomic(paths[rel], desired[rel], 0o600 if rel == RECEIPT else change['mode'])
        print(f'installed RP6 default: /{rel}')
    backup['phase'] = 'complete'
    atomic(paths[BACKUP], json_bytes(backup), 0o600)


def rollback(root):
    path = safe_path(root, BACKUP)
    record = json.loads(path.read_bytes())
    if record.get('format') != 1 or record.get('phase') not in ('prepared', 'complete'):
        raise ValueError('unsupported configuration backup')
    checked = []; seen = set()
    for change in record['changes']:
        rel = change['path']
        if rel not in ALLOWED or rel in seen: raise ValueError('invalid backup path')
        seen.add(rel)
        dest = safe_path(root, rel)
        old = None if change['before'] is None else base64.b64decode(change['before'], validate=True)
        now = current(dest)
        if (sha(now) if now is not None else None) != change['after']:
            # An interrupted install may not have written this file yet.
            if record['phase'] != 'prepared' or now != old:
                raise ValueError(f'configuration changed since update: /{rel}')
        checked.append((dest, old, change['mode']))
    # All later edits are checked before restoring the first file.
    record['phase'] = 'prepared'
    atomic(path, json_bytes(record), 0o600)
    for dest, data, mode in reversed(checked):
        if data is None: dest.unlink(missing_ok=True)
        else: atomic(dest, data, mode)
    path.unlink()
    print('Previous RP6 configuration restored')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--source', type=Path)
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    try:
        root = args.root.resolve(strict=True)
        if args.rollback: rollback(root)
        else: install(root, args.source or root / 'usr/share/rp6-input/defaults')
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'ERROR: {error}', file=sys.stderr); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
