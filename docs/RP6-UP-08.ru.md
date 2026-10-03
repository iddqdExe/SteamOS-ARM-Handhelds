# UP-08: выпуск, обновление и откат

Статус: первый этап инструментов готов; после принятия UP-01 пользователем 2026-10-04 выполняется подготовка согласованного образа и обновления. Весь UP-08 **не принят**. Целевая конфигурация — **Retroid Pocket 6 / SM8550 / 12 ГБ RAM / microSD**.

Работа основана на локальном UP-01 `db3036e73d7ca298cd56dcf2ee28e4f296e7c431`: этот кандидат уже содержит исправления updater и сохранение capabilities. UP-01 остаётся неиспытанным на устройстве. UP-02 и незавершённые изменения питания основного checkout сюда не включены. Интеграцию нужно повторить на принятой базе перед выпуском.

## Что перенесено из практик доноров

| Донор и фиксированный commit | Применение к нашему сборщику |
|---|---|
| [MaSieS4Fun, release checklist](https://github.com/MaSieS4Fun/SteamOS-ARM-SM8550/blob/7eecdb23663fa88b218873a8acbe64e87df6d952/docs/RELEASE-CHECKLIST.md), `7eecdb23663fa88b218873a8acbe64e87df6d952` | Раздельные проверки сборки, образа, устройства и выпуска; контроль итоговых байтов; запрет выдавать успешную сборку за аппаратную приёмку |
| [Armada, patch accounting](https://github.com/armada-os/armada/blob/72f2a63f4b5417522887c781809b712c7b393a8a/packages/kernel/PATCHES.md), `72f2a63f4b5417522887c781809b712c7b393a8a` | Полный donor SHA, автор/лицензия, описание локальной адаптации и SHA256 патчей |
| [Pocknix, provenance](https://github.com/shuuri-labs/pocknix-os/blob/fcd5c755f1ed57ba3d219ffd2ac100bf83c672e1/PATCHES.md), `fcd5c755f1ed57ba3d219ffd2ac100bf83c672e1` | Явные версии входов и различение донорского происхождения и локальных изменений |

Адаптированы принципы проверки и учёта. Донорские скрипты/бинарные файлы не копировались. Лицензии project software проверены на этих SHA: MaSieS4Fun — GPL-2.0, Armada — GPL-2.0-or-later, Pocknix — GPL-2.0. Odin-specific MD5, systemd раскладка и Fedora/Arch база не заменяют наш контракт RP6/Frame. Frame 0.3.0 не выбирался.

## Manifest сборки и выпуска

`scripts/build-rp6-release-manifest.py create` записывает:

- module/task IDs, точную аппаратную границу, channel и decision;
- local SHA, состояние Git и SHA256 незакоммиченных файлов для явно разрешённого beta-кандидата;
- donor URL/SHA, авторов, лицензию и локальную адаптацию;
- проверенные SHA256 объявленных входных файлов и версии компонентов из recipe;
- фактический release и SHA256 KERNEL, kernel payload и ramdisk, соответствующие modules, firmware, локальные патчи, выбранные runtime файлы и их modes/symlinks;
- версии инструментов из recipe и Python/архитектуру среды записи, отдельные source/CI/device/fresh-image/update/rollback результаты и backup ID.

Версии компонентов в recipe — декларации исполнителя. Они не являются результатом запуска этих компонентов на RP6. Inventory фиксирует байты staged rootfs; существующие input/session preflight проверяют их доставку.

Recipe должна содержать `module`, `tasks`, `donors`, `components`, `inputs`, `transfers`, `validation`, `rollback`. Для загружаемого входа нужны `id`, `path`, фиксированный HTTPS `url`, `sha256`. Локальный зафиксированный артефакт использует `kind: "local-artifact"`, полный `source_sha`, `artifact_name`, `id`, `path`, `sha256`, без вымышленного URL. Все входы должны быть обычными файлами. Для донора нужны полный 40-символьный `sha`, `url`, `authors`, `license`, `adaptation`. Пример структуры:

```json
{
  "module": "UP-08",
  "tasks": ["UP-08.1", "UP-08.3", "UP-08.5"],
  "donors": [{
    "url": "https://github.com/MaSieS4Fun/SteamOS-ARM-SM8550",
    "sha": "7eecdb23663fa88b218873a8acbe64e87df6d952",
    "authors": ["MaSieS4Fun"], "license": "GPL-2.0",
    "adaptation": "release checklist adapted for RP6; no donor code copied"
  }],
  "components": {"frame": "ACTUAL_BUILD_AND_VERSION"},
  "inputs": [{"id": "frame-bundle", "path": "/work/inputs/verified.raucb",
              "url": "https://steamdeck-images.steamos.cloud/vr/FIXED_BUILD/FIXED_BUNDLE.raucb",
              "sha256": "REPLACE_WITH_VERIFIED_SHA256"}],
  "transfers": [{"module": "UP-01", "decision": "untested"}],
  "validation": {"source": "not-run", "ci": "not-run", "device": "not-run",
                 "fresh_image": "not-run", "update": "not-run", "rollback": "not-run"},
  "rollback": {"backup_id": null, "procedure": "rollback.md"}
}
```

Заменить placeholders реальными данными и перечислить **все** использованные входы. Запись неполного recipe не доказывает воспроизводимость: аудит остальных сетевых загрузок и полный lock toolchain ещё открыты.

```bash
python3 scripts/build-rp6-release-manifest.py create \
  --recipe /work/rp6-recipe.json --rootfs /work/rootfs \
  --kernel /work/kernel-prebuilt/7.0.14-edge-sm8550/boot/KERNEL \
  --output /work/build-manifest.json

# Полный builder: manifest относится к реально перепакованному BOOT/KERNEL.
SOC=sm8550 RP6_RELEASE_RECIPE=/work/rp6-recipe.json \
  bash make-steamos-sm8650.sh --img /work/rp6-candidate.img
```

Builder сохраняет `.inputs.json` до выделения образа, `.build-manifest.json` с фактическим перепакованным KERNEL, встраивает его в `/usr/share/steamos-arm/release-manifest.json` и создаёт внешний `.release.json` с SHA256 итогового image. Внешний manifest исключает циклическую зависимость от SHA256 собственного образа. Существующие outputs не заменяются. Если сборка остановилась, sidecars/частичный image следует сохранить для диагностики и выбрать новое имя.

По умолчанию channel — `beta-opt-in`, decision — `untested`. Dirty source запрещён; `RP6_RELEASE_ALLOW_DIRTY=1` разрешает учёт локальных изменений только для beta. `RP6_RELEASE_CHANNEL=default` требует clean source, accepted для каждого включённого переноса, backup ID и passed для всех шести областей, с реальными checksummed evidence-файлами в recipe (`evidence.<check>.path/sha256`). Успешный source test этого не заменяет. Рецепт без rejected переносов — обязательное условие любого кандидата.

Этот этап добавляет явный режим UP-08. Старый путь без recipe пока сохранён; он не является подтверждённым выпуском UP-08.

## Пакет обновления и совместимость

```bash
python3 scripts/build-update-package.py \
  --rootfs /work/mounted/root --home /work/mounted/home/steamos \
  --kernel /work/mounted/boot/KERNEL --soc sm8550 --device 'Retroid Pocket 6' \
  --version rp6-up08-candidate --output /work/rp6-update.tar.gz
```

Если manifest встроен в staged rootfs, builder автоматически включает его в поле `release` format-1 пакета. Можно явно передать `--release-manifest /work/build-manifest.json`. KERNEL и modules должны соответствовать manifest. Package metadata и встроенный manifest сравниваются до замены системных файлов; проверяются checksums, modes и symlinks. Старые format-1 пакеты без `release` остаются совместимыми, но не получают статус UP-08.

Updater сохраняет `/etc/konkrd.conf` в нижнем и верхнем `/etc`, InputPlumber remaps, `/var/lib/konkrd`, домашние game profiles, Steam данные и Decky settings. Замена managed Decky плагинов и loader остаётся частью backup/restore. Пользовательские данные вне этих managed директорий не перезаписываются.

В Linux fixtures проверены повреждение payload до root switch, прерывание после реальной частичной замены `usr`, восстановление rootfs/KERNEL, сохранение `appmanifest_*.acf` и повторная очистка терминального `aborted`. Эти тесты не доказывают восстановление после физического отказа microSD или повреждения BOOT; аппаратный rollback остаётся отдельным испытанием.

## Проверки и оставшаяся работа

Локально: **99 tests** в ARM64 Linux без пропусков; macOS — **99 tests, 14 Linux-пропусков**. Bash syntax и `git diff --check` прошли. GitHub Actions не запускались. Результаты и red/green журналы: `../preparation/upstream-porting/UP-08/` относительно основного checkout.

Общие checkbox UP-08.1…UP-08.5 в плане остаются открытыми: ни один из них целиком этим первым этапом не закрыт. Далее нужны полный lock всех загрузок/toolchain, чистая сборка зафиксированного кандидата с обязательными input/session/power проверками, пакет обновления этого же комплекта, испытание свежей установки и обновления принятой базы на RP6, проверка восстановления карты и решение о включении в default. Образы и разделы устройства в этом этапе не изменялись.

## Продолжение после принятия UP-01

`scripts/prepare-rp6-release.py` автоматически собирает opt-in кандидат из зафиксированного образа UP-01. Входом служит весь образ с проверенным SHA256; компоненты базового дистрибутива наследуются из него. Это повторяемая сборка из запечатанного артефакта, а не пересборка дистрибутива с исходного Frame rootfs. Recipe прямо содержит `assembly.type: "sealed-up01-image"` и `clean_distro_source_build: false`.

Сборщик требует чистый Git с совпадающим `assembly.source_sha`, точный размер/разметку образа, ожидаемый SHA256 KERNEL и локальное Linux/root окружение. Контейнер фиксируется полным image ID в `toolchain.builder_image`, архитектура — в `builder_architecture`; переменная `RP6_BUILDER_IMAGE` должна совпасть. Запускать этот контейнер с `--network none`; скрипт не выполняет загрузок. Все новые имена outputs обязательны, частичные результаты сохраняются при отказе.

BOOT монтируется только для чтения, HOME — с `ro,noload`. До и после установки сравниваются содержимое, владельцы, modes, symlinks и xattrs всех записей rootfs. Допустимы только `/usr/share/konkr-update/konkr-update.py` и `/usr/share/steamos-arm/release-manifest.json`. Input/session/standby/initramfs проверки выполняются до и после; остальные компоненты сохраняются. Пакет создаётся из этого же rootfs/BOOT/HOME и дополнительно проверяется на сохранение владельцев, modes и xattrs, включая capabilities. В конце выполняются проверки файловых систем без исправлений и сравнение SHA256 областей BOOT и HOME.

```sh
RP6_BUILDER_IMAGE=sha256:EXACT_LOCAL_IMAGE_ID python3 scripts/prepare-rp6-release.py \
  --recipe /work/recipe.json --image /work/rp6-up08.img \
  --package /work/rp6-up08.tar.gz --version rp6-up08-20261004
```

Outputs: образ, пакет с `.sha256`, `.build-manifest.json`, `.release.json` и `.validation.json`. Пакет и временный staging следует создавать на Linux файловой системе с поддержкой xattrs/capabilities; после проверки готовый tar можно экспортировать на Mac. Запись на microSD не выполняется.

Обновление существующей принятой системы можно установить через SSH штатным updater. Проверка свежей установки требует записи отдельной карты. Пользовательские данные и настройки сохраняются в пределах контракта updater; отдельно установленный developer root helper после замены `/usr` восстанавливается по [RP6-DEVTOOLS.ru.md](RP6-DEVTOOLS.ru.md). Приёмка пользователя для UP-01 не переносится автоматически на обновление, свежую установку или откат UP-08.
