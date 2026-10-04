#!/usr/bin/env python3
"""Pair a verified RP6 kernel with sealed accepted userspace (Linux/root only).

Writes new regular image/package files. Never opens a physical card.
"""
from contextlib import contextmanager
import argparse
import gzip
import json
import os
from pathlib import Path
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile

import importlib.util
REPO = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, REPO / path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


sealed = load('rp6_sealed_release', 'scripts/prepare-rp6-release.py')
kernel_check = load('rp6_kernel_release_check', 'scripts/check-rp6-kernel.py')
release = sealed.release


def assert_root_delta(before, after):
    changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
    def allowed(path):
        return (path == 'usr/share/steamos-arm/release-manifest.json' or
                any(path == prefix or path.startswith(prefix + '/') for prefix in
                    ('usr/lib/modules', 'usr/lib/firmware')))
    unexpected = changed - {p for p in changed if allowed(p)}
    if unexpected:
        raise ValueError('accepted userspace changed: ' + ', '.join(sorted(unexpected)[:20]))
    return sorted(changed)


def assert_boot_delta(before, after):
    changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
    if changed - {'KERNEL', 'KERNEL.md5'}:
        raise ValueError('BOOT changed outside KERNEL/KERNEL.md5')
    return sorted(changed)


@contextmanager
def image_mounts(image):
    folder = Path(tempfile.mkdtemp(prefix='rp6-kernel-release-')); mounted = []
    try:
        for name, (_, start, size) in zip(('boot', 'root', 'home'), sealed.LAYOUT):
            dest = folder / name; dest.mkdir()
            access = 'ro,noload,' if name == 'home' else ''
            sealed.run('mount', '-o', f'{access}loop,offset={start*512},sizelimit={size*512}', image, dest)
            mounted.append(dest)
        yield tuple(folder / name for name in ('boot', 'root', 'home'))
    finally:
        failures = []
        for dest in reversed(mounted):
            try: sealed.run('umount', dest)
            except (OSError, subprocess.CalledProcessError) as error: failures.append(str(error))
        if failures or any(os.path.ismount(folder / name) for name in ('boot', 'root', 'home')):
            raise ValueError(f'unmount failed; retain {folder}: {failures}')
        shutil.rmtree(folder)


def replace_directory(source, dest):
    if source.is_symlink() or not source.is_dir() or dest.is_symlink() or not dest.is_dir():
        raise ValueError('kernel payload paths must be real directories: ' + str(dest))
    sealed.run('rsync', '-aHAX', '--delete', str(source) + '/', str(dest) + '/')


