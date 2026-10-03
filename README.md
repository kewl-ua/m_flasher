# dji-assistant-sdk — milestone 0

Первый инженерный этап: построить надежную модель страницы Firmware Update
на основе Accessibility/UIA дерева DJI Assistant 2.

На этом этапе **никаких операций Refresh/Downgrade не выполняется**.

## Установка

```powershell
cd dji_assistant_sdk_m0
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

DJI Assistant 2 должен быть уже запущен, а дрон подключен.

## Диагностика

```powershell
dji-assistant diagnose
dji-assistant firmware-probe
```

Или напрямую:

```powershell
python -m dji_assistant.devtools.firmware_tree
```

`firmware-probe`:
1. подключается к DJI Assistant;
2. открывает Firmware Update через UIA InvokePattern;
3. находит все строки, похожие на версии;
4. отделяет Current version от строк таблицы;
5. ищет минимального родителя, содержащего одну версию и action-кнопку;
6. печатает структуру найденных firmware-row.

Следующий milestone — превратить подтвержденную структуру в
`FirmwarePage.available()` и `FirmwarePage.current()`.
