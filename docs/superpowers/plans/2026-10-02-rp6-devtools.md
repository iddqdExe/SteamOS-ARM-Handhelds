# RP6 development automation implementation plan

> **For agentic workers:** Use superpowers:executing-plans in this chat. User authorized SSH startup and development/testing setup; no new chat is needed.

**Goal:** Automate RP6 system diagnostics through the existing pinned SSH connection and capture boot reports without network access.

**Architecture:** Opt-in development scripts, outside image overlays. A user timer captures one report after user-manager startup. A root-owned helper exposes only fixed diagnostic/service actions through exact sudoers arguments. Initial root installation uses local Konsole sudo authentication.

**Tech Stack:** Python standard library, OpenSSH, systemd user timer, sudo/visudo.

**Spec:** User instructions in this chat on 2026-10-02: enable SSH at console startup and configure tools that help development/testing. Existing RP6 scope and UP-01 acceptance boundaries apply.

## Global constraints

- Retroid Pocket 6 / SM8550 / 12 GB / microSD; reject other models.
- Strict SSH host-key checking and one existing diagnostic key; no image secrets.
- No kernel/bootloader changes, unrestricted sudo, background repairs or automatic reboot.
- Root operations require an explicit action; commands, unit names and file paths are fixed.
- System checks never imply visual/game/input/suspend acceptance.
- Source/image runtime 26970aa remains distinct from opt-in developer setup.

## Review focus

- An unavailable privileged helper produces limited coverage, never a false full pass.
- Invalid remote host/action input never reaches a shell.
- Wrong model and malformed snapshots fail before a successful report.
- Existing device files or symlinked installation paths are not overwritten silently.
- An offline boot still records local diagnostics; timer executes once, not continuously.

## Task 1: Host runner, diagnostics and opt-in installation

**Files:** scripts/rp6-devtools.py; scripts/rp6-devtools/{snapshot.py,root-helper.py,install-root.sh}; scripts/tests/test_rp6_devtools.py; docs/RP6-DEVTOOLS.ru.md.

**Interfaces:** `snapshot`, `stage`, `boot-report`, `action` over SSH; `report` for a saved JSON. Profile supplies host/user/key/known_hosts/optional expected kernel hash. Root helper accepts snapshot, enable-ssh, restart-decky, restart-konkrd, reboot only.

- [x] Write failing tests for wrong identity, duplicate loader, absent root coverage, hash mismatch, invalid SSH/action input and refused symlink replacement.
- [x] Run focused tests and confirm missing implementation failures.
- [x] Implement standard-library scripts and exact sudo policy; document local root bootstrap.
- [x] Run focused and existing source suites; verify systemd units on RP6 and syntax/checksums of staged files.
- [x] Install user-only files/timer over pinned SSH; collect a fresh report. Stage privileged installation and give the user one concrete local sudo command.
- [x] Review the complete change and record source/device/root-bootstrap boundaries.

Results: 96 ARM64 Linux tests passed without skips; 96 macOS tests, 9 skips.
Live integration fixes added reboot-ID verification and boot-report readiness
regressions, each reproduced RED and fixed GREEN.
Independent review identified file-mode normalization and stale boot-report bugs;
both reproduced RED and fixed GREEN. Observation name now says mounted /etc,
without asserting early ordering from a live snapshot. User timer executed and
saved a current-boot report. User completed local root bootstrap and moved the
policy after vendor wheel; password-free fixed commands and refusal of arbitrary
sudo verified with `-n -k`. Two warm reboots proved automatic SSH startup and
root-helper persistence. The second timer ran at uptime 54.7 s before focusfix
started at 57.2 s; late snapshot passed. Added bounded readiness waiting with
initial/final non-ready observations; timeout preserves a failing report.
Review found the final probe could overrun the service timeout. Reproduced RED;
one deadline now caps every subprocess and prohibits expired-budget commands.
Updated user service validated on RP6 and executed explicitly in the current boot.
Cold/offline boot passed: user confirmed Game Mode and KONKR Control; automatic
new-boot report at 54.91 s recorded Wi-Fi disabled and all system checks passing.
SSH started automatically at 9.69 s; timer exited 0. After Wi-Fi enable, SSH
collected a passing live snapshot with the same boot ID and Loader PID.
Whole-module game/input/suspend and supported-update acceptance remain separate.
No kernel, image credentials or default system overlays changed.
