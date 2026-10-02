# План переноса функционала из других репозиториев в SteamOS ARM для RP6

> **Для исполнителя:** использовать `superpowers:executing-plans` при реализации задач по порядку. Checkbox отмечается только после проверки соответствующего результата. Этот документ задаёт план; переносы пока не выполнены.

**Цель:** перенести полезные исправления и функции из актуальных ARM handheld проектов в `iddqdExe/SteamOS-ARM-Handhelds`, сохранив принятую работу управления и доставляя результат через воспроизводимые образы и обновления.

**Архитектура:** Steam Frame rootfs остаётся базой форка. Переносятся отдельные патчи и адаптированные компоненты; Android/proot, Fedora bootc и Arch служат донорами решений. Каждое изменение проходит сравнение исходников, проверку доставки, испытание на RP6 и решение о включении.

**Стек:** shell/Python сборка и установщики, Linux/DTB/initramfs, systemd, InputPlumber, KONKR, gamescope, Mesa/Turnip, FEX/Proton и Decky.

**Основание:** запрос на отдельный модульный план переноса; [общий Roadmap](RP6-ROADMAP.ru.md), [область проверки](RP6-SCOPE.md), [текущее питание](RP6-POWER.ru.md). Срез источников — **2 октября 2026 года**. Идентификаторы `UP-01…UP-08` отделены от номеров модулей Roadmap.

## Исходная база и границы

- Цель приёмки: **Retroid Pocket 6 / SM8550 / 12 ГБ RAM / microSD**. Результаты Odin, Thor, Pocket FIT и RP6 8 ГБ не заменяют испытание этой конфигурации.
- Опубликованный локальный HEAD при исследовании: `69bca976449a5cebfabf6e64dcd678ef84514911`; база upstream — `5ddfd5ccbc5c76b00526b1279c0adb35b61e08fc`. В рабочем дереве уже идёт модуль питания; перед реализацией нужна новая фиксация состояния.
- По исходникам сейчас: Frame `20260925.6175226 / 0.5.0`, основной импортируемый kernel `7.0.14-edge-sm8550`, Mesa recipe `26.2.3`. Опциональный рецепт Linux `7.2.8` с GCC 15 уже существует: его следует довести и проверить, а не создавать заново.
- В форке уже есть UART reassembly, исправления L4/R4, триггеров и Volume Up через InputPlumber DBus. Их повторный перенос не считается новой функцией. Upstream keyboard/hotplug вариант Volume Up сначала сравнивается с принятым DBus решением.
- Аппаратная приёмка питания открыта. В документации есть перемежающийся отказ подготовки звука и сообщение о потере 40 п.п. заряда за 7 часов ожидания; причина расхода ещё не установлена. Новые патчи сна должны сохранять диагностику и исправления текущего модуля 2.

## Приоритеты и зависимости

Порядок выбора: **стабильность → производительность → автономность**. P1 — прямые исправления и обязательная доставка; P2 — согласованные изменения платформы; P3 — измеряемые эксперименты; P4 — пользовательские инструменты. Зависимости определяют порядок испытаний. Внутри модуля независимые изменения проверяются отдельно, чтобы регрессия имела понятную причину.

| Модуль | Приоритет | Переносимый результат | Зависимости | Связь с Roadmap |
|---|---|---|---|---|
| UP-01 | P1 | Стабильная сессия Steam, QAM, overlays и Decky | Зафиксированная рабочая база | 3, 7 |
| UP-02 | P1 | Быстрый touch RP6 с сохранением управления | База принятого модуля 1 | 1, 6 |
| UP-03 | P2 | Проверенный kernel 7.2.8, SD, GPU priorities, Wi-Fi | UP-02 проверен на кандидате ядра; UP-01 для сравнения сессии | 5, 6 |
| UP-04 | P2 | Полный эксперимент s2idle и исправление USB-PD | UP-03; актуальная диагностика модуля 2 | 2 |
| UP-05 | P3 | CPU scheduling и zram, выбранные по замерам | UP-01; UP-03 для сравнения политик на новом ядре | 3 |
| UP-06 | P3 | Совместимость FEX, согласованные графика и звук | UP-03; фиксированная политика UP-05 для замеров | 7 |
| UP-07 | P4 | Профили игр и управление совместимыми компонентами | Принятые интерфейсы UP-05/UP-06; Decky из UP-01 | 3, 7, 8 |
| UP-08 | P1, в каждом модуле | Образ, обновление, manifest и проверенный откат | Выполняется для каждого переноса; итог — после выбранных модулей | 4, 5, 8 |

Первый пакет: UP-01 → UP-02 → UP-03. Затем UP-04 отдельно от экспериментов UP-05/UP-06; UP-07 использует уже проверенные механизмы. UP-08 сопровождает все пакеты и завершает интеграцию. Отказ от экспериментального решения допустим по результатам сравнения и фиксируется явно.

