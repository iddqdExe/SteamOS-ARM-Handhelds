# UP-04: сон RP6 на базе принятого UP-03

Цель: Retroid Pocket 6 / SM8550 / 12 ГБ / microSD. Основа — принятый UP-03 Linux 7.2.8, исходный SHA `392602eedfdab13826511bae7be4dead830cafc0`, запечатанный R2 image и принятие UP-01/08/03 пользователем. UP-04 экспериментальный до испытаний RP6. Приоритет: стабильность → производительность → автономность.

## Перенос

Донор SteamOS ARM `ccefcd50d716690eba6e57df9798f858512af6b7`: patches 0014–0029 (thermal IRQ, UFS ICE/reset, PCIe suspend OPP и d3cold, RPMh regulator sleep sets с явным opt-in, AudioReach graph close/reopen, UART IRQ, MCU supply). Авторы/источники сохранены в patch headers. Общие AYN DT изменения адаптированы только в RP6 append: Wi-Fi wake GPIO96 active low, переключаемая MCU rail, codec LPM на l15b/bob1. Принятые paddles/touch/panel/SD/GPU/Wi-Fi priorities сохраняются.

Дополнительный 0030 балансирует отключение non-console UART IRQ при ошибке `uart_suspend_port`; без него отменённый suspend мог оставить gamepad отключённым. CONFIG_PM_DEBUG/PM_SLEEP_DEBUG/PM_ADVANCED_DEBUG включены для аппаратной диагностики.

В userspace перенесены recovery guards модуля 2 для частот, звука, Wi-Fi и частичных отказов. Принятый в UP-03 путь DSI readiness перед восстановлением яркости сохранён; PWM-only правило старого кандидата модуля 2 не заменяет его. Принятый daemon/CPU profiles/fan/thermal failsafe наследуются побайтно из R2 image, без замены иной исходной версией.

Standby замораживает InputPlumber после открытия отдельного power-key reader. При partial freeze thaw пытается восстановить все затронутые cgroups. S2idle использует root-only recovery record с исходными loaded Wi-Fi modules, touch bindings и wakeup settings; ошибка pre запускает recovery, ошибка post сохраняет запись и блокирует следующий сон. `ExecStopPost` выполняет recovery также после неудачного запуска systemd подготовки. Отчёт содержит фактические suspend counters, wake IRQ, battery и IRQ delta; rate выводится только при интервале >=3 минут и разряде на обоих концах. Wh/h берётся только из energy_now, без подмены оценкой charge*voltage.

## Выбор режима

Default остаётся standby. Для проверки s2idle:

- На BOOT создать пустой файл `s2idle` или `s2idle.txt`, затем загрузить RP6; флаг действует на этот boot.
- Либо на RP6 выполнить `sudo konkrctl sleep s2idle`. Это постоянный opt-in.
- Проверка: `konkrctl sleep status`.
- Возврат: `sudo konkrctl sleep standby`; создаётся постоянный standby override, он имеет приоритет даже над файлом BOOT. Следующий `sleep s2idle` снимает override.

Прямые команды: `sudo konkrctl sleep s2idle`, `sudo konkrctl sleep standby`.

Read-only диагностика: `sudo /usr/lib/konkr/konkr-sleep-state diagnose`; журнал `journalctl -b -g 's2idle report|standby report|PM: suspend|PM: resume'`. BOOT/debug collector включает эти данные. При pending recovery: `sudo /usr/lib/konkr/konkr-sleep post`; ошибка сохраняет подробности в journal и recovery record.

## USB-PD

Изучен donor `02120f2bc1b34a1ae7203aa28dc3d933e99cbfbc`. Его активный boot connector reset испытан на Pocket FIT. На RP6 аналогичный отказ 5 V/no partner ещё не воспроизведён; перенос active reset не включён. Доставлена read-only диагностика USB power_supply, UCSI debugfs и Type-C partners. Для решения проверить зарядник подключённым до boot, hotplug, сон на зарядке и отключение. Нормальные 5 V от обычного USB не должны вызывать reset.

## Доставка и проверка

Новый kernel/modules/firmware/initramfs и точный whitelist runtime UP-04 устанавливаются в чистый образ из принятого UP-03 R2. Firmware из R2 не удаляется; прочие root bytes/owners/modes/xattrs, HOME и partition table проверяются на сохранение. Это чистая установка согласованного образа, не полная пересборка SteamOS userspace. Артефакты и доказательства — material workspace `preparation/upstream-porting/UP-04/`.

RP6 KERNEL выравнивает каждый appended DTB на8 байт для чтения libfdt прямо в payload. Короткое gzip filename (FNAME) и trailing FDT space сохраняют deflate/Image, все DT properties, reservations и внутренние offsets; DTBs не проходят DTS roundtrip. Artifact validator отклоняет невыравненный boot file и gzip flags вне0/FNAME. Qualcomm ABL пропускает только10 bytes и optional filename перед raw inflate; FEXTRA не поддерживается. Native test выполняет upstream C decompressor: отклонённый FEXTRA воспроизводит отказ, FNAME должен распаковываться с правильным DTB offset. Аппаратная проверка отдельна.

Пользователь отказался от backup и разрешил полную чистую запись вставленной SD-карты. Перед записью сверяются идентичность/размер носителя и image SHA256; после — полный readback записанной области, KERNEL и новая geometry. Остаток старой HOME не сохраняется как раздел или пользовательская установка. Android/ABL не меняются.

После установки: первый и второй cold boot, Game Mode/Desktop, touch/управление/L4/R4/Volume Up, звук, Wi-Fi/Bluetooth и игра; затем 20 последовательных s2idle cycles, игра после resume, Wi-Fi on/off, charger matrix и длительный сон. Проверять фактические PM suspend counters и ранние wake IRQ. Улучшение автономности до этих замеров не заявляется. CI из предыдущего этапа не возобновляется.

Возврат к принятой базе — чистая запись уже существующего UP-03 R2 image с matching modules/firmware. Новые backups не создаются; прежние данные карты не восстанавливаются. UP-04 device acceptance и physical rollback остаются отдельными проверками.
