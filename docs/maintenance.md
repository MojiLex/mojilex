# Maintaining the MojiLex dataset

English | [Русский](maintenance_RU.md) | [Back to the README](../README.md)

This guide is for contributors and application developers. To analyze and
publish a pack through the menu, start with
[MojiLex CLI](https://github.com/MojiLex/mojilex-cli/blob/main/README.md).

For concurrent data submissions, see [automatic PR refresh and its limits](pr-refresh.md#english).

## Data layout

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

`collection.json` and tombstones are two-space JSON. Emoji bucket files contain
one compact object per line sorted by `id`. Membership files contain compact
objects sorted by `status`, `position`, then `id`. All files use UTF-8 without a
BOM, LF line endings, and deterministic formatting.

Emoji and visual-relation file paths use the first eight characters of the
ID's SHA-256: two for the directory and six for the filename. This reduces
shared-file conflicts between independent pull requests. Correctly hashed legacy
four-character paths remain valid for saved runs and open pull requests. New
writes use eight characters; moving a record does not change its ID or content.
Duplicate IDs across legacy and current files are rejected.

The root namespace UUID is permanently fixed in `dataset.json`. Schema-v1 IDs
are UUIDv5 values over NFC-normalized components separated by U+0000. Exact
input bytes and expected UUIDs/hashes are published in
[`examples/test-vectors.json`](../examples/test-vectors.json).

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
cross-record rules are summarized in [FORMAT.md](../FORMAT.md).

## Validate locally

Python 3.11 or newer is required for the maintenance scripts. They are offline
and do not require Telegram or AI credentials.

Run these commands from the repository root after cloning it with Git.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe tools\validate.py . --strict
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python tools/validate.py . --strict
.venv/bin/python -m unittest discover -s tests -v
```

Strict validation covers schema conformance, UUIDv5 IDs, shard paths,
references, uniqueness, Telegram fingerprints, provenance/media alignment,
facets and fingerprints, exact AI qualification matching, independent semantic
and relation review hashes, moderation/review-routing policy, canonical bytes,
tombstone cascades, secret patterns, binary media/LFS pointers, normative test
vectors, and a double deterministic index build.

## Build and validate a distribution snapshot

Run from the repository root with the environment prepared above.
Replace `data-YYYY.MM.DD.N` with the snapshot date and sequence number.
Choose a source commit whose timestamp is no earlier than the evidence in its records.

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

A snapshot binds three release identity inputs: a full Git object ID, an
immutable `data-YYYY.MM.DD.N` snapshot ID, and an integer `source_date_epoch`.
The CLI requires the snapshot ID and epoch; `--revision` defaults to HEAD.
Pass all three explicitly for a reproducible release command. The builder never consults the wall clock. Reusing the
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

Records with `concept_mapping_status=pending` and empty concept IDs can be
published in canonical data and active views. They enter derived search only
after their mapping is complete; publication never invents concept IDs.

AI qualification is optional: records without it retain their actual provenance
and review status. A supplied qualification must match an exact active registry
entry, including for records with human approval.

These snapshots currently use `trust_stage=pre-enforcement`: integrity and
reproducibility are implemented, but an unsigned local snapshot is not an
officially authenticated release and must not be marked safe by an agent.

For tag-triggered CI builds and the boundary between staging artifacts and official
releases, see [release staging](RELEASE_STAGING.md).
