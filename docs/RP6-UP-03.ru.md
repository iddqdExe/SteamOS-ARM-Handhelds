# UP-03: Linux 7.2.8 для Retroid Pocket 6

Цель приёмки: **RP6 / SM8550 / 12 ГБ RAM / microSD**. Приоритет: стабильность → производительность → автономность. UP-03 **закрыт 2026-10-04** по запросу пользователя после фактических проверок RP6; решение `accepted` относится к указанному scope с известными ограничениями. По отдельному указанию пользователя ядро 7.2.8 становится основным для RP6 в `main`; gate публикации готового default image по-прежнему проверяется отдельно.

Основа — принятые UP-01 и UP-08, плюс перенос touch из UP-02. Steam Frame userspace, Mesa/FEX, настройки игр, управление, Volume Up, L4/R4, ориентация и исправление питания панели наследуются из принятого образа UP-08. Чистая установка переносит базовую систему, а не данные установленной карты.

## Состав

- Linux 7.2.8; ROCKNIX `1ebff24f36501fb6493beb2bf83bf2604536d9aa`; GCC 15.3.1.
- RP6 и RP6 TOP-DPAD: удалён унаследованный `sdhci-caps-mask` на SD controller. Реальный SDR104 зависит от карты и измеряется на устройстве.
- GPU: userspace priorities 0/1/2 отображаются в HIGH/NORMAL/LOW; entity indexes непрерывны; VM_BIND сохраняет KERNEL.
- ath12k: вычисленный LOW/MEDIUM priority действительно отправляется в команде запуска сканирования.
- KERNEL, встроенный initramfs, matching modules и firmware поставляются вместе. GPU firmware закреплён по Linux firmware commit; встроенный набор WCN7850 взят из принятого Steam Frame baseline.

Фиксированные inputs: `external-and-mods/kernel-sm8550/recipe-7.2.lock.json`. `scripts/check-rp6-kernel.py inputs` проверяет все архивы/прошивки, clean ROCKNIX SHA, image ID toolchain и static BusyBox. Режим `artifacts` сверяет встроенную конфигурацию, реальные DTB, initramfs, прошивки и ABI всех модулей. Тесты priority выполняют C из реального patched source.

## Доставка

Сборка выполняется offline в ARM64 Linux Docker volume. Образ и update package создаются из одного комплекта через `scripts/prepare-rp6-kernel-release.py`. Сборщик сверяет полный inventory ядра и исходный SHA образа UP-08, сохраняет partition table/HOME исходного образа, меняет только BOOT/KERNEL, BOOT/KERNEL.md5, modules, firmware и release manifest. Полное сравнение userspace проверяет bytes, owners, permissions и xattrs.

Это чистая установка из запечатанного образа с новым ядром. Полная повторная сборка дистрибутива из исходников не заявляется. Канал — `beta-opt-in`; default release остаётся закрыт до аппаратных доказательств.

Пользователь разрешил полную чистую запись microSD и явно отказался от резервного копирования её данных. Перед записью требуется однозначно определить внешний носитель и проверить готовый образ; после записи — прочитать записанную область и сверить SHA256. Android/ABL данным этапом не меняются.

## Приёмка и откат

Проверить первый запуск и повторную холодную загрузку, Game Mode/Desktop, звук, touch, кнопки и триггеры, Volume Up/Down и L4/R4. Проверить полноэкранную игру, оба меню и overlays под нагрузкой. Игры для сравнения: DMC, Dark Souls 3, Dishonored.

Скорость загрузки ОС и игр оценивается одинаковыми сценами до/после при фиксированных userspace/preset. Параллельно записываются реальный SD mode и ошибки; Wi-Fi — десять reconnect cycles на одном AP и поведение после resume. Улучшение скорости не выводится из самого разрешения SDR104.

Программный откат — повторная чистая установка принятого образа UP-08 со всем старым комплектом ядра. Текущие игры/сохранения карты не будут восстановлены: их backup пользователь отклонил. Физический откат нового комплекта UP-03 пока не испытан; аппаратные проверки устройства перечислены ниже. Нельзя восстанавливать только старый KERNEL поверх новых modules.

Решение приёмки, контрольные суммы и source SHAs сохранены в [RP6-UP-03.acceptance.json](RP6-UP-03.acceptance.json). Подробные исходные результаты находятся в `preparation/upstream-porting/UP-03/execution-20261004/` в material workspace рядом с репозиторием.


## Принятые результаты и ограничения

Приняты running kernel 7.2.8 и все 280 matching modules; первый запуск и перезагрузка, Game Mode/Desktop, управление/звук/touch, fullscreen menu cycles, DMC без зависаний/чёрного экрана/потери звука и управления, нормальная вибрация, Bluetooth firmware boot/pairing/audio, SDR104 и bounded HOME integrity, десять reconnect cycles Wi-Fi на одном AP. Пользователь отмечает более быструю загрузку ОС/игр и отзывчивость; численный before/after прирост не измерен.

R1 ошибочно удалял 315 принятых firmware entries. Commit `392602eedfdab13826511bae7be4dead830cafc0` сохраняет их; R2 image/package проверены и exported hashes сверены. На RP6 restored 315 paths и release marker, все 456 firmware entries совпали с R2, ядро и новые игры/настройки сохранены. Физически чисто записан R1 с последующим узким восстановлением; R2 image не перезаписывался на карту, новый supported updater и physical kernel rollback не испытаны.

Один ранний GMU bandwidth-vote timeout/late-response не повторился в DMC и на текущем boot; причина не установлена. Haptic brake warnings есть и в старых принятых UP-01 logs, DMC rumble работает. Единичный SoundWire clock-stop warning сохранён. Предложенные три sleep/wake cycles и DMC после пробуждения не выполнены/не подтверждены; power/resume work относится к следующему этапу UP-04. Известные наблюдения остаются для диагностики, а не объявляются исправленными.

CI, physical R2 fresh image/update/rollback, контролируемые A/B измерения и расширенная game/resume матрица остаются отдельными проверками. Default release не открывается scoped приёмкой. Полное решение: material workspace `preparation/upstream-porting/UP-03/execution-20261004/module-acceptance.json`; assembled artifacts остаются на source SHA `392602eedfdab13826511bae7be4dead830cafc0`, документация закрытия не меняет их байты.


## Основное ядро в main

По указанию пользователя 2026-10-04 recipe 7.2/ROCKNIX/7.2.8 выбран по умолчанию в SM8550 kernel builder. Image builder `SOC=sm8550` разрешает ту же recipe и выбирает `kernel-sm8550/output/current`; GCC15/input/DTB guards сохраняются. Явные legacy overrides остаются доступны. Это изменение выбора уже принятого комплекта; установленные байты ядра/R2 image и их assembly provenance не меняются. Невыполненные аппаратные/CI проверки сохраняют отдельные статусы.