## Общие условия реализации

- [ ] Перед первым изменением сохранить local SHA, `git status`, версии установленной системы, SHA256 KERNEL/rootfs и состояние текущего модуля 2. Согласовать точку интеграции его незавершённых изменений; не заменять рабочее дерево донорской веткой целиком.
- [ ] Для каждого переноса проверить отсутствие эквивалентного исправления, зависимости и лицензию конкретного компонента; сохранить автора, исходный commit и локальную адаптацию. Перед использованием более нового donor HEAD обновить сравнение.
- [ ] Сначала подготовить проверяемый патч, rootfs/BOOT артефакты и процедуру отката. Для изменений поведения добавить проверку реального сценария отказа, затем проверить исправление. Проверки исходников и CI записывать отдельно от устройства.
- [ ] Перед аппаратным изменением проверить точную модель, карту и контрольные суммы; иметь проверенный backup затрагиваемых разделов и способ восстановления. Сохранить игры с `steamapps` и соответствующими `appmanifest_*.acf`, а сохранения и настройки — отдельно.
- [ ] Для каждого принятого переноса выполнить UP-08: результат должен работать в свежем образе и после поддерживаемого обновления. Точечная установка служит испытанию, но не закрывает доставку.

Артефакты реализации сохранять в локальном каталоге `../preparation/upstream-porting/UP-XX/` относительно корня репозитория. В Git включать инструкции, код и обезличенный итог, объёмные журналы/образы хранить отдельно. Минимальные результаты: `manifest.json`, `validation.md`, `rollback.md`.

`manifest.json` должен содержать module/task ID, donor URL и полный SHA, local SHA и состояние дерева, версии компонентов/toolchain, SHA256 патчей/KERNEL/образа, модель/RAM/носитель, результаты source/CI/device, решение `accepted/rejected/untested` и идентификатор backup/отката. Не добавлять пользовательские секреты.

## Области проверки

| Возможная регрессия | Где проверять |
|---|---|
| DTB обновлён, но исчезли L4/R4, триггеры или Volume Up | UP-02 и входной контроль каждого образа UP-08 |
| Служба включена вручную, но не видна systemd после reboot/update | UP-01: initramfs и `/etc`; UP-08: обновление |
| QAM оставляет полноэкранную игру чёрной/свёрнутой; overlays теряют конфигурацию | UP-01: Game Mode и Desktop |
| Сон прервался либо проснулся без звука, подсветки, сети или ввода | UP-04: короткие циклы, игра, зарядка и длительное ожидание |
| FEX, Turnip, loader и gamescope имеют несовместимые ABI/архитектуры | UP-06/UP-07: согласованный комплект и откат всего комплекта |

## UP-01 — Steam, QAM, overlays и Decky

**Результат:** сессия запускается предсказуемо, игра восстанавливается после QAM, включённые службы переживают reboot, плагины Decky работают.

**Донор:** [SteamOS ARM v1.3-beta10][frame-release]. Переносимые группы: [VR layers `c9d87d…`][vr-layers] + [исправление `set -e` `4181b9…`][vr-followup]; [focusfix `4a12b4…`][focusfix]; [MangoHud/startup PR22 `f5361f…`][mangohud]; [ранний `/etc` overlay `f08eaa…`][etc-overlay]; [Decky `20dec1…`][decky] + [network ordering `6799cc…`][decky-network].

**Файлы:** `scripts/apply-overlays.sh`, `steamos-overlay/usr/lib/steamos/gamescope-session`, `sm8650-overlay/usr/src/konkr-focusfix/konkr-focusfix.c`, `sm8650-overlay/usr/lib/systemd/system/plugin_loader.service`, `external-and-mods/kernel-common/initramfs/init`, `scripts/import-sm8550-kernel.sh`, `external-and-mods/kernel-common/build.sh`. Unit с ожиданием окружения Steam адаптировать по фактическому пути в staged rootfs.

- [ ] **UP-01.1 — Vulkan/QAM.** Удалять только Frame RPO/FDM manifests с обработкой отсутствующих файлов; сохранить MangoHud/LSFG. Адаптировать восстановление свёрнутого окна. Проверить QAM поверх fullscreen игры, возврат фокуса, переключение Game Mode/Desktop.
- [ ] **UP-01.2 — Запуск overlays.** Перенести постоянный путь конфигурации mangoapp и ожидание `gamescope-steam.env`. Проверить медленный запуск, повторный вход и отсутствие нужного файла: ограниченное ожидание должно завершаться понятной ошибкой.
- [ ] **UP-01.3 — `/etc` до systemd.** Перенести mount в initramfs с сохранением текущей схемы rootfs/overlay. Проверить порядок mount и включённую тестовую службу после reboot/update. В prebuilt пути проверить внешний ramdisk импортёра и перепаковать реально используемый boot artifact. В source пути `EMBED_INITRAMFS=1` требует пересборки Image со встроенным initramfs; замена dummy ramdisk или одного rootfs эту задачу не закрывает.
- [ ] **UP-01.4 — Decky.** Закрепить фактическую donor версию `v3.2.10-pre1`, а не округлённое имя из release notes; добавить контроль загружаемого артефакта. Проверить backend KONKR Control, старт без сети и появление сети позднее, отсутствие дублирующего loader.
- [ ] **UP-01.5 — Доставка.** Выполнить UP-08 для каждой группы, включая комплект KERNEL/initramfs/modules при UP-01.3. Записать отдельный rollback сессии/Decky и BOOT; принять только после свежего входа и обновления.

