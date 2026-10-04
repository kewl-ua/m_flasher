# Native-анализ: battery checker, Core, Qt и USB dispatch

[Главная и карта документации](../../../README.md) | [Карта документации](../../README.md)

Адреса и layout привязаны к указанным неизмененным бинарным images. Статические связи не доказывают выбор ветки живым M4T; вызовы методов ради исследования не выполнялись.

Материалы ниже сохраняют ход исследования. Последующие записи могут уточнять ранние гипотезы; ограничения приведены рядом с результатами.

## Native-проверка обработчика батареи без запуска сервисов

Следующий этап — статическое локальное чтение PE, RTTI и ограниченных
участков disassembly установленного DJIService.exe. Файл 32-bit,
preferred image base 0x400000; SHA256 до и после исследования:
`37b8bdb0d0351e57fd313140439692355a514991d474ae6267f5a4a2657654a1`.
Ни приложение, ни его DLL для этого этапа не загружались на исполнение;
USB capture, сервисные RPC и новые команды устройству не выполнялись.

Подтверждены отдельные native сущности `DJIBatteryPowerChecker`,
`DJIBatteryPowerChecker1`, `DJIBatteryPowerChecker2`,
`GetBatteryPowerByHash` и callback types с `tagBATTERY_DY_INFO_ACK`.
Это более конкретная граница, чем похожие названия методов зарядного
устройства во frontend, но не доказательство выбора этой ветки M4T.

Для воспроизводимости на указанном image:

- RTTI типизированного success callback указывает на vtable 0x9629E8;
  его entry по смещению +8 ведет в функцию 0x71E6E0.
  В ней аргумент-указатель берется из stack argument, читается один байт
  по смещению **0x14**, затем значение передается следующему callback.
- Конструирование этого callback найдено в 0x71C170; прямой call в него
  находится в 0x71D726. В окружающей ветке создается объект, RTTI которого
  определяет `DJIGeneralCommandSet`, и регистрируется response callback.
  Поэтому отсутствие battery command set 0D в прошлых capture не
  исключает другого пути получения батареи.
- На одной найденной границе разбора ответа (0x74F2D0) проверяется
  размер префикса/наличие данных и следующий callback может получать
  указатель после префикса. Это причина не приравнивать offset структуры
  к offset в raw USB payload без полной проверки конкретного пути.
- Исторический публичный battery dynamic dissector также содержит SOC,
  но описывает варианты с разными префиксами. Совпадение числа 0x14
  с одним из вариантов является лишь согласованной гипотезой,
  а не подтвержденной схемой M4T.

Дополнительная статическая трассировка связала эту ветку с wire-полями,
а не только с числовыми аргументами функций:

- Getter 0x763850 очищает payload и добавляет один байт `01`, затем
  передает `0x78` в 0x74BAA0. Эта функция передает значение в 0x74B0E0,
  где оно записывается в command object +0x34.
- RTTI packer vtable 0x9689C4 определяет `DJIV1CmdPacker`; entry +4
  ведет в 0x79FCE0. Его serializer пишет object +0x34 в DUML byte 10
  (command ID) и object +0x28 в byte 9 (command set).
  Constructor `DJIGeneralCommandSet` в 0x75D150 устанавливает +0x28
  в 0. Поэтому **для этой статической ветки подтверждены `00/78`
  и request payload `01`**.
- Caller 0x71D400 создает sender с type 0x0A/index 1 и receiver с
  type 2/index 5. Порядок аргументов подтвержден constructor
  0x408360/0x4083D0 и записью в command object. Serializer упаковывает
  type в младшие пять бит, index в старшие три: sender **2A**,
  receiver **A2**. Это адрес именно найденной ветки, не универсальный
  адрес батареи и не установленная принадлежность модуля M4T.
- Decoder binder сохраняет prefix length 1: 0x7638B3, 0x75CD0C,
  0x74C4A7; invocation 0x76B72A передает его в 0x74F2D0.
  Разбор читает этот байт как код результата; при нуле и наличии
  данных success callback получает payload pointer +1.
  В сочетании с typed callback +0x14 это дает **кандидат raw payload
  offset 21 (0-based) для этой ветки**, не offset в OSD.

Важное ограничение: проверка в общем decoder перед success callback
гарантирует лишь наличие префикса и как минимум одного байта данных,
не полную длину структуры. Для чтения кандидата по offset 21 требуется
минимум 22 байта raw payload; короткий ответ нельзя интерпретировать
как батарею. Ответ только с префиксом имеет отдельную fallback-ветку
и также не является измерением заряда.

