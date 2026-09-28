# Canonical records

This directory contains canonical collection, emoji, and membership records.
Records are added when validated contributions are accepted.

For human browsing, start with the [Telegram pack catalog](telegram/collections/README.md)
and follow a pack link. Each pack's generated `README.md` lists its members in
order with Russian and English descriptions and direct links to the canonical
emoji records. `collection.json` and `memberships.jsonl` remain the source of
pack metadata and membership status.

Each shared emoji is stored in one file at
`telegram/emojis/<sha256(emoji_id)>.jsonl`, where the filename is the **complete**
64-character lowercase SHA-256 of the UTF-8 stable `mxe_...` ID string, not a
media or content hash. The file contains exactly one compact JSON record. Check
that its full `id` equals the membership's `emoji_id`. If only a decimal Telegram
custom emoji ID is known, search for an exact `native_id` match and confirm
`platform` is `telegram`.

From a fresh clone, pin the full Git commit you intend to use and search the
source files directly. Replace both uppercase placeholders before running:

```console
git clone https://github.com/MojiLex/mojilex.git
cd mojilex
git switch --detach FULL_COMMIT_SHA
rg -F 'EMOJI_ID_FROM_MEMBERSHIP' data/telegram/emojis
```

The match gives the JSONL path; parse its single line and confirm its `id`.
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