**Приёмка:** тесты сценариев запуска/ошибок, затем на RP6 — cold boot, reboot, Game Mode/Desktop, QAM и работа KONKR Control. Откат возвращает согласованные прежние скрипты, units, Decky и boot artifact.

## UP-02 — Touch RP6 и сохранение управления

**Результат:** перенос 400 kHz I2C и bulk read для сенсора RP6 без изменений принятой раскладки.

**Доноры:** [ROCKNIX `3829f7…`][touch] и адаптация [SteamOS ARM `3b01fc…`][wifi-touch]. У автора ROCKNIX получено около 119 Hz событий сенсора; это ориентир для проверки, не доказанный результат нашего устройства и не частота обновления панели.

**Файлы:** `external-and-mods/kernel-sm8550/dts/qcs8550-retroidpocket-rp6.dts.append`, `scripts/import-sm8550-kernel.sh`, `scripts/fix-rp6-paddles.py`, `scripts/check-rp6-input.sh`. Создать отдельный идемпотентный helper `scripts/fix-rp6-touch.py` для prebuilt пути и `scripts/tests/test_rp6_touch.py`.

- [ ] **UP-02.1 — Сравнение DT.** Найти нужный I2C node и touchscreen по совместимости в обеих версиях ядра; перенести `clock-frequency = 400000` и снятие `no-regmap-bulk-read` только там, где они нужны.
- [ ] **UP-02.2 — Два пути сборки.** Добавить source DTS append и точечное изменение RP6 DTB в импортируемом KERNEL через `fdtput`. Проверить повторный запуск, несколько appended DTB, отсутствие RP6 и конфликтующую конфигурацию. Сохранить compressed kernel, ramdisk, прочие DTB и свойства задних кнопок; не выполнять DTS round-trip.
- [ ] **UP-02.3 — Контроль управления.** Расширить preflight и проверить принятые карты/DBus Volume Up, полный диапазон триггеров, GPIO57/58 и L4/R4. UART reassembly и Volume Up повторно не переносить. Armada trigger calibration исследовать отдельно только при воспроизведённом дефекте RP6.
- [ ] **UP-02.4 — Устройство.** Измерить интервалы evdev touch при одинаковом жесте до/после; проверить края, drag, multitouch, ориентацию и touch после сна. Повторить тест кнопок, стиков, триггеров, громкости, L4/R4.
- [ ] **UP-02.5 — Доставка.** Выполнить UP-08 для prebuilt и source кандидатов; для отката сохранить исходный KERNEL и его SHA256. Зафиксировать фактическую частоту touch отдельно от DRM mode list.

**Приёмка:** сохранены принятые органы управления, изменение DT доставляется обоими поддерживаемыми путями, измерение touch на RP6 подтверждает результат без новых пропусков/ошибок. При проблеме возвращается предыдущий KERNEL.

## UP-03 — Kernel 7.2.8, microSD, приоритеты GPU и Wi-Fi

**Результат:** собственный согласованный SM8550 kernel/modules/firmware, пригодный для следующих переносов.

**Донор:** существующий локальный рецепт и SteamOS ARM: [SD UHS-I `18667d…`][sd], [GPU queue priorities `1da337…`][gpu-priority], Wi-Fi часть [ath12k `3b01fc…`][wifi-touch].

**Файлы:** `external-and-mods/kernel-sm8550/soc.env`, `external-and-mods/kernel-sm8550/build.sh`, `external-and-mods/kernel-common/build-gcc15.sh`, `external-and-mods/kernel-common/steamos.config`, `external-and-mods/kernel-sm8550/patches/`, его `dts/`, `scripts/apply-overlays.sh`, `make-steamos-sm8650.sh`.

