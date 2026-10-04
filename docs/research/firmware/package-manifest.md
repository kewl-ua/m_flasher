# M4T 17.02.0501: XML manifest и каталог ZIP entries

[Карта документации](../../README.md) |
[Цель и границы Linux updater](./linux-updater.md)

## Область и степень подтверждения

Offline-наблюдения на 2026-10-04 относятся к одному существующему официальному
пакету `M4T_UAV_17.02.05.01_pro.zip`. Контейнеры читались из ZIP в памяти,
крупные файлы хешировались потоково. Файлы не извлекались на исполнение,
native updater не запускался, USB access не выполнялся.

Подтверждены байтовые границы XML, успешный XML parse, значения атрибутов,
однозначное сопоставление всех компонентов и совпадение whole-member MD5.
Не подтверждены подписи DJI, алгоритм hardware selection, назначение каждого
header field, wire protocol обновления и исполнение указанных `.so`.

Это отчет о структуре и данных, а не инструкция по отправке firmware.
XML здесь описан таблицами и схемой; полный proprietary manifest не копируется.

## 1. Внешний ZIP

| Свойство | Наблюдение |
|---|---|
| Локальный исходник | `C:\dev\fw_list\m4t\M4T_UAV_17.02.05.01_pro.zip` |
| Размер ZIP на диске | 665800202 байта |
| Число ZIP entries | 23: 22 `.fw.sig` и один `.cfg.sig` |
| Сумма содержимого entries | 665796192 байта |
| Сумма 22 firmware members | 665770560 байт |
| Размер config member | 25632 байта / `0x6420` |
| Compression method | У всех entries 0: ZIP Stored |
| ZIP encryption flag | Не установлен |
| Первые четыре байта всех 23 members | ASCII `IM*H` / hex `49 4D 2A 48` |
| DWORD LE по +4 всех 23 members | 2; семантика поля отдельно не доказана |

Разница между размером ZIP и суммой содержимого равна 4010 байтам.
Это арифметическая разница, не полностью разобранная карта ZIP overhead.
Отсутствие ZIP encryption не доказывает отсутствие шифрования внутри `IM*H`.
Общее magic не доказывает одинаковую структуру или обработку всех members.

### Идентичность config и XML slice

- Config member: `wa345t_0000_v17.02.0501_20260529.pro.cfg.sig`.
- SHA256 полного config:
  `d743d563d0585701e85367f376725d4547439bc9e1a7761f034d561889ac4f00`.
- SHA256 XML slice `[0x260:0x6405]`, без хвоста:
  `47972d1000b7622eb10cce8a2123b064eb626f4b44c2510a61574b0cfb98f025`.

Хеш slice зависит от точных пробелов/переносов исходного XML.
Parse/повторная сериализация могут дать другой хеш без изменения дерева.
Эти SHA256 фиксируют прочитанные байты, но не являются проверкой подписи.

## 2. Наблюдаемый header config

Все значения ниже прочитаны как DWORD little-endian из конкретного config.
Названия криптографических полей не присваиваются по сходству значений.

| Offset | Значение hex | Проверенное наблюдение |
|---|---|---|
| `0x00` | `0x482A4D49` | Байты `IM*H` |
| `0x04` | `0x00000002` | Совпадает с DWORD +4 остальных members |
| `0x08` | `0x00006420` | Численно равно полному размеру config |
| `0x0C` | `0x00900000` | Семантика неизвестна |
| `0x10` | `0x000000E0` | 224; в сумме с +0x14 дает начало XML |
| `0x14` | `0x00000180` | 384; в сумме с +0x10 дает `0x260` |
| `0x18` | `0x000061C0` | 25024; численно равно размеру от начала XML до EOF |
| `0x1C` | `0x00006420` | Численно равно полному размеру config |
| `0x20` | `0x00000000` | Семантика неизвестна |
| `0x24` | `0x00000003` | Семантика неизвестна |
| `0x28` | `0x4B415250` | Байты ASCII `PRAK`; назначение не установлено |
| `0x2C` | `0x00000000` | Семантика неизвестна |

Наблюдаемые арифметические связи:

