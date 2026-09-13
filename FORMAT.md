# MojiLex format 1.0.0

This document is an implementation guide to the normative JSON Schema in
`schemas/v1/`. If prose and schema disagree, a schema-valid record plus the
cross-record rules enforced by `tools/validate.py` define what may be published.

## Common encoding

- JSON Schema Draft 2020-12; `schema_version` is `1.0.0`.
- UTF-8 without BOM and LF line endings; ordinary non-empty text files have one
  final LF. The allowlisted immutable JSON files under `analysis-profiles/` are
  the sole exception: they are stored as exact RFC 8785 JCS bytes without a
  trailing LF so source bytes, snapshot resource bytes, and selector hashes are
  identical.
- Strings are Unicode NFC. Unknown optional values are omitted, not `null`.
- Times are second-precision UTC: `YYYY-MM-DDTHH:MM:SSZ`.
- SHA-256 is 64 lowercase hexadecimal characters.
- Structured hashes use RFC 8785 JCS UTF-8 bytes. Schema v1 contains no
  floating-point fields, and the reference implementation rejects floats.
- External numeric identifiers are JSON strings.

## Stable identifiers

The namespace UUID is published in `dataset.json`. Each identity component is
NFC-normalized, UTF-8 encoded, and must not contain U+0000. Components are joined
with one U+0000 character before UUIDv5 is calculated:

```text
collection = platform NUL collection NUL native_namespace NUL scope_id NUL native_id NUL identity_epoch
emoji      = platform NUL emoji      NUL native_namespace NUL scope_id NUL native_id NUL identity_epoch
membership = collection_id NUL emoji_id
```

`identity_epoch` is unsigned decimal ASCII with no leading zero except `0`.
Prefixes are `mxc_`, `mxe_`, and `mxm_`. Approved visual relations use the
derived `visual_relation_namespace`, prefix `mxr_`, and the NUL-joined identity
covered by the normative vector in `examples/test-vectors.json`.

## Entities

A collection identifies a platform collection and records availability and its
count of active memberships. An emoji identifies one platform emoji independently
of the collections containing it. A membership connects the two and preserves
the last known position if it leaves a collection.

For Telegram v1:

- collection identity uses `sticker_set.name`, `global`, and the canonical
  short name;
- emoji identity uses `custom_emoji.id`, `global`, and the decimal ID string;
- `extensions.telegram.short_name` equals collection `native_id`;
- `extensions.telegram.custom_emoji_id` equals emoji `native_id`; and
- only one primary PNG, WebP, TGS, or WebM media metadata object is stored.

PNG and WebP are static: `kind: "static"`, `animated: false`, and no
`duration_ms`. PNG uses `format: "png"` and `mime_type: "image/png"`; WebP
uses `format: "webp"` and `mime_type: "image/webp"`. Record the format of the
original downloaded bytes and its SHA-256, regardless of the source filename.
PNG support is additive; existing WebP, TGS, and WebM records remain valid.

Media objects contain metadata and a source-file hash only. URLs, Telegram
`file_id`, filesystem paths, and binary content are forbidden.

Every active emoji has `facets` and `fingerprints`. Facets bind one rendering
item to every media role/variant, keep literal text separate from translation,
and use the versioned dictionaries under `taxonomy/v1/`. Fingerprints bind one
item to every media role/variant, declare the active deterministic profile, and
carry an `input_media_digest` equal to the current media digest. Canonical data
forbids `partial`; `unavailable` is allowed only on a non-active record with no
fingerprint items.

`dataset.json` pins `color-v1`, `dedupe-v1`, and `collection-dedupe-v1` to
SHA-256 of the full canonical profile. Except for the direct
`concept-candidates-v1` branch, each deterministic profile is a closed
`delegated-profile-v1` wrapper. Its `contract_schema_ref` resolves to a
separately embedded Draft 2020-12 schema, `contract_schema_sha256` pins that
schema's exact bytes, and its `body` must validate with no unevaluated fields.
Immutable profile JSON lives under `analysis-profiles/` as exact JCS and is
copied byte-for-byte into a distribution snapshot. Algorithm implementations
belong to `mojilex-cli`; normative digest/ID vectors remain in
`examples/test-vectors.json` here.

## Composition fragments

`semantic_tags` reserves the English marker `fragment` for an emoji verified
to be part of a larger picture made from several emoji. For example, a tile
from an assembled tree may have this illustrative metadata excerpt:

```json
{"semantic_tags": ["fragment", "tree"]}
```

Consumers can display a label such as "Part of a larger image" or filter these
records when they need standalone images. The marker does not mean the tile is
unusable on its own. Its absence does not guarantee a standalone image: the
analysis is conservative, and older or unexamined records may lack the marker.
Do not assign it solely because an isolated image looks cropped or incomplete.

Tags remain unique, lexicographically sorted lowercase kebab-case English.
One to 12 descriptive tags are required, plus the optional `fragment` marker
(13 total only when `fragment` is present). The marker preserves all existing
descriptive tags and is carried into derived search records. Existing records
remain valid and no new field is required. Consumers with an older validator
that unconditionally limits tags to 12 must update it before accepting records
with 12 descriptive tags plus `fragment`.

Composition member lists, dimensions, coordinates, image evidence, and model
checks remain local to the CLI and are not part of this public marker. It does
not provide enough information to reconstruct the full picture. Adding or
removing the marker changes semantic content and resets review to `unreviewed`
under the same rules as other semantic tags.