def build(recipe_path, kernel_dir, image, package, version):
    paths = sealed.output_paths(image, package)
    if not sys.platform.startswith('linux') or os.geteuid() != 0:
        raise ValueError('Linux/root required')
    recipe = json.loads(recipe_path.read_text()); assembly = recipe.get('assembly', {})
    if assembly.get('type') != 'sealed-up08-kernel-replacement' or assembly.get('clean_distro_source_build') is not False:
        raise ValueError('explicit sealed UP08 kernel replacement provenance required')
    tc = recipe.get('toolchain', {})
    if (not re.fullmatch(r'sha256:[0-9a-f]{64}', tc.get('builder_image', '')) or
            os.environ.get('RP6_BUILDER_IMAGE') != tc['builder_image'] or
            platform.machine() != tc.get('builder_architecture')):
        raise ValueError('assembly toolchain does not match lock')
    source = release.source_record(REPO, False)
    if source['sha'] != assembly.get('source_sha'):
        raise ValueError('assembly source SHA mismatch')
    release.validate_recipe(recipe)
    inputs = {item['id']: item for item in recipe['inputs']}
    base_item = inputs[assembly['base_input']]; base = Path(base_item['path'])
    sealed.validate_base(base, base_item['sha256'])
    bundle_item = inputs[assembly['bundle_inventory_input']]
    if sealed.tree_inventory(kernel_dir) != json.loads(Path(bundle_item['path']).read_text()):
        raise ValueError('kernel bundle inventory mismatch')
    lockfile = REPO / 'external-and-mods/kernel-sm8550/recipe-7.2.lock.json'
    artifacts = kernel_check.check_artifacts(lockfile, kernel_dir)
    for path in paths: path.parent.mkdir(parents=True, exist_ok=True)
    regions = {'partition_table': (0, sealed.LAYOUT[0][1]*512),
               'home': (sealed.LAYOUT[2][1]*512, sealed.LAYOUT[2][2]*512)}
    protected = {name: sealed.region_digest(base, *region) for name, region in regions.items()}
    partial = image.with_name(image.name + '.partial')
    sealed.run('cp', '--reflink=auto', '--sparse=always', base, partial)
    with image_mounts(partial) as (boot_dir, root, home):
        session = load('rp6_kernel_session', 'scripts/check-rp6-session.py')
        session.check(root, boot_dir / 'KERNEL', home / 'steamos')
        if release.digest(boot_dir / 'KERNEL') != assembly.get('base_kernel_sha256'):
            raise ValueError('accepted base KERNEL SHA256 mismatch')
        before = sealed.tree_inventory(root); before_boot = sealed.tree_inventory(boot_dir)
        replace_directory(kernel_dir / 'modules', root / 'usr/lib/modules')
        replace_directory(kernel_dir / 'firmware', root / 'usr/lib/firmware')
        boot = load('rp6_kernel_boot', 'external-and-mods/ufs-install/ufs-bootimg.py')
        kernel = boot.BootImg((kernel_dir / 'boot/KERNEL').read_bytes())
        with partial.open('rb') as stream:
            stream.seek(440); disk_id = struct.unpack('<I', stream.read(4))[0]
        cmdline = boot.retarget(kernel.cmdline, f'PARTUUID={disk_id:08x}-02')
        target = boot_dir / 'KERNEL'
        if target.is_symlink(): raise ValueError('base KERNEL must be regular')
        target.write_bytes(kernel.build(cmdline))
        (boot_dir / 'KERNEL.md5').write_text(__import__('hashlib').md5(target.read_bytes()).hexdigest() + '  KERNEL\n')
        # Validate the retargeted KERNEL against installed modules/firmware.
        with tempfile.TemporaryDirectory(prefix='rp6-retargeted-') as tmp:
            delivery_dir = Path(tmp); (delivery_dir / 'boot').mkdir()
            shutil.copyfile(target, delivery_dir / 'boot/KERNEL')
            for config in kernel_dir.glob('config-*'): shutil.copyfile(config, delivery_dir / config.name)
            delivered = kernel_check.check_artifacts(lockfile, delivery_dir, root)
        delivered_session = session.check(root, target, home / 'steamos')
        sealed.run('bash', REPO / 'scripts/check-rp6-input.sh', root, target)
        sealed.run('python3', REPO / 'scripts/fix-rp6-touch.py', '--check-boot', target)
        manifest = release.create(REPO, root, target, recipe)
        manifest_path = image.with_name(image.name + '.build-manifest.json'); release.save(manifest_path, manifest)
        marker = root / 'usr/share/steamos-arm/release-manifest.json'
        if marker.is_symlink(): raise ValueError('release marker must be regular')
        shutil.copyfile(manifest_path, marker); marker.chmod(0o644)
        after = sealed.tree_inventory(root); delta = assert_root_delta(before, after)
        boot_delta = assert_boot_delta(before_boot, sealed.tree_inventory(boot_dir))
        inventory_path = image.with_name(image.name + '.root-inventory.json.gz')
        with inventory_path.open('xb') as handle:
            with gzip.GzipFile(fileobj=handle, mode='wb', mtime=0, filename='') as compressed:
                compressed.write(json.dumps(after, sort_keys=True).encode())
        home_inventory = sealed.tree_inventory(home / 'steamos')
        sealed.run('python3', REPO / 'scripts/build-update-package.py', '--rootfs', root,
                   '--home', home / 'steamos', '--kernel', target, '--soc', 'sm8550',
                   '--device', 'Retroid Pocket 6', '--version', version, '--output', package)
        metadata = sealed.verify_package_metadata(package, after, home_inventory)
    for name, region in regions.items():
        if sealed.region_digest(partial, *region) != protected[name]:
            raise ValueError('sealed region changed: ' + name)
    filesystems = {}
    for name, (_, start, size) in zip(('boot', 'root', 'home'), sealed.LAYOUT):
        loop = subprocess.check_output(['losetup', '--find', '--show', '--read-only', '--offset', str(start*512),
                                        '--sizelimit', str(size*512), str(partial)], text=True).strip()
        try:
            sealed.run('fsck.fat' if name == 'boot' else 'e2fsck', '-n', loop)
            filesystems[name] = 'passed-read-only'
        finally: sealed.run('losetup', '-d', loop)
    os.replace(partial, image)
    final = {**manifest, 'build_manifest_sha256': release.digest(manifest_path),
             'outputs': {'image': release.output_artifact(image), 'package': release.output_artifact(package),
                         'root_inventory': release.output_artifact(inventory_path)}}
    release.save(image.with_name(image.name + '.release.json'), final)
    report = {'source': source, 'assembly': assembly, 'root_delta': delta, 'boot_delta': boot_delta,
              'kernel': artifacts, 'delivered_kernel': delivered, 'delivery': delivered_session,
              'package_metadata': metadata, 'preserved_regions': protected, 'filesystems': filesystems,
              'root_entries_compared': len(before), 'device': 'untested'}
    release.save(image.with_name(image.name + '.validation.json'), report)
    image.with_name(image.name + '.sha256').write_text(final['outputs']['image']['sha256'] + '  ' + image.name + '\n')
    print(json.dumps(report, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('recipe', 'kernel-dir', 'image', 'package'): parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args(); build(args.recipe, args.kernel_dir, args.image, args.package, args.version)


if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError, subprocess.CalledProcessError) as error: raise SystemExit(str(error))
