# Скрытый режим: IsolatedAssistant и CLI

[Главная и карта документации](../README.md)

Отдельный Windows desktop, worker и восстановление через attach. Запись прошивки в этом режиме не доступна; offline-select только выбирает пакет.

Материалы ниже сохраняют ход исследования. Последующие записи могут уточнять ранние гипотезы; ограничения приведены рядом с результатами.

## Экспериментальный API IsolatedAssistant

`IsolatedAssistant` управляет отдельным Python worker и официальным
Assistant на отдельном Windows desktop. Worker всегда использует
`allow_physical_input=False, addressed_input=True`. Установленные файлы
DJI не меняются, desktop пользователя не переключается. IPC использует
ограниченные JSON-кадры через временный loopback socket с одноразовым
случайным секретом; секрет передается worker через окружение, не аргументы.
Произвольное исполнение Python/JS и команды записи прошивки не доступны.
Пакет должен быть установлен в интерпретаторе, запускающем этот API.

Перед `launch` необходимо штатно закрыть обычный Assistant.
Worker проверяет отсутствие процессов DJI перед запуском и запрещает
одновременную работу второго SDK worker через именованный mutex.
Он не закрывает существующее приложение автоматически.
Все новые launch используют один desktop `DjiSdk_IsolatedAssistant`
в текущей WinSta0, переиспользуя его после штатного выхода.
Перед запуском проверяются также окна чужих процессов на этом desktop
(включая скрытые); при их наличии или ошибке проверки запуск запрещен.
Старые desktop с уникальными именами по-прежнему доступны через attach.
Один удерживаемый Windows-объект допустим; SDK не обещает немедленно
удалить его и не закрывает чужие handles.

```python
from dji_assistant import IsolatedAssistant

dji = IsolatedAssistant.launch(
    r"C:\Program Files (x86)\DJI Product\DJI Assistant 2 (Enterprise Series)\DJI Assistant 2.exe",
    title="DJI Assistant 2 (Enterprise Series)",
)
print("Recovery desktop:", dji.desktop_name)
try:
    dji.open_device("Matrice 4T", timeout=45)
    print(dji.current(), dji.status())
    dji.ignore_flysafe()  # Ignore only; does not update the database.
    dji.select_package(r"C:\dev\fw_list\m4t\M4T_UAV_17.02.05.01_pro.zip")
    print(dji.current())  # Returns to Firmware Update and waits for readable Current.
    dji.quit_application()  # Guarded normal exit, only on an idle firmware page.
finally:
    dji.close()
```

`close()` только отключает канал и освобождает ресурсы контроллера:
**Assistant остается на скрытом desktop**, если не вызван успешный
`quit_application()`. Не используется принудительное завершение DJI.
Для восстановления после отключения:

```python
recovered = IsolatedAssistant.attach(
    saved_desktop_name,
    title="DJI Assistant 2 (Enterprise Series)",
)
print(recovered.current(), recovered.status())
recovered.quit_application()
```

При timeout/обрыве IPC результат команды считается неизвестным:
канал больше не выполняет команды, автоматических повторов нет.
Сначала вызовите `close()`, затем восстановите соединение через `attach`
и проверьте состояние. Если worker еще заканчивает команду, это явно
сообщается; новый worker не получает управление одновременно с ним.
`attach` не запускает второй Assistant. Сохраните `desktop_name` до
первых действий. При неудачном запуске имя desktop включено в ошибку;
если приложение еще не появилось или desktop уже исчез, attach завершится
ошибкой, а не запустит приложение заново.

Поддержаны `open_device`, `current`, `status`, `ignore_flysafe`,
`select_package`, `quit_application`, `close` и `attach`.
Для CLI доступна отдельная группа `isolated` (пример ниже).
Terms of Use автоматически не принимаются;
ручной показ скрытого desktop и взаимодействие с неизвестными диалогами
не реализованы. Режим остается экспериментальным.

## CLI скрытого режима

