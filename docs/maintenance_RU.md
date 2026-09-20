# Обслуживание базы MojiLex

[English](maintenance.md) | Русский | [Вернуться к README](../README_RU.md)

Эта инструкция предназначена для участников проекта и разработчиков приложений.
Для анализа и отправки пака через меню начните с
[MojiLex CLI](https://github.com/MojiLex/mojilex-cli/blob/main/README_RU.md).

При одновременной отправке паков смотрите [автоматическое обновление PR и его границы](pr-refresh.md).

## Структура данных

```text
dataset.json
data/<platform>/collections/<sha256(id)[0:2]>/<collection_id>/
  collection.json
  memberships.jsonl
data/<platform>/emojis/<sha256(id)[0:2]>/<sha256(id)[2:8]>.jsonl
data/relations/visual/<sha256(id)[0:2]>/<sha256(id)[2:8]>.jsonl
tombstones/<sha256(target_id)[0:2]>/<target_id>.json
schemas/v1/
schemas/distribution/v1/
analysis-profiles/
rights/
taxonomy/v1/
platforms/
quality/
examples/
tools/
tests/
```

Файлы `collection.json` и tombstone используют JSON с отступом в два пробела.
Bucket-файлы эмодзи содержат по одному компактному JSON-объекту на строку и
сортируются по `id`. Записи membership сортируются по `status`, `position`,
затем по `id`. Для всех текстовых файлов используются UTF-8 без BOM, окончания
строк LF и детерминированное форматирование.

Путь файлов эмодзи и визуальных связей использует первые восемь символов
SHA-256 идентификатора: два в имени каталога и шесть в имени файла. Это снижает
вероятность, что независимые PR изменят один файл. Старые пути с четырьмя
символами продолжают проходить проверку для совместимости с сохранёнными
запусками и открытыми PR. Новые записи используют восемь символов; идентификаторы
и содержимое записей при переносе не меняются. Дубликаты идентификаторов между
старыми и новыми файлами запрещены.

Корневой UUID namespace зафиксирован в `dataset.json`. Идентификаторы Schema v1
формируются как UUIDv5 из NFC-нормализованных компонентов, разделенных U+0000.
Точные входные данные и ожидаемые идентификаторы опубликованы в
[examples/test-vectors.json](../examples/test-vectors.json).

## Schema v1

Схемы используют JSON Schema Draft 2020-12:

- `dataset.schema.json` — корневой manifest;
- `collection.schema.json` — коллекция платформы;
- `emoji.schema.json` — семантическая запись эмодзи;
- `facets.schema.json` — семантические и визуальные признаки;
- `fingerprints.schema.json` — точные и перцептивные fingerprints;
- `membership.schema.json` — связь коллекции и эмодзи;
- `visual-relation.schema.json` — подтвержденные решения о дубликатах;
- `tombstone.schema.json` — обезличенная запись об удалении;
- `common.schema.json` — общие типы и правила;
- `extensions/telegram.schema.json` — поля, относящиеся только к Telegram.

Неизвестные свойства отклоняются. Описания `ru` и `en` обязательны. Поля,
специфичные для платформы, допускаются только в `extensions.<platform>`.
Формат идентификаторов, хешей и ссылок описан в [FORMAT.md](../FORMAT.md).

## Локальная проверка

Maintenance scripts требуют Python 3.11 или новее. Проверка выполняется офлайн
и не требует токенов Telegram или AI API keys.

Выполняйте команды из корня репозитория, предварительно клонировав его через Git.

Windows PowerShell:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe tools\validate.py . --strict
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Если команда `python` недоступна, установите Python 3.11 или новее с
[python.org](https://www.python.org/downloads/), включите добавление Python в
PATH и откройте новое окно терминала.

Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python tools/validate.py . --strict
.venv/bin/python -m unittest discover -s tests -v
```

Строгая проверка охватывает JSON Schema, UUIDv5, shard paths, ссылки,
уникальность, fingerprints, происхождение записей, facets, соответствие
квалификации модели, review hashes, правила модерации, канонические байты,
tombstone cascades, поиск секретов, запрет бинарных медиа и LFS pointers,
нормативные test vectors и двойную детерминированную сборку индекса.

## Сборка snapshot

Выполняйте команды из корня репозитория после подготовки окружения выше.
Выберите коммит, время которого не предшествует свидетельствам в его записях.

Windows PowerShell:

```powershell
$dataCommit = (git rev-parse HEAD).Trim()
$sourceDateEpoch = (git show -s --format=%ct $dataCommit).Trim()

.\.venv\Scripts\python.exe tools\build_index.py . `
  --output dist\index `
  --revision $dataCommit `
  --snapshot-id data-YYYY.MM.DD.N `
  --source-date-epoch $sourceDateEpoch

.\.venv\Scripts\python.exe tools\validate_distribution.py . dist\index
```

Linux/macOS:

```bash
DATA_COMMIT="$(git rev-parse HEAD)"
SOURCE_DATE_EPOCH="$(git show -s --format=%ct "$DATA_COMMIT")"
.venv/bin/python tools/build_index.py . --output dist/index \
  --revision "$DATA_COMMIT" \
  --snapshot-id data-YYYY.MM.DD.N \
  --source-date-epoch "$SOURCE_DATE_EPOCH"
.venv/bin/python tools/validate_distribution.py . dist/index
```

Значение `data-YYYY.MM.DD.N` заменяется фактическим идентификатором snapshot.
Снимок связан с полным Git object ID, неизменяемым snapshot ID и целым
значением `source_date_epoch`. CLI требует snapshot ID и epoch; если `--revision`
не задан, используется HEAD. Для воспроизводимой команды задавайте все три явно. Сборщик не использует текущее системное время.
Повторная сборка одного дерева с одинаковыми входными параметрами создает
идентичные байты.

Результат содержит канонические JSONL, производные active/search views,
collection facets, группы подтвержденных дубликатов, registries, точный JCS
`manifest.json` и отсортированный `SHA256SUMS`. Snapshot также включает копии
схем, профилей анализа, taxonomy и platform profiles, необходимые для офлайн-
проверки.

`tools/validate_distribution.py` проверяет физический состав файлов, пути,
размеры, хеши, schema resolution, bindings, roots, counts, lineage и projections
без сетевого доступа. Каталог `dist/` является производным и игнорируется в
ветке `main`.

Файлы под `analysis-profiles/` хранятся как точные JCS-байты без завершающего
LF. Все детерминированные профили, кроме прямого профиля кандидатов концептов,
используют оболочку `delegated-profile-v1`: читатель офлайн проверяет указанные
байты и хеш схемы контракта, валидирует `body` и применяет его как настройки
алгоритма. Хеш селектора охватывает всю оболочку, а не только `body`.

В active/search views попадают только активные эмодзи с активной связью
membership с активной коллекцией.

Рейтинг и предупреждения о содержимом сохраняются в данных и доступны для
фильтров потребителя. Они не требуют ручного одобрения перед публикацией.
В active/search views допускаются записи `approved` и `unreviewed`; записи
`changes_requested` и `rejected` исключаются.

Записи с `concept_mapping_status=pending` и пустым списком концептов можно
публиковать в канонических данных и active views. В производный поиск они
попадают после завершения сопоставления; публикация не придумывает концепты.

Квалификация AI также необязательна: без неё сохраняются настоящие provenance
и статус проверки. Если `qualification_id` указан, он должен точно соответствовать
активной записи реестра, в том числе после ручного одобрения.

Текущие snapshot используют `trust_stage=pre-enforcement`: проверка целостности
и воспроизводимости реализована, однако неподписанный локальный snapshot не
является аутентифицированным релизом и не должен отмечаться агентами как
доверенный.

Запуск сборки по тегу и отличие временных артефактов CI от официального релиза
описаны в [инструкции по подготовке релиза](RELEASE_STAGING.md) (английский).
