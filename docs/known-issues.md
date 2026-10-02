# RP6 validation status and limitations

This fork targets **Retroid Pocket 6, Snapdragon 8 Gen 2 / SM8550, 12 GB RAM, with SteamOS installed on and booted from microSD**. See [RP6-SCOPE.md](RP6-SCOPE.md) for the hardware test policy.

## Current development scope

The priority is button layout and rear buttons, then power management, then measured SteamOS and game performance. Each change needs its own image and hardware acceptance results. This page does not mark those modules complete.

## Validation limits

- Other RP6 RAM variants, TOP-DPAD, Nova and other handhelds have not been validated by this fork.
- Internal UFS installation is outside the tested configuration.
- Battery, standby, thermal and performance figures from Pocket FIT or other upstream devices do not apply to this RP6 without measurement.
- Automated checks and successful builds do not establish hardware acceptance of a new image.
- UP-01 hardware acceptance found a black physical screen after software standby
  in DMC, with audio and game rendering still running. QAM was also invisible;
  an explicit panel wake and a separate DPMS off/on cycle did not recover it.
  A reboot restored visible Game Mode. An isolated test reproduced a premature
  DSI brightness write returning EPROTO after the panel-on request; retrying
  after panel unblank restored the display. The RP6 standby script now waits
  for unblank and reports restoration failures. Three isolated display cycles
  passed, but full standby and delivery of this fix in the image remain
  unaccepted. See [RP6-UP-01.ru.md](RP6-UP-01.ru.md).

For upstream device reports, consult the [upstream tracker](https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/issues). Keep the device, image and component versions attached to every result.