- [ ] **UP-03.1 — Воспроизводимый рецепт.** Зафиксировать ROCKNIX ref, Linux 7.2.8, GCC 15, config и порядок патчей; сравнить уже включённые исправления. Собирать в Linux окружении с подготовленными `WORK/ROCKNIX_DIR`; wrapper GCC 15 требует путей внутри своего mount и static BusyBox.
- [ ] **UP-03.2 — SD.** Проверить donor снятие `sdhci-caps-mask` и реальные negotiated modes/ошибки карты. Исправление устраняет регрессию нового ядра; оно не означает обещанный рост относительно текущего 7.0.14, где SDR104 уже доступен.
- [ ] **UP-03.3 — GPU/Wi-Fi.** Перенести исправление отображения GPU queue priorities и фактическую передачу ath12k scan priority. Проверить отсутствие эквивалента в выбранной базе; не переносить связанные изменения других SoC. Измерить QAM/UI под нагрузкой и reconnect RP6, а не использовать замеры Odin.
- [ ] **UP-03.4 — Полный комплект.** Собрать KERNEL, initramfs, matching modules и firmware; прогнать UP-02/preflight. Пользовательское окружение оставить фиксированным для сравнения с предыдущим ядром: Mesa/FEX/rootfs одновременно не обновлять.
- [ ] **UP-03.5 — Приёмка и доставка.** Проверить cold boot/reboot, microSD чтение/запись на тестовом файле, Wi-Fi, звук, ввод, Game Mode и игру. Выполнить UP-08. Прежний kernel/modules/initramfs комплект должен оставаться доступен для ручного восстановления.

**Приёмка:** нет boot/storage/input regressions, версия modules совпадает с kernel, журнал не показывает новые ошибки SD/GMU/ath12k, QAM остаётся отзывчивым. Переход на kernel 7.2.8 не меняет режим сна по умолчанию автоматически.

## UP-04 — S2idle, диагностика сна и USB-PD

**Результат:** отдельный проверенный путь kernel suspend с возвратом текущего standby; исправление старта зарядки переносится только при подтверждённой применимости RP6.

**Доноры:** целостный SM8550 stack [SteamOS ARM `ccefcd…`][suspend], происхождение и варианты в [Armada kernel patches][armada-kernel], [USB-PD kick `02120f…`][pd].

**Файлы:** kernel patches/config/DT из UP-03; `sm8650-overlay/usr/lib/konkr/konkr-suspend`, `konkr-sleep`, `konkr-standby`, `konkrd`; `external-and-mods/kernel-common/initramfs/bootdebug`; `scripts/install-rp6-power.sh`; `docs/RP6-POWER.ru.md`. Изменения этих файлов интегрировать с актуальным модулем 2, а не поверх его старого HEAD.

- [ ] **UP-04.1 — Исходное состояние.** Получить журнал отказов аудио и длительного standby; измерить заряд/ток, fan, runtime PM и wake IRQ локально. Сначала отделить уже исправленное в исходниках standby-aware охлаждение от новых donor патчей. Не приписывать весь ночной расход одному компоненту.
- [ ] **UP-04.2 — Карта зависимостей.** Сопоставить donor patches 0014–0029 с базой UP-03: thermal/UART IRQ, UFS ICE restore, PCIe OPP/regulators, AudioReach graph release, MCU rail, DT wake polarity и codec LPM. Отметить уже имеющиеся и неприменимые части; переносить полный необходимый набор для RP6.
- [ ] **UP-04.3 — Userspace.** Адаптировать s2idle opt-in, отчёт батареи/IRQ/ошибок и заморозку InputPlumber с отдельным чтением power key. Сохранить текущие error handling, восстановление PWM/звука/сети и тепловой failsafe. Повторный вход и ошибка подготовки должны оставлять восстановимую систему.
- [ ] **UP-04.4 — USB-PD.** Проверить наличие и смысл RP6 UCSI/sysfs/debugfs interfaces, сценарий 5 V без PD partner при boot. При воспроизведении адаптировать ограниченный reset/retry; при отсутствии дефекта записать решение не переносить. Проверить зарядку до boot, hotplug, сон с зарядкой и отключение зарядки.
- [ ] **UP-04.5 — Устройство и доставка.** После source/CI проверок выполнить 20 последовательных циклов, длительный сон и сон с игрой; Wi-Fi on/off, звук, экран, ввод, зарядка. Измерять расход при одинаковых условиях, отдельно `%/час` и `Wh/час`, если доступны корректные данные. Выполнить UP-08 и проверить возврат standby/предыдущего kernel.

**Приёмка:** подтверждён фактический s2idle, проходят восстановление устройств и длительный тест; нет необъяснённых ранних выходов. До этого статус экспериментальный, default остаётся прежним. Выключенная подсветка и чужой результат автономности приёмку не закрывают.

## UP-05 — GPU polling, scheduling и zram

**Результат:** настройки производительности выбираются по замерам RP6 12 ГБ и управляются одним механизмом.

