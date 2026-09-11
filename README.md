# MojiLex data

MojiLex is an open, machine-readable semantic index for custom emoji. This
repository is the source of truth for the current dataset and schema. It stores
identifiers, technical metadata, hashes, multilingual descriptions, provenance,
and review state. It deliberately stores **no original emoji, frames, contact
sheets, or other binary media**.

Telegram custom emoji are the first supported platform. The importer and other
executable product code live in the separate
[`MojiLex/mojilex-cli`](https://github.com/MojiLex/mojilex-cli) repository.
Nothing in this repository contacts Telegram, an AI provider, or a URL found in
a contribution.

## Data layout

```text
dataset.json
data/<platform>/collections/<sha256(id)[0:2]>/<collection_id>/
  collection.json
  memberships.jsonl
data/<platform>/emojis/<sha256(id)[0:2]>/<sha256(id)[2:4]>.jsonl
data/relations/visual/<sha256(id)[0:2]>/<sha256(id)[2:4]>.jsonl
tombstones/<sha256(target_id)[0:2]>/<target_id>.json
schemas/v1/
taxonomy/v1/
platforms/
quality/
examples/
tools/
tests/
```

`collection.json` and tombstones are two-space JSON. Emoji bucket files contain
one compact object per line sorted by `id`. Membership files contain compact
objects sorted by `status`, `position`, then `id`. All files use UTF-8 without a
BOM, LF line endings, and deterministic formatting.

The root namespace UUID is permanently fixed in `dataset.json`. Schema-v1 IDs
are UUIDv5 values over NFC-normalized components separated by U+0000. Exact
input bytes and expected UUIDs/hashes are published in
[`examples/test-vectors.json`](examples/test-vectors.json).

## Schema v1

The schemas use JSON Schema Draft 2020-12:

- `dataset.schema.json` — root manifest;
- `collection.schema.json` — platform collection;
- `emoji.schema.json` — platform-independent semantic emoji record;
- `facets.schema.json` — multidimensional semantic and rendering facets;
- `fingerprints.schema.json` — deterministic exact/perceptual fingerprints;
- `membership.schema.json` — collection/emoji relationship;
- `visual-relation.schema.json` — approved human duplicate decisions;
- `tombstone.schema.json` — anonymized takedown marker;
- `common.schema.json` — shared types, provenance, review, and content rules;
- `extensions/telegram.schema.json` — Telegram-only fields.

Unknown properties are rejected. Russian (`ru`) and English (`en`) descriptions
are mandatory in v1. Platform-specific fields are confined to
`extensions.<platform>`. The complete identity, hashing, availability, and
cross-record rules are summarized in [FORMAT.md](FORMAT.md).

## Validate locally

Python 3.11 or newer is required for the maintenance scripts. They are offline
and do not require Telegram or AI credentials.

```bash
python -m venv .venv
python -m pip install -r requirements-dev.txt
python tools/validate.py . --strict
python -m unittest discover -s tests -v
```

Strict validation covers schema conformance, UUIDv5 IDs, shard paths,
references, uniqueness, Telegram fingerprints, provenance/media alignment,
facets and fingerprints, exact AI qualification matching, independent semantic
and relation review hashes, moderation/review-routing policy, canonical bytes,
tombstone cascades, secret patterns, binary media/LFS pointers, normative test
vectors, and a double deterministic index build.

## Build an aggregate snapshot

```bash
python tools/build_index.py . --output dist
```

The output contains full canonical JSONL payloads, an active-only emoji index,
Russian and English search rows with flattened facets, collection facet
aggregates, exact/reviewed duplicate groups, approved visual relations, the
complete taxonomy snapshot, an integrity manifest, and `SHA256SUMS`.
`dist/` is generated and ignored on the main branch. The manifest contains the
full Git commit SHA but no wall-clock timestamp, so the same tree and revision
produce identical bytes.

Active/search files contain only active emoji connected by active memberships
to active collections. Approved records of allowed ratings and unreviewed
`general` records without warnings are eligible; `changes_requested` and
`rejected` records are excluded.

## Contributing and safety

Contributions use forks and pull requests. Read [CONTRIBUTING.md](CONTRIBUTING.md)
before changing data. Never submit downloaded media, credentials, raw Telegram
download URLs, personal data, or quarantined material. Sensitive reports belong
in a private GitHub Security Advisory as described in [SECURITY.md](SECURITY.md)
and [TAKEDOWN.md](TAKEDOWN.md).

## Licensing

MojiLex-created metadata, descriptions, tags, and examples are dedicated under
CC0-1.0. Maintenance code, JSON Schema, and documentation are MIT-licensed.
MojiLex does not grant rights to third-party emoji artwork, names, trademarks,
or other third-party material. See [LICENSING.md](LICENSING.md).