```text
0xE0 + 0x180 = 0x260                    начало читаемого XML
0x6420 - 0x260 = 0x61C0 = 25024        XML вместе с хвостом
0x6405 - 0x260 = 0x61A5 = 24997        XML до конца </dji>
0x6420 - 0x6405 = 0x1B = 27            хвост после </dji>
24997 + 27 = 25024
```

Связи полезны для следующей проверки layout, но не доказывают, что +0x10
есть header length, +0x14 signature length, а +0x18 payload length.
Нельзя использовать эти догадки как универсальный parser `.sig`.
Байты до `0x260` не классифицированы полностью; ключ/подпись не проверены.

### XML bounds и хвост

- В offset `0x260` / 608 начинается declaration XML 1.0 с UTF-8 encoding.
- Slice заканчивается сразу после closing `</dji>` в exclusive offset
  `0x6405` / 25605; длина slice 24997 байт.
- Следующий байт — newline `0A`, затем ровно 26 нулевых байтов до EOF.
- Хвост поэтому **не полностью zero-filled**.
- Смысл нулевого дополнения не доказан: alignment/padding остаются гипотезой.
- Slice успешно разобран стандартным `xml.etree.ElementTree`.

Границы найдены в этом конкретном файле по declaration и closing tag.
Поиск substring не является готовым безопасным parser произвольного
signed container: для такого parser нужны проверенный layout, bounds,
однозначность payload и отдельная проверка подлинности.

## 3. Дерево и release metadata

Структурная схема, не копия исходного XML:

```text
dji                                      без атрибутов, 1 child
  device                                 id=wa345t, 2 children
    firmware                             formal=17.02.0501, 1 child
      release                            22 module children
        module                           22 records, без children
    upgrade_center                       без атрибутов, 1 child
      module_info                        без атрибутов, 2 children
        module                           name=WA345T_E2, diff_up_capability=true
        module                           name=WA345T_V1, diff_up_capability=true
```

22 firmware records и две записи `module_info` выполняют разные роли:
это 24 XML elements с tag `module`, но только 22 firmware components.
Считать все `root.iter("module")` файлами прошивки было бы ошибкой.

| Узел/атрибут | Точное строковое значение |
|---|---|
| `device.id` | `wa345t` |
| `firmware.formal` | `17.02.0501` |
| `release.version` | `17.02.0501` |
| `release.antirollback` | `0` |
| `release.antirollback_ext` | `cn:0` |
| `release.enforce` | `0` |
| `release.enforce_ext` | `cn:0` |
| `release.enforce_time` | `2026-05-29T03:29:24+00:00` |
| `release.from` | `2026/05/29` |
| `release.expire` | `2027/05/29` |

`17.02.05.01` в имени ZIP и `17.02.0501` в manifest — разные строковые
формы. Manifest version совпала с ранее прочитанной Current на M4T.
Версии модулей ниже не обязаны совпадать с общей release version.

Dates и antirollback/enforce прочитаны, но consumer semantics не восстановлены.
Нельзя утверждать, что `expire` автоматически запрещает установку после
этой даты, `enforce_time` запускает обновление или `antirollback=0`
разрешает любой downgrade. Правила устройства/авторизации не проверены.

## 4. Все 22 firmware records

Номер `#` — локальный индекс в XML document order, начиная с 1.
Это не wire ID и не установленный порядок прошивки.
`(пусто)` обозначает реально присутствующий `type=""`, а не отсутствие поля.
В колонке `O/U/W` приведены точные `order / upgrade_order / wait`.
Размер — bytes полного ZIP member, не размер unsigned/decrypted payload.