Последующая проверка условия существенно сузила применимость `00/78`:

- Import slot 0x841C24 разрешен в Qt5Core `QString::operator==(const
  char*)`. В 0x71D5D3 сравнивается QString устройства по смещению +0x98.
- Локальная реконструкция статической строки, включая порядок
  добавления байтов, shifts и length getter, дала literal **`rcp501`**.
  Getter 0x4109F0 возвращает число добавленных байтов минус терминатор;
  поэтому размер allocation 8 не является длиной сравниваемой строки.
- В неизмененном app.asar `build\index.js` и `build\dass.js` содержат
  маршрут `Rc_rcp501` с id `rcp501`, redirect `rc430`. Это отдельная
  Rc-категория, не ранее найденный маршрут `Uav_wa345t` для M4T.
  Семантика поля native object +0x98 пока не прослежена до его записи,
  но literal и сравнение подтверждены; `00/78` нельзя объявлять
  установленным battery-запросом подключенного M4T.

При false результате этого сравнения найдена другая статическая ветка:

- В 0x71D901 создается четырехбайтовый request argument `00 00 01 05`;
  адреса в 0x71D92F–0x71D945 дают sender **2A**, receiver **0B**.
- Constructor 0x79D620 имеет RTTI `DJIBatteryCommandSet` (vtable
  0x968778) и в 0x79D6F4 устанавливает command set **0D**.
- Getter 0x79E4C0 копирует четыре байта request argument в payload;
  dispatch в 0x79E5DE передает command ID **02** через ранее проверенный
  serializer path. Итого **`0D/02`, payload `00 00 01 05`** для этой
  альтернативной ветки, а не новая отправленная устройству команда.
- Decoder 0x79B040 использует отдельный путь: при нулевом result prefix
  проверяет минимум prefix length + **30** байт данных (0x79B313).
  Bound prefix argument здесь 1 (0x79E519). Успешный callback получает
  pointer после префикса; его constructor 0x71BAF0 использует ту же
  typed vtable 0x9629E8, читающую структуру +0x14. Таким образом,
  для этой ветки кандидат SOC также raw offset 21, но native success
  path требует как минимум **31 байт payload**, не только 22.

Не установлено, что подключенный M4T использует этот checker и отвечает
по этой схеме. В прошлых обычных navigation capture `0D/02` не наблюдалась;
они не проверяли специально этот native workflow. Ни `00/78`, ни
`0D/02` не отправлялись исследователем, нет correlated live ответа и
независимой сверки SOC. Ни один кандидат offset не добавляется в
OSD-декодер и не используется для выдачи процента пользователю.

Продолжение трассировки обнаружило еще одну границу до USB-запроса:
метод checker в 0x71D300 проверяет byte +0x67 объекта, на который
указывает checker +8. При нуле он вызывает callback с boolean true
и не вызывает getter 0x71D400; только ненулевой флаг ведет к getter
(direct call 0x71D3C0). Поэтому успешный результат общей проверки
сам по себе не доказывает чтение заряда.

Constructor checker 0x71C6D0 устанавливает vtable 0x9624EC.
Его создание подтверждено call 0x5C01F8 в factory 0x5C01A0;
пять disassembly-проверенных вызовов этой factory находятся в
0x5D6EB9, 0x5D6F14, 0x5D8366, 0x5D8524 и 0x5D9529.
Они сохраняют checker в объект +0x4C; выбор зависит от аргументов
и отдельных условий, а не только от наличия подключенного дрона.
Семантика флага +0x67, аргументов выбора и связь с живым M4T
пока не установлены. Factory создает объект, но не доказывает
выполнение его Check; firmware workflow для проверки не запускался.

Дополнительная проверка constructor базового `DJIBatteryPowerChecker`
(0x612030, RTTI vtable 0x952B08) уточнила владельца флага:
checker +8 хранит context, переданный factory из ее caller.
Флаг +0x67 принадлежит этому context, а не непосредственно device object.
Device object в getter достигается еще одним разыменованием context +8.
Присваивание checker в context +0x4C (0x5BF370) переносит shared ownership;
само присваивание не выполняет Check.

