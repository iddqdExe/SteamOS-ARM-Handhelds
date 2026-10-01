#!/usr/bin/env bash
# Install ShadowBlip InputPlumber + SM8550 deck-uhid composite into a SteamOS rootfs.
# deck-uhid (Steam Deck controller) + keyboard target (touch OSK haptic).
# USB/Bluetooth HID is ignored in the composite so it is not grabbed.
# Usage: install-inputplumber-sm8550.sh <rootfs> [--config-only]
# --config-only refreshes profiles/maps without downloading or replacing binaries.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
R="${1:-${ROOT}/rootfs}"
OVL="${ROOT}/steamos-overlay"
CACHE="${ROOT}/external-and-mods/InputPlumber"
# 0.79+ drives the rumble motors of the AYANEO/KONKR pad in its HID mode.
IP_VER="${INPUTPLUMBER_VERSION:-0.81.0}"
IP_SHA256_0_81_0="5509a6f79bec95c240de34833639e3ba8a144752e3745e6eb978b38b8aa05a10"
TGZ="${CACHE}/inputplumber-${IP_VER}-aarch64.tar.gz"
TGZ_URL="https://github.com/ShadowBlip/InputPlumber/releases/download/v${IP_VER}/inputplumber-aarch64.tar.gz"

log() { printf '==> [inputplumber] %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ -d "${R}/usr" ]] || die "not a rootfs: ${R}"
MODE="${2:-}"
[[ "$MODE" == "" || "$MODE" == --config-only ]] || die "unknown mode: $MODE"
[[ $# -le 2 ]] || die "usage: $0 <rootfs> [--config-only]"

fetch() {
  local url="$1" dest="$2"
  [[ -s "$dest" ]] && return 0
  log "Downloading ${url}"
  if command -v curl >/dev/null; then
    curl -fL --retry 3 -o "${dest}.part" "$url"
  else
    wget -O "${dest}.part" "$url"
  fi
  mv -f "${dest}.part" "$dest"
}

install_tarball() {
  if [[ ! -s "$TGZ" ]]; then
    fetch "$TGZ_URL" "$TGZ"
  fi
  [[ -s "$TGZ" ]] || die "missing ${TGZ}"
  # Pinned hash for the default version; for an override, the release's own.
  local want_var="IP_SHA256_${IP_VER//./_}" want got
  want="${!want_var:-}"
  if [[ -z "$want" ]]; then
    fetch "${TGZ_URL}.sha256.txt" "${TGZ}.sha256.txt"
    want="$(awk '{print $1; exit}' "${TGZ}.sha256.txt")"
  fi
  got="$(sha256sum "$TGZ" | awk '{print $1}')"
  if [[ "$want" != "$got" ]]; then
    rm -f "$TGZ"
    die "InputPlumber ${IP_VER} checksum mismatch (got ${got}); removed the download, run again"
  fi
  local stage="${CACHE}/extract"
  rm -rf "$stage"
  mkdir -p "$stage"
  # --no-same-owner: the release tarball is owned by uid 1001, and cp -a
  # below would hand /usr, /usr/lib, /usr/share … to that uid.
  tar -C "$stage" --no-same-owner -xzf "$TGZ"
  chown -R root:root "$stage"
  local src="$stage"
  if [[ ! -x "${src}/usr/bin/inputplumber" ]]; then
    local inner
    inner="$(find "$stage" -type f -name inputplumber -path '*/usr/bin/*' | head -1)"
    [[ -n "$inner" ]] || die "tarball has no usr/bin/inputplumber"
    src="$(cd "$(dirname "$inner")/../.." && pwd)"
  fi
  log "Installing InputPlumber files from ${src}"
  mkdir -p "${R}/usr" "${R}/etc"
  cp -a "${src}/usr/." "${R}/usr/"
  if [[ -d "${src}/etc" ]]; then
    # Input configuration is merged below, never overwritten by the release tar.
    rm -rf "${src}/etc/inputplumber"
    cp -a "${src}/etc/." "${R}/etc/"
  fi
  [[ -x "${R}/usr/bin/inputplumber" ]] || die "inputplumber binary missing after extract"
  # Local 0.81.0 fix prevents the output-only AYANEO rumble source spinning.
  if [[ "$IP_VER" == 0.81.0 ]]; then
    local fixed="$CACHE/inputplumber-0.81.0-konkr"
    [[ -f "$fixed" && -f "$fixed.sha256" ]] || die "missing verified AYANEO polling fix; run build-inputplumber-konkr.sh"
    (cd "$CACHE" && sha256sum -c "$(basename "$fixed").sha256") || die "patched InputPlumber checksum mismatch"
    install -m0755 "$fixed" "$R/usr/bin/inputplumber"
  fi
}

install_libiio() {
  if [[ -e "${R}/usr/lib/libiio.so.0" || -e "${R}/usr/lib/libiio.so" ]]; then
    log "libiio already in rootfs"
    return 0
  fi
  # Minimal local-backend libiio — InputPlumber links it even without IMU.
  local src="${CACHE}/libiio-src"
  if [[ ! -f "${src}/CMakeLists.txt" ]]; then
    rm -rf "$src"
    fetch "https://github.com/analogdevicesinc/libiio/archive/refs/tags/v0.26.tar.gz" \
      "${CACHE}/libiio-0.26.tar.gz"
    mkdir -p "$src"
    tar -C "$src" --strip-components=1 -xzf "${CACHE}/libiio-0.26.tar.gz"
  fi
  command -v cmake >/dev/null || die "cmake required to build libiio"
  local bld="${CACHE}/libiio-src/build-steamos"
  cmake -S "$src" -B "$bld" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DWITH_LOCAL_BACKEND=ON \
    -DWITH_XML_BACKEND=OFF \
    -DWITH_NETWORK_BACKEND=OFF \
    -DWITH_USB_BACKEND=OFF \
    -DWITH_SERIAL_BACKEND=OFF \
    -DHAVE_DNS_SD=OFF \
    -DWITH_ZSTD=OFF \
    -DWITH_EXAMPLES=OFF \
    -DWITH_TESTS=OFF \
    -DWITH_IIOD=OFF \
    -DWITH_AIO=OFF \
    -DWITH_HWMON=ON
  cmake --build "$bld" -j"$(nproc)"
  DESTDIR="$R" cmake --install "$bld"
  if [[ -e "${R}/usr/lib/aarch64-linux-gnu/libiio.so.0" && ! -e "${R}/usr/lib/libiio.so.0" ]]; then
    ln -sfn aarch64-linux-gnu/libiio.so.0 "${R}/usr/lib/libiio.so.0"
  fi
  if [[ -e "${R}/usr/lib/libiio.so" && ! -e "${R}/usr/lib/libiio.so.0" ]]; then
    ln -sfn "$(basename "$(readlink -f "${R}/usr/lib/libiio.so")")" "${R}/usr/lib/libiio.so.0"
  fi
  [[ -e "${R}/usr/lib/libiio.so.0" || -e "${R}/usr/lib64/libiio.so.0" ]] \
    || die "libiio.so.0 missing after build"
  if [[ -e "${R}/usr/lib64/libiio.so.0" && ! -e "${R}/usr/lib/libiio.so.0" ]]; then
    ln -sfn ../lib64/libiio.so.0 "${R}/usr/lib/libiio.so.0"
  fi
  log "Built local-backend libiio into rootfs"
}

install_odin_composite() {
  install -d "${R}/etc/inputplumber/devices.d" \
    "${R}/etc/inputplumber/capability_maps.d" \
    "${R}/usr/share/inputplumber/capability_maps" \
    "${R}/usr/share/konkr-update" \
    "${R}/usr/lib/steamos" "${R}/usr/lib/udev/rules.d" \
    "${R}/usr/lib/systemd/system/inputplumber.service.d" \
    "${R}/etc/systemd/system/multi-user.target.wants"
  if [[ ! -e "${R}/etc/inputplumber/devices.d/02-ayn-odin.yaml" && ! -L "${R}/etc/inputplumber/devices.d/02-ayn-odin.yaml" ]]; then
    install -m0644 "${OVL}/etc/inputplumber/devices.d/02-ayn-odin.yaml" \
      "${R}/etc/inputplumber/devices.d/02-ayn-odin.yaml"
  fi
  # Image-only builds also call this installer, without apply-overlays.sh.
  # Deliver the RP6 composite here so its D-pad/menu/paddle map is selected.
  # Every map, not just ayn_mcu: the RP6 profile points at retroid_mcu and
  # without the file InputPlumber passed the raw buttons through (A/B swapped).
  local m
  for m in "${OVL}"/etc/inputplumber/capability_maps.d/*.yaml; do
    [[ "${m##*/}" == retroid_mcu.yaml ]] && continue
    if [[ ! -e "${R}/etc/inputplumber/capability_maps.d/${m##*/}" && ! -L "${R}/etc/inputplumber/capability_maps.d/${m##*/}" ]]; then
      install -m0644 "$m" "${R}/etc/inputplumber/capability_maps.d/${m##*/}"
    fi
    install -m0644 "$m" "${R}/usr/share/inputplumber/capability_maps/${m##*/}"
  done
  install -m0755 "${OVL}/usr/lib/steamos/rp6-input-config.py" \
    "${R}/usr/lib/steamos/rp6-input-config.py"
  # Image-only builds need the same pre-InputPlumber axis calibration as
  # full overlay builds, including the measured RP6 signed trigger range.
  install -m0755 "${OVL}/usr/lib/steamos/sm8550-fixpad" \
    "${R}/usr/lib/steamos/sm8550-fixpad"
  install -m0644 "${OVL}/usr/lib/systemd/system/sm8550-fixpad.service" \
    "${R}/usr/lib/systemd/system/sm8550-fixpad.service"
  ln -sfn /usr/lib/systemd/system/sm8550-fixpad.service \
    "${R}/etc/systemd/system/multi-user.target.wants/sm8550-fixpad.service"
  local defaults
  defaults="$(mktemp -d)"
  install -d "$defaults/devices.d" "$defaults/capability_maps.d"
  install -m0644 "${ROOT}/sm8550-overlay/etc/inputplumber/devices.d/02-retroid-pocket.yaml" \
    "$defaults/devices.d/02-retroid-pocket.yaml"
  install -m0644 "${OVL}/etc/inputplumber/capability_maps.d/retroid_mcu.yaml" \
    "$defaults/capability_maps.d/retroid_mcu.yaml"
  if ! python3 "${R}/usr/lib/steamos/rp6-input-config.py" "$R" --source "$defaults"; then
    rm -rf "$defaults"
    die "RP6 configuration merge failed"
  fi
  rm -rf "$defaults"
  # Bootstrap preservation before the first update of a staged beta8 rootfs.
  # The deployed updater copies itself into recovery when it stages a package.
  install -m0755 "${ROOT}/external-and-mods/konkr-update/konkr-update.py" \
    "${R}/usr/share/konkr-update/konkr-update.py"
  install -m0644 "${OVL}/usr/lib/systemd/system/inputplumber.service.d/99-sm8550.conf" \
    "${R}/usr/lib/systemd/system/inputplumber.service.d/99-sm8550.conf"
  install -m0755 "${OVL}/usr/lib/steamos/sm8550-inputplumber-ext-hid" \
    "${R}/usr/lib/steamos/sm8550-inputplumber-ext-hid"
  install -m0644 "${OVL}/usr/lib/systemd/system/sm8550-inputplumber-ext-hid.service" \
    "${R}/usr/lib/systemd/system/sm8550-inputplumber-ext-hid.service"
  install -m0644 "${OVL}/usr/lib/udev/rules.d/71-sm8550-ext-hid.rules" \
    "${R}/usr/lib/udev/rules.d/71-sm8550-ext-hid.rules"
  mkdir -p "${R}/lib/udev/rules.d" \
    "${R}/usr/lib/systemd/system/multi-user.target.wants"
  install -m0644 "${OVL}/usr/lib/udev/rules.d/71-sm8550-ext-hid.rules" \
    "${R}/lib/udev/rules.d/71-sm8550-ext-hid.rules"
  ln -sfn /usr/lib/systemd/system/sm8550-inputplumber-ext-hid.service \
    "${R}/usr/lib/systemd/system/multi-user.target.wants/sm8550-inputplumber-ext-hid.service"
  # Existing composites are user-owned; do not remove them by filename.
  ln -sfn /usr/lib/systemd/system/inputplumber.service \
    "${R}/etc/systemd/system/multi-user.target.wants/inputplumber.service"
}

verify_needed() {
  python3 "$SCRIPT_DIR/check-inputplumber-elf.py" "$R/usr/bin/inputplumber" "$R"
}

if [[ "$MODE" == --config-only ]]; then
  install_odin_composite
  log "SM8550 input configuration refreshed (binaries unchanged)"
  exit 0
fi
mkdir -p "${CACHE}"
install_tarball
install_libiio
install_odin_composite
verify_needed
log "Steam will see Valve Steam Deck Controller (deck-uhid)"
log "Keyboard target for OSK haptic; USB/BT HID disables that target"