| # | id | name | type | version | size | com_prama1 | O/U/W |
|---|---|---|---|---|---:|---|---|
| 1 | 1200 | ESC0 | mc01 | 01.35.01.13 | 95392 | 0x0c00 | 3/4/0 |
| 2 | 1202 | ESC1 | mc01 | 01.35.01.13 | 95392 | 0x0c02 | 2/2/0 |
| 3 | 1200 | ESC0 | mc02 | 01.35.04.43 | 100000 | 0x0c00 | 3/4/0 |
| 4 | 1202 | ESC1 | mc02 | 01.35.04.43 | 100000 | 0x0c02 | 2/2/0 |
| 5 | 0802 | WA345T_E2 | (пусто) | 10.00.21.17 | 291207392 | 0x0801 | 2/4/2 |
| 6 | 1502 | WA345T_V1 | (пусто) | 10.00.21.17 | 360281440 | 0x0f02 | 2/5/2 |
| 7 | 1100 | Battery | BA03WA345 | 29.00.00.25 | 202656 | 0x0b00 | 3/1/1 |
| 8 | 1100 | Battery | WA345PTL | 29.02.01.54 | 210112 | 0x0b00 | 3/1/1 |
| 9 | 1100 | Battery | WA345GY0 | 29.02.05.54 | 211264 | 0x0b00 | 3/1/1 |
| 10 | 0105 | LCPU | (пусто) | 31.20.10.03 | 330464 | 0x0105 | 3/3/0 |
| 11 | 2506 | RTK_Mobile | lifnx17 | 52.94.83.33 | 404736 | 0x1906 | 2/2/0 |
| 12 | 0106 | Laser | (пусто) | 03.04.04.02 | 983936 | 0x0106 | 2/2/0 |
| 13 | 1005 | SEARCHLIGHT | GB95 | 01.00.29.85 | 547520 | 0x0a05 | 2/2/0 |
| 14 | 0103 | IR_Sensor | IA640 | 02.75.00.96 | 627552 | 0x0103 | 2/2/0 |
| 15 | 0103 | IR_Sensor | HK | 26.01.27.01 | 1638816 | 0x0103 | 2/2/0 |
| 16 | 1006 | SPEAKER_MCU | PA02 | 01.00.01.11 | 283648 | 0x0a06 | 2/2/0 |
| 17 | 0501 | CORE_MCU | (пусто) | 01.00.00.45 | 248096 | 0x0501 | 3/3/0 |
| 18 | 2405 | LIDAR | ld04 | 27.02.02.36 | 5770912 | 0x1305 | 2/2/0 |
| 19 | 2400 | RADAR_FRONT | RD03 | 09.25.09.30 | 607808 | 0x1800 | 2/2/0 |
| 20 | 2401 | RADAR_LEFT | RD03 | 09.25.09.30 | 607808 | 0x1801 | 2/2/0 |
| 21 | 2402 | RADAR_RIGHT | RD03 | 09.25.09.30 | 607808 | 0x1802 | 2/2/0 |
| 22 | 2403 | RADAR_UP | RD03 | 09.25.09.30 | 607808 | 0x1803 | 2/2/0 |

Names приведены ровно как в XML. По ним нельзя автоматически определять
CPU architecture, partition, физическую плату или наличие аксессуара.
Особенно нельзя отождествлять `WA345T_V1` с transport `com_method="V1"`:
это разные атрибуты, совпадение части имени не доказывает общую семантику.

### Точное соответствие ZIP filenames

| # | Member name |
|---|---|
| 1 | `wa345t_1200_v01.35.01.13_20231229_mc01.pro.fw.sig` |
| 2 | `wa345t_1202_v01.35.01.13_20231229_mc01.pro.fw.sig` |
| 3 | `wa345t_1200_v01.35.04.43_20250814_mc02.pro.fw.sig` |
| 4 | `wa345t_1202_v01.35.04.43_20250814_mc02.pro.fw.sig` |
| 5 | `wa345t_0802_v10.00.21.17_20260529.ar0.pro.fw.sig` |
| 6 | `wa345t_1502_v10.00.21.17_20260529.ar0.pro.fw.sig` |
| 7 | `wa345t_1100_v29.00.00.25_20240603_BA03WA345.pro.fw.sig` |
| 8 | `wa345t_1100_v29.02.01.54_20250806_WA345PTL.pro.fw.sig` |
| 9 | `wa345t_1100_v29.02.05.54_20250806_WA345GY0.pro.fw.sig` |
| 10 | `wa345t_0105_v31.20.10.03_20241030.pro.fw.sig` |
| 11 | `wa345t_2506_v52.94.83.33_20250321_lifnx17.pro.fw.sig` |
| 12 | `wa345t_0106_v03.04.04.02_20241212.pro.fw.sig` |
| 13 | `wa345t_1005_v01.00.29.85_20250319_GB95.pro.fw.sig` |
| 14 | `wa345t_0103_v02.75.00.96_20260417_IA640.pro.fw.sig` |
| 15 | `wa345t_0103_v26.01.27.01_20260127_HK.pro.fw.sig` |
| 16 | `wa345t_1006_v01.00.01.11_20241230_PA02.pro.fw.sig` |
| 17 | `wa345t_0501_v01.00.00.45_20250930.pro.fw.sig` |
| 18 | `wa345t_2405_v27.02.02.36_20250509_ld04.pro.fw.sig` |
| 19 | `wa345t_2400_v09.25.09.30_20250930_RD03.pro.fw.sig` |
| 20 | `wa345t_2401_v09.25.09.30_20250930_RD03.pro.fw.sig` |
| 21 | `wa345t_2402_v09.25.09.30_20250930_RD03.pro.fw.sig` |
| 22 | `wa345t_2403_v09.25.09.30_20250930_RD03.pro.fw.sig` |

