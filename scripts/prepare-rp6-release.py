#!/usr/bin/env python3
"""Assemble an offline UP-08 image/package from a sealed accepted UP-01 image.

Linux/root only. Writes regular image files, never a card. The underlying distro
is inherited from the checksummed image, not rebuilt from raw upstream source.
"""
from contextlib import contextmanager
import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile

REPO = Path(__file__).resolve().parents[1]
SIZE = 16447963136
LAYOUT = [(0x0c, 2048, 1048576), (0x83, 1050624, 23939072), (0x83, 24989696, 7135232)]
CHANGES = {'usr/share/konkr-update/konkr-update.py', 'usr/share/steamos-arm/release-manifest.json'}


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


release = load('release_manifest', REPO / 'scripts/build-rp6-release-manifest.py')


def run(*args, **kwargs):
    print('+', ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def validate_base(base, expected):
    if base.is_symlink() or not base.is_file() or base.stat().st_size != SIZE:
        raise ValueError('base must be the regular sealed RP6 image')
    with base.open('rb') as handle: mbr = handle.read(512)
    layout = [(mbr[446 + i * 16 + 4], *struct.unpack_from('<II', mbr, 454 + i * 16)) for i in range(3)]
    if mbr[510:] != b'\x55\xaa' or layout != LAYOUT: raise ValueError('unexpected RP6 partition layout')
    if release.digest(base) != expected: raise ValueError('base SHA256 mismatch')


def output_paths(image, package):
    paths = [image, image.with_name(image.name + '.partial'), package, package.with_name(package.name + '.part'),
             package.with_name(package.name + '.sha256')]
    paths += [image.with_name(image.name + suffix) for suffix in
              ('.build-manifest.json', '.release.json', '.validation.json', '.root-inventory.json.gz', '.sha256')]
    if len({str(p.resolve()) for p in paths}) != len(paths): raise ValueError('output paths overlap')
    if any(p.exists() or p.is_symlink() for p in paths): raise ValueError('output already exists')
    return paths


@contextmanager
def image_mounts(image):
    folder = Path(tempfile.mkdtemp(prefix='rp6-release-')); mounted = []
    try:
        for name, (_, start, size) in zip(('boot', 'root', 'home'), LAYOUT):
            dest = folder / name; dest.mkdir()
            access = 'ro,' if name == 'boot' else 'ro,noload,' if name == 'home' else ''
            run('mount', '-o', f'{access}loop,offset={start * 512},sizelimit={size * 512}', image, dest)
            mounted.append(dest)
        yield tuple(folder / name for name in ('boot', 'root', 'home'))
    finally:
        failures = []
        for dest in reversed(mounted):
            try: run('umount', dest)
            except (OSError, subprocess.CalledProcessError) as error: failures.append(str(error))
        if failures or any(os.path.ismount(folder / name) for name in ('boot', 'root', 'home')):
            raise ValueError(f'could not unmount image; directory retained at {folder}: {failures}')
        shutil.rmtree(folder)


def tree_inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        info = path.lstat()
        record = {'mode': f'{stat.S_IMODE(info.st_mode):04o}', 'uid': info.st_uid, 'gid': info.st_gid,
                  'xattrs': {name: base64.b64encode(os.getxattr(path, name, follow_symlinks=False)).decode()
                            for name in sorted(os.listxattr(path, follow_symlinks=False))}}
        if stat.S_ISREG(info.st_mode): record.update(kind='file', sha256=release.digest(path))
        elif stat.S_ISLNK(info.st_mode): record.update(kind='symlink', link=os.readlink(path))
        elif stat.S_ISDIR(info.st_mode): record.update(kind='directory')
        else: record.update(kind='special', type=stat.S_IFMT(info.st_mode), device=info.st_rdev)
        result[str(path.relative_to(root))] = record
    return result


def assert_delta(before, after):
    changed = {name for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
    unexpected = changed - CHANGES
    if unexpected: raise ValueError('accepted payload changed outside UP-08: ' + ', '.join(sorted(unexpected)[:20]))
    return sorted(changed)


def region_digest(image, start, size):
    h = hashlib.sha256()
    with image.open('rb') as stream:
        stream.seek(start); remaining = size
        while remaining:
            block = stream.read(min(remaining, 4 << 20))
            if not block: raise ValueError('short image region')
            h.update(block); remaining -= len(block)
    return h.hexdigest()


def verify_package_metadata(package, root_inventory, home_inventory):
    """The package builder verifies bytes; additionally verify owners/modes/xattrs."""
    expected = {}
    for name, record in root_inventory.items():
        if any(name == prefix or name.startswith(prefix + '/') for prefix in
               ('usr', 'opt', 'etc', 'var/lib/overlays/etc/upper')): expected['root/' + name] = record
    for name, record in home_inventory.items():
        if any(name == prefix or name.startswith(prefix + '/') for prefix in
               ('homebrew/plugins/konkr-control', 'homebrew/plugins/decky-lsfg-vk', 'homebrew/services')):
            expected['home/steamos/' + name] = record
    checked = set(); capabilities = 0
    with tarfile.open(package) as archive:
        for member in archive:
            name = member.name.rstrip('/'); record = expected.get(name)
            if record is None: continue
            if (f'{member.mode:04o}', member.uid, member.gid) != (record['mode'], record['uid'], record['gid']):
                raise ValueError('package ownership/mode mismatch: ' + name)
            meta = member
            if member.islnk(): meta = archive.getmember(member.linkname)
            attrs = {key.removeprefix('SCHILY.xattr.'): base64.b64encode(value.encode('utf-8', 'surrogateescape')).decode()
                     for key, value in meta.pax_headers.items() if key.startswith('SCHILY.xattr.')}
            if attrs != record['xattrs']: raise ValueError('package xattr mismatch: ' + name)
            if record['kind'] == 'symlink' and (not member.issym() or member.linkname != record['link']):
                raise ValueError('package symlink mismatch: ' + name)
            checked.add(name)
            if 'security.capability' in attrs: capabilities += 1
    if checked != expected.keys(): raise ValueError('package omitted accepted files or directories')
    return {'entries': len(checked), 'capability_files': capabilities, 'ownership_modes_xattrs': 'passed'}


def build(recipe_path, image, package, version):
    paths = output_paths(image, package)
    if not sys.platform.startswith('linux') or os.geteuid() != 0: raise ValueError('Linux/root required')
    recipe = json.loads(recipe_path.read_text())
    assembly = recipe.get('assembly', {})
    if assembly.get('type') != 'sealed-up01-image' or assembly.get('clean_distro_source_build') is not False:
        raise ValueError('explicit sealed UP-01 assembly provenance is required')
    lock = recipe.get('toolchain', {})
    if (not re.fullmatch(r'sha256:[0-9a-f]{64}', lock.get('builder_image', '')) or
            os.environ.get('RP6_BUILDER_IMAGE') != lock['builder_image'] or
            platform.machine() != lock.get('builder_architecture')):
        raise ValueError('builder environment does not match the toolchain lock')
    source = release.source_record(REPO, False)
    if source['sha'] != assembly.get('source_sha'): raise ValueError('assembly source SHA mismatch')
    release.validate_recipe(recipe)
    items = {item['id']: item for item in recipe['inputs']}
    base_input = items[assembly['base_input']]; base = Path(base_input['path'])
    validate_base(base, base_input['sha256'])
    for path in paths: path.parent.mkdir(parents=True, exist_ok=True)
    # BOOT and HOME must remain byte-identical, including the partition table.
    regions = {'table_boot': (0, (LAYOUT[0][1] + LAYOUT[0][2]) * 512),
               'home': (LAYOUT[2][1] * 512, LAYOUT[2][2] * 512)}
    sealed = {name: region_digest(base, *region) for name, region in regions.items()}
    partial = image.with_name(image.name + '.partial')
    run('cp', '--reflink=auto', '--sparse=always', base, partial)
    with image_mounts(partial) as (boot, root, home):
        checker = load('release_session', REPO / 'scripts/check-rp6-session.py')
        delivery = checker.check(root, boot / 'KERNEL', home / 'steamos')
        run('bash', REPO / 'scripts/check-rp6-input.sh', root, boot / 'KERNEL')
        if release.digest(boot / 'KERNEL') != assembly.get('kernel_sha256'):
            raise ValueError('accepted KERNEL SHA256 mismatch')
        print('Inventorying sealed root...', flush=True)
        before = tree_inventory(root)
        updater = root / 'usr/share/konkr-update/konkr-update.py'
        if updater.is_symlink() or not updater.is_file(): raise ValueError('base updater must be a regular file')
        shutil.copyfile(REPO / 'external-and-mods/konkr-update/konkr-update.py', updater)
        manifest = release.create(REPO, root, boot / 'KERNEL', recipe)
        manifest_path = image.with_name(image.name + '.build-manifest.json')
        release.save(manifest_path, manifest)
        marker = root / 'usr/share/steamos-arm/release-manifest.json'
        if marker.is_symlink(): raise ValueError('release marker must not be a symlink')
        shutil.copyfile(manifest_path, marker); marker.chmod(0o644)
        print('Checking accepted root preservation...', flush=True)
        after = tree_inventory(root); delta = assert_delta(before, after)
        inventory_path = image.with_name(image.name + '.root-inventory.json.gz')
        with inventory_path.open('xb') as target:
            with gzip.GzipFile(fileobj=target, mode='wb', mtime=0, filename='') as compressed:
                compressed.write(json.dumps(after, sort_keys=True).encode())
        delivery = checker.check(root, boot / 'KERNEL', home / 'steamos')
        run('bash', REPO / 'scripts/check-rp6-input.sh', root, boot / 'KERNEL')
        home_inventory = tree_inventory(home / 'steamos')
        run('python3', REPO / 'scripts/build-update-package.py', '--rootfs', root, '--home', home / 'steamos',
            '--kernel', boot / 'KERNEL', '--soc', 'sm8550', '--device', 'Retroid Pocket 6',
            '--version', version, '--output', package)
        metadata = verify_package_metadata(package, after, home_inventory)
    for name, region in regions.items():
        if region_digest(partial, *region) != sealed[name]: raise ValueError('accepted image region changed: ' + name)
    filesystems = {}
    for name, (_, start, size) in zip(('boot', 'root', 'home'), LAYOUT):
        loop = subprocess.check_output(['losetup', '--find', '--show', '--read-only', '--offset', str(start * 512),
                                        '--sizelimit', str(size * 512), str(partial)], text=True).strip()
        try:
            run('fsck.fat' if name == 'boot' else 'e2fsck', '-n', loop)
            filesystems[name] = 'passed-read-only'
        finally: run('losetup', '-d', loop)
    os.replace(partial, image)
    final = {**manifest, 'build_manifest_sha256': release.digest(manifest_path),
             'outputs': {'image': release.output_artifact(image), 'package': release.output_artifact(package),
                         'root_inventory': release.output_artifact(inventory_path)}}
    release.save(image.with_name(image.name + '.release.json'), final)
    report = {'source': source, 'assembly': assembly, 'delta': delta, 'root_entries_compared': len(before),
              'delivery': delivery, 'input_preflight': 'passed', 'package_metadata': metadata,
              'preserved_regions': sealed, 'filesystems': filesystems, 'device': 'not-tested'}
    release.save(image.with_name(image.name + '.validation.json'), report)
    image.with_name(image.name + '.sha256').write_text(final['outputs']['image']['sha256'] + '  ' + image.name + '\n')
    print(json.dumps(report, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recipe', type=Path, required=True)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    build(args.recipe, args.image, args.package, args.version)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error: raise SystemExit(str(error))