**Доноры:** [default GPU polling `5d023c…`][gpu-polling]; [pb-os][pb] — EAS/schedutil/uclamp без жёсткого CPU pinning и zstd zram до 8 ГБ; [Pocknix][pocknix] — альтернативный scx_lavd и pinning игр на big cores 3–7. Это конкурирующие политики, не набор для одновременного включения.

**Точки переноса в донорах:** pb-os `sm8550-overlay/usr/lib/steamos-sm8550/sm8550-boostd` и `sm8550-overlay/usr/lib/systemd/zram-generator.conf.d/60-sm8550-zram.conf`; Pocknix `packages/shared/pocknix-steam/pocknix-proton-wrapper` и `packages/shared/pocknix-bsp-common/pocknix-lavd.service`.

**Файлы:** `sm8650-overlay/usr/lib/konkr/konkrd`, `sm8650-overlay/usr/bin/konkrctl`, `external-and-mods/Decky/sm8650/konkr-control/main.py`; создать RP6 config `sm8550-overlay/usr/lib/systemd/zram-generator.conf.d/60-rp6-zram.conf` только после проверки имеющегося zram-generator. Учесть ещё не интегрированные средства измерения Roadmap модуля 3 перед созданием дубликатов.

- [ ] **UP-05.1 — Ранний отдельный патч.** Проверить donor возврат default GPU polling вместо 16 ms на SM8550 на исходном kernel и UP-03. Этот малый эксперимент можно выполнить сразу после UP-01, до остальных задач UP-05; принять только по нашим frametime/стабильности, не по заявленному автором приросту 1% low.
- [ ] **UP-05.2 — CPU A/B.** Адаптировать сначала pb-os EAS/uclamp к KONKR. Отдельно проверить Pocknix scx_lavd/pinning при поддержке ядра. Исключить конкурирующие daemons и остаточные affinity/uclamp после игры; при активном sched_ext явно определить владение настройками.
- [ ] **UP-05.3 — Память.** Сравнить текущую zram с zstd и donor пределом `min(ram, 8192)`. На RP6 12 ГБ измерить RAM/swap, CPU cost, OOM и время загрузки при одинаковом сценарии; предел 8 ГБ не принимать без проверки.
- [ ] **UP-05.4 — Матрица.** Выполнить минимум три сопоставимых прогона DMC, Dark Souls 3 и Dishonored для каждой меняемой политики. Зафиксировать сцены, версии, яркость, температуру, cooling/power profile; менять один параметр за раз. 1% low считать только по корректным frame intervals; frame generation не выдавать за базовый FPS.
- [ ] **UP-05.5 — Применение и доставка.** Сохранённый профиль считать применённым только после подтверждённого reload активного `konkrd`. Проверить game exit, reboot и возврат baseline. Включить победившие настройки через UP-08; отклонённые оставить в отчёте эксперимента.

**Приёмка:** отсутствие новых crashes/OOM и зависаний важнее среднего FPS. Выбор учитывает frametime, температуру и расход; неповторяемая разница не становится default. Откат возвращает прежний policy/config и подтверждает его применение.

## UP-06 — FEX, графика и RP6 audio firmware

**Результат:** новые варианты совместимости игр поставляются согласованными комплектами, с профилями и воспроизводимым откатом.

**Доноры:** [Armada kernel][armada-kernel], [FEX profiles][armada-fex], [gamescope patches][armada-gamescope], [Pocknix profiles/wrapper][pocknix]; [ROCKNIX DPU rotation][rotation]. Местный Mesa recipe уже `26.2.3`, поэтому совпадение номера с донорами не является переносом.

**Точки переноса в донорах:** Armada `packages/kernel/patches/` (unaligned atomics 0505 и follow-up), `packages/kernel/dts/qcs8550-retroidpocket-rp6.dts.patch`, RP6 firmware под `system_files/usr/lib/firmware/qcom/sm8550/retroidpocket/rp6/`, `system_files/usr/share/armada/fex-profiles.json`; Pocknix `packages/shared/pocknix-steam/fex-profiles.json`. Trigger calibration — отдельный условный кандидат UP-02, а не обязательная замена принятой калибровки.

**Файлы:** kernel patches/DT из UP-03, `external-and-mods/mesa/patches/`, `scripts/build-mesa.sh`, `external-and-mods/gamescope/`, `scripts/build-gamescope-in-rootfs.sh`, `steamos-overlay/usr/lib/steamos/gamescope-session`, `steamos-overlay/usr/lib/steamos/sm8550-audio-setup`. Создать `steamos-overlay/usr/share/rp6/game-profiles.json` и launcher helper `steamos-overlay/usr/lib/steamos/rp6-game-launch` для Linux адаптации профилей.