`20260529.ar0` у #5/#6 отличается от suffix остальных members.
Значения `.ar0`, `.pro`, даты и suffix не разобраны как flags протокола.
Проверка не использовала правило «самая новая дата/самая высокая версия».

## 5. Сопоставление и integrity

Для каждого из 22 records проверено:

1. Среди `.fw.sig` members ровно одно совпадение по `id` token,
   `v<version>` token и полному `file_size == int(size)`.
2. Все выбранные filenames уникальны: 22 records -> 22 разных members.
3. `type` согласуется с variant suffix там, где он присутствует.
4. Потоковый MD5 полного member совпадает с manifest `md5`.
5. Сумма 22 `size` плюс размер config равна сумме всех 23 ZIP members.

Это эмпирический способ сопоставления данного пакета, не восстановленный
native algorithm. В другом пакете этот набор ключей может быть неоднозначным.

### Manifest MD5 values

Оба поля ниже — строки из XML. Проверялось только `md5` по полным members.
`md5_unsign` не проверялся: границы/преобразование unsigned image неизвестны.

| # | md5: совпал с whole member | md5_unsign: только прочитан |
|---|---|---|
| 1 | `2f2d9b0cdcec963433f53ae9df9fdc7f` | `8935bf88522f71a94cfdfdb7eaa9501b` |
| 2 | `42e4ac44ac95623b0fe517bb720e50d8` | `17638486f0d27fc6667afab8a2980f5a` |
| 3 | `ec634217ab6fb956dbfefa4855b0e526` | `cf4a214115bf33fdd693a12f02d491de` |
| 4 | `a185ba12b813c7e2c4682a6214ab4f1b` | `4d4044df9e7303b0f3f188652da9fa34` |
| 5 | `7c9d9ac019e8176d4eb8d7f17041ab6e` | `674516570c04cdadcaf746c942aa885e` |
| 6 | `f7aa7afe010729a8bfd247aaf3774988` | `66a7aa258abfcdace3c0eb9bc39b9104` |
| 7 | `6fa97a74f7acafd89f616ba896b19921` | `60353371c71c5466f62a9ec1bd9bb86a` |
| 8 | `d9dca9080d107f433f21b38986df3727` | `8ee86780018be50c164fcc483bb8bb09` |
| 9 | `dbdffb79e167b46d436beceab354fdcd` | `1d1e1a5a61e8e0a15ba37f19c0a1f90c` |
| 10 | `ac809cc91086ba5832b43f769d09ccd4` | `873d28c5e2c7964a0a763c6c292544a4` |
| 11 | `04e1f30461b90b0ce47faea810f303d2` | `8214a9d954f74a85b2c76133076d3405` |
| 12 | `a2fa9b33cdbbbf3f717090b8c12af63b` | `b37d5c8cd53e9f4e20c6303ea896c74e` |
| 13 | `c451d2e77b6fb8521bc237c498773a05` | `626c212bd9b6dc4cb6dbb80a809e4d06` |
| 14 | `9efe22fd58cfb52472bcd67c1676e4c4` | `2a6eb6600ccf01d4281408d752b0c2af` |
| 15 | `b14bbb1868c0516556708f3358dad0f8` | `4ce22ec6090a03349f73a9a8d570aca7` |
| 16 | `c599352873b3aa450a7f03d42798dd2c` | `5ce00a11fba5f32fcb6e666ef87731cf` |
| 17 | `3dd6d752c9eca880313217006f395e33` | `5f38a2a09faa1a0a813cf11f935b77c4` |
| 18 | `b9b8dbcf35da3c0655c1cd5120077b69` | `4685a173f1f667fea137727179ef1662` |
| 19 | `981982669b9ac3a74b367e9ec84f3950` | `0d65e5c4ad6b9a62ac9be1d3777015a9` |
| 20 | `6d9fe4cc5644a0c74a2b12ce2c682487` | `0d65e5c4ad6b9a62ac9be1d3777015a9` |
| 21 | `e1f8de10974f38adc5a734359475eb2d` | `0d65e5c4ad6b9a62ac9be1d3777015a9` |
| 22 | `7ba989e3266e61475ff455298773081d` | `0d65e5c4ad6b9a62ac9be1d3777015a9` |

