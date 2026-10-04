# dji-assistant-sdk

Первый инженерный этап: построить надежную модель страницы Firmware Update
на основе Accessibility/UIA дерева DJI Assistant 2.

Команды диагностики и методы чтения SDK **не выполняют операций прошивки**.
Отдельные экспериментальные прогоны через штатный UI описаны в [журнале проверок](./docs/validation/firmware-live.md).

## Текущее состояние

- Обычный SDK: чтение Current/таблицы/status, запуск приложения,
  навигация и отдельно разрешаемые операции прошивки.
- Экспериментальный скрытый режим: отдельный Windows desktop,
  адресный ввод без физических кликов, восстановление через attach.
  Доступен из Python (`IsolatedAssistant`) и CLI (`isolated`).
  Запись прошивки в скрытом режиме не доступна.
- Последняя проверенная версия Matrice 4T: **17.02.0501**, idle.
  Исторические снимки в документации описывают состояние на момент каждого прогона.
- Прямой USB-доступ исследуется: отдельный локальный пробник выполнил
  один запрос версии M4T и получил коррелируемый CRC-валидный ответ
  17.02.0501. После этого штатный Assistant подтвердил прежний Current / idle.
  Это проверка конкретного устройства/драйвера, не готовый USB backend SDK.
- После переподключения Windows повторно увидела DJI MI04 со статусом OK;
  текущие USB bus address и libusb path еще не определены. Старые значения
  нельзя повторно использовать без новой проверки привязки.
- Linux updater: offline сопоставлены все 22 компонента официального ZIP,
  их MD5 совпали с manifest. Статически найдена цепочка IM*H container ->
  extraction -> Qt XML parser; поле +0xC8 задает slice длиной 24998 байт
  для этого config. Подписи, hardware selection и upgrade-center protocol
  пока не подтверждены полностью; в этой рабочей копии независимый writer
  не интегрирован, Linux transport на устройстве не проверен.
  Подробности: [XML manifest и native consumer](./docs/research/firmware/package-manifest.md).
- Предоставленный полный USB capture независимо разобран offline:
  23 файла release **17.01.0516** переданы по DUML `00/2A` на адрес 48;
  **666015264 байта за 61,05 секунды**; размеры, непрерывность chunks
  и finish MD5 совпали. Переданы все hardware variants из manifest.
  Команды `00/81` и `00/82` инициирует 48, ПК отвечает; data ACK
  имеют собственный sequence. Полный контракт session, pacing и recovery
  еще не восстановлен. Это не проверка нашего Linux writer.
  [Результаты и поправки к пересказу](./docs/research/firmware/capture-transfer.md).
- Второй capture штатного **Offline Upgrade 17.02.0501** подтвердил
  содержимое нашего ZIP: config совпал побайтно, все 22 firmware — по SHA256;
  **665796192 байта за 69,73 секунды**. В обоих captures получены terminal
  `04 01 00` и post-reconnect `4F`, согласующийся с целевым release.
  Найдены разные длины расширенного `42` и ACK с медианой около 100 ms;
  универсальная схема статусов, ошибки и recovery еще не подтверждены.
  [Сравнение online/offline и управляющая последовательность](./docs/research/firmware/capture-offline-upgrade.md).
- Проверен журнал внешней реализации `dji_duml`: **Windows Refresh
  17.02.0501 -> 17.02.0501 за 205,026 s**. Все 2444 сохраненных кадра
  прошли CRC; есть terminal `04 01 00`, ответы `4F` и затем `1F`
  с целевой версией. Отчеты о 23 файлах совпали с нашим offline capture,
  но data chunks в JSONL отсутствуют. Это не проверка Linux или смены версии.
  [Доказательства, ограничения и следующие проверки](./docs/research/firmware/direct-refresh-journal.md).
- **120 unit-тестов**; живые проверки описаны в [отчете о валидации](./docs/validation/coverage.md) отдельно от unit-тестов.

