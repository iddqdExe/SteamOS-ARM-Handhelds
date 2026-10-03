#!/usr/bin/env python3
"""Record RP6 build provenance; source tests never confer hardware acceptance."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import zlib

REPO = Path(__file__).resolve().parents[1]
FORMAT = 'rp6-release-1'
TARGET = {'model': 'Retroid Pocket 6', 'soc': 'SM8550', 'ram_gib': 12, 'media': 'microSD'}
REQUIRED_CHECKS = ('source', 'ci', 'device', 'fresh_image', 'update', 'rollback')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(4 << 20), b''): h.update(chunk)
    return h.hexdigest()


def entry(path):
    info = path.lstat()
    record = {'mode': f'{stat.S_IMODE(info.st_mode):04o}'}
    if path.is_symlink(): record['symlink'] = os.readlink(path)
    elif path.is_file(): record.update(sha256=digest(path), bytes=info.st_size)
    else: raise ValueError(f'not a regular file or symlink: {path.name}')
    return record


def inventory(folder):
    if not folder.is_dir(): return {}
    return {str(p.relative_to(folder)): entry(p) for p in sorted(folder.rglob('*'))
            if p.is_symlink() or p.is_file()}


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args]).decode().rstrip('\n')


def source_record(repo, allow_dirty):
    status = git(repo, 'status', '--porcelain=v1', '--untracked-files=all')
    if status and not allow_dirty: raise ValueError('source tree is dirty; commit or use --allow-dirty for beta only')
    # diff HEAD includes staged changes; ls-files includes untracked and worktree
    # changes even when the staged version differs but current bytes equal HEAD.
    names = sorted(set(git(repo, 'diff', '--name-only', 'HEAD', '-z').split('\0')) |
                   set(git(repo, 'ls-files', '-m', '-o', '--exclude-standard', '-z').split('\0')))
    changes = {name: entry(repo / name) if (repo / name).exists() or (repo / name).is_symlink()
               else {'deleted': True} for name in names if name}
    return {'sha': git(repo, 'rev-parse', 'HEAD'), 'dirty': bool(status),
            'status': status.splitlines(), 'changes': changes}


def kernel_record(path, root):
    spec = importlib.util.spec_from_file_location('release_bootimg', REPO / 'external-and-mods/ufs-install/ufs-bootimg.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    image = helper.BootImg(path.read_bytes())
    if image.id != image.expected_id(): raise ValueError('KERNEL header checksum mismatch')
    raw = zlib.decompressobj(31).decompress(image.kernel) if image.kernel.startswith(b'\x1f\x8b') else image.kernel
    match = re.search(rb'Linux version ([^\s\x00]+)', raw)
    if not match: raise ValueError('cannot identify KERNEL release')
    release = match.group(1).decode('ascii')
    modules = root / 'usr/lib/modules' / release
    if not modules.is_dir() or not any(modules.rglob('*.ko*')):
        raise ValueError(f'missing matching kernel modules: {release}')
    return {'release': release, **entry(path),
            'payload_sha256': hashlib.sha256(image.kernel).hexdigest(),
            'ramdisk_sha256': hashlib.sha256(image.ramdisk).hexdigest()}, inventory(modules)


def validate_recipe(recipe):
    if not re.fullmatch(r'UP-0[1-8]', recipe.get('module', '')): raise ValueError('invalid module ID')
    if not recipe.get('tasks') or any(not re.fullmatch(r'UP-0[1-8]\.\d+', task) for task in recipe['tasks']):
        raise ValueError('task IDs are required')
    if not recipe.get('donors'): raise ValueError('donor provenance is required')
    for donor in recipe['donors']:
        if not re.fullmatch(r'[0-9a-f]{40}', donor.get('sha', '')): raise ValueError('donor must use full commit SHA')
        for key in ('url', 'authors', 'license', 'adaptation'):
            if not donor.get(key): raise ValueError(f'missing donor {key}')
    if not recipe.get('components'): raise ValueError('component versions are required')
    if not recipe.get('inputs'): raise ValueError('checksummed build inputs are required')
    seen = set()
    for item in recipe['inputs']:
        if not item.get('id') or item['id'] in seen: raise ValueError('build input IDs must be unique')
        seen.add(item['id'])
        kind = item.get('kind', 'download')
        if kind == 'local-artifact':
            if not re.fullmatch(r'[0-9a-f]{40}', item.get('source_sha', '')):
                raise ValueError('local artifact source SHA is required')
            name = item.get('artifact_name', '')
            if not name or Path(name).name != name or name in ('.', '..'):
                raise ValueError('local artifact name is required')
            if item.get('url'): raise ValueError('local artifacts must not invent a download URL')
        elif kind == 'download':
            url = item.get('url', '')
            if not url.startswith('https://') or re.search(r'/(?:main|master|latest)(?:[/?#]|$)', url):
                raise ValueError('moving or invalid build input URL')
        else: raise ValueError('unsupported build input kind')
        path = Path(item['path'])
        if path.is_symlink() or not path.is_file(): raise ValueError('input must be a regular file')
        if not re.fullmatch(r'[0-9a-f]{64}', item.get('sha256', '')): raise ValueError('input SHA256 is required')
        if digest(item['path']) != item['sha256']: raise ValueError(f'input checksum mismatch: {item["id"]}')
    transfers = recipe.get('transfers', [])
    if not transfers or any(item.get('decision') not in ('accepted', 'rejected', 'untested') for item in transfers):
        raise ValueError('transfer decisions are required')
    if any(item['decision'] == 'rejected' for item in transfers):
        raise ValueError('rejected transfers cannot be included in a build')


def default_gate(manifest):
    if manifest['source']['dirty']: raise ValueError('dirty source cannot be released as default')
    if any(t['decision'] != 'accepted' for t in manifest['transfers']):
        raise ValueError('default release requires accepted transfers')
    if not manifest.get('rollback', {}).get('backup_id'): raise ValueError('default release requires a rollback backup ID')
    for name in REQUIRED_CHECKS:
        if manifest.get('validation', {}).get(name) != 'passed':
            raise ValueError(f'default release requires passed {name} validation')
        proof = manifest.get('evidence', {}).get(name, {})
        if not re.fullmatch(r'[0-9a-f]{64}', proof.get('sha256', '')):
            raise ValueError(f'default release requires checksummed {name} evidence')


def create(repo, root, kernel, recipe, channel='beta-opt-in', allow_dirty=False):
    validate_recipe(recipe)
    source = source_record(repo, allow_dirty)
    boot, modules = kernel_record(kernel, root)
    tracked = git(repo, 'ls-files', '-z').split('\0')
    patches = {name: entry(repo / name) for name in tracked if name.endswith('.patch') and (repo / name).exists()}
    paths = ('usr/bin/inputplumber', 'usr/bin/gamescope', 'usr/bin/mangoapp', 'usr/local/bin/box64',
             'usr/lib/libvulkan_freedreno.so', 'usr/lib/steamos/gamescope-session',
             'usr/share/konkr-update/konkr-update.py', 'usr/lib/os-release', 'etc/os-release')
    runtime = {name: entry(root / name) for name in paths if (root / name).is_file() or (root / name).is_symlink()}
    manifest = {'format': FORMAT, 'module': recipe['module'], 'tasks': recipe['tasks'], 'target': TARGET,
                'channel': channel, 'decision': 'untested', 'source': source,
                'donors': recipe['donors'], 'components': recipe['components'],
                'inputs': [{key: item[key] for key in ('id', 'url', 'sha256', 'kind', 'source_sha', 'artifact_name')
                            if key in item} for item in recipe['inputs']],
                'kernel': boot, 'modules': modules, 'firmware': inventory(root / 'usr/lib/firmware'),
                'patches': patches, 'runtime': runtime, 'transfers': recipe['transfers'],
                'validation': recipe.get('validation', {}), 'rollback': recipe.get('rollback', {}),
                'toolchain': {'python': platform.python_version(), 'architecture': platform.machine(),
                              **recipe.get('toolchain', {})}, 'evidence': {}}
    if 'assembly' in recipe: manifest['assembly'] = recipe['assembly']
    for name, proof in recipe.get('evidence', {}).items():
        if digest(proof['path']) != proof['sha256']: raise ValueError(f'evidence checksum mismatch: {name}')
        manifest['evidence'][name] = {'sha256': proof['sha256'], 'name': Path(proof['path']).name}
    if channel == 'default':
        default_gate(manifest); manifest['decision'] = 'accepted'
    return manifest


def save(path, data):
    if path.exists(): raise ValueError('output already exists')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidentally replacing a previously verified artifact.
    with path.open('x') as handle: handle.write(json.dumps(data, indent=2, sort_keys=True) + '\n')


def output_artifact(path):
    # Filesystem inventory records links; a release artifact must have hashed bytes.
    if path.is_symlink() or not path.is_file(): raise ValueError('output artifact must be a regular file: ' + path.name)
    return {'name': path.name, **entry(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    p = commands.add_parser('create')
    for name in ('rootfs', 'kernel', 'recipe', 'output'): p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--repo', type=Path, default=REPO)
    p.add_argument('--allow-dirty', action='store_true')
    p.add_argument('--channel', choices=('beta-opt-in', 'default'), default='beta-opt-in')
    p = commands.add_parser('finalize')
    for name in ('manifest', 'image', 'output'): p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--package', type=Path)
    args = parser.parse_args()
    try:
        if args.output.exists(): raise ValueError('output already exists')
        if args.command == 'create':
            data = create(args.repo, args.rootfs, args.kernel, json.loads(args.recipe.read_text()), args.channel, args.allow_dirty)
        else:
            data = json.loads(args.manifest.read_text())
            if data.get('format') != FORMAT: raise ValueError('unsupported release manifest')
            data['build_manifest_sha256'] = digest(args.manifest)
            data['outputs'] = {'image': output_artifact(args.image)}
            if args.package: data['outputs']['package'] = output_artifact(args.package)
        save(args.output, data)
        print(args.output)
    except (ValueError, OSError, KeyError, zlib.error, subprocess.CalledProcessError) as error:
        print('ERROR:', error, file=sys.stderr); return 1
    return 0


if __name__ == '__main__': sys.exit(main())
