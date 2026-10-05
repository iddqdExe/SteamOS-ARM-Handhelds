# Building

**Fork scope:** build for Retroid Pocket 6, Snapdragon 8 Gen 2 / SM8550, using `SOC=sm8550`. Hardware acceptance uses the 12 GB RAM model with SteamOS on microSD. Other SoC build paths below are inherited upstream reference material. See [RP6-SCOPE.md](RP6-SCOPE.md).

I build everything in an arm64 Linux VM (Colima on a Mac).

- Kernels: `external-and-mods/kernel-sm8650/build.sh` and `external-and-mods/kernel-sm8550/build.sh` (shared script in `kernel-common/`, chip specific bits in each `soc.env`)
- gamescope: `scripts/build-gamescope-in-rootfs.sh`, source in `external-and-mods/gamescope/`
- the image: `make-steamos-sm8650.sh` (`SOC=sm8550` for the 8 Gen 2 one), or `./make-steamos-sm8750.sh` for the Snapdragon 8 Elite (Odin 3); `./make-steamos-sm8350.sh` turns the rootfs from `make-steamos-sm8650.sh` (or a release image) into the REDMAGIC 6 fastboot kit (kernel: `external-and-mods/kernel-sm8350/build.sh`, see [redmagic6.md](redmagic6.md))

Valve's files and the Steam client aren't in this repo, the build downloads them. How the pieces fit together is in [HOW-IT-WORKS.md](HOW-IT-WORKS.md).


## RP6 primary baseline (accepted UP-02 on UP-04)

UP-02 on UP-04 R3 is the accepted baseline in `main`, including RP6 400 kHz touch with bulk read, the RP6 suspend/recovery patches, executable initramfs and permanent diagnostics. For `SOC=sm8550`, the primary recipe is 7.2 with kernel `7.2.8-sm8550-steamos`, pinned ROCKNIX and GCC15. The image builder defaults to `${STEAMOS_WORK:-/work}/kernel-sm8550/output/current`. Prepare the locked Frame WCN7850 firmware and toolchain as described in [RP6-UP-03.ru.md](RP6-UP-03.ru.md); missing/mismatched inputs still fail the build.

Use `SM8550_RECIPE=7.1` explicitly for the legacy recipe. An existing legacy prebuilt image bundle can still be selected explicitly with `SM8550_KERNEL=prebuilt` or `IMAGE_KERNEL_OUT`. The legacy path is optional; it is no longer the implicit RP6 image default.

For the sealed accepted-userspace image/update path, use `scripts/prepare-rp6-kernel-release.py` with a locked UP-04 recipe. It applies the checksum-pinned wake guard while preserving the accepted profiles/fan and other userspace. The generic image builder already installs UP-04 power runtime; it is a separate full-userspace build path, not the tested sealed R3 artifact. Assembly/kernel source SHAs and earlier UP-04 checks are in [RP6-UP-04.acceptance.json](RP6-UP-04.acceptance.json). R3 clean installation, measured touch and standby resume are recorded in [RP6-UP-02.acceptance.json](RP6-UP-02.acceptance.json). The SSH/recovery and bounded touch diagnostics installer is generated separately with `scripts/build-rp6-access-installer.py` and applied after installation; see [RP6-UP-02.ru.md](RP6-UP-02.ru.md). Local images and build caches were removed after acceptance at the project owner's request; regenerate artifacts from the locked recipes rather than expecting those local paths to exist.
