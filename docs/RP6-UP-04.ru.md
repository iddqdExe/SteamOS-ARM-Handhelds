# UP-04: сон RP6 на базе принятого UP-03

Цель: Retroid Pocket 6 / SM8550 / 12 ГБ / microSD. Основа — принятый UP-03 Linux 7.2.8, исходный SHA `392602eedfdab13826511bae7be4dead830cafc0`, запечатанный R2 image и принятие UP-01/08/03 пользователем. UP-04 экспериментальный до испытаний RP6. Приоритет: стабильность → производительность → автономность.

## Перенос

Донор SteamOS ARM `ccefcd50d716690eba6e57df9798f858512af6b7`: patches 0014–0029 (thermal IRQ, UFS ICE/reset, PCIe suspend OPP и d3cold, RPMh regulator sleep sets с явным opt-in, AudioReach graph close/reopen, UART IRQ, MCU supply). Авторы/источники сохранены в patch headers. Общие AYN DT изменения адаптированы только в RP6 append: Wi-Fi wake GPIO96 active low, переключаемая MCU rail, codec LPM на l15b/bob1. Принятые paddles/touch/panel/SD/GPU/Wi-Fi priorities сохраняются.

Дополнительный 0030 балансирует отключение non-console UART IRQ при ошибке `uart_suspend_port`; без него отменённый suspend мог оставить gamepad отключённым. CONFIG_PM_DEBUG/PM_SLEEP_DEBUG/PM_ADVANCED_DEBUG включены для аппаратной диагностики.

В userspace перенесены recovery guards модуля 2 для частот, звука, Wi-Fi и частичных отказов. Принятый в UP-03 путь DSI readiness перед восстановлением яркости сохранён; PWM-only правило старого кандидата модуля 2 не заменяет его. Принятые CPU profiles/fan/thermal failsafe сохраняются из R2 image. В принятом daemon точечно добавляется защита кнопки питания после kernel resume; полной замены daemon исходной версией донора нет.

Standby замораживает InputPlumber после открытия отдельного power-key reader. При partial freeze thaw пытается восстановить все затронутые cgroups. S2idle использует root-only recovery record с исходными loaded Wi-Fi modules, touch bindings и wakeup settings; ошибка pre запускает recovery, ошибка post сохраняет запись и блокирует следующий сон. `ExecStopPost` выполняет recovery также после неудачного запуска systemd подготовки. Отчёт содержит фактические suspend counters, wake IRQ, battery и IRQ delta; rate выводится только при интервале >=3 минут и разряде на обоих концах. Wh/h берётся только из energy_now, без подмены оценкой charge*voltage.

## Выбор режима

Default остаётся standby. Для проверки s2idle:

- На BOOT создать пустой файл `s2idle` или `s2idle.txt`, затем загрузить RP6; флаг действует на этот boot.
- Либо на RP6 выполнить `sudo konkrctl sleep s2idle`. Это постоянный opt-in.
- Проверка: `konkrctl sleep status`.
- Возврат: `sudo konkrctl sleep standby`; создаётся постоянный standby override, он имеет приоритет даже над файлом BOOT. Следующий `sleep s2idle` снимает override.

Прямые команды: `sudo konkrctl sleep s2idle`, `sudo konkrctl sleep standby`.

Read-only диагностика: `sudo /usr/lib/konkr/konkr-sleep-state diagnose`; журнал `journalctl -b -g 's2idle report|standby report|PM: suspend|PM: resume'`. BOOT/debug collector включает эти данные. При pending recovery: `sudo /usr/lib/konkr/konkr-sleep post`; ошибка сохраняет подробности в journal и recovery record.

По прямому указанию пользователя RP6 recipe7.2 сохраняет диагностику после приёмки: `console=tty0 loglevel=7 systemd.show_status=1 steamos.debug=1`. Collector пишет последние снимки в BOOT/debug-logs каждые20 секунд в начале и каждые60 секунд далее всю сессию. Включены kernel/system/user/gamescope journals, cmdline/release, storage/mounts, input, network, GPU/display/backlight, remoteproc, thermal/CPU frequency, power supplies и suspend reports. Persistent journal ограничен96MiB, RAM journal32MiB, выгрузки journal — последние3000 записей; снимки перезаписываются. Vulkan probe выполняется один раз с timeout10s. Диагностика не отключается автоматически после аппаратных испытаний.

Initramfs builder устанавливает BusyBox с mode0755 независимо от прав входного файла. Artifact validator проверяет исполняемый обычный файл интерпретатора внутри packed KERNEL, помимо SHA256 и hook bytes: mode0644 воспроизводит RP6 panic `Failed to execute /init (error -13)`.