В той же selection routine 0x5D6CC0 создается отдельный объект с RTTI
`DJIFirmServiceAgent2` (constructor 0x59F9C0, vtable 0x94AE48).
Это связывает найденные checkers с native firmware-service контекстом,
но не определяет безопасный отдельный read workflow. Успех checker,
наличие объекта и создание service agent нельзя считать доказательством
живой battery telemetry. Точное имя флага пока не установлено;
его constructor initialization подтверждена ниже, но последующие
изменения не прослежены. Сервисы и операции прошивки не запускались.

Последующее чтение конструктора контекста уточнило default флага:
vtable 0x94D330 имеет RTTI `DJIUpgradeMgr`; в constructor участок
0x5C0661 устанавливает этот vtable, а 0x5C0667 сохраняет device pointer
в manager +8. В 0x5C070B адрес manager +0x64 помещается в ESI;
0x5C0725 записывает туда DWORD 0x01000001. В little-endian это
`01 00 00 01`, то есть байт **manager +0x67 изначально равен 1**.
Так найдена запись, которую поиск отдельного byte store +0x67 не видел.
Рядом, в 0x5C0732, записывается второй DWORD группы полей; названия
каждого поля пока не восстановлены. Это default на стадии construction,
не доказательство значения после последующих настроек и не подтверждение
выполнения Check на подключенном M4T.

Проверена также собственная Qt metaobject-таблица `DJIUpgradeMgr`
(0xA1D654, method metadata 0x94CBE0, string records 0x94CA40).
Она содержит шесть методов: signals `PushData`, `UpgradeOk`,
`SubDeviceChanged` и slots `OnPushDownloadProgress`,
`OnPushFlylimitNfzVersion`, `OnSubDeviceChanged`. Dispatch routine
0x5BE720 и jump table 0x5BE7F8 подтверждают шесть entries;
три slot entry ведут соответственно в 0x5D2080, 0x5D23F0 и
0x5D5400. Последний является переходом к signal `SubDeviceChanged`
(0x5BE5F0). Отдельного battery-read метода в этой собственной таблице
нет. Это ограниченный результат: таблица не перечисляет обычные C++
методы, унаследованные методы или другие интерфейсы и не доказывает
отсутствие отдельного native read path. Методы не вызывались; Qt
metadata сама по себе не означает доступность RPC.

Прослежена передача context в один из выбранных firmware upgraders:
после checker selection участок 0x5D9576 передает manager в constructor
0x6BA5D0 (call 0x5D9584). Constructor устанавливает vtable 0x95C318,
RTTI `DJIFirmRegisterUpgrader`, и передает тот же аргумент в base
constructor 0x5E6A40 (call 0x6BA60D). Base vtable 0x94F268 имеет RTTI
`DJIFirmwareUpgrader`; инструкция 0x5E6AE9 сохраняет manager pointer
в upgrader +0x4C. Созданный upgrader сохраняется в manager +0x3C
(0x5D9593). Это подтвержденная связь ownership/context, но не вызов
battery Check и не подтверждение выбора такого upgrader для живого M4T.

При поиске вызова нельзя приравнивать общий slot offset к имени метода:
у battery checker vtable 0x9624EC entry +0x2C равен 0x71D300, тогда
как у register upgrader vtable 0x95C318 тот же offset ведет в 0x6EC760.
Последний читает два аргумента и вызывает Qt-функцию для полей
upgrader +0x1B8/+0x1BC; это не найденная battery-check routine.
Virtual-call candidates требуют доказать конкретный receiver и vtable;
фактический caller battery Check в этом пути пока не установлен.
Native constructors и методы исследователем не выполнялись.

Прослежена и граница между числовым ответом и boolean результата Check:
callback vtable 0x962978 имеет RTTI signature с одним byte argument.
Entry +8 (0x71E610) передает этот байт в 0x71CA20. Там он расширяется
со знаком (0x71CAE1) и сравнивается с unsigned byte checker +0x0C
(0x71CD77–0x71CD81); predicate — значение >= порога. Default порог
в base constructor 0x612050 равен 0x32 (50); отдельные selection
ветки записывают другие значения. Это порог проверки, не процент,
прочитанный из устройства.

Перед завершением callback есть дополнительное условие:
при исходном byte == 0 инструкция 0x71CED5 принудительно выбирает
boolean true независимо от результата сравнения. Это наблюдаемая
семантика native checker, не доказательство того, что 0 означает
неизвестный заряд или отсутствие батареи. Вместе с пропуском Check
по context flag она означает, что boolean success нельзя использовать
как подтверждение измеренного SOC или как самостоятельный telemetry API.
Для нового read API нужны коррелируемый raw response, проверки длины
и результата, а затем независимая сверка показания Pilot 2.

