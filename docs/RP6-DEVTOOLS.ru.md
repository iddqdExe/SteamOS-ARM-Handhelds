# Автоматизация разработки и проверки RP6

Дополнительный режим разработчика для Retroid Pocket 6 / SM8550 / 12 ГБ / microSD.
Инструменты не включены в системные overlays и не меняют ядро. SSH-ключи и
локальный профиль подключения не входят в образ или Git.

`scripts/rp6-devtools.py` запускается на Mac с Python 3 и стандартным OpenSSH.
На RP6 используются уже установленные Python, systemd, sudo и NetworkManager.

## Подключение и установка

Создай локальный JSON вне репозитория:

```json
{
  "host": "192.168.31.125",
  "user": "steamos",
  "key": "/absolute/path/to/diagnostic-key",
  "known_hosts": "/absolute/path/to/pinned-device-known-hosts",
  "expected_kernel_sha256": "SHA256-of-the-installed-test-KERNEL"
}
```

Путь ключа используется только клиентом OpenSSH; содержимое ключа не читается
и не передаётся в отчёт. Host key должен быть предварительно проверен и закреплён.
Поле ожидаемого SHA256 необязательно; при смене тестового ядра обнови его явно.

```sh
python3 scripts/rp6-devtools.py --profile /path/profile.json stage
```

Команда устанавливает пользовательские файлы в `~/.local/lib/rp6-devtools`,
проверяет systemd units и включает `rp6-devtools-snapshot.timer`. Таймер снимает
один отчёт после старта user manager, без ожидания сети. Через 45 секунд начинается
сбор; если службы или focusfix активной Game Mode сессии ещё запускаются,
сборщик ждёт готовности до 90 секунд. Отчёт сохраняет исходные неготовые проверки,
время ожидания и результат `ready`/`timeout`; при timeout нарушения остаются видимыми.
Отчёты: `~/.local/state/rp6-devtools/<boot-id>.json` и `latest.json`.
Несовпадающие существующие файлы и symlink paths требуют осмотра перед заменой.

Один раз выполни на RP6 в Konsole:

```sh
sudo /usr/bin/bash /home/steamos/.local/lib/rp6-devtools/install-root.sh
```

Установщик проверяет RP6 и microSD root, валидирует sudoers, устанавливает
root-owned `/usr/local/libexec/rp6-devtools-root` и включает `sshd.service`.
Новый SSH-ключ он не устанавливает. Пароль вводится локально в Konsole.
Правило `/etc/sudoers.d/zz-rp6-devtools` загружается после стандартного `wheel`.
Установщик проверяет реальный `sudo -n -k ... snapshot` от пользователя `steamos`
без использования credentials cache:
одного успешного разбора синтаксиса sudoers недостаточно.

## Повторяемые проверки

```sh
python3 scripts/rp6-devtools.py --profile /path/profile.json --output /path/unique-snapshot.json snapshot
python3 scripts/rp6-devtools.py --profile /path/profile.json boot-report
python3 scripts/rp6-devtools.py --profile /path/profile.json report /path/unique-snapshot.json
```

Проверяются модель/RAM, `/etc` overlay, службы, автозапуск SSH, единственный
Decky Loader, focusfix при активном gamescope и BOOT SHA256. Записываются
boot ID, uptime, состояние Wi-Fi, MangoHud preset/inode и ограниченные журналы.
Process arguments и SSH secrets не записываются.

Статусы: `fail` — нарушена проверка; `limited` — системные наблюдения прошли,
но root helper недоступен; `pass_system_checks` — пройдены перечисленные системные
проверки. Ни один статус не заменяет визуальную, игровую, input или suspend приёмку.
SSH transport failures имеют ненулевой exit code и не создают успешный отчёт.
`boot-report` сверяет boot ID с текущим ядром и отклоняет отчёт предыдущей загрузки,
если новый таймер ещё не создал файл или завершился ошибкой.

Привилегированные действия выполняются отдельной явной командой:

