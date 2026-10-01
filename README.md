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

To support the original upstream developer, the upstream donation links are [Ko-fi](https://ko-fi.com/aimalb) and [PayPal](https://paypal.me/Basit2000).

## License

Project scripts and overlays are GPL-2.0. Components in `external-and-mods/` retain their own licenses. See [LICENSE](LICENSE).

## Disclaimer

Not affiliated with or endorsed by Valve. Steam and SteamOS are trademarks of Valve Corporation. This is a community adaptation of the Steam Frame ARM software; upstream support claims and measurements do not establish validation on this fork's RP6 test configuration.