Следующая граница — подтвердить выбор этой ветки для модели и получить
wire response в согласованном безопасном сценарии, затем сравнить
валидный результат с Pilot 2. Вызов firmware workflow ради срабатывания
battery checker, hooks, обход проверок и перебор native методов не нужны
и не выполнялись. Установленный image не изменен; SDK/CLI пока без
нового battery API.

### Проверка memory-кандидатов SOC

Read-only live memory проверка на обычном экране Firmware Update
не подтвердила SOC в `DJIService.exe`. Pilot 2 до и после чтений
подтверждал 55%, 54% и 52%; из baseline при 55% после 54% остались
четыре уникальных адреса, но при 52% все отсеялись. Повторное чтение
этих четырех адресов при подтвержденных 51% также не дало совпадений;
адреса оставались доступны. При первой фильтрации 2210 прежних
address/type candidates стали недоступны и были исключены, поэтому
поиск по фиксированным адресам не покрывает перемещающиеся значения.

Дополнительно учтена ASLR: loaded image base получен из процесса,
а relocated entry battery checker vtable +0x2C проверен чтением.
В 10 571 776 прочитанных байтах committed private RW memory того же
`DJIService.exe` не найдены aligned pointer candidates для трех
проверенных vtables: `DJIUpgradeMgr`, `DJIBatteryPowerChecker1` и
base `DJIBatteryPowerChecker`. Ошибок чтения этого scan не было.
Это ограниченный отрицательный результат по одному процессу и типам
памяти, не доказательство отсутствия объектов или SOC во всем Assistant.
`DJIServiceCore.exe` и browser processes этим scan не проверялись.
Совпадения чисел не признаны telemetry; raw memory dumps не сохранялись,
память не изменялась и native методы не вызывались.

### DJIServiceCore: V1 observer и log export

Проверка соседнего `DJIServiceCore.exe` уточнила границы поиска:
в текущем process tree он является дочерним процессом `DJIService.exe`,
но это отдельный PE32 Go binary, а не второй экземпляр C++ image.
SHA256 core image:
`831051acc24af67f07f3a2d6e748bf2dd0a6e2a8078df2e2937a242d40e4ec24`.
Pointer-based Go build-info сообщает `go1.14.1`. Таблица pclntab
с magic 0xFFFFFFFB содержит 6611 function entries; проверены порядок
entry addresses, соответствие entry в function records и UTF-8 имена.
Среди них присутствуют `runtime.main`, `main.main`, device detectors,
`PCWSDevice`, protocol и device-identification functions. Ни одно
function name этой таблицы не содержит `battery` без учета регистра.
Это результат поиска имен, не доказательство отсутствия battery data
в общих обработчиках или памяти. Адреса C++ vtables из `DJIService.exe`
нельзя переносить в core process; его SOC scan не выполнялся.
Роль core на живом battery path и источник актуального SOC остаются
неподтвержденными. Новый процентный baseline пока не снимается.

Дальнейшее static чтение core подтвердило общий путь передачи decoded
V1 data: `protocol.(*Mgr).v1Decode` (0x680460) вызывает
`protocol/v1.(*Decoder).StreamDecode` в 0x6804A0, получает результат,
затем под `sync.(*RWMutex).RLock` (0x680529) обходит список из manager
+0x1C/+0x20. В 0x68058B вызывается `runtime.selectnbsend`; завершение
освобождает read lock через `RUnlock` в 0x680628. Все четыре call target
сверены с Go function metadata и instruction bytes. Это общий
nonblocking channel delivery, не специализированный SOC decoder.
Получатели этих channels и наличие battery payload на живом пути пока
не установлены; вызов `selectnbsend` не означает отправку USB-команды.
Исследование выполнено без исполнения core методов.

Уточнены подписчики этого общего потока. `Mgr.AddV1Observer`
(0x680A10) создает channel с capacity 0x400 (1024) через
`runtime.makechan` в 0x680A3A и добавляет его в тот же manager list
+0x1C/+0x20 под write lock. Disassembly подтвердил регистрацию из
`CmdIo.SendV1WithTimeout` (call 0x68A668) и worker
`CmdIo.RequestV1PushWithChan2.func1` (call 0x68ACA2).
Worker использует `runtime.selectgo`, проверяет byte поля decoded
message +7/+8/+9 и передает подходящее сообщение в следующий channel
через второй select; имена этих полей подтверждены ниже.
На рассмотренных exit paths вызывается `RemoveV1Observer`.

