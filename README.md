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

| Тема | Содержание |
|---|---|
| [USB и DUML: транспорт и запрос версии](./docs/research/transport/usb-duml.md) | На M4T проверен единичный запрос версии через USB. Это исследовательский пробник, не готовый backend SDK; драйверы и configuration не менялись. |
| [Батарея: наблюдения и однократные DUML-запросы](./docs/research/telemetry/battery.md) | Есть стабильное совпадение кандидата SOC с Pilot 2 при 35% и совпадение при переходе 34 -> 33%. Универсальный decoder и production battery API не подтверждены. |
| [Native-анализ: battery checker, Core, Qt и USB dispatch](./docs/research/native/analysis.md) | Адреса и layout привязаны к указанным неизмененным бинарным images. Статические связи не доказывают выбор ветки живым M4T; вызовы методов ради исследования не выполнялись. |
| [Независимый Linux updater: пакет и manifest](./docs/research/firmware/linux-updater.md) | Цель утверждена, но Linux writer пока не реализован. XML прочитан, все 22 компонента сопоставлены и проверены по MD5; криптографические подписи и firmware-session protocol пока не проверены. |
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
