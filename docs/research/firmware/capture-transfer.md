# M4T: проверка USB передачи firmware по полному захвату

[Карта документации](../../README.md) |
[Linux updater](./linux-updater.md) |
[Каталог пакета 17.02.0501](./package-manifest.md) |
[Offline Upgrade и сравнение captures](./capture-offline-upgrade.md)

## Статус

Первичная независимая offline-проверка предоставленного захвата 2026-10-04.
Подтверждена передача файлов через USB/DUML `00/2A` на адрес `48`.
Файлы восстановлены потоково для вычисления хешей, не записаны на диск.
Config разобран в памяти. Новых запросов устройству, прошивок или replay
исследователем не выполнялось.

Первичная проверка установила прежде всего file transfer.
Последующий [разбор control/status и Offline Upgrade](./capture-offline-upgrade.md)
добавил `83/84/85`, terminal `04 01 00` и post-reconnect `4F`, согласующийся
с release 17.01.0516. Полный контракт session, recovery и текущая live-версия
дрона не установлены. Это не готовый алгоритм writer.

## Исходные файлы и границы захвата

| Источник | Размер | Records | Время локальной системы |
|---|---:|---:|---|
| `C:\dev\captures\full_usb3.pcap` | 709568865 | 689950 | 18:07:36.486117 - 18:12:58.681802 |
| `C:\dev\captures\full_net.pcapng` | 6484 | 29 | 18:05:41.659822 - 18:12:33.047238 |

SHA256:

- USB: `fee639776407e833d652e16959f7b1947d4cea8d5279287f3f9ae4b3388bded7`.
- Network: `b560e8d292df356b9a96320c7ca0cfb396d8339a618a28380040f9110408ba96`.

USB capture имеет linktype 249 (USBPcap), little-endian pcap, snaplen 65535.
В нем встречаются bus 1 / device address 52 и 54.
File-transfer идет через endpoint OUT 04 / IN 85 на address 52.
Address 54 появляется позднее; эти исторические адреса нельзя считать
текущими или постоянными идентификаторами устройства.

Найдено два truncated records: frames 689012 и 689018,
captured 65535 / original 65563 bytes; оба относятся к address 54,
endpoint 83, заявленная USB data length 65536.
Они не относятся к собранному file-transfer потоку 04/85.
На других bulk endpoints встречаются не-DUML данные; их нельзя считать
испорченными DUML пакетами только из-за неудачного поиска framing.
Полнота capture всех интерфейсов/событий не заявляется.

## Метод проверки

1. Прочитаны pcap record headers и USBPcap variable header length.
2. Bulk payloads собраны по отдельным `(bus, address, endpoint)` streams:
   один USB record может содержать несколько DUML packets.
3. DUML выделен по `55`, version/length и CRC8; перед учетом каждого
   packet проверен CRC16. Незавершенные хвосты сохранялись между records.
4. Выделены направление, flags, command set/id, sequence и payload.
5. Для каждой file-open/data/finish последовательности проверены
   chunk index, объявленная длина, потоковый MD5 и finish digest.
6. Собранный config сопоставлен с собственными переданными firmware files
   и отдельно с нашим ZIP 17.02.0501.

В потоках 04/85 для адресов 52/54 не осталось незавершенных bytes.
На всех принятых DUML packets CRC проверен; иные потоки не декодированы полностью.
Примеры frames 12109/12145/12149 дополнительно сверены через tshark
по direction, endpoint и raw USB payload.

## Что реально передано

| Счетчик | Значение |
|---|---:|
| Исходящие `2A -> 48`, `00/2A`, flags 40 | 679668 |
| File-open payload op 01 | 23 |
| File-data payload op 04 | 679622 |
| File-finish payload op 03 | 23 |
| Обратные `48 -> 2A`, `00/2A`, flags C0 | 627 |
| Сумма именно файловых bytes | 666015264 |
| Окно исходящей передачи | 18:10:09.413948 - 18:11:10.464394 |
| Длительность до последней исходящей finish | 61.050446 s |
| Последний ответ `00/2A` | 18:11:10.482003 |

679668 — число исходящих DUML packets, а не число data chunks.
666015264 — bytes файлов без DUML/USB/pcap overhead. Округленные
«680 МБ» не следует использовать как точный размер image.
61 секунда относится к file transfer, не ко всей установке и reboot.

### Наблюдаемый формат payload `00/2A`

Все offsets ниже относительно payload после 11-байтового DUML header.
`01`, `04`, `03` — подоперации payload одной команды, не command IDs.

