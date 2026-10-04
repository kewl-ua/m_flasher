# USB и DUML: транспорт и запрос версии

[Главная и карта документации](../../../README.md) | [Карта документации](../../README.md)

На M4T проверен единичный запрос версии через USB. Это исследовательский пробник, не готовый backend SDK; драйверы и configuration не менялись.

Материалы ниже сохраняют ход исследования. Последующие записи могут уточнять ранние гипотезы; ограничения приведены рядом с результатами.

## DUML: карта подтверждения

Сводка на 2026-10-04. Номера ниже записаны в hex как
`CmdSet/CmdId`, а не как адрес получателя. Совпадение номера команды
не гарантирует одинаковые payload, адреса, encoding или поведение на
разных платформах. Наличие имени в публичном dissector означает
«описано сообществом», а не «доступно на M4T».

### Что проверено нами

| Объект / команда | Проверка | Результат и ограничение |
|---|---|---|
| USB MI04, OUT 04 / IN 85 | Descriptor, native ABI/host mapping; live обмен | Interface 4 / alt 0, bulk 512 на данном Windows-драйвере; Linux пока не проверен |
| DUML framing / CRC | Offline-разбор live capture и отдельных ответов | Есть CRC8/CRC16-valid пакеты; полнота разбора потока не заявляется |
| `00/01` — версия | Один самостоятельный запрос, CRC и обратные адреса/sequence | Ответ 17.02.0501 совпал с Assistant Current; полная схема ответа не подтверждена |
| `0D/02` — dynamic battery | Три отдельно разрешенные однократные попытки | При исправленном фильтре flags 80/result 00/payload 45: raw offset 21 совпал с 35% и последующим 33%; универсальный SOC decoder не подтвержден |
| `03/43` — OSD | Пассивное наблюдение и offline-анализ | Наблюдался payload 84 байта; проверенный SOC не найден, самостоятельный запрос не выполнялся |
| `00/78`, payload 01, receiver A2 | Только static native tracing | Найденная checker-ветка связана с `rcp501`; не установленный запрос батареи M4T, не отправлялся |
| `00/0C` — device state | Только static Go metadata | Loader/no-repower/version fields; named SOC нет, не отправлялся |
| `00/1F` — log-export subscription | Только static Go metadata/consumer | Подписка concrete log-export type, не battery API; workflow не запускался |
| SmartBattery Qt push | Только static C++ dispatcher | Копируется 30 байт; значение +0x34 = 0x51 пока не связано с wire `03/51`, SOC не декодирован |
| Firmware file-transfer через DUML | Offline-разбор двух предоставленных captures | По 23 файла `00/2A` на 48; MD5 проверены, Offline Upgrade совпал с ZIP также по SHA256; собственный writer не запускался |
| `00/81` / `00/82` | Все пары двух captures | Инициатор 48, ПК отвечает; command/address/sequence совпадают; роль в authorization неизвестна |
| `00/83` / `00/84` / `00/85` | CRC-валидные control exchanges двух captures | Наблюдаемый порядок установлен; `84` содержит сумму bytes, `85` отвечает `06` в обоих прогонах; полная семантика неизвестна |
| `00/42` / `00/4F` / `00/41` | Terminal и post-reconnect exchanges | `04 01 00` согласуется с public Complete / Success, `4F` — с целевым release; длинные `42` и универсальный Current API не декодированы полностью |

Подробности и оговорки: [battery queries](../telemetry/battery.md),
[native analysis](../native/analysis.md),
[штатные UI-прошивки](../../validation/firmware-live.md).
Первый отрицательный battery result относится к ошибочно строгому
exact-C0 фильтру; без сохраненного raw stream его нельзя переоценить.

### Что еще описано в открытых источниках

Новый [отчет по capture 17.01.0516](../firmware/capture-transfer.md)
подтверждает формат open/data/finish `00/2A` и корректирует направление
`00/81` / `00/82`: инициатор 48, ПК отвечает. Полный workflow не восстановлен.
[Второй capture и сравнение](../firmware/capture-offline-upgrade.md)
добавляют 17.02.0501, control sequence, ACK timing и границы status decoder.

