# Updating

**Fork scope:** this is the upstream update procedure. This fork validates only Retroid Pocket 6, Snapdragon 8 Gen 2 / SM8550, 12 GB RAM, with SteamOS on microSD. Update and recovery behavior must be checked for the specific RP6 image; the upstream rollback description below is not a guarantee that an unbootable kernel will recover automatically. See [RP6-SCOPE.md](RP6-SCOPE.md).

From v1.2 on, new versions install over your current system and keep your games, saves, accounts and Wi-Fi.

1. Download the update package for your chip from [Releases](https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/releases).
2. Open **SteamOS Update** in Desktop Mode and pick the package.
3. Paste its SHA-256 from the release page and hit **Restart and install**.

If the update gets interrupted, it rolls back on the next boot. An update package only installs on the devices it was made for, so you can't grab the wrong one by accident.

Coming from v1.1? That one has no updater yet, so flash v1.2 once.
