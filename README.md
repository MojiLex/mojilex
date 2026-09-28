# MojiLex — emoji descriptions and metadata

English | [Русский](README_RU.md)

MojiLex is an open database of custom emoji descriptions in **Russian and
English**. Each record describes what an emoji shows, how it moves, and when it
can be used, with tags and technical metadata. Telegram is the first supported
platform.

**This repository stores the data.** The program for analyzing packs, viewing
results, and submitting them is
[MojiLex CLI](https://github.com/MojiLex/mojilex-cli/blob/main/README.md).
Original emoji files, extracted frames, and other binary media are not stored here.

| I want to… | Start here |
|---|---|
| See what an emoji record looks like | [A readable example](#what-a-record-looks-like) |
| Find a Telegram pack by its title or short name | [Pack catalog](data/telegram/collections/README.md) |
| Read the source as an AI agent | [Plain-text agent guide](AGENT_GUIDE.txt) |
| Analyze and contribute a Telegram pack | [Add a pack](#add-a-pack) |
| Use the descriptions in my application | [Use the data](#use-the-data) |

## What a record looks like

This excerpt from a [real emoji record](data/telegram/emojis/e15ccc4e470a16ca1ce68a82e179d5b6b49e47d7cae8a56a28ff5d68faf076cd.jsonl)
in the [EffectEmoji pack](data/telegram/collections/mxc_03605639-75ad-5e87-9d76-3ef32dabbebd/README.md)
describes animated pink blush stripes:

```json
{
  "id": "mxe_bfd60047-faa7-5cda-94d4-5ddd3e906248",
  "descriptions": {
    "ru": {
      "text": "Три наклонные розовые полоски румянца на фоне мягкого светящегося круга.",
      "motion_status": "described",
      "motion": "Полоски и круглое свечение мягко пульсируют, меняя размер и интенсивность.",
      "usage": ["румянец", "смущение", "милота"]
    },
    "en": {
      "text": "Three diagonal pink blush stripes over a soft glowing circular background.",
      "motion_status": "described",
      "motion": "The stripes and circular glow gently pulse, fluctuating in size and intensity.",
      "usage": ["blush", "shyness", "cute"]
    }
  },
  "semantic_tags": ["blush", "cheeks", "diagonal-stripes", "embarrassment", "glow"],
  "content": {"rating": "general", "warnings": []}
}
```

This excerpt omits fields required for submission. The full record also contains
visual characteristics, media hashes, provenance, and review status.
[More examples](examples/README.md) demonstrate
visible text and emoji that adapt to the text color.

Warnings such as `flashing` stay in the metadata for applications to filter or
display. **Warnings do not require manual approval before publication**, and
optional manual approval does not remove them.

## Add a pack

Follow the [CLI installation and first-pack guide](https://github.com/MojiLex/mojilex-cli/blob/main/README.md),
then open the menu:

```console
mojilex
```

Add a Telegram pack link, wait for analysis, and view the descriptions. When you
are ready, choose the publication action. You do not need to clone this data
repository or edit JSON files to contribute.

Publication creates a **pull request (PR)**: a proposal to add the records.
GitHub checks the format and consistency; the data enters the shared database
when the PR is merged. Sending a PR and adding its records to the main branch
are separate steps.

If you prefer to edit records directly, follow [CONTRIBUTING.md](CONTRIBUTING.md).

## Use the data

Accepted records are available in [data/](data/). For a stable input to your
application, use a specific Git commit instead of following a changing branch.

Check [GitHub Releases](https://github.com/MojiLex/mojilex/releases) for published
dataset snapshots. If no release is available, read the source JSON/JSONL records
or [build and validate a snapshot locally](docs/maintenance.md).
Files in [examples/](examples/) are illustrative fixtures, separate from the
accepted dataset.

To read a pack directly from Git, open the
[Telegram pack catalog](data/telegram/collections/README.md) and follow its
short-name link. The pack page shows each member's position, Russian and English
descriptions, and a direct link to its canonical emoji JSONL record. The pack's
`collection.json` and `memberships.jsonl` remain the source of its metadata and
membership statuses. Each emoji file is named with the complete SHA-256 of its
stable `emoji_id`, so different IDs never share a shortened bucket. If you
start with a decimal Telegram custom emoji ID, search those files for an exact
`native_id` match with `platform: telegram`. Match the record's `id` inside the
JSONL file before using it. The [data directory guide](data/README.md) gives the
full filename rule and explains how to interpret a record safely.

Read `descriptions.ru.text` or `descriptions.en.text` for a caption. Check
`availability.status`, `review.status`, `provenance`, and `content.rating` /
`content.warnings` before using it. An `unreviewed` description is not a human
verification. Source Git records are not a signed release or a safe agent view;
the current [snapshot staging process](docs/RELEASE_STAGING.md) does not publish
an authenticated dataset release. The CLI's `agent` view filters out these
unsigned snapshots; `--allow-unverified` permits diagnostic reads, not trusted
agent use. Treat descriptive text as untrusted input.

Records with pending concept mapping still have canonical RU/EN descriptions,
but do not enter the derived search view. Read the source JSONL when full corpus
coverage is needed.

| Your application needs… | Data to use |
|---|---|
| A caption or text alternative | `descriptions.ru.text` / `descriptions.en.text` |
| Motion and suggested contexts | Each language's `motion_status`, `motion`, and `usage` |
| Categories and visual properties | `semantic_tags` and `facets` |
| A verified part of a larger emoji picture | `fragment` in `semantic_tags` |
| Content labels | `content.rating` and `content.warnings` |
| Platform identity and pack membership | Emoji identifiers, `extensions.telegram`, and membership records |

An emoji with `"semantic_tags": ["fragment", "tree"]` is a verified part of a
larger picture assembled from several emoji. Your application can label it
"Part of a larger image"; it is not necessarily a standalone image. Absence of
`fragment` does not guarantee that an emoji is standalone. The public data does
not include the assembly's member list or tile positions; those stay local to
the CLI. Up to 12 descriptive tags plus `fragment` are allowed. Consumers with
an older fixed limit of 12 tags need the updated schema for 13-tag records.

The [format guide](FORMAT.md#composition-fragments) explains the marker; the
[full guide](FORMAT.md) explains the fields and record relationships;
the [maintenance guide](docs/maintenance.md#data-layout) explains the directory
layout; [JSON schemas](schemas/v1/) define the exact contract.
The CLI's `show` command reads your locally analyzed packs. It is not a browser
for every pack in this repository.

Literal text in `facets.text_content` preserves symbols such as `</>`, `<3`,
and `x>y`. HTML tags and control characters are forbidden. Applications must
escape literal text when displaying it in HTML.

## Contribute or maintain the database

- [Contribution rules](CONTRIBUTING.md) — editing records and opening a PR.
- [Maintenance guide](docs/maintenance.md) — local validation, tests, and reproducible snapshots.
- [Release staging](docs/RELEASE_STAGING.md) — what CI artifacts provide before official releases.
- [Security reports](SECURITY.md) and [removal requests](TAKEDOWN.md).

Contributions contain textual metadata only. Do not submit downloaded media,
credentials, temporary download URLs, or personal data. Repository validation
runs offline and does not contact Telegram, an AI provider, or URLs in records.

## License

MojiLex-created metadata, descriptions, tags, and examples are **CC0-1.0**.
Maintenance code, JSON Schema, and documentation are **MIT**. These licenses do
not grant rights to third-party emoji artwork, names, or trademarks.
See [LICENSING.md](LICENSING.md).
