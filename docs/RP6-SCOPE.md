# Retroid Pocket 6 development and testing scope

This fork is exclusively for Retroid Pocket 6 with Snapdragon 8 Gen 2 (SM8550). The project owner has specified a **12 GB RAM RP6 with SteamOS installed on and booted from a microSD card** as the hardware test configuration.

## Validation boundaries

- All hardware tests and acceptance checks in this fork use this configuration.
- Results do not establish support for other RAM capacities, TOP-DPAD, Nova, Odin, AYANEO, KONKR or other devices.
- Internal UFS installation and performance are outside the tested configuration.
- Inherited profiles, scripts and guides for other hardware are upstream reference material.
- Source tests, synthetic DTB checks and CI runs on development machines are recorded separately from hardware tests.

## Recording results

Each hardware report must record RP6, SM8550, 12 GB RAM, microSD boot, image and kernel versions, relevant component versions and the test conditions. Storage-sensitive tests must also record the card model, capacity and filesystem; no single card model or capacity is prescribed by this scope.

Mark checks as passed, failed or not tested. A source check or upstream release note does not establish that a new image boots, sleeps correctly, handles all buttons or improves performance on this RP6.

Development priorities are button layout and rear buttons, then power management, then measured SteamOS and game performance. Installation and rollback checks accompany each hardware change.

## Upstream references

The base project is [hashtagbasit/SteamOS-ARM-Handhelds](https://github.com/hashtagbasit/SteamOS-ARM-Handhelds). Its broader device support and measurements remain upstream claims unless independently checked on this fork's test configuration.
