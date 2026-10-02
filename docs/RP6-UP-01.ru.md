# UP-01: сессия Steam, QAM, overlays и Decky

Кандидат разработан в `codex/up-01` от `main` `fa389fb28dc624418e3f3436e20a81c6bb87c88a`.
Область приёмки: **Retroid Pocket 6 / SM8550 / 12 ГБ RAM / microSD**.
Исходники и доставка проверяются отдельно от cold boot, reboot и испытаний игры.
Изменения рабочего дерева модуля питания в основной копии не включены.

## Оценка донора и решения

Донор: [hashtagbasit/SteamOS-ARM-Handhelds](https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/tree/682281c0d82319324fd3f7d09b34d0f7005148fc),
зафиксированный срез beta10 `682281c0d82319324fd3f7d09b34d0f7005148fc`.
Лицензия перенесённых скриптов и focusfix — GPL-2.0; авторы hashtagbasit и FearlessSpiff.
Происхождение доставляется в `/usr/share/steamos-arm/up-01.json` и manifest обновления.

| Группа | Оценка кода | Перенос и адаптация |
|---|---|---|
| VR layers, `c9d87d6` + `4181b9c` | Применимое узкое изменение; первый commit аварийно завершался при отсутствии manifest под `set -e` | Только RPO/FDM manifests перемещаются вне Vulkan search path. Отсутствующие файлы допустимы, MangoHud/LSFG сохраняются |
| QAM, `4a12b47` | Воспроизведён отказ восстановления Iconic и уже Normal окна; донор испытан на Pocket FIT, не на нашем RP6 | Перенесён переход WM_STATE Iconic → Normal с ограничением частоты. После задержки повторно проверяются focus, window и app. ARM64 бинарник собран из изменённого C |
| Mango/startup, `c0dcada` | Постоянный путь исправляет потерю пресета. Донорский тайм-аут молча разрешает Steam стартовать без настроек; файл wait нужно явно доставлять нашим сборщиком | Пресет сохраняется в runtime текущего login; env публикуется атомарно; ожидание ограничено 5 s и завершается диагностикой при отказе |
| Ранний `/etc`, `f08eaa6` | Устраняет чтение systemd bare `/etc`; поздний fallback не гарантирует работающие enabled units | Overlay монтируется после update recovery, до switch_root; отказ оставляет boot в аварийной оболочке. Helper включён в оба пути initramfs |
| Decky, `20dec11` + `6799cc4` | Фактическая версия — prerelease `v3.2.10-pre1`; одной версии без digest недостаточно для воспроизводимости | Официальный asset закреплён SHA256, проверяется и offline cache. Добавлен Wants для network-online; локальный loader не скачивается при boot |
| Обновление и откат | Старый пакет переносил плагины и пропускал loader | `homebrew/services` сохраняется, переносится и откатывается; Linux capabilities восстанавливаются из tar. Settings/data/logs не заменяются. Старые пакеты и snapshots сохраняют прежнее поведение |

В исходном плане Mango был ошибочно связан с `f5361f9422e3d7c5aaee04773b13928a98f4787a`:
этот merge относится к Bluetooth REDMAGIC 6. Нужные изменения находятся в
`c0dcada7d40c7ff1dca2a09634b1ae2d73d671a9` (PR26). Остальной код PR26 для Odin 3 не переносился.
Из beta10 не переносились kernel, touch, сон, GPU scheduling и альтернативное управление громкостью.

## Доставка

`apply-overlays.sh` использует `install-rp6-session.sh` для сессии/units и проверенного Decky.
Настройки InputPlumber и KONKR не изменяются установщиком сессии.
Контроль состава: `python3 scripts/check-rp6-session.py ROOTFS KERNEL [--home STEAMOS_HOME]`.
Он проверяет ARM64 focusfix, pinned Decky, реальные init/helper в BOOT и matching modules.
Корректный rootfs с прежним BOOT не проходит эту проверку.

Prebuilt importer собирает внешний ramdisk с новым helper.
Для существующего нашего busybox BOOT допустима отдельная перепаковка:

```sh
python3 scripts/repack-rp6-initramfs.py KERNEL KERNEL-UP01 --expected-sha256 FULL_SHA256
```

