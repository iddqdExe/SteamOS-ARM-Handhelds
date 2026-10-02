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
один отчёт через 45 секунд после старта user manager, без ожидания сети.
Отчёты: `~/.local/state/rp6-devtools/<boot-id>.json` и `latest.json`.
Несовпадающие существующие файлы и symlink paths требуют осмотра перед заменой.

Один раз выполни на RP6 в Konsole:

```sh
sudo /usr/bin/bash /home/steamos/.local/lib/rp6-devtools/install-root.sh
```

Установщик проверяет RP6 и microSD root, валидирует sudoers, устанавливает
root-owned `/usr/local/libexec/rp6-devtools-root` и включает `sshd.service`.
Новый SSH-ключ он не устанавливает. Пароль вводится локально в Konsole.

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

## Удаление режима разработчика

На RP6:

```sh
systemctl --user disable --now rp6-devtools-snapshot.timer
sudo rm /etc/sudoers.d/rp6-devtools /usr/local/libexec/rp6-devtools-root
```

После осмотра можно удалить только созданные `rp6-devtools` файлы и отчёты
из Home. SSH остаётся включённым; его можно отключить отдельно, когда диагностика
закончена. Fresh-image и supported-update приёмка UP-01 учитываются отдельно.

## Текущая проверка

90 source tests прошли на ARM64 Linux без пропусков; macOS — 90 tests, 9 пропусков.
На RP6 проверены keyed SSH, включённая служба SSH, синтаксис точной sudo-политики,
systemd units, установка и однократное выполнение пользовательского таймера.
Первый отчёт забран по SSH; перечисленные системные наблюдения прошли со статусом
`limited`. Root bootstrap, автозапуск SSH после следующей загрузки и отчёт при
фактически выключенном Wi-Fi ещё требуют проверки на устройстве.