```sh
python3 scripts/rp6-devtools.py --profile /path/profile.json action restart-decky
python3 scripts/rp6-devtools.py --profile /path/profile.json action restart-konkrd
python3 scripts/rp6-devtools.py --profile /path/profile.json action enable-ssh
python3 scripts/rp6-devtools.py --profile /path/profile.json action reboot
```

Разрешены только эти действия и `snapshot`. Нельзя передать произвольную службу,
команду или путь. Диагностика сама не перезапускает службы. Одновременные действия
root helper защищены lock; изменять устройство следует из одного чата за раз.
Физическое включение после shutdown и оценка изображения/ощущения управления
остаются ручными. Offline report можно забрать после возврата Wi-Fi.
`action reboot` ожидает восстановление SSH и проверяет смену boot ID;
ожидаемый обрыв соединения при выключении не считается успешным перезапуском
без подтверждения новой загрузки. Готовность Game Mode проверяется отдельным snapshot.

Штатный пакет заменяет `/usr`, поэтому отдельно установленный root helper
может исчезнуть после обновления. Пользовательский таймер, SSH-ключ и enabled
`sshd.service` сохраняются; первый отчёт в таком случае имеет статус `limited`.
Сначала сохранить этот отчёт, затем повторно установить helper из проверенных
исходников в HOME и снять полный snapshot. При реальной проверке UP-01 SSH
вернулся автоматически, а повторная установка восстановила root coverage.
В исходной системе `proxy_vars` и `wheel` имели права `0600` и `0644`;
перед успешной повторной установкой их привели к `0440` с проверкой SHA256,
владельца и типа файла, без изменения содержимого и backup.

Обычный `action reboot` имеет короткий срок ожидания SSH. Для update recovery
нужно отдельное длительное наблюдение за новым boot ID: фактическое применение
пакета на microSD заняло около 19 минут. Истечение короткого ожидания не доказывает
отказ загрузки и не является основанием для повторной перезагрузки.

## Удаление режима разработчика

На RP6:

```sh
systemctl --user disable --now rp6-devtools-snapshot.timer
sudo rm -f /etc/sudoers.d/zz-rp6-devtools /etc/sudoers.d/rp6-devtools /usr/local/libexec/rp6-devtools-root
```

После осмотра можно удалить только созданные `rp6-devtools` файлы и отчёты
из Home. SSH остаётся включённым; его можно отключить отдельно, когда диагностика
закончена. Fresh-image и supported-update приёмка UP-01 учитываются отдельно.

## Текущая проверка

96 source tests прошли на ARM64 Linux без пропусков; macOS — 96 tests, 9 пропусков.
Регрессии ожидания новой загрузки и готовности сессии воспроизведены RED и исправлены GREEN.
На RP6 установлен root helper. Два удалённых тёплых перезапуска подтвердили
автозапуск SSH, сохранение точной sudo-политики и чтение ожидаемого BOOT SHA256.
`sudo -n -k ... snapshot` проходит, произвольный `sudo -n -k /usr/bin/true`
требует пароль. Финальная версия установщика добавляет такую проверку от `steamos`;
на устройстве первый установщик дополнен переименованием политики пользователем,
его итоговые условия проверены отдельно.

Первый автоматический загрузочный отчёт прошёл системные проверки. Во второй
загрузке таймер зафиксировал ещё не запущенный focusfix; поздний snapshot прошёл.
По этому результату добавлено ограниченное ожидание готовности и проверено явным
запуском обновлённого oneshot на устройстве. Затем пользователь полностью выключил
и включил RP6 без Wi-Fi и подтвердил Game Mode и Decky → KONKR Control без ошибок.
Автоматический отчёт нового boot ID снят на uptime 54,91 с: Wi-Fi `disabled`,
все системные проверки прошли, SSH активен с 9,69 с и загрузочный таймер завершился
с кодом 0. После включения Wi-Fi по SSH подтверждены тот же boot ID, работающие
службы и тот же единственный Loader. Аппаратная приёмка всего UP-01 продолжается.
Один общий deadline ограничивает все команды загрузочного сборщика; медленная
последняя команда не продлевает ожидание и не мешает сохранить timeout-отчёт.
