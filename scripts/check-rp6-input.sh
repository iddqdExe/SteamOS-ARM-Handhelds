#!/usr/bin/env bash
# Read-only preflight for the RP6 configuration in a shared SM8550 image.
# Usage: check-rp6-input.sh <staged-rootfs> <boot-KERNEL>
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
R="${1:?staged rootfs required}"
KERNEL="${2:?boot KERNEL required}"
[[ $# -eq 2 && -d "$R/usr" ]] || { echo 'ERROR: expected staged rootfs and KERNEL' >&2; exit 1; }
check_file() {
  cmp -s "$1" "$2" || { echo "ERROR: missing or stale RP6 input configuration: $2" >&2; exit 1; }
}
PROFILE="$ROOT/sm8550-overlay/etc/inputplumber/devices.d/02-retroid-pocket.yaml"
MAP="$ROOT/steamos-overlay/etc/inputplumber/capability_maps.d/retroid_mcu.yaml"
check_file "$PROFILE" "$R/etc/inputplumber/devices.d/02-retroid-pocket.yaml"
check_file "$MAP" "$R/etc/inputplumber/capability_maps.d/retroid_mcu.yaml"
check_file "$MAP" "$R/usr/share/inputplumber/capability_maps/retroid_mcu.yaml"
check_file "$ROOT/steamos-overlay/usr/lib/steamos/sm8550-fixpad" "$R/usr/lib/steamos/sm8550-fixpad"
check_file "$ROOT/steamos-overlay/usr/lib/steamos/sm8550-volume-keys" "$R/usr/lib/steamos/sm8550-volume-keys"
check_file "$ROOT/steamos-overlay/usr/lib/systemd/user/sm8550-volume-keys.service" \
  "$R/usr/lib/systemd/user/sm8550-volume-keys.service"
[[ -x "$R/usr/bin/gdbus" ]] || { echo 'ERROR: gdbus missing; RP6 Volume Up cannot be handled' >&2; exit 1; }
check_file "$ROOT/steamos-overlay/usr/lib/systemd/system/sm8550-fixpad.service" \
  "$R/usr/lib/systemd/system/sm8550-fixpad.service"
check_file "$ROOT/steamos-overlay/usr/lib/systemd/system/inputplumber.service.d/99-sm8550.conf" \
  "$R/usr/lib/systemd/system/inputplumber.service.d/99-sm8550.conf"
if [[ -d "$R/var/lib/overlays/etc/upper" ]]; then
  check_file "$PROFILE" "$R/var/lib/overlays/etc/upper/inputplumber/devices.d/02-retroid-pocket.yaml"
  check_file "$MAP" "$R/var/lib/overlays/etc/upper/inputplumber/capability_maps.d/retroid_mcu.yaml"
fi
python3 "$ROOT/scripts/fix-rp6-paddles.py" --check-boot "$KERNEL"
echo 'PASS: RP6 input profile, axis calibration and D-pad/menu/paddle map match the build sources'
