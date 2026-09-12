# Данные MojiLex

[English](README.md) | Русский

MojiLex — открытый машиночитаемый семантический индекс кастомных эмодзи. Этот
репозиторий является источником истины для канонических данных и схем проекта.

В репозитории хранятся:

- стабильные идентификаторы;
- технические метаданные и хеши;
- описания на русском и английском языках;
- сведения о происхождении записей;
- результаты проверки и модерации;
- JSON Schema и профили детерминированной обработки.

Исходные эмодзи, декодированные кадры, contact sheet и другие бинарные медиа в
репозитории не хранятся.

Исполняемый код импорта, анализа и публикации находится в отдельном репозитории
[MojiLex CLI](https://github.com/MojiLex/mojilex-cli). Код этого репозитория не
обращается к Telegram, AI-провайдерам или URL из пользовательских данных.

## Структура данных

```text
dataset.json
data/<platform>/collections/<sha256(id)[0:2]>/<collection_id>/
  collection.json
  memberships.jsonl
data/<platform>/emojis/<sha256(id)[0:2]>/<sha256(id)[2:4]>.jsonl
data/relations/visual/<sha256(id)[0:2]>/<sha256(id)[2:4]>.jsonl
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

Корневой UUID namespace зафиксирован в `dataset.json`. Идентификаторы Schema v1
формируются как UUIDv5 из NFC-нормализованных компонентов, разделенных U+0000.
Точные входные данные и ожидаемые идентификаторы опубликованы в
[examples/test-vectors.json](examples/test-vectors.json).

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
Формат идентификаторов, хешей и ссылок описан в [FORMAT.md](FORMAT.md).

## Локальная проверка

Maintenance scripts требуют Python 3.11 или новее. Проверка выполняется офлайн
и не требует токенов Telegram или AI API keys.

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

В Linux и macOS используйте `.venv/bin/python`.

Строгая проверка охватывает JSON Schema, UUIDv5, shard paths, ссылки,
уникальность, fingerprints, происхождение записей, facets, соответствие
квалификации модели, review hashes, правила модерации, канонические байты,
tombstone cascades, поиск секретов, запрет бинарных медиа и LFS pointers,
нормативные test vectors и двойную детерминированную сборку индекса.

## Сборка snapshot

Пример для PowerShell:

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

Значение `data-YYYY.MM.DD.N` заменяется фактическим идентификатором snapshot.
Для сборки обязательны полный Git object ID, неизменяемый snapshot ID и целое
значение `source_date_epoch`. Сборщик не использует текущее системное время.
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

Текущие snapshot используют `trust_stage=pre-enforcement`: проверка целостности
и воспроизводимости реализована, однако неподписанный локальный snapshot не
является аутентифицированным релизом и не должен отмечаться агентами как
доверенный.

## Внесение изменений

Изменения принимаются через fork и pull request. Перед редактированием данных
ознакомьтесь с [CONTRIBUTING.md](CONTRIBUTING.md).

Запрещено добавлять:

- загруженные файлы эмодзи и другие бинарные медиа;
- токены, API keys и учетные данные;
- временные Telegram download URLs;
- персональные данные;
- материалы из карантина.

Сообщения об уязвимостях передаются через private GitHub Security Advisory в
соответствии с [SECURITY.md](SECURITY.md). Запросы на удаление обрабатываются по
правилам [TAKEDOWN.md](TAKEDOWN.md).

## Лицензирование

Созданные MojiLex метаданные, описания, теги и примеры публикуются по CC0-1.0.
Maintenance code, JSON Schema и документация распространяются по лицензии MIT.
MojiLex не предоставляет права на сторонние изображения эмодзи, названия,
товарные знаки и другие материалы третьих лиц. Подробные условия приведены в
[LICENSING.md](LICENSING.md).