## USB-PD

Изучен donor `02120f2bc1b34a1ae7203aa28dc3d933e99cbfbc`. Его активный boot connector reset испытан на Pocket FIT. На RP6 аналогичный отказ 5 V/no partner ещё не воспроизведён; перенос active reset не включён. Доставлена read-only диагностика USB power_supply, UCSI debugfs и Type-C partners. Для решения проверить зарядник подключённым до boot, hotplug, сон на зарядке и отключение. Нормальные 5 V от обычного USB не должны вызывать reset.

## Доставка и проверка

Новый kernel/modules/firmware/initramfs и точный whitelist runtime UP-04 устанавливаются в чистый образ из принятого UP-03 R2. Firmware из R2 не удаляется; прочие root bytes/owners/modes/xattrs, HOME и partition table проверяются на сохранение. Это чистая установка согласованного образа, не полная пересборка SteamOS userspace. Артефакты и доказательства — material workspace `preparation/upstream-porting/UP-04/`.

RP6 KERNEL выравнивает каждый appended DTB на8 байт для чтения libfdt прямо в payload. Короткое gzip filename (FNAME) и trailing FDT space сохраняют deflate/Image, все DT properties, reservations и внутренние offsets; DTBs не проходят DTS roundtrip. Artifact validator отклоняет невыравненный boot file и gzip flags вне0/FNAME. Qualcomm ABL пропускает только10 bytes и optional filename перед raw inflate; FEXTRA не поддерживается. Native test выполняет upstream C decompressor: отклонённый FEXTRA воспроизводит отказ, FNAME должен распаковываться с правильным DTB offset. Аппаратная проверка отдельна.

Пользователь отказался от backup и разрешил полную чистую запись вставленной SD-карты. Перед записью сверяются идентичность/размер носителя и image SHA256; после — полный readback записанной области, KERNEL и новая geometry. Остаток старой HOME не сохраняется как раздел или пользовательская установка. Android/ABL не меняются.

После установки: первый и второй cold boot, Game Mode/Desktop, touch/управление/L4/R4/Volume Up, звук, Wi-Fi/Bluetooth и игра; затем 20 последовательных s2idle cycles, игра после resume, Wi-Fi on/off, charger matrix и длительный сон. Проверять фактические PM suspend counters и ранние wake IRQ. Улучшение автономности до этих замеров не заявляется. CI из предыдущего этапа не возобновляется.

Возврат к принятой базе — чистая запись уже существующего UP-03 R2 image с matching modules/firmware. Новые backups не создаются; прежние данные карты не восстанавливаются. UP-04 device acceptance и physical rollback остаются отдельными проверками.

## Исправление повторного сна после DuckTales (2026-10-05)

После шести успешных menu/charger циклов пользователь сообщил чёрный экран при пробуждении DuckTales (app237630). Приставка восстановилась без перезагрузки после повторного питания и Volume Up. Журнал показал новые запросы suspend через 1.7–1.9 секунды после resume; последний wake IRQ200 соответствует Volume Up. Ошибок kernel suspend нет, boot ID не менялся.

Запечатанный UP03 daemon (`1c1c25761996b6c5042ff1e3916bf787b547705ef372e74f8c0cfa4f7efa13d9`) имеет grace только для standby. Из-за отсутствия CLOCK_BOOTTIME offset wake press после s2idle передаётся в Steam как новый shortpowerpress. Поведенческий тест выполняет настоящий delivered power loop с воспроизведёнными часами и событиями: до исправления получается лишний запрос сна.

`fix-rp6-s2idle-wake.py` допускает только этот SHA или уже исправленный SHA, вставляет две точные группы строк, сохраняет owner/mode/xattrs и проверяет результат (`d6eef68a80d88c08a27501b94a3f6872b6bdcbac2cc1e0a8eb1f68e290c8667e`). CLOCK_BOOTTIME−MONOTONIC отмечает выход из kernel sleep; прежнее окно 2.5 секунды игнорирует накопленную кнопку пробуждения. Незавершённый power press сбрасывается, событие resume записывается в постоянный журнал. Изменение попадает в clean image и update package через sealed assembler; ROOT delta допускает только эту пару SHA с неизменными метаданными daemon.

По решению пользователя серия ограничена пятью kernel циклами (включая charging), затем отдельно выполнен battery-only sleep 767 секунд. Это не 20-cycle, overnight или точный power measurement. Game-resume проверка остаётся открытой до аппаратного повторения с исправленным daemon; холодный повторный boot также ещё не проверен.
