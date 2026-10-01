# Internal storage

**Fork scope:** internal UFS installation is outside this fork's tested configuration. All RP6 hardware testing uses the 12 GB RAM Snapdragon 8 Gen 2 / SM8550 model with SteamOS on microSD. The guide below applies to upstream devices and is not an RP6 installation procedure. See [RP6-SCOPE.md](RP6-SCOPE.md).

Right now this is for the KONKR Pocket FIT and AYANEO Pocket S2 only. 8 Gen 2 devices run from the SD card for now.

Once it runs from the SD card, open **Easy UFS Installer** in Desktop Mode, pick how much space Android keeps, and choose whether your games come along. This erases Android's user data (Android itself stays and sets itself up again), and the old partition table is saved on the SD card so you can give the space back later.

When it's done, set **Boot source** to **Internal** in the ABL menu. If you installed an older version to internal before, run **UNINSTALL CFW** in the ABL menu first.

More details in [external-and-mods/ufs-install](../external-and-mods/ufs-install/README.md).
