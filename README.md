# MojiLex data

English | [Русский](README_RU.md)

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

## Add an emoji pack

The data repository does not need to be cloned manually. Install the CLI from
GitHub:

```console
uv tool install git+https://github.com/MojiLex/mojilex-cli.git@main
```

Authenticate and configure it once:

```console
gh auth login
mojilex init --model gemini-3.8-flash --non-interactive
```

Then provide the public pack URL:

```console
mojilex add https://t.me/addemoji/PackName
```

The command requests missing Telegram and Gemini credentials through hidden
prompts, analyzes and validates the pack, and opens a pull request in this
repository. Credentials remain in memory only for the current command and are
never committed. To check a pack without AI or publication, run
`mojilex add URL --dry-run --check-media`. See the
[MojiLex CLI quick start](https://github.com/MojiLex/mojilex-cli#quick-start)
for prerequisites and troubleshooting.

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

## Build and validate a distribution snapshot

```bash
DATA_COMMIT="$(git rev-parse HEAD)"
SOURCE_DATE_EPOCH="$(git show -s --format=%ct "$DATA_COMMIT")"
python tools/build_index.py . --output dist/index \
  --revision "$DATA_COMMIT" \
  --snapshot-id data-YYYY.MM.DD.N \
  --source-date-epoch "$SOURCE_DATE_EPOCH"
python tools/validate_distribution.py . dist/index
```

All three release identity inputs are mandatory: a full Git object ID, an
immutable `data-YYYY.MM.DD.N` snapshot ID, and an integer
`source_date_epoch`. The builder never consults the wall clock. Reusing the
same source tree and all three inputs produces the same bytes.

The output contains canonical JSONL payloads, active/search derived views,
collection facets, exact/reviewed duplicate groups, registry singletons, an
exact JCS `manifest.json`, and a complete sorted `SHA256SUMS`. Every artifact
declares a schema. The snapshot also embeds byte-identical source copies of all
canonical, derived, and transport schemas (including the read-only CLI JSON and
JSONL contracts), analysis profiles, taxonomy sources, and platform profiles.
`tools/validate_distribution.py` verifies the physical file set, paths,
source/resource bytes, sizes, hashes, offline schema resolution, bindings,
aliases, roots, counts, derived lineage, and projections without network
access. `dist/` is generated and ignored on the main branch.

Authority files under `analysis-profiles/` are exact JCS bytes without a final
LF. All deterministic profiles except the direct concept-candidate profile use
the `delegated-profile-v1` wrapper: readers verify the wrapper's referenced
contract schema bytes and hash offline, validate `body`, then use that `body` as
the effective algorithm configuration. The selector digest covers the complete
wrapper, not only its body.

Active/search files contain only active emoji connected by active memberships
to active collections. Approved and unreviewed records are eligible regardless
of rating or warnings; `changes_requested` and `rejected` records are excluded.
Content labels remain available for consumer filters.

These snapshots currently use `trust_stage=pre-enforcement`: integrity and
reproducibility are implemented, but an unsigned local snapshot is not an
officially authenticated release and must not be marked safe by an agent.

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