- [ ] **UP-06.1 — FEX atomics.** Проверить необходимость и переносимость Armada unaligned atomic kernel patches, включая последующие load128/store-exclusive исправления. Закрепить FEX с соответствующим per-thread opt-in интерфейсом; проверить не только применение патча, но и runtime использование. Без совместимого FEX не включать неполный комплект.
- [ ] **UP-06.2 — Профили игр.** Перенести подход default/compatible/fast и app-specific overrides. Определить AppID, допустимые настройки, приоритет override и reset. TSO-off оставить отдельным experimental профилем, проверять сохранения и корректность игры; глобально не включать.
- [ ] **UP-06.3 — Display/Turnip.** Сравнить фактические патчи Mesa и согласованные DPU/gamescope изменения rotation/color. Переносить по одной паре зависимых изменений с matching driver/loader ABI. Проверить ориентацию touch, fullscreen, QAM и suspend. Физические 60 Hz проверять по DRM modes отдельно; nested refresh и touch sample rate их не доказывают.
- [ ] **UP-06.4 — Звук.** Сравнить RP6 DT/ADSP/amp пути Armada с текущими firmware и audio setup. Проверить происхождение, право распространения и контрольные суммы нужных blobs; переносить только при подтверждённом отличии/дефекте RP6. Проверить динамики, jack, громкость и восстановление после обоих режимов сна.
- [ ] **UP-06.5 — Доставка.** Прогнать игровую матрицу UP-05 и конкретную игру, для которой вводится профиль. Через UP-08 сохранить версии и SHA256 kernel/FEX/host+guest Vulkan/gamescope/firmware. Проверить откат всего зависимого комплекта, а не только одного пакета.

**Приёмка:** исправлен воспроизведённый дефект либо появилась подтверждённая совместимость игры без регрессии базовой матрицы. Проверенные и experimental профили различимы; несовместимый комплект отклоняется до установки.

## UP-07 — Инструменты профилей и безопасной установки компонентов

**Результат:** пользователь выбирает уже проверенные профили игры и комплекты компонентов из существующего интерфейса KONKR/Decky.

**Доноры:** [DroidDeck 0.3.0][droid-release] — per-game options и согласование runtime/display drivers; [MaSieS4Fun v1.1][masi-release] — защита графических библиотек при установке приложений и организация Decky. Android APK, proot и KGSL bundles не подходят для прямой установки в Linux DRM rootfs; здесь требуется адаптация интерфейсов и политики выбора.

**Файлы:** `external-and-mods/Decky/sm8650/konkr-control/main.py`, `sm8650-overlay/usr/bin/konkrctl`, профиль/launcher UP-06, `scripts/apply-overlays.sh`, `external-and-mods/konkr-update/konkr-update.py`. Пути installer/graphics manager определить по существующей реализации ARM-Manager до изменения; не создавать второй механизм установки.

- [ ] **UP-07.1 — Контракт профиля.** Связать настройки UI с AppID/schema из UP-06 и политикой UP-05: показать фактически применённое состояние, reset и причину отказа. Unsupported параметры не должны сохраняться как успешно применённые.
- [ ] **UP-07.2 — Комплекты drivers/runtime.** Адаптировать проверку архитектуры, ABI, зависимостей и совместных версий host/guest драйвера. Неполный download или несовместимый комплект не меняет активную систему; предыдущий комплект остаётся доступен.
- [ ] **UP-07.3 — Установка приложений.** Перенести защиту платформенных Mesa/Vulkan/Wayland библиотек от подмены при установке Lutris и других приложений. Проверять план package transaction, а не только имена файлов после неё. Проверить native/Box64/FEX пути и отсутствие дублирующих input/Decky служб.
- [ ] **UP-07.4 — Пользовательская проверка.** На RP6 выбрать профиль для игры, запустить её, закрыть, перезагрузиться и выполнить reset. Проверить отказ backend, потерю сети при download и rollback; действия должны отражать фактический результат.
- [ ] **UP-07.5 — Доставка.** Выполнить UP-08 с сохранением пользовательских overrides при обновлении. Документировать поддерживаемые комплекты и применение профилей; experimental варианты требуют явного выбора.

**Приёмка:** интерфейс управляет существующим рабочим механизмом, ошибочная операция не оставляет половину комплекта, default/reset восстанавливают проверенную конфигурацию. Заявленные DroidDeck ускорения запуска не переносятся в обещания нашего форка.

## UP-08 — Выпуск, обновление и откат переносов

**Результат:** все выбранные переносы воспроизводятся в чистом RP6 образе и безопасно проходят существующий путь обновления. Этот модуль выполняется частями вместе с UP-01…UP-07.

**Доноры:** release/checklist практики [MaSieS4Fun][masi], provenance/patch accounting [Armada][armada-kernel] и [Pocknix][pocknix]. [pb-os][pb] со stable Frame `0.3.0` — источник для отдельного сравнения базы, а не основание автоматически менять наш `0.5.0` rootfs.