Это выборочная карта направлений, не полный список DUML и не набор
готовых запросов. Во всех строках ниже live-совместимость с нашим M4T
**не проверена**, кроме пересечений, явно отмеченных в таблице выше.
Некоторые entries содержат только имя, без полного dissector.

| Направление | CmdSet/CmdId из источника | Что описано | Источник / наш статус |
|---|---|---|---|
| Идентификация | `00/51`, `00/FF` | Serial number, device/build information | [General][duml-general]; не запрашивали |
| Общая диагностика | `00/4B`, `00/4C`, `00/54`, `00/55` | Date/time, module system status, temperature, alive time | [General][duml-general]; layout/единицы/адреса M4T не установлены |
| Static battery | `0D/01`, `0D/04`, `0D/05` | Static data, barcode, history | [Protocol tables][duml-proto]; только публичные названия, не проверенные поля M4T |
| Dynamic battery | `0D/02`, `0D/03`, `0D/06`, `0D/32` | Dynamic data, cell voltages, common info, multi-battery info | [Protocol tables][duml-proto]; только `0D/02` проверен в ограниченном объеме; остальные не отправлялись |
| Альтернативная battery-ветка | `05/02`, `05/06`, `05/07`, `05/08`, `05/21`, `05/22` | Center-board battery dynamic/common/status/history/static data | [Protocol tables][duml-proto]; это отдельный CmdSet, не замена `0D/02` без проверки |
| Flight-controller telemetry | `03/01`, `03/0A`, `03/43`, `03/44`, `03/45`, `03/51` | Status, battery status, OSD, home point, GPS SNR, smart battery status | [Flight Control][duml-flyc]; `03/43` наблюдали пассивно, остальное не подтверждено |
| Vision / RTK | `0A/07`, `0A/2F`, `0F/09` | Obstacle info, sensor status, RTK status | [Protocol tables][duml-proto]; не проверяли |
| Файловый обмен | `00/20`, `00/21`, `00/22`, `00/23`, `00/24`, `00/25`, `00/2A` | List/info, send/receive, segments/error/general transfer | [General][duml-general]; `00/2A` теперь подтвержден отдельным capture firmware files; остальные не проверены |
| Upgrade session | `00/07`, `00/08`, `00/09`, `00/0A`, `00/0F` | Loader entry, prepare/start, data transfer, verify, consistency request | [General][duml-general]; не отправляли, порядок/payload/ACK/apply для M4T не восстановлены |
| Upgrade notifications/control | `00/40`, `00/41`, `00/42`, `00/43` | Descriptor push, control, progress/status, finish | [General][duml-general]; `42` push и последующий `41/04` наблюдались в captures; полный M4T decoder и обязательность команд не установлены |

В источнике также есть camera/gimbal/RC/link command families.
Они не исследованы нами как интерфейсы M4T; публичный каталог не является
официальной матрицей поддержки DJI.

### Граница безопасного продолжения

Название `Get` не гарантирует отсутствие побочных эффектов: команда может
изменять push subscription или режим модуля. Перед отдельным экспериментом
нужно проверить payload, receiver, encoding/result, минимальную длину,
correlation и условия устройства; подбор адресов/команд не выполняется.
Приоритет чтения: static battery/cell voltage, device identification/state,
затем независимая сверка каждого поля. Это направления исследования,
не разрешение на отправку.

Loader/update/file-transfer, reboot, battery shutdown, activation,
authentication, setters, calibration и flight/motor control не входят
в read-only scope. Для Linux updater сначала требуется восстановить
[manifest consumer и upgrade protocol](../firmware/linux-updater.md),
а не отправлять последовательность исторических номеров из dissector.
В рамках этой документационной сверки новых USB-запросов не было.

### Открытые источники и воспроизводимость

Проверены 2026-10-04 в community-проекте `o-gs/dji-firmware-tools`,
revision `195692263c2684cf1ddc4995f2736be6c0fb135e`:

- [Protocol tables][duml-proto]: CmdSet, адресные типы, ACK/encoding names,
  battery/center-board/vision/RTK command names.
- [General][duml-general]: идентификация, диагностика, файлы и upgrade.
- [Flight Control][duml-flyc]: OSD, GPS и battery command names.