Подтвержден один конкретный application consumer:
`module/log_export.getFileImpl.func2` вызывает
`CmdIo.RequestV1PushWithCmdAndCancel` в 0x6A7783; этот wrapper вызывает
`RequestV1PushWithChan2` в 0x68AA09, который запускает worker через
`runtime.newproc` в 0x68A3CA. Это static связь с log-export workflow,
не найденный battery consumer и не доказательство запуска этого пути
на текущем экране. Проверены 11 call anchors по instruction bytes
и Go function names, а также аргумент capacity channel.
Log export, подписки и отправка команд исследователем не запускались.

Go type metadata уточнила фильтр worker: observer channel type
0x6D52E0 содержит pointers на message struct 0x6FE000 (size 24).
Его поля — embedded `ProtocolHeader` в +0 и `Body` в +12.
Header type 0x71EB20 содержит девять именованных полей;
+7 = `CmdType`, +8 = `CmdSet`, +9 = `CmdId`. Worker принимает
только `CmdType == 0` (0x68ADD0/0x68ADD4), затем сравнивает
`CmdSet` и `CmdId` с аргументами подписки (0x68ADE4/0x68ADF5).
Смещения относятся к decoded message, не raw USB payload и не SOC.
В StreamDecode wire bytes +9/+10 записываются в decoder header
+0x10/+0x11 (0x67F8F9/0x67F8FD и 0x67F911/0x67F915);
manager переносит соответствующую часть header в message +8/+9.
Проверены channel element type chain, все девять header offsets
и восемь instruction anchors. Семантика имени `CmdType` не дает
основания называть значение 0 измерением батареи или безопасной
командой: это общий фильтр заголовка, а Body еще требует отдельного
decoder и подтверждения применимости к M4T.

Чтение log-export callback уточнило назначение его Body:
переданный descriptor 0x6F8A00 является Go pointer type, не interface
method table; его element struct 0x7139E0 содержит `Code` (+0),
`Length` (+4), `LengthRemained` (+8), `OffsetAdd` (+12), `Data` (+16).
Callback 0x6A73B0 проверяет concrete type в 0x6A7466/0x6A746C,
передает Data slice в `bytes.(*Buffer).Write` (call 0x6A74A6),
накапливает OffsetAdd и читает LengthRemained. Это подтверждает
сборку порций file data в данном callback, не получение SOC.
Никакие файлы этим исследованием не скачивались.

Wrapper вызывает `gen/v1g.GetCmdInfo` в 0x68A99D, то есть получает
command metadata через отдельный lookup, а не из первых слов
переданного Go type descriptor. Нельзя трактовать эти слова как
номер команды. Проверены пять named field offsets, pointer element,
callback instruction anchors и два call target по Go metadata.

Продолжение чтения method metadata связало pointer type 0x6F8A00
с `module/log_export.(*PushFileReq).GetCmdInfo` (0x699A60).
Это имя concrete type, используемого callback; прежнее описание
«file response» обозначало его роль в потоке, не имя Go-типа.
Uncommon metadata содержит два метода; relative method entry
0x298A60 соответствует 0x699A60 и проверенному Go function name.
Его command-info struct 0x708AA0 имеет `CmdSetInfo` (+0),
`CmdId` (+4), `Type` (+5). Отдельный CmdSetInfo struct 0x708B20
имеет `Version` (+0), `CmdSet` (+2), `EncType` (+3).
Инструкция 0x699A9D записывает packed bytes `01 00 00 03`,
то есть Version 1, CmdSet 0, EncType 3; 0x699AB3 задает CmdId 0x1F.
Wrapper читает именно CmdSetInfo +2 и CmdId +4
(0x68A9EB/0x68A9EF), затем передает их push-фильтру.
Таким образом, конкретная найденная log-file подписка фильтрует
**00/1F**, не ранее исследованные battery candidates 00/78 или 0D/02.
Это не новый live запрос, не доказательство текущей активности
подписки и не разрешение запускать log-export workflow.
Проверены layout и scalar types metadata, связанный method record
и десять instruction anchors на неизмененном core image.

