#!/usr/bin/env bash
# Install power transitions and the CPU-profile runtime into an offline rootfs.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# != 1 || ! -d "$1/usr" ]]; then
  echo 'Usage: install-rp6-power.sh <offline rootfs with usr directory>' >&2
  exit 2
fi
R="$(cd "$1" && pwd -P)"
[[ "$R" != / ]] || { echo 'ERROR: requires an offline rootfs' >&2; exit 1; }
SOURCE="$ROOT/sm8650-overlay"
FILES=(usr/lib/konkr/konkr-standby usr/lib/konkr/konkr-sleep
       usr/lib/konkr/konkrd usr/bin/konkrctl)
# Check every destination and source before replacing any runtime file.
for path in "$R/usr" "$R/usr/lib" "$R/usr/lib/konkr" "$R/usr/bin"; do
  [[ ! -L "$path" ]] || { echo "ERROR: symlink destination: $path" >&2; exit 1; }
done
for name in "${FILES[@]}"; do
  [[ ! -L "$R/$name" ]] || { echo "ERROR: symlink destination: $R/$name" >&2; exit 1; }
  [[ -f "$SOURCE/$name" && ! -d "$R/$name" ]] || exit 1
done
bash -n "$SOURCE/usr/lib/konkr/konkr-sleep"
python3 - "$SOURCE/usr/lib/konkr/konkr-standby" "$SOURCE/usr/lib/konkr/konkrd" "$SOURCE/usr/bin/konkrctl" <<'PY'
import ast, pathlib, sys
for name in sys.argv[1:]:
    ast.parse(pathlib.Path(name).read_text(), filename=name)
PY
mkdir -p "$R/usr/lib/konkr" "$R/usr/bin"
for name in "${FILES[@]}"; do
  install -m0755 "$SOURCE/$name" "$R/$name"
done