Это reverse-engineered сведения, в том числе о старых DJI платформах;
комментарии прямо отмечают разные назначения некоторых номеров.
Закрепленная revision позволяет повторить сверку независимо от будущих
изменений ветки master. Публичные названия не подтверждают firmware/auth
совместимость M4T и не заменяют наши live результаты.

[duml-proto]: https://github.com/o-gs/dji-firmware-tools/blob/195692263c2684cf1ddc4995f2736be6c0fb135e/comm_dissector/wireshark/dji-dumlv1-proto.lua
[duml-general]: https://github.com/o-gs/dji-firmware-tools/blob/195692263c2684cf1ddc4995f2736be6c0fb135e/comm_dissector/wireshark/dji-dumlv1-general.lua
[duml-flyc]: https://github.com/o-gs/dji-firmware-tools/blob/195692263c2684cf1ddc4995f2736be6c0fb135e/comm_dissector/wireshark/dji-dumlv1-flyc.lua

## Исследование прямого USB-чтения M4T

### Повторное перечисление после переподключения

На 2026-10-04 после сообщенного пользователем переподключения Windows
PresentOnly PnP снова показывает VID 2CA3/PID 0020, MI00/MI02/MI03-MI07.
Все перечисленные nodes имеют status OK, включая MI04/libusb-win32;
DJI-процессы при проверке не обнаружены.
Это чтение OS metadata, без open/claim/read/write USB и DUML queries.
USB bus address и текущий libusb device path этой проверкой **не определены**.
Исторические address 47 и libusb path нельзя использовать повторно
без новой live mapping проверки. PnP InstanceId, bus address и
внутренний libusb номер — разные идентификаторы.

Read-only наблюдение 2026-10-04 подтвердило USB composite
VID 2CA3 / PID 0020: RNDIS (MI00), Mass Storage (MI02) и пять
vendor-specific bulk-интерфейсов MI03-MI07, class FF/subclass 43/protocol 01,
с установленным libusb-win32. Это не означает, что любой из интерфейсов
пригоден для произвольных команд; драйверы не менялись.

USBPcap уже установлен. Windows hub connection query подтвердил
Port 9 и текущий USB device address 47 на USBPcap1. Это разные
идентификаторы: после переподключения address нужно определять заново.
Короткий локальный захват ограничен только address 47, без режима
capture-all и без трафика клавиатур, мышей или камеры того же hub.
Захват выполнялся при штатном скрытом запуске Assistant, открытии
Matrice 4T и чтении Current 17.02.0501 / idle; прошивки не запускались.
USBPcap не завершился по переданному через stdin q, поэтому остановлен
его конкретный тестовый процесс; файл после остановки успешно прочитан.

В bulk-трафике обнаружено 9042 пакета с валидными header CRC8
(seed 77, reflected polynomial 8C) и CRC16
(seed 3692, reflected polynomial 8408), совместимых с описанным
публичными dji-firmware-tools DUPC/DUML framing. Это результат
экспериментального offline-разбора: остались нераспознанные байты
и короткие хвосты, полнота декодирования не заявляется.
Сопоставления запросов/ответов могут включать повторные ответы.

Одна проверенная пара на endpoint OUT 04 / IN 85:
command set 00, command ID 01, одинаковый sequence 0x2710 (bytes 10 27),
обратные адреса 2A/1F и флаг ответа. Ответ содержит
`WA345T AC Ver.A` и последовательность `f5 01 02 11`.
Если трактовать их как build (uint16 little-endian), minor (uint8), major (uint8),
получается 17.02.0501, совпадающая с Current UIA. Полное описание полей
и семантика адреса модуля пока не подтверждены.
На этапе этого захвата наблюдаемый ответ не доказывал безопасную поддержку
самостоятельного запроса: прямых команд устройству еще не отправлялось,
bulk-интерфейсы нашим кодом не захватывались. USB backend пока не добавлен.
Планируемый первый этап backend ограничен чтением версии/идентификации:
нужны подтверждение раскладки ответа, привязка endpoints к интерфейсу
и проверка самостоятельного запроса при закрытых DJI-процессах.
Транспортная доступность не означает поддержку всех команд, отсутствие
авторизации или безопасность прямой записи прошивки. Запись остается
за отдельно разрешаемым штатным сценарием Assistant.
Серийные строки из захвата не публикуются; сырой временный capture удален.