Скрипт требует контрольную сумму, проверяет boot ID, сохраняет compressed Image, DTBs,
cmdline и адреса, сохраняет прочие файлы ramdisk и пишет только новый файл.
Dummy/embedded initramfs отвергается: для `EMBED_INITRAMFS=1` нужен
`external-and-mods/kernel-sm8550/build.sh --repack-boot`, пересобирающий Image.
Свежий source build и embedded kernel пока не собраны; изменение проверено для внешнего ramdisk.

Локальный образ-кандидат можно получить только в Linux от известного регулярного файла:

```sh
python3 scripts/fetch-decky-loader.py
python3 scripts/prepare-rp6-session-test.py BASE.img UP01.img \
  --expected-sha256 FULL_BASE_SHA256 --update-package UP01.tar.gz
```

Это производный тестовый образ, а не чистая сборка всего дистрибутива.
Пакет нужно собирать в Linux filesystem с xattrs и разным регистром имён;
в Docker на macOS используйте native volume для package output, затем копируйте готовый tar.gz.
Пакет ограничен моделью `Retroid Pocket 6`; BOOT и rootfs проверяются как комплект.
При первом обновлении со старым updater нужно до staging доставить текущий проверенный
`konkr-update.py`: конфигурационный установщик ввода уже выполняет этот bootstrap;
установщик сессии также включает новый engine. Старый engine не переносит loader из пакета UP-01.
Факт применения файлов не равен успешной новой загрузке.

## Проверки и открытая приёмка

- ARM64 Linux: 80 тестов, без пропусков; реальные сценарии Xvfb проверяют восстановление игры,
  исключение Steam и ограничение частоты. Проверены upgrade/rollback loader, пользовательские maps/settings,
  malformed/missing cache, отсутствующий env, повторный вход, SHA/boot ID и отказ embedded repack.
  Реальный security.capability проходит tar extraction → upgrade → rollback.
- Реальный overlay mount в отдельном Linux mount namespace: enabled test unit появляется до systemd,
  повторный вызов не перемонтирует `/etc`, upper сохраняется после unmount.
- macOS: 80 тестов, 9 Linux/Xvfb/root сценариев пропущены; это не заменяет Linux прогон.
- Проверены shell syntax и отсутствие whitespace ошибок. Workflow `rp6-session.yml` добавлен;
  удалённый GitHub Actions запуск не выполнялся.
- На RP6 ещё нужны cold boot/reboot, enabled test service после reboot/update, Game Mode/Desktop,
  fullscreen QAM, MangoHud и KONKR Control при старте без сети и появлении сети позднее,
  отсутствие второго loader, прежние L4/R4/триггеры/Volume Up и звук/сон.

UP-01 пока **кандидат для аппаратной проверки**, checkbox приёмки исходного плана не отмечены.
Decky prerelease остаётся явно закреплённым тестовым компонентом.

Первая загрузка кандидата на RP6 остановилась на `ETC OVERLAY FAILED` до systemd.
Проверка фактического импортированного ядра выявила `CONFIG_OVERLAY_FS=m`, хотя
фрагмент нашей новой source-сборки задаёт `y`. В минимальном initramfs отсутствует
`/sbin/modprobe`, поэтому автоматическая загрузка модуля до `switch_root` не работает.
Helper теперь при отсутствии OverlayFS в `/proc/filesystems` вызывает `modprobe`
через `chroot` в смонтированный rootfs с соответствующими модулями ядра.
`early-etc.log` сохраняет диагностику; недоступный лог не блокирует корректный mount.
Проверены регрессии модульного/builtin OverlayFS, отказ загрузчика и недоступный лог,
реальный BusyBox из BOOT и dry-run kmod в rootfs образа без `/proc` и `/sys`.
Это исправление требует повторной аппаратной загрузки; исходный кандидат не принят.

## Откат

До установки сохранить полный backup принятой microSD и отдельный комплект BOOT/rootfs/HOME loader.
Сверить модель, носитель и SHA256; игры хранить как `steamapps` + `appmanifest_*.acf`,
сохранения и конфигурацию — отдельно. В производном кандидате остаётся `KERNEL-before-UP-01`;
он не заменяет полный backup и не является автоматическим boot fallback.

Обновлятор сохраняет согласованные старые `/usr`, `/opt`, `/etc`, persistent upper,
плагины, `homebrew/services` и BOOT. Проверен откат файлов в временных Linux roots.
Если boot не дошёл до recovery, возвращать принятую карту/образ с компьютера.
Ручной возврат одного KERNEL нельзя считать откатом всей сессии/Decky.
