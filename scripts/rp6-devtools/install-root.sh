#!/usr/bin/bash
# Opt-in RP6 development setup; one local sudo authentication is required.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo 'Run this installer with sudo in Konsole' >&2; exit 1; }
model=$(/usr/bin/python3 -I -c 'from pathlib import Path; print(Path("/sys/firmware/devicetree/base/model").read_text().rstrip("\x00\n"))')
[ "$model" = 'Retroid Pocket 6' ] || { echo 'Wrong device' >&2; exit 1; }
root_device=$(/usr/bin/findmnt -n -o SOURCE /)
case "$root_device" in /dev/mmcblk*) ;; *) echo 'microSD root required' >&2; exit 1 ;; esac
folder=$(cd -- "$(dirname -- "$0")" && pwd -P)
helper=/usr/local/libexec/rp6-devtools-root
policy=/etc/sudoers.d/rp6-devtools
for path in /usr/local /usr/local/libexec /etc/sudoers.d "$helper" "$policy"; do
    [ ! -L "$path" ] || { echo "Refusing symlink: $path" >&2; exit 1; }
done
if [ -e "$helper" ]; then
    cmp -s "$folder/root-helper.py" "$helper" || { echo 'Existing helper differs; inspect before replacement' >&2; exit 1; }
fi
/usr/bin/install -d -o root -g root -m 0755 /usr/local/libexec
temporary=$(mktemp /etc/sudoers.d/.rp6-devtools-XXXXXX)
trap 'rm -f -- "$temporary"' EXIT
cat >"$temporary" <<'POLICY'
# RP6 development helper; exact arguments, no general shell or arbitrary files.
steamos ALL=(root) NOPASSWD: /usr/local/libexec/rp6-devtools-root snapshot, /usr/local/libexec/rp6-devtools-root enable-ssh, /usr/local/libexec/rp6-devtools-root restart-decky, /usr/local/libexec/rp6-devtools-root restart-konkrd, /usr/local/libexec/rp6-devtools-root reboot
POLICY
chmod 0440 "$temporary"
/usr/bin/visudo -cf "$temporary"
if [ -e "$policy" ]; then
    cmp -s "$temporary" "$policy" || { echo 'Existing sudo policy differs; inspect before replacement' >&2; exit 1; }
fi
/usr/bin/install -o root -g root -m 0755 "$folder/root-helper.py" "$helper"
/usr/bin/install -o root -g root -m 0440 "$temporary" "$policy"
/usr/bin/systemctl enable --now sshd.service
/usr/bin/visudo -c
echo 'RP6 development root helper installed; SSH enabled at boot.'