**Точки переноса в донорах:** MaSieS4Fun `docs/BUILD-AND-FIXES.md` и `docs/RELEASE-CHECKLIST.md`; Armada `packages/kernel/PATCHES.md`; Pocknix `PATCHES.md`. Адаптировать только проверки, применимые к нашему сборщику и RP6.

**Файлы:** `make-steamos-sm8650.sh`, `scripts/apply-overlays.sh`, `scripts/build-update-package.py`, `scripts/prepare-rp6-beta8-test.py`, `external-and-mods/konkr-update/konkr-update.py`, `scripts/check-rp6-input.sh`, `.github/workflows/rp6-input.yml`, актуальный workflow питания; документация результата каждого модуля.

- [ ] **UP-08.1 — Manifest и provenance.** Включить в build/release manifest поля из общих условий, версии компонентов, donor commits и локальные изменения. Зафиксировать checksums загрузок, firmware, patches и output image; устранить неявное использование moving `main/latest`.
- [ ] **UP-08.2 — Чистая сборка.** Собрать кандидат из зафиксированного состояния без ручных правок rootfs. Проверить установленные файлы, modes/units/configs и RP6 input preflight. На Linux выполнить существующие тесты и добавленные сценарии конкретного переноса; пропуски явно перечислить.
- [ ] **UP-08.3 — Обновление.** Подготовить пакет существующим updater: версии и совместимость kernel/modules/rootfs, сохранение custom maps, power/game profiles, Decky настроек и пользовательских данных. Проверить отказ/прерывание до переключения и восстановление после него в границах реально поддерживаемого updater.
- [ ] **UP-08.4 — Устройство и rollback.** На RP6 проверить свежий образ, затем обновление с принятой базы. Повторить ввод, сессию, звук/сеть, игру и сценарии сна затронутых модулей. Отдельно проверить процедуру восстановления карты/комплекта; ручной rollback не называть автоматическим.
- [ ] **UP-08.5 — Решение о выпуске.** Составить список принятых/отклонённых/неиспытанных переносов и открытых дефектов. Включать в default только принятые; beta opt-in фиксировать отдельно. Сравнение stable Frame 0.3.0 запускать отдельным кандидатом только при дефекте базы, удерживая остальные компоненты постоянными.

**Приёмка:** контрольные суммы совпадают, источник каждого переноса восстановим, чистая установка и обновление подтверждены на RP6 12 ГБ / microSD. Исходники/CI без устройства дают статус «готово к аппаратной проверке», а не «принято». Незавершённые эксперименты не должны попадать в default выпуск.

## Команды проверки при реализации

Выполнять из корня репозитория в подготовленном Linux окружении. Это проверки будущих патчей, не результаты исследования:

```bash
python -m unittest discover -s scripts/tests -v
bash -n scripts/apply-overlays.sh scripts/import-sm8550-kernel.sh scripts/check-rp6-input.sh make-steamos-sm8650.sh
bash -n sm8650-overlay/usr/lib/konkr/konkr-sleep sm8650-overlay/usr/lib/konkr/konkr-suspend scripts/install-rp6-power.sh
bash scripts/check-rp6-input.sh "$RP6_PORT_ROOTFS" "$RP6_PORT_KERNEL"
```

`RP6_PORT_ROOTFS` — абсолютный путь к staged rootfs, `RP6_PORT_KERNEL` — к соответствующему BOOT/KERNEL. Их нужно задать перед preflight. Новые тесты добавлять для проверяемых отказов и совместимости; точный текущий набор CI сверять перед каждым переносом.

## Задание для отдельной реализации модуля

> Реализуй UP-XX из `docs/RP6-UPSTREAM-PORTING-PLAN.ru.md` в форке SteamOS ARM для RP6. Сначала прочитай этот план, актуальные `RP6-ROADMAP.ru.md`, `RP6-SCOPE.md` и, при изменениях питания, `RP6-POWER.ru.md`. Проверь checkout, незавершённые изменения и зависимости; сравни зафиксированные donor commits с текущим кодом. Перенеси выбранные функции с сохранением принятого управления и выполнением UP-08. Подготовь проверяемый кандидат и откат до аппаратной установки. Отчёт раздели на исходники/CI, доставку и испытание RP6 12 ГБ / microSD; не отмечай checkbox до соответствующей проверки.

## Источники и зафиксированные версии

