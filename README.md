# SteamOS ARM for Retroid Pocket 6

This fork develops the unofficial Steam Frame ARM SteamOS port **exclusively for Retroid Pocket 6 with Snapdragon 8 Gen 2 (SM8550)**. It is based on [hashtagbasit/SteamOS-ARM-Handhelds](https://github.com/hashtagbasit/SteamOS-ARM-Handhelds).

## Target and hardware testing

All hardware testing in this fork is performed on the following configuration:

| Component | Test configuration |
| --- | --- |
| Handheld | Retroid Pocket 6 |
| SoC | Snapdragon 8 Gen 2 / SM8550 |
| RAM | 12 GB |
| SteamOS installation and boot storage | microSD card |

Other RAM variants, RP6 TOP-DPAD, Retroid Pocket Nova and other handhelds are outside this fork's validation scope. Installing SteamOS on internal UFS storage is also outside the tested configuration. Device profiles and guides inherited from upstream do not establish support or test results for this fork.

Automated source and build checks may run on development computers or CI. They do not replace hardware tests on the RP6 configuration above. Every hardware result must identify the image, kernel and relevant component versions; an untested function must be marked as untested.

See [RP6 scope and test policy](docs/RP6-SCOPE.md).

## Primary RP6 baseline (UP-02 on UP-04)

The primary SM8550 kernel in `main` is **7.2.8-sm8550-steamos**, with the accepted UP-04 suspend, recovery and boot fixes on top of UP-03. For `SOC=sm8550`, kernel builds select recipe 7.2/ROCKNIX and image builds use `kernel-sm8550/output/current` by default. GCC 15 and the locked Frame firmware inputs remain required. Select `SM8550_RECIPE=7.1` explicitly for the legacy recipe, or `SM8550_KERNEL=prebuilt` for an existing legacy bundle.

The accepted **UP-02 on UP-04 R3** is the baseline for further work in `main`; see [UP-02 acceptance](docs/RP6-UP-02.ru.md) and [the acceptance record](docs/RP6-UP-02.acceptance.json). The R3 image was clean-installed on RP6/12 GB/microSD and Steam started. Live touch uses 400 kHz I2C and bulk read; a coordinated 30-second gesture measured 119.53 evdev reports/s with no SYN_DROPPED. The user confirmed edges, dragging, multitouch, Game Mode and touch after standby. SSH uses a verified, pinned host key; permanent debugging and automatic SSH recovery remain enabled. The additional access/debug installer is applied after the sealed R3 image through `scripts/build-rp6-access-installer.py`; the image hash identifies the original sealed artifact, before this setup.

UP-04 suspend, recovery and boot fixes remain part of this baseline; see [UP-04 acceptance](docs/RP6-UP-04.acceptance.json) for its earlier s2idle and game-resume checks. Standby remains the default and s2idle is an explicit opt-in. The UP-02 checks cover standby resume. Before/after touch comparisons, full controls regression, update/rollback, broader power/game/charger matrices and CI remain separate checks. Source promotion does not publish a binary release. Local build images and caches are removed after promotion at the project owner's request; source recipes, checksums and acceptance evidence are retained.

## Development priorities

1. Correct button layout, D-pad, Steam and Quick Access buttons, and independently assignable rear buttons.
2. Reliable power-button behavior, standby, wake-up, power profiles and cooling.
3. Measured improvements to SteamOS responsiveness and game performance where feasible.

This is an experimental development fork. Inherited features and performance figures require verification on the 12 GB RP6 running from microSD. New source changes are not considered hardware-validated until the resulting image is tested on that configuration.

## Documentation

| Topic | Guide |
| --- | --- |
| Fork scope and testing | [RP6-SCOPE.md](docs/RP6-SCOPE.md) |
| microSD installation | [install.md](docs/install.md) |
| Building for SM8550 | [building.md](docs/building.md) |
| Validation status and limitations | [known-issues.md](docs/known-issues.md) |
| Updating | [updating.md](docs/updating.md) |
| Profiles, commands and SSH | [tips.md](docs/tips.md) |
| Upstream architecture reference | [HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md) |

Some guides describe upstream behavior or hardware other than RP6. Use the fork's scope above when interpreting them. Upstream releases remain [upstream releases](https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/releases); they are not releases validated by this fork.

When reporting an RP6 problem, include the 12 GB model, microSD installation, image and kernel versions, mode, steps to reproduce, expected behavior and actual result. Do not include passwords, keys or account data. The [upstream issue tracker](https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/issues) is for upstream reports.

## Upstream and credits

The original multi-device port is maintained in [hashtagbasit/SteamOS-ARM-Handhelds](https://github.com/hashtagbasit/SteamOS-ARM-Handhelds). This fork narrows development and testing to the RP6 configuration above; upstream retains its own device support and release policy.

Kernel and device work comes from [ROCKNIX](https://github.com/ROCKNIX/distribution), with groundwork from [MaSi's SM8550 project](https://github.com/MaSieS4Fun/SteamOS-ARM-SM8550). See [CREDITS.md](CREDITS.md) for acknowledgements.

## License

Project scripts and overlays are GPL-2.0. Components in `external-and-mods/` retain their own licenses. See [LICENSE](LICENSE).

## Disclaimer

Not affiliated with or endorsed by Valve. Steam and SteamOS are trademarks of Valve Corporation. This is a community adaptation of the Steam Frame ARM software; upstream support claims and measurements do not establish validation on this fork's RP6 test configuration.