| Подоперация | Разобранные bytes | Проверенная граница |
|---|---|---|
| Open `01` | byte 0 = 01; bytes 1..4 = file size LE; byte 5 = name length; далее filename с завершающим NUL, затем `00 01 01` | Во всех 23 opens имя/размер согласуются с собранными файлами; смысл tail неизвестен |
| Data `04` | byte 0 = 04; bytes 1..4 = zero-based chunk index LE; bytes 5..end = file data | Индекс начинается с 0 для каждого файла, непрерывен, без повторной отправки chunk в выделенном потоке |
| Finish `03` | byte 0 = 03; следующие 16 bytes = MD5 | Во всех 23 случаях digest совпал с MD5 собранных bytes |

Максимум file data в chunk — 980 bytes; полный data payload тогда 985 bytes,
DUML packet — 998 bytes с header/CRC. Таких chunks 679599;
последние chunks файлов короче. Значение 980 подтверждено наблюдением,
но negotiation/fallback на других devices не восстановлены.

Первое имя `wa345t.cfg.sig`, размер 25632; filename отличается от
длинного versioned имени config в нашем ZIP. Это не переименование
именно нашего config: содержимое относится к другому release.

### ACK: три разных формы, не один ACK на каждый chunk

| Ответов | Payload | Наблюдение |
|---:|---|---|
| 23 | `00 d4 03 88 13 01 01` | Ответы на open; `d4 03` как LE дает 980, согласуется с размером chunk |
| 581 | `00` + 4-byte LE index | Промежуточные/final data acknowledgements |
| 23 | `00` | Ответы после finish |

Значение `88 13` как LE дает 5000, но объявлять его window size,
timeout или bytes-per-ACK нельзя без дальнейшей проверки.
Во всех трех формах первый byte нулевой; это наблюдаемый ответ,
не доказательство успешной установки компонентов.
Все 23 open replies и все 23 finish replies отдельно сопоставлены
с запросами по exact sequence и соответствующей длине/типу ответа.

У 581 data ACK собственный DUML sequence идет 0..580.
Он не является echo sequence каждого host data packet.
Поэтому generic matcher «всегда same sequence» для этого transfer
не подходит: open/finish и data ACK требуют различения.

В каждом файле acknowledged indices не убывают; последний равен
последнему отправленному chunk index. Но есть повторяющиеся indices:
пять у WA345T_E2, семь у WA345T_V1. Это ответы с новым ACK sequence,
не доказательство повторной передачи data chunks.
481 ACK соответствует последнему chunk, уже видимому в захвате к моменту ACK;
для остальных host успел передать больше. Нельзя вывести flow-control
окно или retry policy из одного отношения общих счетчиков.

## Переданный release и связь с нашим ZIP

Переданный config:

- MD5 `5157ce9aebfc2d918f22a6fd3d1f8a82`;
- XML `firmware.formal` и `release.version` равны **17.01.0516**;
- все 22 firmware files совпали по size/MD5 и точному имени с этим config;
- все 23 файла совпали по размеру и finish MD5 с переданными bytes.

Наш ранее исследованный config 17.02.0501 имеет другой MD5:
`7f7857ab44e5c086b17f6b5215a8d353`.
Оба config имеют размер 25632, но отличаются 665 byte positions.
В XML различаются release metadata и три component records.
Это разные releases, а не доказанное изменение signed config Assistant.

Из firmware files 19 совпадают по size/MD5 с нашим ZIP 17.02.0501.
Три отличаются:

| Module | В capture 17.01.0516 | Bytes | MD5 в capture | В нашем ZIP 17.02.0501 |
|---|---|---:|---|---|
| 0802 / WA345T_E2 | 10.00.19.43 | 291320384 | `85f96345c5b38ecc874f7e9788a7b122` | 10.00.21.17 |
| 1502 / WA345T_V1 | 10.00.19.49 | 360377952 | `54d00472418b56d73d1536f4e91b5040` | 10.00.21.17 |
| 0103 / IR_Sensor IA640 | 02.75.00.94 | 637120 | `38772530c7717bd11561ad1de242294c` | 02.75.00.96 |

При этом структура дерева и остальные проверенные attribute/text значения
совпадают, кроме дат/версии release и version/size/hashes/filename трех записей.
Подписи собранных файлов не проверены, MD5 — проверка целостности, не доверия.
Version manifest — цель пакета, не независимая проверка Current после reboot.

### Переданы все hardware variants

Config передан первым, затем 22 firmware records в XML document order.
В том числе отправлены:

- обе пары ESC mc01/mc02;
- все три Battery types;
- оба IR_Sensor IA640/HK;
- все четыре отдельных radar images.