| Донор | Проверенный срез | Роль и предел доказательства |
|---|---|---|
| [hashtagbasit/SteamOS-ARM-Handhelds][frame] | `682281c0d82319324fd3f7d09b34d0f7005148fc`, beta10 от 02.10 | Прямой upstream; 33 commits после базы форка, часть относится к другим устройствам |
| [project-barry/pb-os][pb] | `73399066c1d55830d7aba7720a846a31343e52c6` | Frame 0.3.0; README сообщает RP6 8 ГБ и Thor, не нашу аппаратную приёмку |
| [armada-os/armada][armada] | `72f2a63f4b5417522887c781809b712c7b393a8a`, release 20260926 | Fedora bootc; kernel/FEX/graphics/audio решения требуют адаптации |
| [shuuri-labs/pocknix-os][pocknix] | `fcd5c755f1ed57ba3d219ffd2ac100bf83c672e1`, image v0.4.0 | Arch Linux ARM; source свежее образа, CPU policy отличается от pb-os |
| [ROCKNIX/distribution][rocknix] | release 20261001; touch `3829f7c5a80a8a9e78576ea5a3bb0c1ceeebb939` | RP6 touch и DPU; Linux образ и пользовательская среда отличаются |
| [MaSieS4Fun/SteamOS-ARM-SM8550][masi] | `7eecdb23663fa88b218873a8acbe64e87df6d952`, v1.1 | Frame; release сообщает испытание Odin 2, остальные устройства не испытаны |
| [Droid-Deck/DroidDeck][droid] | `ec016f85bc029e3303ec4d33567aa02ac41b8dba`, 0.3.0 от 02.10 | Android/proot; донор принципов и переносимых частей, не Linux image/driver bundle |

Локальный архив исследования вне Git репозитория: `../../research/upstream-2026-10-02/findings.json`, `source-manifest.json` и `sources/` относительно этого документа. Он фиксирует полученные байты и SHA256; первичные ссылки ниже позволяют повторить исследование без архива. Дата плана не означает испытание donor образов на устройстве.

[frame]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/tree/682281c0d82319324fd3f7d09b34d0f7005148fc
[frame-release]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/releases/tag/v1.3-beta10
[vr-layers]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/commit/c9d87d6492932b73e88fbf53edb9119e5163d137
[vr-followup]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/commit/4181b9cfa42a68694595b7be2ba68414d0a35e23
[focusfix]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/commit/4a12b47208b8576a54f8191b8abc31290ec89921
[mangohud]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/commit/f5361f9422e3d7c5aaee04773b13928a98f4787a
[etc-overlay]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/commit/f08eaa6d28949690f9c0ed1b835b2cdb33ee9f6f
[decky]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/commit/20dec11ad5e49754b7a27854d043205303350677
[decky-network]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/commit/6799cc45307dda4a65a777a890b6a2de44356663
[touch]: https://github.com/ROCKNIX/distribution/commit/3829f7c5a80a8a9e78576ea5a3bb0c1ceeebb939
[wifi-touch]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/commit/3b01fcc60759b590a064387379b6858c2cbbb3cd
[sd]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/commit/18667d70bc8ddf6a49f7eb64ee8cc64cc54842a0
[gpu-priority]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/commit/1da337d8ecbb59bc2a5c983060a1960241f83dc1
[suspend]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/commit/ccefcd50d716690eba6e57df9798f858512af6b7
[pd]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/commit/02120f2bc1b34a1ae7203aa28dc3d933e99cbfbc
[gpu-polling]: https://github.com/hashtagbasit/SteamOS-ARM-Handhelds/commit/5d023cdd5d9a9f9dc9695a51acb6a5f2705f4cfe
[pb]: https://github.com/project-barry/pb-os/tree/73399066c1d55830d7aba7720a846a31343e52c6
[armada]: https://github.com/armada-os/armada/tree/72f2a63f4b5417522887c781809b712c7b393a8a
[armada-kernel]: https://github.com/armada-os/armada/blob/72f2a63f4b5417522887c781809b712c7b393a8a/packages/kernel/PATCHES.md
[armada-fex]: https://github.com/armada-os/armada/blob/72f2a63f4b5417522887c781809b712c7b393a8a/system_files/usr/share/armada/fex-profiles.json
[armada-gamescope]: https://github.com/armada-os/armada/blob/72f2a63f4b5417522887c781809b712c7b393a8a/packages/gamescope/PATCHES.md
[pocknix]: https://github.com/shuuri-labs/pocknix-os/tree/fcd5c755f1ed57ba3d219ffd2ac100bf83c672e1
[rotation]: https://github.com/ROCKNIX/distribution/commit/ec3d53baacd2c96d9524414cfeae91a64415d2d3
[rocknix]: https://github.com/ROCKNIX/distribution/releases/tag/20261001
[masi]: https://github.com/MaSieS4Fun/SteamOS-ARM-SM8550/tree/7eecdb23663fa88b218873a8acbe64e87df6d952
[masi-release]: https://github.com/MaSieS4Fun/SteamOS-ARM-SM8550/releases/tag/v1.1
[droid]: https://github.com/Droid-Deck/DroidDeck/tree/ec016f85bc029e3303ec4d33567aa02ac41b8dba
[droid-release]: https://github.com/Droid-Deck/DroidDeck/releases/tag/0.3.0
