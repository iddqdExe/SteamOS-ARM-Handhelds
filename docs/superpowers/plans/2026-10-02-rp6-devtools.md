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

Results: 90 ARM64 Linux tests passed, no skips; 90 macOS tests, 9 skips.
Independent review identified file-mode normalization and stale boot-report bugs;
both reproduced RED and fixed GREEN. Observation name now says mounted /etc,
without asserting early ordering from a live snapshot. User timer executed and
saved a current-boot report; root helper is staged but requires local sudo bootstrap.
No kernel, image credentials or default system overlays changed.