В этом прогоне host **не отфильтровал передачу до одного варианта на id**.
Это не означает, что устройство установило все варианты.
Выбор на стороне принимающего компонента/последующих этапов еще не доказан.
Все переданные files перечислены в config; отдельного `dji_system.bin`
в выделенной последовательности 23 opens нет. Это не доказывает
отсутствия внутренней сборки контейнера на устройстве.

### Уточнение нашего XML-каталога

У каждого из 22 `release/module` нет child elements, но есть **text content**:
точное имя `.fw.sig`. Это проверено и для нашего original config, и для
собранного capture config. «Нет children» не означает «нет текста».
Для сопоставления теперь доступно прямое filename, а не только
эвристика по id/version/size. Безопасность пути/уникальность/хеши
все равно нужно проверять отдельно.

## Управляющие команды: поправка к исходному пересказу

| Команда / направление | Наблюдение |
|---|---|
| `48 -> 2A`, `00/81`, flags 40 | 294 packets; примеры приходят на IN 85 |
| `2A -> 48`, `00/81`, flags 80 | 294 ответов ПК; все пары проверены по sequence/address/command |
| `48 -> 2A`, `00/82`, flags 40 | 294 packets; входящие на IN 85 |
| `2A -> 48`, `00/82`, flags 80 | 294 ответов ПК |
| `2A -> 48`, `00/83`, flags 40 | Две отправки payload `04`, с одинаковым sequence 12959 |
| `48 -> 2A`, `00/83`, flags C0 | Два ответа `00 07 00`; первый пришел до второй отправки |
| `48 -> 2A`, `00/42`, flags 00 | 82 notifications; первые sample payloads `03 00 00`, `03 03 00` |
| `2A -> 1F`, `00/01`, flags 40 | 103 version requests за весь USB capture, столько же обратных C0 replies |

Следовательно, фраза «Assistant раз в секунду опрашивает 48 через 81/82
вместо Version Inquiry к 1F» неверна: в observed packets инициатор
81/82 — **48**, ПК отвечает, а version inquiry тоже присутствует.
Последующая проверка всех пар 81/82 подтвердила корреляцию и медианы
интервалов 1.000003 / 0.999969 s. Роль этих команд в authorization/session
не установлена. Terminal `00/42` равен `04 01 00`, согласуется с
public-schema Complete / Success; длинные 147-byte payload этим старым
decoder полностью не описаны. Развернутая последовательность, ACK timing,
post-reconnect `4F` и ограничения приведены в
[сравнении двух captures](./capture-offline-upgrade.md).

## Сеть и вывод об FTP

В network capture 29 packets: SSDP (16), Steam discovery (6),
mDNS (3), ICMPv6 (3), LLDP (1); TCP conversations нет.
Это не исключительно «шум Windows»: часть пакетов относится к Steam discovery.
Interface metadata: `Ethernet 2`; GUID захваченного интерфейса совпал
с текущим Windows adapter `Remote NDIS based Internet Sharing Device`.
Network timestamps покрывают все окно file-transfer, но заканчиваются
примерно за 25 секунд до конца USB capture.

**Положительное доказательство:** все перечисленные файлы собраны из DUML
с совпавшими digest. Основная передача этого прогона шла по USB, не FTP.
В данном network capture FTP/TCP не наблюдается.
Не доказано отсутствие FTP во всех состояниях/на всех interfaces M4T,
и не проверена полнота network capture при reconnect.

Режим с предположением FTP нельзя считать реализацией наблюдаемого пути.
Но исходник/версия упомянутого `pyduml legacy-ftp` в этой проверке
не исследованы; совместимость проекта в целом не оценивалась.

## Что остается до независимого flasher

1. Полный preflight/session flow: 81/82/83, другие управляющие команды,
   authorization и обязательные ответы ПК.
2. Правило pacing/window ACK, duplicate indices, timeout и recovery.
3. Native-подтверждение `00/42`/`4F`, ошибок и окончательных post-upgrade checks.
4. Реальная device-side hardware selection и связь 48 с upgrade-center.
5. [Проверка Offline Upgrade 17.02.0501 выполнена](./capture-offline-upgrade.md):
   содержимое файлов совпало с ZIP; обязательность этапов и recovery еще не проверены.
6. Отдельно проверенный Linux transport; Windows capture не проверяет Linux.

Не воспроизводить сырые пакеты как сценарий. Sequence, адрес USB,
состояние session и device identity изменчивы. Все исследования выше
выполнены offline, новых live-разрешений не использовали.
