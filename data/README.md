# Canonical records

This directory contains canonical collection, emoji, and membership records.
Records are added when validated contributions are accepted. Empty shard
directories and empty bucket files are not committed.

Start with the [Telegram pack catalog](telegram/collections/README.md), open a
collection directory, and read `collection.json` plus `memberships.jsonl`.
An active membership's `emoji_id` points to a shared record under
`telegram/emojis/`. For the current layout, compute SHA-256 of the UTF-8
`emoji_id` string: use the first two hex characters as the directory and the
next six as the `.jsonl` filename. Older valid buckets use the next two hex
characters as the filename. Match the full `id` within that file; a bucket can
contain multiple records. If only a decimal Telegram custom emoji ID is known,
scan emoji records for an exact `native_id` match and confirm `platform` is
`telegram`.

From a fresh clone, pin the full Git commit you intend to use and search the
source files directly. Replace both uppercase placeholders before running:

```console
git clone https://github.com/MojiLex/mojilex.git
cd mojilex
git switch --detach FULL_COMMIT_SHA
rg -F 'EMOJI_ID_FROM_MEMBERSHIP' data/telegram/emojis
```

The match gives a JSONL path and line; parse the line and confirm its `id`.
`git grep -F 'EMOJI_ID_FROM_MEMBERSHIP' -- data/telegram/emojis` is an alternative
when ripgrep (`rg`) is unavailable. For a known decimal Telegram ID, run
`rg -F 'TELEGRAM_CUSTOM_EMOJI_ID' data/telegram/emojis` and confirm an exact
`native_id` match in the result. A record with pending concept mapping still has
RU/EN descriptions in canonical JSONL, although derived search omits it.

Read the caption from `descriptions.ru.text` or `descriptions.en.text`, then
inspect availability, review, provenance, rating, and warnings. The records
contain no original emoji media;
they are source data, not an authenticated release. See [Use the data](../README.md#use-the-data)
or [Использовать данные](../README_RU.md#использовать-данные) for the consumer
workflow, the [maintenance guide](../docs/maintenance.md#data-layout) for the
full path contract, and [schemas/v1/](../schemas/v1/) for record fields.
