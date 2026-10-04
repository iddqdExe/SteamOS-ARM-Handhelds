#!/usr/bin/env bash
# UP-04 runtime for offline RP6 ROOT. Validate all destinations before writing.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $# == 1 && -d "$1/usr" ]] || { echo 'Usage: install-rp6-power.sh <offline ROOT>' >&2; exit 2; }
R="$(cd "$1" && pwd -P)"
[[ "$R" != / ]] || { echo 'ERROR: requires an offline rootfs' >&2; exit 1; }
FILES=(usr/lib/konkr/konkr-standby usr/lib/konkr/konkr-sleep usr/lib/konkr/konkr-suspend
       usr/lib/konkr/konkr-sleep-state usr/bin/konkrctl
       usr/lib/systemd/system/konkr-sleep.service usr/lib/systemd/system/konkr-bootflags.service
       usr/lib/systemd/system/systemd-suspend.service.d/10-konkr-standby.conf)
LINKS=(usr/lib/systemd/system/multi-user.target.wants/konkr-bootflags.service
       usr/lib/systemd/system/sleep.target.wants/konkr-sleep.service)
for name in "${FILES[@]}" usr/lib/steamos-arm/bootdebug "${LINKS[@]}"; do
  path="$R/$(dirname "$name")"
  while [[ "$path" != "$R" ]]; do
    [[ ! -L "$path" && ( ! -e "$path" || -d "$path" ) ]] || { echo "ERROR: symlink/non-directory destination: $path" >&2; exit 1; }
    path="$(dirname "$path")"
  done
  [[ ! -d "$R/$name" ]] || exit 1
  if [[ " $name " != *'.wants/'* && -L "$R/$name" ]]; then
    echo "ERROR: symlink destination: $R/$name" >&2; exit 1
  fi
done
for name in "${FILES[@]}"; do
  [[ -f "$ROOT/sm8650-overlay/$name" && ! -L "$ROOT/sm8650-overlay/$name" ]] || exit 1
done
bash -n "$ROOT/sm8650-overlay/usr/lib/konkr/konkr-sleep"
sh -n "$ROOT/sm8650-overlay/usr/lib/konkr/konkr-suspend" "$ROOT/external-and-mods/kernel-common/initramfs/bootdebug"
python3 - "$ROOT/sm8650-overlay/usr/lib/konkr/konkr-standby" "$ROOT/sm8650-overlay/usr/lib/konkr/konkr-sleep-state" "$ROOT/sm8650-overlay/usr/bin/konkrctl" <<'PY'
import ast,pathlib,sys
for p in sys.argv[1:]:ast.parse(pathlib.Path(p).read_text(),filename=p)
PY
for name in "${FILES[@]}"; do
  mode=0755
  [[ "$name" != *.service && "$name" != *.conf ]] || mode=0644
  install -D -m "$mode" "$ROOT/sm8650-overlay/$name" "$R/$name"
done
install -D -m0755 "$ROOT/external-and-mods/kernel-common/initramfs/bootdebug" "$R/usr/lib/steamos-arm/bootdebug"
for name in "${LINKS[@]}"; do
  mkdir -p "$R/$(dirname "$name")"
  ln -sfn "../$(basename "$name")" "$R/$name"
done
