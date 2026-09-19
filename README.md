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
| Analyze and contribute a Telegram pack | [Add a pack](#add-a-pack) |
| Use the descriptions in my application | [Use the data](#use-the-data) |

## What a record looks like

This excerpt from the [full example](examples/telegram/emoji.json) describes a
yellow cat raising an eyebrow:

```json
{
  "descriptions": {
    "ru": {
      "text": "Жёлтый кот подозрительно приподнимает одну бровь.",
      "motion_status": "described",
      "motion": "Кот медленно поднимает бровь и замирает.",
      "usage": ["подозрение", "недоверие"]
    },
    "en": {
      "text": "A yellow cat suspiciously raises one eyebrow.",
      "motion_status": "described",
      "motion": "The cat slowly raises an eyebrow and pauses.",
      "usage": ["suspicion", "doubt"]
    }
  },
  "semantic_tags": ["cat", "doubt", "raised-eyebrow"],
  "content": {"rating": "general", "warnings": []}
}
```

This is an illustrative excerpt, not a complete record ready for submission.
The full record also contains identifiers, visual characteristics, media hashes,
provenance, and review status. [More examples](examples/README.md) demonstrate
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

As of **13 September 2026**, there are no downloadable dataset releases on
[GitHub Releases](https://github.com/MojiLex/mojilex/releases). You can read the
source JSON/JSONL records or [build and validate a snapshot locally](docs/maintenance.md).
Files in [examples/](examples/) are illustrative fixtures, separate from the
accepted dataset.

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
[full guide](FORMAT.md) explains the fields, directory layout, and record
relationships; [JSON schemas](schemas/v1/) define the exact contract.
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
