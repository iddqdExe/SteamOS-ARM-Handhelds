#!/usr/bin/env python3
"""Build a verified offline update bundle from a completed rootfs and boot image."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import importlib.util

_spec = importlib.util.spec_from_file_location(
    'konkr_update', Path(__file__).resolve().parent.parent / 'external-and-mods/konkr-update/konkr-update.py')
_updater = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_updater)

ap = argparse.ArgumentParser()
ap.add_argument('--rootfs', required=True)
ap.add_argument('--kernel', required=True)
ap.add_argument('--home', help='staged steamos HOME when mounted separately from rootfs')
ap.add_argument('--soc', default='sm8650', choices=sorted(_updater.SOC_MODELS))
ap.add_argument('--device', action='append', help='restrict the package to named models within --soc')
ap.add_argument('--version', required=True)
ap.add_argument('--output', required=True)
ap.add_argument('--staging-dir', help='temporary staging parent; use rootfs for metadata-preserving hard links')
ap.add_argument('--release-manifest', help='UP-08 build manifest; defaults to the embedded staged-rootfs manifest')
a = ap.parse_args()
root = Path(a.rootfs).resolve(); output = Path(a.output).resolve()
home = Path(a.home).resolve() if a.home else root / 'home/steamos'
staging_parent = Path(a.staging_dir).resolve() if a.staging_dir else output.parent
copy_sources = [root / rel for rel in ('usr', 'opt', 'etc', 'var/lib/overlays/etc/upper')]
copy_sources += [home / 'homebrew/plugins' / name for name in ('konkr-control', 'decky-lsfg-vk')]
copy_sources.append(home / 'homebrew/services')
if any(staging_parent == src.resolve() or src.resolve() in staging_parent.parents for src in copy_sources):
    raise SystemExit('staging directory overlaps payload')
devices = a.device or _updater.SOC_MODELS[a.soc]
if any(device not in _updater.SOC_MODELS[a.soc] for device in devices): raise SystemExit('device does not belong to selected SoC')
if output.exists() or output.with_name(output.name + '.part').exists(): raise SystemExit('output already exists')
if not (root / 'usr/lib/liblsfg-vk-layer-arm64.so').is_file(): raise SystemExit('missing LSFG v2 ARM layer')
if (root / 'usr/lib/steamos/wait-gamescope-env').is_file():
    subprocess.run(['python3', str(Path(__file__).with_name('check-rp6-session.py')), str(root), a.kernel, '--home', str(home)], check=True)
with tempfile.TemporaryDirectory(prefix='konkr-package-', dir=staging_parent) as temp:
    stage = Path(temp)
    def copy(src, dst):
        dst.mkdir(parents=True, exist_ok=True)
        # The completed build tree must remain unchanged throughout packaging.
        # Same-filesystem hard links retain exact metadata without another full copy.
        if src.stat().st_dev == dst.stat().st_dev:
            subprocess.run(['cp', '-a', '--link', str(src) + '/.', str(dst) + '/'], check=True)
        else:
            subprocess.run(['rsync', '-aHAX', '--numeric-ids', str(src) + '/', str(dst) + '/'], check=True)
    for rel in ('usr', 'opt', 'etc', 'var/lib/overlays/etc/upper'):
        src = root / rel
        if src.exists(): copy(src, stage / 'root' / rel)
    for name in ('konkr-control', 'decky-lsfg-vk'):
        copy(home / 'homebrew/plugins' / name, stage / 'home/steamos/homebrew/plugins' / name)
    services = home / 'homebrew/services'
    if services.is_dir(): copy(services, stage / 'home/steamos/homebrew/services')
    release_path = Path(a.release_manifest) if a.release_manifest else root / 'usr/share/steamos-arm/release-manifest.json'
    release = json.loads(release_path.read_text()) if release_path.is_file() else None
    if a.release_manifest and release is None: raise SystemExit('missing release manifest')
    if release is not None:
        marker = stage / 'root/usr/share/steamos-arm/release-manifest.json'
        marker.parent.mkdir(parents=True, exist_ok=True)
        # Copy by replacement: the stage may have hard-linked files from rootfs.
        marker.unlink(missing_ok=True)
        marker.write_text(json.dumps(release, indent=2, sort_keys=True) + '\n')
    (stage / 'boot').mkdir()
    subprocess.run(['cp', a.kernel, str(stage / 'boot/KERNEL')], check=True)
    files = {}
    for p in sorted(stage.rglob('*')):
        if not p.is_file() or p.is_symlink(): continue
        h = hashlib.sha256()
        with p.open('rb') as f:
            for b in iter(lambda: f.read(4 << 20), b''): h.update(b)
        files[str(p.relative_to(stage))] = h.hexdigest()
    manifest = {'format': 1, 'architecture': 'aarch64', 'devices': devices, 'version': a.version, 'files': files}
    provenance = root / 'usr/share/steamos-arm/up-01.json'
    if provenance.is_file(): manifest['provenance'] = json.loads(provenance.read_text())
    if release is not None: manifest['release'] = release
    _updater.verify_payload(stage, manifest)
    (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    subprocess.run(['tar', '--xattrs', '--acls', '--numeric-owner', '-czf', str(output) + '.part',
                    '-C', str(stage), 'manifest.json', 'root', 'home', 'boot'], check=True)
    _updater.validate_archive(str(output) + '.part')
    os.replace(str(output) + '.part', output)
h = hashlib.sha256()
with output.open('rb') as f:
    for b in iter(lambda: f.read(4 << 20), b''): h.update(b)
output.with_name(output.name + '.sha256').write_text(h.hexdigest() + '  ' + output.name + '\n')
print(output, h.hexdigest())
