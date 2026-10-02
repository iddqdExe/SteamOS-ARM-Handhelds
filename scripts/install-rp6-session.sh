#!/usr/bin/env bash
# UP-01 staged rootfs delivery; GPL-2.0. No device or BOOT writes.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
root="${1:?staged rootfs}"
[[ -d "$root" ]] || { echo "missing rootfs: $root" >&2; exit 1; }
if [[ $# == 3 ]]; then
    python3 "$repo/scripts/fetch-decky-loader.py" --verify "$3" >/dev/null
elif [[ $# != 1 ]]; then
    echo 'usage: install-rp6-session.sh ROOTFS [STEAMOS_HOME VERIFIED_LOADER]' >&2
    exit 2
fi

# Upstream c9d87d6 + 4181b9c (hashtagbasit): remove only Frame VR layers
# from the loader's search path; keep bytes available for rollback.
layers="$root/usr/share/vulkan/explicit_layer.d"
mkdir -p "$layers.frame"
for name in VkLayer_VALVE_rpo.json VkLayer_VALVE_fdm_injection.json; do
    if [[ -f "$layers/$name" ]]; then
        mv -f "$layers/$name" "$layers.frame/"
    fi
done
for rel in usr/lib/steamos/gamescope-session usr/lib/steamos/wait-gamescope-env; do
    mkdir -p "$root/$(dirname "$rel")"
    install -m0755 "$repo/steamos-overlay/$rel" "$root/$rel"
done
for name in 60-gamescope-env.conf 61-gamescope-env-wait.conf; do
    rel="usr/lib/systemd/user/steam.service.d/$name"
    mkdir -p "$root/$(dirname "$rel")"
    install -m0644 "$repo/steamos-overlay/$rel" "$root/$rel"
done
for rel in usr/lib/systemd/system/plugin_loader.service usr/lib/systemd/user/konkr-focusfix.service; do
    mkdir -p "$root/$(dirname "$rel")"
    install -m0644 "$repo/sm8650-overlay/$rel" "$root/$rel"
done
mkdir -p "$root/usr/lib/konkr"
install -m0755 "$repo/sm8650-overlay/usr/lib/konkr/konkr-focusfix" "$root/usr/lib/konkr/konkr-focusfix"
install -m0755 "$repo/sm8650-overlay/usr/lib/konkr/konkr-standby" "$root/usr/lib/konkr/konkr-standby"
mkdir -p "$root/usr/lib/systemd/user/gamescope-session.target.wants"
ln -sfn ../konkr-focusfix.service "$root/usr/lib/systemd/user/gamescope-session.target.wants/konkr-focusfix.service"
mkdir -p "$root/usr/share/konkr-update"
install -m0644 "$repo/external-and-mods/konkr-update/konkr-update.py" "$root/usr/share/konkr-update/konkr-update.py"
mkdir -p "$root/usr/share/steamos-arm"
install -m0644 "$repo/steamos-overlay/usr/share/steamos-arm/up-01.json" "$root/usr/share/steamos-arm/up-01.json"
if [[ $# == 3 ]]; then
    home=$2
    mkdir -p "$home/homebrew/services" "$home/homebrew/settings" "$home/homebrew/data" "$home/homebrew/logs" "$home/.cache"
    install -m0755 "$3" "$home/homebrew/services/PluginLoader"
    python3 - "$repo/external-and-mods/Decky/loader.json" "$home/homebrew/services/.loader.version" <<'PY'
import json,sys
from pathlib import Path
Path(sys.argv[2]).write_text(json.loads(Path(sys.argv[1]).read_text())['version'])
PY
    mkdir -p "$root/usr/lib/systemd/system/multi-user.target.wants"
    ln -sfn ../plugin_loader.service "$root/usr/lib/systemd/system/multi-user.target.wants/plugin_loader.service"
fi