MD5 нужен здесь только для соответствия данным manifest. Совпадение не
доказывает подлинность/авторство; измененный файл вместе с измененным
manifest мог бы пройти такое сравнение без проверки подписи.

### Аппаратные варианты и нетривиальные совпадения

- ESC #1/#3 и #2/#4 повторяют `id`, `name`, `com_prama1`, но отличаются
  `type` mc01/mc02, версиями, размерами и хешами.
- Battery #7-#9 повторяют `id=1100`, `name=Battery`, `com_prama1=0x0b00`,
  но имеют три разных `type`. Численно большая версия не означает,
  что она предназначена для батареи подключенного экземпляра.
- IR #14/#15 повторяют `id=0103`, `name=IR_Sensor`, `com_prama1=0x0103`,
  но имеют `type=IA640/HK`. Обе версии включены в один release.
- Radar #19-#22 имеют одинаковые size/version/type/`md5_unsign`,
  но разные id/name/`com_prama1` и whole-member MD5. Это согласуется
  с возможным общим unsigned содержимым и разными контейнерами, однако
  **не доказывает** равенство распакованных/decrypted images: `md5_unsign`
  не вычислялся, подписи/метаданные не сравнивались.
- Большие #5/#6 занимают 651488832 байта вместе. Общая версия
  `10.00.21.17` не делает их взаимозаменяемыми: отличаются размер,
  id, имя, handler, security и flags.

## 6. Полный словарь module attributes

В 22 firmware records обнаружены следующие 46 attribute names.
XML parser возвращает строки. Ни `"null"`, ни `"false"` не являются
Python `None`/`False`; пустой `type=""` отличается от `"null"` и отсутствия.
Написание **`com_prama1` / `com_prama2`** сохранено как в исходнике.

### Идентификация, файлы и транспорт

| Поле | Наблюдаемое значение / распределение | Граница интерпретации |
|---|---|---|
| `id` | В каталоге 22 records выше | Module token; не готовый packed DUML receiver |
| `name` | ESC0/ESC1/WA345T_E2/WA345T_V1/Battery и другие | Label; устройство/плата из одного имени не доказаны |
| `type` | Варианты либо пустая строка | Hardware selection rule неизвестен |
| `version` | По каждому record выше | Строка component version, не release version |
| `size` | По каждому record выше | Совпадает с whole ZIP member size |
| `md5` | По каждому record выше | Подтвержден whole-member MD5 |
| `md5_unsign` | По каждому record выше | Значение прочитано, unsigned hashing boundary неизвестна |
| `group` | `ac` у всех | Группировка consumer не установлена |
| `com_method` | `V1` у всех | Связь с native V1 согласована по имени, wire route не доказан |
| `com_prama1` | По каждому record выше | 16-bit-looking strings; packing/index/type не восстановлены |
| `com_prama2` | `null` у всех | Не определено, какое default значение выбирает consumer |
| `op_lib_name` | Standard у 20; Eagle у #5; Standard V2 у #6 | Не установлен host/device execution context |
| `sec_type` | `normal` у 21, `secure` у #6 | Не криптографическая проверка и не определение encryption algorithm |
| `sound_file` | `null` у всех | Назначение/default не проверены |

Нельзя просто взять low byte `com_prama1` как DUML адрес:
например #5 имеет `id=0802`, но `com_prama1=0x0801`.
Id не является механическим преобразованием этого transport parameter.
Связь параметра с command set также не установлена.

### Общие flags, задержки и retry

