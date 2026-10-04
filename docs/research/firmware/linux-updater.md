# Независимый Linux updater: пакет и manifest

[Главная и карта документации](../../../README.md) | [Карта документации](../../README.md)

Цель утверждена, но Linux writer пока не реализован. XML прочитан, все 22 компонента сопоставлены и проверены по MD5; криптографические подписи и полный контракт firmware session пока не проверены.

## Новое свидетельство: полный file-transfer capture

[Offline-проверка предоставленного захвата](./capture-transfer.md) подтвердила
23 файла по USB/DUML `00/2A` на 48: 666015264 bytes, непрерывные chunks,
совпавшие finish MD5. Переданный manifest относится к **17.01.0516**,
а не к нашему ZIP 17.02.0501; 19 из 22 компонентов совпадают между releases.
Формат transfer частично установлен; session setup, ACK pacing,
verify/apply и recovery остаются открытыми. Linux writer не реализован.
В этом прогоне переданы все варианты hardware, не только выбранные host.
Ранние записи ниже сохраняют хронологию до появления этого capture.

Следующий [capture Offline Upgrade 17.02.0501](./capture-offline-upgrade.md)
подтвердил содержимое именно нашего ZIP: config побайтно, 22 firmware по SHA256.
23 файла / 665796192 bytes переданы за 69.733858 s; основная последовательность
83/84/2A/85/42, затем 4F и 41, совпала с первым прогоном.
Оба прогона содержат terminal `04 01 00` и post-reconnect version-like `4F`,
согласующийся с целевым release. Полный M4T decoder, обязательность команд,
ACK pacing/recovery и Linux transport еще не проверены.

Материалы ниже сохраняют ход исследования. Последующие записи могут уточнять ранние гипотезы; ограничения приведены рядом с результатами.

## Цель: независимый Linux updater из имеющегося пакета

Пользователь определил следующий deliverable: прошивка M4T из
имеющихся firmware files на Linux без установленного Assistant,
а не перенос Windows UI automation. Linux writer пока не реализован.
Разрешения на предыдущие battery queries не распространяются
на запуск нового firmware workflow или запись firmware по USB.

Первый offline inspection существующего
`M4T_UAV_17.02.05.01_pro.zip` установил 23 entries:
22 component `.fw.sig` и один `.cfg.sig`, всего 665796192
байта содержимого. Все 23 entry начинаются magic `IM*H`;
внешние ZIP entries не имеют encryption flag. Это не проверка
подписи и не доказательство отсутствия шифрования внутри контейнеров.
Config `wa345t_0000_v17.02.0501_20260529.pro.cfg.sig` имеет
размер 25632 и SHA256
`d743d563d0585701e85367f376725d4547439bc9e1a7761f034d561889ac4f00`.
Файлы не извлекались и не передавались устройству.

В именах повторяются component tokens: 1200 и 1202 по два раза,
1100 три раза, 0103 два раза, с разными suffix/version.
Их нельзя считать дубликатами или выбирать highest version
без manifest/device applicability rules. Текущий Windows
`package_target` читает модель/версию из имени config, а
`validate_package` проверяет ZIP safety/CRC и наличие `.cfg.sig`;
они не разбирают signed container и не проверяют криптографическую
подпись. Для самостоятельного updater этих проверок недостаточно.

Ближайшая задача: определить формат config и проследить его
consumer в штатном updater, включая выбор компонентов и порядок
операций. Затем требуется восстановить firmware-session protocol,
transfer/acknowledgement, verify/apply и recovery, а также проверить
Linux USB transport отдельно. Нельзя предполагать, что весь ZIP
отправляется через MI04, только потому что этот канал успешно
ответил на version/battery requests. Никаких новых live запросов,
firmware операций или изменений production SDK на этом этапе не было.

## Offline manifest: XML и сопоставление всех компонентов

Полный offline-каталог вынесен в
[XML manifest и ZIP entries](./package-manifest.md): байтовые границы,
header DWORDs, release metadata, все 22 records/filenames/MD5,
словарь атрибутов, флаги/таймауты и открытые вопросы.

После утверждения Linux-updater направления разобрано содержимое
config без исполнения/извлечения файлов и без device access.
На данном config читаемый XML начинается в 0x260 и заканчивается
после `</dji>` в 0x6405; далее newline и 26 zero bytes.
Сумма header DWORDs по +0x10/+0x14 также равна 0x260, но
семантика этих header fields и общий IM*H layout еще не доказаны.
XML успешно разобран стандартным parser: root `dji`, device
`wa345t`, firmware formal/release `17.02.0501`, 22 module entries.
Release содержит antirollback/enforce metadata; их наличие/значение
не означает разрешение обходить ограничения устройства.

Каждая из 22 записей однозначно сопоставлена с ZIP member по
component token, версии и размеру. Проверены MD5 полного содержимого
всех 22 members: все совпали с manifest `md5`. Это integrity
comparison, не cryptographic signature verification и не выбор
подходящих файлов для конкретной аппаратуры.
Повторяющиеся component tokens различаются manifest `type`:
например ESC mc01/mc02, battery BA03WA345/WA345PTL/WA345GY0
и IR sensor IA640/HK. Manifest содержит `support_multi_hw`,
`order`, `upgrade_order`, loader/reboot/check/transfer timeouts
и другие параметры; порядок/выбор нельзя выводить только из их имен.

Все 22 entries задают `com_method="V1"` и `com_prama1`;
формат адреса этих значений еще не привязан к wire packing.
Module 0802 / WA345T_E2 имеет `is_upgrade_center="true"` и
`op_lib_name="libeagle_md_up.so"`. Module 1502 / WA345T_V1
задает `libstandard_v2_md_up.so`, `sec_type="secure"`;
остальные — `libstandard_md_up.so`, `sec_type="normal"`.
Отдельная XML section `upgrade_center/module_info` перечисляет
WA345T_E2 и WA345T_V1 с `diff_up_capability="true"`.
Эти строки не доказывают host Linux execution указанных библиотек:
где и кем они используются, пока не установлено.

В DJIService.exe не найдены точные null-terminated ASCII literals
is_upgrade_center/support_multi_hw/op_lib_name/com_prama1/
upgrade_center/libeagle_md_up.so. Это ограниченный string-search
результат, не отсутствие parser: возможны другие encodings,
обфускация или другой модуль. Следующая граница — native consumer
config и передача пакета/manifest центру обновления.
Production SDK и firmware writer не изменены, новых USB запросов нет.

### Продолжение: container -> XML consumer

Последующая static трассировка установила gate `0x5A6AD0`,
extraction `0x5A55A0` и переход caller `0x62D8DC` к Qt XML parser
`0x4B6E40`. Extraction использует start = +0x10 + +0x14 и length
из +0xC8; в нашем config length 24998 включает XML/newline,
но исключает 26 trailing zero bytes.
Gate вызывает auth/digest helper, но не проверяет его return value
в показанном участке; это не доказательство signature success.
Полные anchors, импорты и границы вывода приведены в
[native continuation каталога](./package-manifest.md#9-продолжение-native-extraction-и-qt-xml-consumer).
Module selection, upgrade-center routing и writer по-прежнему не установлены.

## Связанные материалы

[USB и DUML: транспорт и запрос версии](../transport/usb-duml.md) · [Native-анализ: battery checker, Core, Qt и USB dispatch](../native/analysis.md) · [Прошивка M4T: журнал живых проверок](../../validation/firmware-live.md)