### GetDeviceState 00/0C: не подтвержденный источник SOC

Отдельно проверена state-команда core, чтобы не принимать общее имя
`GetDeviceState` за battery telemetry. В Go function table найдено
15 application entries с именем, заканчивающимся на `.GetCmdInfo`,
включая generic lookup; среди этих имен нет battery/OSD команды.
Это ограниченный перечень именованных методов, не всех обработчиков.
`GetDeviceStateReq` (0x68B300) и `GetDeviceStateRsp` (0x68B380)
задают command metadata **00/0C**. Pointer type 0x6EABE0 связан
единственным method record с response GetCmdInfo; element struct
0x71CF40 содержит `RetCode`, `MinorVersion`, `MajorVersion`,
`IsLoaderMode`, `IsNoRepower`, `Reserve1`, `Reserve2`, `Reserve3`.
Named SOC field в этой структуре нет. Reserve fields не декодировались
как заряд; их смысл и применимость ответа к M4T не установлены.
Проверены method binding, восемь field offsets и шесть instruction
anchors на неизмененном core image. Команда 00/0C не отправлялась.

### Qt push-ветка батареи

В C++ service найдена отдельная push-ветка, не связанная с upgrade
checker. Qt metaobject 0x968B50 использует string table 0x968B68,
data table 0x968F48 и static metacall 0x7A0920.
Class name в таблице — `DJIControllerCommandSet`; все 12 собственных
методов имеют signal flags 0x6. Signal index 5 —
`PushSmartBatteryStatus(SMART_BATTERY_STATUS)`, index 4 —
`PushOsdGeneralData(OSD_GENERAL_DATA)`. Это не RC signal
`PushBatteryInfo(PUSH_RC_BATTERY_INFO)`, принадлежащий отдельной
таблице `DJIRcCommandSet`.

Jump-table entry 5 в static metacall ведет к 0x7A0991; call
0x7A099A вызывает signal wrapper 0x7A0D80. Wrapper передает
metaobject 0x968B50 и signal index 5. Помимо metacall найден
и disassembly-проверен call 0x7851D7 из обработчика 0x785080.
Он берет data pointer/length из входного объекта +0x40/+0x44,
проверяет минимум 0x1E (30) байт в 0x7851A9, копирует первые
30 байт в локальную структуру и передает ее signal wrapper.
Две dispatch tables выбирают эту ветку при значении 0x51
16-битного поля входного объекта +0x34. Пока связь этого поля
с wire CmdId не проверена, 0x51 не публикуется как номер
батарейной команды. SOC offset, устройство-источник, связь
с M4T и live активность сигнала также не установлены.
Проверены Qt method/type names, jump-table mapping, шесть
instruction anchors и неизменность image hash. Обработчик
не запускался, память процесса и USB в этой проверке не читались.

Продолжение проверки push-ветки подтвердило RTTI
`DJIControllerCommandSet` для vtable 0x96822C; slot +0x2C
указывает на обработчик 0x785080. Battery branch копирует payload
частями 16 + 8 + 4 + 2 байта без извлечения отдельного SOC-поля.
Единственная absolute reference на signal wrapper 0x7A0D80
в этом executable находится в 0x7A0ABB: disassembly показывает
сравнение адреса метода и возврат signal index 5, а не подключение
потребителя. Тексты `PushSmartBatteryStatus` и
`SMART_BATTERY_STATUS` встречаются по одному разу, в уже разобранной
Qt таблице. Прямой именованный/адресный consumer этим поиском
не найден; динамические Qt connections и другие модули не исключены.
Constructor устанавливает controller vtable в 0x77FF2D и записывает
3 в private object +0x28 (0x77FF37); значение пока не трактуется
как wire CmdSet без проверки базового маршрутизатора.
Проверены RTTI/slot, число absolute/string references и восемь
instruction anchors. Размер структуры не задает SOC offset;
из этих данных нельзя выводить процент заряда или активность M4T.

### Device-scoped dispatch и USB channel