| Поле | Значение у всех 22 records | Что пока не доказано |
|---|---|---|
| `loader_needed` | `true` | Конкретная команда/модуль loader transition |
| `only_check_ver` | `false` | Условие пропуска по совпадению версии |
| `post_check_ver` | `true` | Критерий завершения и timing проверки |
| `resp_get_ver` | `true` | Формат/допустимость ответа на version query |
| `fail_repeat` | `2` | Это число попыток или повторов, какие failures покрывает |
| `delay_after_1_pkg_us` | `0` | Реальные defaults/rate limits и единицы consumer |
| `delay_after_a_cmd_s` | `0` | Реальные defaults/rate limits и единицы consumer |

Suffix `_us`/`_s` намекает на единицы, но код consumer не прослежен.
Нулевые явные задержки не разрешают бесконтрольный bulk flood.
`fail_repeat=2` не переносится в наш updater как retry policy:
повтор команды записи после неопределенного результата может быть опасен.

### Переменные flags по локальным индексам

Для каждой строки обе группы вместе покрывают все 22 records.
Один и тот же `support_multi_hw=true` встречается и у записей без
повторяющегося `id`; сам флаг не выбирает вариант.

| Поле | `true` | `false` |
|---|---|---|
| `allow_skip` | #7-9, #13, #16-22 | #1-6, #10-12, #14-15 |
| `support_multi_hw` | #1-4, #7-9, #11, #13-16, #19-22 | #5-6, #10, #12, #17-18 |
| `is_upgrade_center` | #5 | #1-4, #6-22 |
| `post_reset` | #1-4, #7-22 | #5-6 |
| `reboot_after_fail` | #5, #10-22 | #1-4, #6-9 |
| `reboot_notify` | #5, #7-9 | #1-4, #6, #10-22 |

`allow_skip=true` не означает «безопасно исключить компонент»:
неизвестны условие skip и связь с отсутствием optional hardware.
`post_reset`/`reboot_*` также не задают восстановленный recovery algorithm.

### Order, upgrade_order и wait

| Поле | Значение | Records |
|---|---|---|
| `order` | `2` | #2, #4-6, #11-16, #18-22 |
| `order` | `3` | #1, #3, #7-10, #17 |
| `upgrade_order` | `1` | #7-9 |
| `upgrade_order` | `2` | #2, #4, #11-16, #18-22 |
| `upgrade_order` | `3` | #10, #17 |
| `upgrade_order` | `4` | #1, #3, #5 |
| `upgrade_order` | `5` | #6 |
| `wait` | `0` | #1-4, #10-22 |
| `wait` | `1` | #7-9 |
| `wait` | `2` | #5-6 |

Есть как минимум три разных понятия порядка: XML document order,
`order` и `upgrade_order`. Совпадающие числа группируют записи, но
не доказывают последовательность/параллельность, dependency graph
или tie-break. Единицы/enum `wait` не известны: `2` не объявляется
двумя секундами. Сортировать и прошивать все entries по таблице нельзя.

### Timing/status attributes

Значение `"null"` буквально присутствует, а не является отсутствием поля.
Не установлено, означает ли оно default из handler, auto timing или
отсутствие соответствующего этапа.

| Поле | Значения |
|---|---|
| `get_version_dt` | `null` у всех |
| `get_version_to` | `null` у всех |
| `request_upgrade_dt` | `null` у всех |
| `request_upgrade_to` | `null` у всех |
| `request_accept_data_dt` | `null` у всех |
| `request_accept_data_to` | `40` у #18 LIDAR; `null` у остальных 21 |
| `transfer_data_dt` | `null` у всех |
| `transfer_data_to` | `null` у всех |
| `transfer_complete_dt` | `null` у всех |
| `transfer_complete_to` | `null` у всех |
| `check_status_dt` | `null` у всех |
| `check_status_to` | `null` у всех |
| `reboot_dt` | `null` у всех |
| `reboot_to` | `null` у всех |
| `wait_status_report_time` | `null` у всех |
| `wait_status_report_time_total` | `null` у всех |

LIDAR #18 выделяется единственным non-null значением в этой timing group.
По имени ожидается timeout принятия данных, но единицы и момент отсчета
не доказаны. Нельзя молча трактовать `40` как секунды или подменять `"null"`
нулевыми таймаутами. `dt` и `to` пока не получили проверенные определения.

