# UP-08: выпуск, обновление и откат

Статус 2026-10-04: **UP-08 принят пользователем**. Образ и пакет собраны; SSH-обновление, ручной snapshot rollback и повторная установка подтверждены на RP6. Проверка чистой установки по решению пользователя отложена до совместного образа с UP-03. Целевая конфигурация — **Retroid Pocket 6 / SM8550 / 12 ГБ RAM / microSD**.

Первый этап 2026-10-02 использовал UP-01 `db3036e73d7ca298cd56dcf2ee28e4f296e7c431`, тогда ещё без аппаратного принятия. Продолжение 2026-10-04 включает принятую пользователем UP-01 `178b2dc276afe9e6e5170e8a3eece8dd9f3e8b93` через merge `d94894a3402a9c99a9a942ecd7ab7a7b94a31663`. UP-02 и незавершённые изменения питания основного checkout сюда не включены.

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

## Первый этап 2026-10-02: проверки и оставшаяся работа

На первом этапе локально: **99 tests** в ARM64 Linux без пропусков; macOS — **99 tests, 14 Linux-пропусков**. Bash syntax и `git diff --check` прошли. GitHub Actions не запускались. Результаты и red/green журналы: `../preparation/upstream-porting/UP-08/` относительно основного checkout.

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

Обновление существующей принятой системы можно установить через SSH. **Для первого UP-08 запускать `stage` проверенной новой копией `konkr-update.py` из этого кандидата**, предварительно сверив SHA256 updater и пакета. Старый updater базы UP-01 не проверяет новое поле `release` и не сохраняет `konkrd.conf`. Новый файл можно передать в HOME и вызвать с правами администратора без предварительной установки в `/usr`: `stage` сохраняет собственную копию в приватном recovery runtime, а новый updater устанавливается уже вместе с пакетом. `stage` меняет BOOT и создаёт pending transaction; подготовка пакета и `inspect` этих действий не выполняют.

Проверка свежей установки требует записи отдельной карты. Пользовательские данные и настройки сохраняются в пределах контракта нового updater; отдельно установленный developer root helper после замены `/usr` восстанавливается по [RP6-DEVTOOLS.ru.md](RP6-DEVTOOLS.ru.md). Приёмка пользователя для UP-01 не переносится автоматически на обновление, свежую установку или откат UP-08.

## Проверки продолжения 2026-10-04

Зафиксированный build source: `201ea939973a191a7a687180b7fdabbba471f6ec`; последующие изменения этого документа не меняют байты кандидата. ARM64 Linux — **144 tests, 0 skips**; macOS — **144 tests, 27 Linux skips**. GitHub Actions не запускались. Pinned builder `sha256:4f53986876692fe70381c5f9915e912fcfd1d7d69da330fc0555bd7cf29bf4c4`, без сети.

| Артефакт | SHA256 |
|---|---|
| `steamos-rp6-up08-20261004.img`, 16447963136 bytes | `668d6fea7c2295ec02346bec843411efc0f9b705f5af143b3499ece5c04589ed` |
| `rp6-up08-20261004.tar.gz`, 4373171310 bytes | `659c33d8428f488c93d4ebb88e47dac9ffff4476cb343a8892d081323c964754` |
| KERNEL / `7.0.14-edge-sm8550` | `526e213186ef1f5955810e5a47ef2671dd22d25a1585c5149df796d99a1ed394` |

Локальный каталог результатов: `/Users/iddqd/Projects/steamos-arm/preparation/upstream-porting/UP-08/accepted-base-20261004/`. `device-attestation.json` фиксирует актуальные результаты отдельно от неизменяемого встроенного manifest. До hardware update независимая резервная копия проверена на RP6/Mac и восстановлена в отдельный Linux volume: 236582 стабильных записи совпали, 14 изменяемых Steam htmlcache records отдельно раскрыты. Копия включает затрагиваемую систему, BOOT и настройки; игровые файлы и полная карта в неё не входят.

Первое обновление с принятого UP-01: transaction `48102251-ef07-49f1-909d-69431e40240f`, новый boot `3e0ea3ec-f869-47c8-94c5-943a6a14696e`, state committed. Kernel/updater/release payload совпали с пакетом; input maps, power/profile config, protected lower/upper/etc, Steam appmanifests и Decky settings сохранились. Raw metadata result выявил ровно две дополнительные debug service/link записи, создаваемые прежним initramfs; независимая проверка подтвердила полное совпадение с принятым UP-01 backup. Raw result сохранён, объяснение вынесено в `post-apply-assessment.json`. Два изменяемых Steam userdata cache/config файла после запуска Steam указаны отдельно.

Ручной возврат проверен через supported `rollback-requested` recovery state, опубликованный под update lock после сверки полного snapshot; restore в работающем `/` не запускался. Rollback boot `847353f7-15f7-44a7-aa09-21e8bdeca12f`, state rolled-back. Все **236284** управляемые записи и их bytes/types/modes/UID/GID/xattrs/links точно совпали с physical pre-apply baseline; SHA256 inventory `569804e4c1cea1f9788daa26f83a0c7520f3aa1c7a79f93ac5a1c2ef81761010`. Все 10 capability files и отдельно Decky settings сохранены, вернулся предыдущий updater, UP08 marker отсутствует. Это ручной snapshot rollback; аппаратный power-cut, automatic failure recovery и восстановление всей карты этим не проверены.

После проверки rollback обычным `stage` выполнена повторная установка UP-08: новая transaction `bf2ce07e-8e95-4bac-b52b-b5fc1348087d`, boot `33b39743-ed4a-4de1-8b49-659e79b6bb92`, state committed/no pending/no failure. Завершённая rolled-back transaction не включалась повторно. `post-restage-result.json` подтверждает полную сверку usr/opt bytes/metadata с кандидатом (с отдельно записанными 4 точными штатными boot adjustments), сохранность protected etc/input/profiles/appmanifests/Decky settings и 10 capabilities. Необъяснённых metadata/preservation differences нет. Сохранённая диагностика текущей загрузки обновлена и отдельно проверена: pass_system_checks.

На всех трёх проверенных загрузках SSH system checks прошли: RP6 identity, early/etc overlay, InputPlumber, KONKR, Game Mode focusfix и единственный Decky loader. 2026-10-04 пользователь подтвердил: «Все описанное тобой работает и уже было протестировано в модуле UP-01». Ранее принятую функциональную базу UP-01 используем с этим подтверждением текущей работы; повторный полный список кнопок/ориентации/Steam-QAM/Decky/сети/звука/игр/standby больше не ожидается. Новый независимый прогон UP-08 и новые игровые/энергетические замеры не заявляются. Обновление, сохранность защищённых настроек, ручной snapshot rollback и повторная установка UP-08 подтверждены собственными аппаратными отчётами.

Пользователь подтвердил отсутствие запасной microSD, затем явно принял модуль: «Отметим, что 08 принят, проверю чистую установку вместе с правками 03». UP-08 отмечен accepted по этому решению. Fresh-image проверка отложена до совместного образа с UP-03 и не отмечается passed. Рабочая карта сейчас не перезаписывается. CI, interrupted recovery и media recovery не испытаны; эти ограничения сохранены отдельно от принятия модуля. Текущий кандидат остаётся beta-opt-in, перевод в default не выполнялся. UP-02, UP-03 и незавершённые изменения питания не входят в установленный кандидат UP-08.