Быстрый старт скрытого режима и ограничения:
[CLI скрытого режима](./docs/guides/isolated-assistant.md#cli-скрытого-режима),
[API IsolatedAssistant](./docs/guides/isolated-assistant.md#экспериментальный-api-isolatedassistant).
Закройте обычный Assistant перед скрытым launch. Terms of Use и неизвестные
диалоги пока могут требовать вмешательства пользователя; полностью
безусловная автономность не гарантируется.

## Установка

```powershell
cd dji_assistant_sdk_m0
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

Для обычных команд диагностики DJI Assistant 2 должен быть уже запущен,
а дрон подключен. `isolated launch` запускает установленное приложение сам.

## Документация и исследования

Полная [карта документации](./docs/README.md) разделяет инструкции,
проверенные результаты и исследования, объясняет степень подтверждения
и маршрут к независимому Linux updater.

### Руководства SDK

| Тема | Содержание |
|---|---|
| [Windows SDK и CLI](./docs/guides/windows-sdk.md) | Чтение, операции, запуск и штатное закрытие |
| [Скрытый режим](./docs/guides/isolated-assistant.md) | IsolatedAssistant, worker и attach; запись прошивки запрещена |

### Валидация

| Тема | Содержание |
|---|---|
| [Покрытие и ограничения](./docs/validation/coverage.md) | Исторические результаты unit-тестов и границы live-покрытия |
| [Журнал прошивок M4T](./docs/validation/firmware-live.md) | Отдельно разрешенные операции и проверенные результаты |

### Исследования

Быстрый справочник: [адреса DUML — type/index, публичные имена и роли на M4T](./docs/research/transport/usb-duml.md#справочник-адресов-duml).
В нем отдельно разобраны `2A` (ПК), `48` (принимающая firmware сторона),
адресные prefixes из XML/статусов и отличие от USB addresses.

| Тема | Содержание |
|---|---|
| [USB и DUML: транспорт и запрос версии](./docs/research/transport/usb-duml.md) | На M4T проверен единичный запрос версии через USB. Это исследовательский пробник, не готовый backend SDK; драйверы и configuration не менялись. |
| [Батарея: наблюдения и однократные DUML-запросы](./docs/research/telemetry/battery.md) | Есть стабильное совпадение кандидата SOC с Pilot 2 при 35% и совпадение при переходе 34 -> 33%. Универсальный decoder и production battery API не подтверждены. |
| [Native-анализ: battery checker, Core, Qt и USB dispatch](./docs/research/native/analysis.md) | Адреса и layout привязаны к указанным неизмененным бинарным images. Статические связи не доказывают выбор ветки живым M4T; вызовы методов ради исследования не выполнялись. |
| [Независимый Linux updater: пакет и manifest](./docs/research/firmware/linux-updater.md) | XML/MD5 компонентов, captures Assistant и журнал внешнего Windows Refresh. Linux transport, интеграция writer, подписи и полный контракт session/recovery не проверены. |
| [Windows: адресный ввод, file picker и отдельный desktop](./docs/research/windows/automation.md) | Экспериментальные способы автоматизации и их ограничения. Отрицательные и предварительные результаты сохранены; они не являются обещанием готовой автономности. |

Исследовательские результаты не являются готовым USB/Linux backend. Новые live-запросы и операции записи требуют отдельного согласования; прежние однократные разрешения не переносятся на новые эксперименты.

## Диагностика

```powershell
dji-assistant diagnose
dji-assistant firmware-probe
```

Или напрямую:

```powershell
python -m dji_assistant.devtools.firmware_tree
```

Для DJI Assistant 2 (Enterprise Series), в том числе при проверке M4T,
укажите точный заголовок окна:

```powershell
dji-assistant --window-title "DJI Assistant 2 (Enterprise Series)" diagnose
dji-assistant --window-title "DJI Assistant 2 (Enterprise Series)" firmware-probe
python -m dji_assistant.devtools.firmware_tree --window-title "DJI Assistant 2 (Enterprise Series)"
```

SDK также принимает заголовок в `DJIAssistant.connect(title=...)`.
Успешный `diagnose` подтверждает подключение к окну, но не обнаружение дрона:
для `firmware-probe` откройте карточку устройства в DJI Assistant.
Если UIA видит только оболочку окна, чтение прошивок невозможно, пока
приложение не предоставит дерево элементов Accessibility.

`firmware-probe`:
1. подключается к DJI Assistant;
2. открывает Firmware Update через UIA InvokePattern;
3. находит все строки, похожие на версии;
4. отделяет Current version от строк таблицы;
5. ищет минимального родителя, содержащего одну версию и action-кнопку;
6. печатает структуру найденных firmware-row.

Методы чтения `FirmwarePage.available()` и `FirmwarePage.current()`
описаны в [Windows SDK](./docs/guides/windows-sdk.md); `firmware-probe` остается подробным инструментом исследования.