## 7. Upgrade center, handlers и security

| Свойство | #5 WA345T_E2 | #6 WA345T_V1 |
|---|---|---|
| `id` | 0802 | 1502 |
| `version` | 10.00.21.17 | 10.00.21.17 |
| `is_upgrade_center` | true | false |
| `op_lib_name` | libeagle_md_up.so | libstandard_v2_md_up.so |
| `sec_type` | normal | secure |
| `post_reset` | false | false |
| `reboot_after_fail` | true | false |
| `reboot_notify` | true | false |
| `support_multi_hw` | false | false |
| `allow_skip` | false | false |
| `upgrade_order` / `wait` | 4 / 2 | 5 / 2 |
| `upgrade_center/module_info` | diff_up_capability=true | diff_up_capability=true |

Два контекста надо различать:

1. `release/module.is_upgrade_center` выделяет только #5.
2. `upgrade_center/module_info` упоминает оба имени и capability.

Из второго не следует, что #6 тоже является center: его boolean flag false.
`diff_up_capability=true` не означает, что текущий ZIP содержит delta,
что host должен вычислять diff или что M4T принимает такой diff по USB.
Ни один из этих сценариев не проверен.

Остальные 20 records используют `libstandard_md_up.so` и `sec_type=normal`.
`.so` похоже на Linux/shared-library имя, но оно может относиться к
device-side service либо другому executor. Файлов этих библиотек в данном
23-entry ZIP нет. Их местонахождение, ABI, entry points и consumer неизвестны.
Это не доказательство готового Linux host updater.

`normal` не означает «не подписано» или «можно отправлять без авторизации».
`secure` не задает AES/RSA/ключ/handshake само по себе.
Все members по-прежнему имеют `.sig` и `IM*H`; проверки криптографии нет.

## 8. Где остановилась native трассировка

В проверенном DJIService.exe не найдены точные null-terminated ASCII
literals `is_upgrade_center`, `support_multi_hw`, `op_lib_name`,
`com_prama1`, `upgrade_center`, `libeagle_md_up.so`.
Это только ограниченный string search одного executable.
Иные encodings, составные/обфусцированные строки, DLL и device-side
consumer не исключены. Нельзя объявить отсутствие parser.

Binary identity и установленные updater/context anchors приведены в
[native-анализе](../native/analysis.md).
Наличие `DJIUpgradeMgr` и `DJIFirmwareUpgrader` не связывает их
автоматически с этим XML и не устанавливает live strategy M4T.

## 9. Что нужно подтвердить до writer

| Граница | Есть сейчас | Нужно установить |
|---|---|---|
| Container parser | Magic, bytes и arithmetic на одном config | Layout/version/bounds и полный signed-region format |
| Подлинность | Совпавшие MD5, SHA256 fingerprints | Signature verification, trust/key chain, защищенные metadata |
| Hardware applicability | type/flags/variants | Как узнаются реальные hardware IDs и выбирается ровно подходящий record |
| Component addressing | id и com_prama1 strings | Type/index packing, receiver routing, реальные transport params |
| Center/executor | Flags/handlers/capability | Кто читает config, получает ZIP/образ и распределяет компоненты |
| Ordering | Три наблюдаемых набора order | Dependency/phase/tie-break, wait semantics |
| Transfer | Имена timing attributes | Session start, chunk size, sequence/ACK, retries и encoding |
| Verify/apply | post_check_ver/post_reset | Критерии завершения, целевая версия, reboot/reconnect |
| Recovery | reboot_after_fail/fail_repeat | Безопасное поведение при timeout/disconnect/частичной записи |
| Linux | Читаемый package без UI | Отдельно проверенный Linux libusb transport и updater implementation |

До этого этапа нельзя отправлять все 22 members подряд, подменять
`null` defaults догадками, выбирать highest version, удалять контейнерную
подпись либо считать single version/battery exchange firmware протоколом.

## Связанные материалы

- [Linux updater: цель и статус](./linux-updater.md)
- [USB/DUML: проверенные обмены и публичный каталог](../transport/usb-duml.md)
- [Native checker, Core и dispatch](../native/analysis.md)
- [Журнал штатных прошивок M4T](../../validation/firmware-live.md)