Сначала штатно закройте обычный Assistant. Пример для PowerShell:

```powershell
$title = "DJI Assistant 2 (Enterprise Series)"
$exe = "C:\Program Files (x86)\DJI Product\DJI Assistant 2 (Enterprise Series)\DJI Assistant 2.exe"
dji-assistant --window-title $title isolated launch $exe
dji-assistant --window-title $title isolated open-device "Matrice 4T" --timeout 45
dji-assistant --window-title $title isolated current
dji-assistant --window-title $title isolated status
dji-assistant --window-title $title isolated ignore-flysafe
dji-assistant --window-title $title isolated offline-select "C:\dev\fw_list\m4t\M4T_UAV_17.02.05.01_pro.zip"
dji-assistant --window-title $title isolated quit
```

Проверяйте `$LASTEXITCODE` после каждого вызова: `0` означает успешную
команду и отключение worker; `1` означает ошибку команды либо отключения.
Ошибки аргументов возвращают `2` до подключения. Не продолжайте сценарий
и не повторяйте действия автоматически после ошибки.

`launch` запускает приложение и печатает desktop для восстановления.
Остальные команды подключаются к существующему `DjiSdk_IsolatedAssistant`;
после каждой команды worker штатно отключается, а Assistant остается
на скрытом desktop. Только `isolated quit` закрывает приложение
с проверкой idle и штатного выхода. Вызов `attach` проверяет подключение
без навигации; если приложение закрыто, он сообщает ошибку, не запускает
новый экземпляр. Для старого desktop можно явно указать имя:

```powershell
dji-assistant --window-title $title isolated attach --desktop DjiSdk_old_name
dji-assistant --window-title $title isolated current --desktop DjiSdk_old_name
```

Все команды принимают `--timeout` (положительное конечное число секунд):
launch по умолчанию 60, offline-select 120, quit 20, остальные 30.
Он задает срок подключения, а для open-device, offline-select и quit
также передается соответствующему действию. Для current/status/Ignore
таймаут самого RPC остается стандартным API (30 секунд).
Опции `--window-title` указываются до `isolated`, остальные опции
после конкретной команды. Глобальные флаги физического/адресного ввода
для этой группы запрещены: безопасные настройки заданы самим worker.
Команд upgrade/downgrade/refresh/offline-upgrade в группе нет.
offline-select только выбирает ZIP и возвращается на Firmware Update;
Start Upgrade/Start Update не нажимаются.

Live-прогон установленного CLI прошел последовательность launch,
open-device, current, status, ignore-flysafe, offline-select, attach,
current/status, quit отдельными вызовами. Current до и после выбора
официального ZIP: 17.02.0501, idle. После quit процессов DJI/worker
не осталось. Дополнительный attach с timeout 2 после закрытия вернул
код 1 и не запустил приложение; в конце Assistant оставлен закрытым,
как перед этим прогоном. Прошивки не запускались.

Проверено закрытие Assistant вне существующего контроллера: отдельный
тестовый процесс на том же desktop штатно закрыл idle-приложение,
пока основной worker ожидал команды. Следующее current вернуло ошибку,
не устаревшую версию; attach после выхода также завершился ошибкой
без автоматического запуска. Явный launch восстановил чтение
17.02.0501 / idle, после чего приложение штатно закрыто.
Неясная ошибка WinError 0 при обращении к исчезнувшему HWND заменена
явной проверкой существования окна и инструкцией по восстановлению.
Проверка HWND не гарантирует, что окно не исчезнет сразу после нее;
последующие Win32/UIA ошибки по-прежнему передаются без повторов действий.

Live-проверка самого API: отказ запуска при существующем обычном Assistant;
изолированное открытие Matrice 4T, Current 17.02.0501 / idle,
выбор официального ZIP, отключение worker без закрытия Assistant,
повторное подключение к тому же desktop и штатный выход. Первый прогон
выявил задержку Current после возврата со страницы Offline Upgrade;
повторного выбора не было, приложение восстановлено через attach.
После исправления весь сценарий прошел непрерывно, включая немедленное
чтение Current после select_package. OpenInputDesktop опрашивался
каждые 50 мс: все результаты Default, ошибок наблюдения не было.
Обычный Assistant восстановлен с Current 17.02.0501 / idle;
процессов isolated worker после завершения не осталось.
Ни Start Upgrade, ни Start Update не нажимались.