Источники формата и транспорта:
[comm_serialtalk.py](https://github.com/o-gs/dji-firmware-tools/blob/master/comm_serialtalk.py),
[comm_dat2pcap.py](https://github.com/o-gs/dji-firmware-tools/blob/master/comm_dat2pcap.py),
[Windows USB hub connection information](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbioctl/ns-usbioctl-_usb_node_connection_information_ex).
Публичный USB bulk transport существует, но совместимость готовых
сторонних CLI-команд с Matrice 4T не подтверждена.

Следующий read-only этап получил полный USB configuration descriptor
через стандартный Windows hub GET_DESCRIPTOR (не команду DJI):
213 байт, 8 interfaces. Наблюдавшийся OUT 04 / IN 85 принадлежит
interface 4, alternate 0 (MI04), class FF/subclass 43/protocol 01;
оба endpoints bulk, max packet size 512. Другие vendor-specific
интерфейсы имеют пары 03/84, 05/86, 06/87 и 07/88; назначение этих
каналов не установлено, пробные команды на них не отправлялись.

DLL из каталога Assistant имеют PE machine 014C (32-bit), несовместимый
с нашим 64-bit Python. Системная libusb0_device.dll имеет PE machine 8664
и версию 1.2.6.0, экспортирует функции перечисления/open/claim/bulk.
Ее native enumeration видит пять DJI device paths, однако раскладка
usb_device из проверенного публичного заголовка не дала валидных
device descriptor полей. На этом этапе источник ABI-несовпадения еще не был установлен;
исправлять его подбором смещений или угадыванием interface нельзя.
Наш пробник не вызывал usb_open, claim, bulk read/write, reset,
set_configuration либо set_altinterface. Стандартный Windows
GET_DESCRIPTOR выше выполнен отдельно через hub API.
Самостоятельный запрос версии отложен до проверки native ABI/транспорта.
Временный пробник удален, установленный SDK USB backend по-прежнему
не содержит. Установленные файлы DJI и драйверы не изменялись.

Последующая read-only проверка разрешила причину некорректного перечисления
для конкретной установленной DLL: native код usb_open обращается к bus
по смещению 0x410, а код перечисления записывает 18-байтовый device descriptor
по смещению 0x418 и выделяет usb_device размером 0x444. Эти значения
подтверждены ограниченным disassembly установленной DLL, не подбором
смещений по ответам USB. Между filename и bus присутствует дополнительное
512-байтовое поле; его содержимое при перечислении выглядит как строка
топологии подключения. С этой раскладкой все пять записей вернули валидный
device descriptor (length 18, type 1, VID 2CA3/PID 0020, одна configuration).
Объявленная версия 1.2.6.0 не означает ABI-совместимость с upstream:
публичный заголовок этого дополнительного поля не содержит.

Проверка относится только к DLL с SHA256
`8f681861a8e7abf6ec85f83bd08d4456cc9d6c0b0172c83d878da7404fb7f468`.
Обобщенный backend на этих смещениях пока не добавляется.
Пять native device paths имеют одинаковые VID/PID и topology;
какой из них представляет MI04, еще не подтвержден. Индекс имени
libusb0-000N нельзя приравнивать к номеру USB-интерфейса.
Поэтому даже после исправления enumeration usb_open/claim/bulk
не выполнялись. Следующая граница: достоверно сопоставить native path
с MI04, затем отдельно проверить один коррелируемый запрос версии.
Assistant оставлен закрытым; драйверы и установленные DLL не менялись.

Следующий этап подтвердил привязку native path через локальные метаданные
драйвера, а не через пробные команды дрону. Windows QueryDosDevice показал,
что имя для открытия не содержит суффикс VID/PID. Host-only
LIBUSB_IOCTL_GET_OBJECT_NAME (0x2223FC, objname_index 0) возвращает PnP
registry path; публичная реализация этого запроса копирует сохраненную
строку драйвера и не выполняет USB transfer. На текущем подключении:

| Native Windows path | Подтвержденный PnP interface |
| --- | --- |
| `\\.\libusb0-0001` | MI03 |
| `\\.\libusb0-0002` | MI04 |
| `\\.\libusb0-0003` | MI05 |
| `\\.\libusb0-0004` | MI06 |
| `\\.\libusb0-0005` | MI07 |

Для чтения этих метаданных кратковременно открывались Windows handles
с desired access 0, без usb_open, claim или bulk I/O. Все handles закрыты.
Это снимок конкретного подключения: номера нельзя сохранять как
постоянную привязку, после переподключения сопоставление нужно повторять.
GUID класса установки и GUID device interface также нельзя приравнивать.

## Первый самостоятельный USB-запрос версии

Локальный эксперимент 2026-10-04 выполнен при закрытых DJI-процессах.
До обращения к устройству проверены SHA256 DLL и native structure layout,
повторно подтверждена привязка выбранного пути к MI04. Стандартный
configuration descriptor через открытый native handle подтвердил
interface 4 / alternate 0 / FF-43-01 и bulk endpoints 04/85, size 512.
Только после этих проверок захвачен interface 4.

Отправлен ровно один ранее наблюдавшийся запрос command set 00 / ID 01
с новым sequence 0x5A13, sender 2A / receiver 1F:
`550d04332a1f135a400001c486` (13 байт). Bulk write вернул ровно 13.
Получен 44-байтовый ответ с обратными адресами, тем же sequence,
флагами C0, теми же command set / ID и валидными CRC8/CRC16.
Payload длиной 31 содержит result byte 00, `WA345T AC Ver.A`
и `f5 01 02 11` по смещениям payload[22:26], то есть **17.02.0501**
при указанной выше интерпретации build/minor/major.

Это самостоятельный коррелируемый ответ, а не выдача сохраненного
результата Assistant. При чтении также встретились 3276 CRC-валидных
пакетов, не совпадающих с ключом ответа; они не использовались для версии.
Наличие другого трафика требует stream framing и корреляции, нельзя
считать первый bulk read единственным ответом на запрос.
Непрерывность/полнота разбора всего трафика не заявляется.

Повторной отправки, reset, set_configuration, set_altinterface и операций
прошивки не было. Интерфейс освобожден, native handle закрыт, MI04 сохранил
PnP status OK. Затем штатный скрытый Assistant успешно открыл Matrice 4T,
подтвердил **Current 17.02.0501 / idle** и нормально завершился.

Проверка доказывает возможность этого read-only обмена на данном M4T
с установленным драйвером. Она не подтверждает все модели, все DLL,
полную схему ответа, назначение остальных полей или безопасность
произвольных команд. Пробник не добавлен в публичный API/CLI; следующий
этап — ограниченный backend с повторной проверкой пути, fingerprint gate,
тестами framing/correlation и явным запретом повторной отправки
после неопределенного результата. USB-запись прошивки не входит в scope.

Источники локального metadata IOCTL:
[driver_api.h](https://github.com/mcuee/libusb-win32/blob/master/libusb/src/driver/driver_api.h),
[ioctl.c](https://github.com/mcuee/libusb-win32/blob/master/libusb/src/driver/ioctl.c).

### RNDIS и ограниченная проверка FTP

По предложению проверить FTP исследован USB network interface:
present DJI VID/PID 2CA3/0020 MI00 определяется Windows как Remote NDIS
based Internet Sharing Device. Его IPv4 на ПК — 192.168.42.1/24,
default gateway отсутствует. В installed `DJIService.exe` найден literal
192.168.42.120; это кандидат адреса, не доказательство FTP-сервиса.
Маршрут к нему проверен через DJI RNDIS interface. Единственная TCP
попытка к порту 21, с local bind 192.168.42.1, завершилась timeout
через 4 секунды, без server banner. После попытки Windows neighbor
entry 192.168.42.120 имела состояние Reachable: есть свидетельство
разрешения сетевого соседа, но доступность FTP не подтверждена.
Отсутствие FTP по этому адресу/порту во всех состояниях не доказано.
Login, получение списка файлов, скачивание, запись, подбор credentials
и сканирование портов/подсети не выполнялись.

## Связанные материалы

[Батарея: наблюдения и однократные DUML-запросы](../telemetry/battery.md) · [Native-анализ: battery checker, Core, Qt и USB dispatch](../native/analysis.md) · [Независимый Linux updater: пакет и manifest](../firmware/linux-updater.md)
