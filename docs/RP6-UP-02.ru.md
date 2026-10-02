# UP-02 — touch RP6

Статус на 2 октября 2026: подготовлен локальный кандидат переноса. Область
аппаратной приёмки: **Retroid Pocket 6 / SM8550 / 12 ГБ RAM / microSD**.
Аппаратные испытания, свежий образ и обновление пока не приняты.

## Донор и адаптация

Автор исходного исправления — Diogo Trindade,
[ROCKNIX `3829f7c5a80a8a9e78576ea5a3bb0c1ceeebb939`](https://github.com/ROCKNIX/distribution/commit/3829f7c5a80a8a9e78576ea5a3bb0c1ceeebb939).
Исходный RP6 DTS имеет SPDX `BSD-3-Clause` и copyright ROCKNIX.
[SteamOS ARM `3b01fcc60759b590a064387379b6858c2cbbb3cd`](https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/commit/3b01fcc60759b590a064387379b6858c2cbbb3cd)
содержит адаптацию source append; проектные скрипты распространяются по GPL-2.0
согласно `LICENSE`. Сохранены происхождение и авторство. Wi-Fi часть donor
commit относится к UP-03 и в этот перенос не входит.

В ROCKNIX refs `20260801` и `20260901` сенсор `focaltech,ft5426` по адресу
`0x38` находится на `&i2c_hub_3`, работает при 100000 Hz и имеет
`no-regmap-bulk-read`. Append устанавливает 400000 Hz и удаляет это свойство;
TOP-DPAD наследует RP6 DTS. Рецепты ядра, GPIO и ориентация здесь не меняются.

В проверенном локальном prebuilt KERNEL `7.0.14-edge-sm8550` оба RP6 DTB
уже используют bulk read, но шина работает при 100000 Hz. Поэтому в этом
кандидате фактическая разница — только 400000 Hz. Частота событий около
119 Hz получена автором донора на его системе; на нашем RP6 она ещё не измерена.
Это не частота панели: её следует отдельно проверять по списку режимов DRM.

## Доставка

- Source: `external-and-mods/kernel-sm8550/dts/qcs8550-retroidpocket-rp6.dts.append`.
- Prebuilt: `scripts/import-sm8550-kernel.sh` вызывает `fix-rp6-touch.py`
  после исправления paddles и перед упаковкой KERNEL, затем проверяет результат.
- Локальный beta8 image builder: `scripts/prepare-rp6-beta8-test.py`
  переносит touch вместе с module1, сохраняет источник KERNEL и записывает
  хеш helper в metadata.
- `scripts/check-rp6-input.sh` отклоняет медленную шину или отключённый bulk read
  вместе с прежними проверками карт InputPlumber, калибровки, DBus Volume Up
  и независимых GPIO57/58. Проверка вызывается перед упаковкой SM8550 образа.
- Существующий CI `rp6-input.yml` запускает touch-тесты; добавлен фильтр DTS.
  GitHub Actions в рамках этой работы не запускался.

Helper изменяет DTB только через `fdtput`. Сравниваются все свойства и узлы,
memory reservations; сохраняются compressed Image, остальные DTB, настройки
питания, панели, ориентации, задних кнопок и триггеров. Повторный запуск
на готовом payload возвращает те же байты. Неизвестный bus/сенсор, другая
частота шины, отключённый узел, неоднозначная конфигурация или повреждённый
payload приводят к ошибке до записи результата.

Проверки на рабочем компьютере:

```sh
python3 -m unittest discover -s scripts/tests -v
python3 scripts/fix-rp6-touch.py --check-boot /path/to/KERNEL
python3 scripts/fix-rp6-paddles.py --check-boot /path/to/KERNEL
bash scripts/check-rp6-input.sh /path/to/staged-rootfs /path/to/KERNEL
```

Для отдельного **локального файла** KERNEL предусмотрен `--patch-boot`
с обязательным `--expect-sha256`; выход должен быть новым файлом.
Поддерживается канонический Android boot header v0 с корректным ID и уже
принятыми paddles. Сохраняются ramdisk, second stage, cmdline и header fields;
ID пересчитывается. Подписанные/нестандартные boot layouts отклоняются.
Не применять helper к блочному устройству или непосредственно к карте.

## Остаток приёмки

- [x] Сравнить prebuilt DTB и обе source refs, сохранить донорские SHA.
- [x] Проверить два RP6 DTB, идемпотентность, отсутствие RP6, конфликт,
  сохранность свойств, compressed kernel, ramdisk и других устройств.
- [x] Подключить перенос к importer, image builder и input preflight.
- [ ] Пересобрать полный комплект source kernel/modules, включая кандидат 7.2.8.
- [ ] Собрать и проверить свежий образ и поддерживаемый пакет обновления UP-08.
- [ ] Подтвердить текущий RP6/12 ГБ/microSD, установленную версию,
  контрольные суммы и актуальную резервную копию перед записью на устройство.
- [ ] До/после одинакового непрерывного жеста измерить интервалы evdev
  `SYN_REPORT` только для touch event node; записать медиану, разброс,
  пропуски/ошибки и условия нагрузки. Частоту вывода панели записать отдельно.
- [ ] Проверить края, drag, multitouch, Game Mode/Desktop, ориентацию,
  touch после сна, все кнопки/стики, полный ход триггеров, Volume Up/Down и L4/R4.
- [ ] Испытать обновление, reboot и откат на том же устройстве.

Локальные артефакты находятся в `preparation/upstream-porting/UP-02/` рядом с
репозиторием: исходный KERNEL, кандидат, SHA256, сравнение DTB, `manifest.json`,
`validation.md`, `rollback.md`, журналы и patch. Эти файлы не устанавливались
на устройство; сохранённый KERNEL — откат офлайн-кандидата, не подтверждённая
резервная копия текущей карты.