## Structured hashes

The Telegram set fingerprint is SHA-256 over the JCS array of
`{custom_emoji_id, file_unique_id}` for active memberships, ordered by those two
fields.

`media_digest` is SHA-256 over a JCS array containing only `role`, optional
`variant_id`, and `sha256`, ordered by `role`, `variant_id`, then `sha256`.

For a non-`unreviewed` record, `reviewed_content_sha256` is SHA-256 over this JCS
object. Media contributes only the same sorted `role`, optional `variant_id`,
and `sha256` projection used by `media_digest`; facets are covered, while
deterministic fingerprints and derived media metadata are intentionally excluded:

```json
{
  "media": [
    {
      "role": "primary",
      "sha256": "..."
    }
  ],
  "descriptions": {},
  "facets": {},
  "semantic_tags": [],
  "content": {},
  "provenance": {}
}
```

Any change to the hashed fields invalidates review and requires status
`unreviewed` until a reviewer approves the new content. A fingerprint-only
profile migration does not reset semantic review.

`reviewed_relation_sha256` covers the JCS object `{identity_epoch, subject_id,
object_id, scope, relation_type, evidence}`. Binary and decoded exact groups are
computed at build time. Only approved `same-artwork`, `variant-of`,
`related-series`, and `not-duplicate` decisions are stored as relations; native
emoji identities and memberships are never merged.

Generated duplicate group IDs use prefix `mxdg_` and UUIDv5 in the published
`visual_relation_namespace`. Exact group names are the NUL join of
`["duplicate-group", group_type, scope, profile_or_empty, content_digest]`.
For a binary media group, `content_digest` is SHA-256 of the JCS object
`{byte_size, sha256}`; for a decoded media group it is the decoded payload hash.
Entity-level digests hash the complete canonical role/variant signature, so a
primary-only match cannot create an entity group when alternates differ. A
reviewed component instead uses the NUL join of
`["duplicate-group", "reviewed-same-artwork", "entity", "", ...sorted_ids]`.
The exact byte/ID vectors are fixed in `examples/test-vectors.json`.

Each `provenance.human_edits[]` item keeps the original `languages` field and
may add a sorted, unique `changed_paths` array of JSON Pointers such as
`/facets/styles`. The paths belong to that individual edit, not to the enclosing
provenance object.

## Availability and moderation

Collections may be `active`, `unavailable`, `private`, `deleted`, or `unknown`.
Emoji omit the collection-only `private` state. Removing an emoji from one pack
changes only its membership status. Network/authentication failure is not proof
of deletion.

Content ratings and warnings do not require `approved` review for publication.
Concept mapping may remain `pending` with empty `concept_ids` in canonical
records and active views. Derived search requires complete mapping and nonempty
concept IDs. Its literal text projection maps `letter` and `punctuation` to
`symbol`, and `code` and `other` to `mixed`, preserving canonical text metadata.
Unreviewed records retain their ratings, warnings, and review status so consumers
can apply their own filters. Active/search views exclude `changes_requested`
and `rejected` records.
Potentially illegal/privacy-sensitive quarantine is never represented in the
public repository.

AI and mixed records may omit `qualification_id` without requiring human approval.
A declared qualification must match an exact active entry in
`quality/model-qualifications.json` for its model/revision, prompt and request
hashes, schema, taxonomy, pipeline, routing policy, languages, and generation
time, regardless of review status. Missing qualification is not an attestation;
preserve the actual provenance and review status.

A policy takedown removes affected current records and cascading memberships.
Only the fields allowed by `tombstone.schema.json` may remain. The same target ID
cannot occur in both `data/` and `tombstones/`.

## Distribution snapshot v1

`tools/build_index.py` requires the exact revision, snapshot ID, and
`source_date_epoch`; it never supplies a time-dependent default. It emits the
15 Stage-A monolith artifacts declared by `PAYLOAD_NAMES`, including canonical
tables, registry singletons, `emojis-active`, collection facets, duplicate
groups/memberships, and English/Russian search rows. Tombstones never restore
withheld fields.

The JCS manifest binds every artifact and physical resource by safe POSIX path,
media type, byte size, SHA-256, schema URI, semantic role, and exact lineage.
Canonical and derived state roots use logical table roots rather than incidental
JSONL layout. `SHA256SUMS` lists every physical file except itself, including
the manifest, in bytewise path order. Duplicate/case-colliding paths, links,
reparse points, extra files, missing descriptors, and media are rejected.

Schema resources under `schemas/distribution/v1/` define the release manifest,
resource/artifact descriptors, concepts, rights, taxonomy, search and agent
records, structured search input, and the closed read-only CLI envelope/result,
request, resolution/similar items, and JSONL metadata/item/summary frames. A
consumer resolves these schemas only from verified snapshot resources. The
distribution validator checks embedded schema bytes against `source_path`,
requires `$id` to equal the descriptor URI, and fails if any `$ref`, artifact
`schema_ref`, or resource `content_schema_ref` is unavailable offline.

Agent/search records are derived projections and do not replace canonical
records. Visible text is untrusted content. Runtime trust and `safe_eligible`
are consumer overlays; Stage A/B snapshots remain `pre-enforcement` until the
post-MVP signed catalog, revocation, errata, and trust-root work is implemented.
