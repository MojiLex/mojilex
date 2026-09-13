# Автоматическое обновление PR с данными

После попадания workflow `Refresh open data PRs` и его инструмента в `main`
каждое изменение `main` запускает обновление открытых PR этого репозитория.
Повторный запуск доступен в **Actions → Refresh open data PRs → Run workflow**.
До публикации этих файлов на GitHub автоматизация не активна.

Два разных эмодзи могут попасть в один JSONL-файл. Обновление объединяет записи
по идентификаторам, сохраняет обе записи и записывает их в новые бакеты по первым
8 символам SHA-256 идентификатора (`ab/cdef01.jsonl`). Старые бакеты с 4 символами
читаются для совместимости. Сам идентификатор и содержимое записи не меняются.

Если PR и `main` по-разному изменили одну запись, автоматизация оставляет PR
без изменений и сообщает о конфликте в журнале Actions. Аналогично обрабатывается
удаление записи, которую другая ветка успела изменить. Успешное обновление
создаёт обычный merge-коммит в ветке PR; PR не сливается в `main` автоматически.
Одна проблемная ветка не мешает обработать остальные.

Перед обновлением выполняется строгая проверка объединённых данных, включая
воспроизводимость сборки. После обновления отдельно запускается `Validate dataset`,
поскольку изменения через `GITHUB_TOKEN` сами по себе не запускают обычный push CI.
Если запрос запуска CI не удался, ветка уже обновлена; повторите workflow обновления.
Он распознает свой коммит и повторит запуск проверок.

## Границы автоматизации

- Поддерживаются PR из веток **этого репозитория**. Для PR из форков стандартный
  `GITHUB_TOKEN` не даёт права записи в чужой репозиторий: автор обновляет свою
  ветку самостоятельно. Увеличение длины бакета уменьшает вероятность конфликта
  и для таких PR.
- PR может менять только канонические коллекции, эмодзи, memberships, визуальные
  связи и tombstones. Изменения кода, workflow, схем или `dataset.json` требуют
  отдельного рассмотрения; инструмент не пытается их автоматически объединять.
- Инструмент запускается из доверенной `main`. Содержимое PR читается как данные;
  код PR никогда не запускается в процессе с токеном записи. Символические ссылки,
  исполняемые файлы данных и дубли идентификаторов отклоняются.
- Если автор успел добавить коммит, обновление без `force` не перезапишет его.
  Повторите workflow, чтобы пересчитать объединение по свежей версии ветки.
- Workflow использует стандартный `GITHUB_TOKEN` с `contents: write`,
  `pull-requests: read`, `actions: write`. Дополнительный секрет не нужен.
  Правила организации или защиты веток могут запретить запись: тогда требуется
  настройка разрешений владельцем репозитория, а не обход защиты инструментом.

Для проверки без изменения веток можно запустить в доверенной локальной копии:

```powershell
python -m tools.refresh_pull_requests --repository MojiLex/mojilex --dry-run
```

Токен должен быть задан через переменную окружения `GITHUB_TOKEN`; не передавайте
его аргументом команды и не вставляйте в отчёты. Режим `--dry-run` читает GitHub
и загружает Git-объекты локально, проверяет объединение, но не записывает ветки
и не запускает CI.

О поведении токена: [GitHub: triggering a workflow](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

## English

Once this workflow reaches `main`, pushes to `main` refresh open, data-only PRs
whose branches belong to this repository. Records are merged by identity and
strictly validated before a non-force branch update. Incompatible edits of the
same record require human resolution; other PRs continue. Fork branches are
skipped because the repository token cannot write to contributors' repositories.
PRs changing code, schemas, workflows, or the manifest are also skipped.

Run **Actions → Refresh open data PRs → Run workflow** to retry. Successful updates
explicitly dispatch the read-only dataset checks. A failed CI dispatch does not
undo the branch update; rerunning refresh retries CI for that bot commit.
No PR is merged automatically, and no PR code executes with a write token.