При обсуждении самостоятельного DUML-запроса пользователь выбрал
сначала статически проверить маршрут/формат 0D/02, без отправки.
Повторное чтение getter 0x79E4C0 и decoder 0x79B040 подтвердило
четырехбайтовый request copy, command ID 02, result-prefix length 1
и guard prefix +30 перед success callback. Caller в 0x71D914
получает context из checker +8, затем device из context +8;
в 0x71D91E передает device +0xC8 в constructor command set.
Этот путь использует device-scoped объект, но не устанавливает,
какой физический компонент M4T принимает receiver 0B.
Назначение четырех request bytes и связь device +0xC8 с текущим
USB transport еще требуют проверки. Подтвержденная serialization
не означает совместимость или отсутствие побочных эффектов на M4T.
Не выполнялись USB open/claim/read/write, новый query или перебор
адресов/команд. До live проверки ответ нельзя выдавать как заряд;
нужны CRC, correlation по sequence/адресам/команде, нулевой result,
достаточная длина и независимое сравнение с Pilot 2.

Статическая трассировка device +0xC8 уточнила границу транспорта.
Battery constructor 0x79D620 берет argument +0x30, передает его
базовому constructor 0x74AB70, который копирует pointer/control-block
pair в command-set +0x18/+0x1C с увеличением reference count.
Следовательно, device +0xC8 здесь передается как адрес пары владения,
не как готовый USB handle или номер endpoint.
Dispatch 0x74B0E0 сначала вызывает packer slot +4, затем использует
сохраненный pointer +0x18: ветки вызывают 0x73C380 (0x74B1DC)
или 0x73FAE0 (0x74B269). Во втором пути читается вложенный pointer
+0x160; его virtual slot +0x10 вызывается как boolean gate.
Concrete type этого вложенного объекта и связь с MI04 не установлены;
наличие уровня dispatch не доказывает USB transport.
Проверены image hash и 19 instruction anchors. `tshark` не запускался,
захват и DUML отправка не выполнялись.

Далее найдены и disassembly-проверены два concrete пути установки
вложенного channel pointer +0x160. В 0x73ED93 вызывается constructor
0x748210, устанавливающий vtable 0x966E48; RTTI определяет
`DJISerialDeviceIO`. Pointer на объект allocation +0x10 сохраняется
в +0x160 в 0x73EE83. Другой путь вызывает constructor 0x742600
(0x73F194), устанавливающий vtable 0x966894 с RTTI
`DJIUSBDeviceIO`; pointer allocation +0x10 сохраняется в +0x160
в 0x73F258. В обоих случаях соседнее +0x164 хранит control block.
Таким образом, ранее найденный dispatch допускает serial и USB
каналы, а не только один предполагаемый USB transport.
USB vtable slot +0x10 ведет в 0x743AF0, возвращающий boolean
из byte +0x28: это readiness gate, не отправка пакета.
Проверены две RTTI identities, constructor/install цепочки и восемь
instruction anchors на неизмененном image. Не установлено, какая
ветка выбрана живым device M4T, либо какие endpoints использует
этот USB object. Наличие `DJIUSBDeviceIO` не подтверждает MI04.
Capture, чтение process memory и DUML send не выполнялись.

Статический open-путь `DJIUSBDeviceIO` (0x743B80) разрешен до
импортов `libusb0_dji.dll`: `usb_open`, `usb_set_configuration`,
`usb_claim_interface`, `usb_bulk_setup_async`. Helper 0x74A020
получает 16-битный lookup key из native enumeration object +0x416
и возвращает тройку interface / IN endpoint / OUT endpoint.
Initializer в 0x40810A--0x4081CC создает для key 0x0020 запись
**4 / 85 / 04**; fallback helper задает ту же тройку.
Это совпадает с ранее прочитанным descriptor MI04 с bulk OUT 04 /
IN 85. Идентичность поля +0x416 именно product ID в ABI этой
32-bit DLL отдельно не проверена; key 0020 не подменяет live выбор.

Open-путь использует тройку при claim (0x7446AD), затем передает
OUT endpoint в bulk setup (0x7446CC, context object +0x3C)
и IN endpoint (0x7446E9, context +0x40). Он также содержит
set_configuration(1); этот native метод не является чистым
read-only наблюдением и исследователем не вызывался.
Проверены PE import identities, map initialization, fallback
и 19 instruction anchors на неизмененном image. Это подтверждает
конкретный статический USB путь, но не live выбранный channel,
поддержку запроса 0D/02 либо семантику его ответа на M4T.
Новых capture, USB transfers и изменений configuration не было.

## Связанные материалы

[Батарея: наблюдения и однократные DUML-запросы](../telemetry/battery.md) · [USB и DUML: транспорт и запрос версии](../transport/usb-duml.md) · [Независимый Linux updater: пакет и manifest](../firmware/linux-updater.md)