Дополнительная безопасная матрица 2026-10-04: два последовательных
изолированных запуска с открытием устройства прошли за 8.47 и 10.15 с.
В каждом проверены повторный open_device на уже открытом устройстве,
Ignore и повторный Ignore без prompt, отказ второго worker при attach,
отказ несуществующего файла с сохранением Current/idle, выбор ZIP,
повторный выбор уже выбранного ZIP и отказ команды refresh в IPC.
Первый цикл проверил close/idempotence/attach. Второй вызвал настоящий
IPC timeout при ожидании несуществующего устройства: канал заблокировал
последующие команды; close и attach восстановили чтение того же Assistant
без повторения команды. Оба цикла завершены штатным quit; процессов DJI
и worker после выхода не осталось. Все отсчеты OpenInputDesktop
(каждые 50 мс) вернули Default. Обычный запуск восстановлен,
Current 17.02.0501, idle. Запись прошивки не выполнялась.

Проверка очистки выявила отдельное ограничение: после выхода всех процессов
и закрытия SDK handles пустой desktop еще открывался по имени; его окон
не было. Причина удержания Windows-объекта не установлена.
`close()` гарантирует освобождение handles контроллера, но не немедленное
исчезновение desktop-объекта из Windows. Многократные длительные циклы
на накопление desktop-ресурсов пока не проверены.

Последующая ограниченная проверка очистки уточнила риск: 20 циклов
CreateDesktop/CloseDesktop без worker, пять коротких Python GUI-thread
worker и пять SDK worker, отказавших запуску из-за существующего DJI,
не добавили desktop-объектов. Однако три полных read-only цикла
Assistant (launch -> open_device -> Current/idle -> Ignore -> quit)
оставили три новых именованных desktop после завершения процессов DJI
и worker. Циклы заняли 16.32, 15.91 и 16.58 с; выбор ZIP не выполнялся.
Таким образом, удержание воспроизводится и без native file picker.
Причина удержания и владелец ссылки не установлены. Перечисление
доступных desktop-ссылок потоков не нашло SDK desktop, но большинство
потоков было недоступно; это не доказывает отсутствие внешнего владельца.
В исследованной первоначальной реализации каждый launch создавал уникальный desktop; длительные циклы могли
накапливать Windows-объекты; режим не следует использовать как
неограниченный restart-loop в этой реализации. Обычный запуск после проверки восстановлен,
Current 17.02.0501, idle; после замены батареи также подтверждены
доступность Matrice 4T и эти значения. Прошивки не запускались.

После перехода на один переиспользуемый desktop проверены три живых
read-only цикла с тем же `DjiSdk_IsolatedAssistant`, включая close/attach
во втором цикле. После первого цикла появился ровно один новый
desktop-объект; после второго и третьего множество имен не выросло.
Предыдущие уникальные desktop этим изменением не удаляются. Во всех
циклах Current оставался 17.02.0501, idle; обычный Assistant восстановлен.
Это ограниченная проверка отсутствия накопления desktop-имен, а не
доказательство отсутствия любых утечек памяти или handles.

`flysafe_prompt()` обнаруживает известное предупреждение базы No-fly Zone.
`confirm_flysafe(confirm=True)` требует отдельного явного разрешения; вызов
подтверждения сам по себе не доказывает успешное обновление базы.

## Связанные материалы

[Windows: адресный ввод, file picker и отдельный desktop](./windows-experiments.md) · [Windows SDK: чтение, операции, запуск и CLI](./windows-sdk.md) · [Валидация: unit-тесты и границы live-покрытия](./validation.md)
