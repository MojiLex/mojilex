from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"
SCHEMA_BASE = "https://schemas.mojilex.org/v1/"


class DataError(ValueError):
    """Raised when JSON cannot be read without losing information."""


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DataError(f"duplicate object key: {key!r}")
        result[key] = value
    return result


def parse_json(text: str, *, source: str = "<string>") -> Any:
    try:
        return json.loads(text, object_pairs_hook=_object_without_duplicate_keys)
    except (json.JSONDecodeError, DataError) as exc:
        raise DataError(f"{source}: {exc}") from exc


def read_utf8(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise DataError(f"{path}: UTF-8 BOM is forbidden")
    if b"\r" in raw:
        raise DataError(f"{path}: CR/CRLF line endings are forbidden")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DataError(f"{path}: file is not valid UTF-8: {exc}") from exc


def load_json(path: Path) -> Any:
    return parse_json(read_utf8(path), source=str(path))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    text = read_utf8(path)
    if text and not text.endswith("\n"):
        raise DataError(f"{path}: missing final LF")
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            raise DataError(f"{path}:{line_number}: blank JSONL lines are forbidden")
        value = parse_json(line, source=f"{path}:{line_number}")
        if not isinstance(value, dict):
            raise DataError(f"{path}:{line_number}: a JSONL record must be an object")
        records.append(value)
    return records


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reject_non_jcs_numbers(value: Any) -> None:
    if isinstance(value, float):
        raise DataError("floating-point values are outside the MojiLex JCS profile")
    if isinstance(value, list):
        for item in value:
            _reject_non_jcs_numbers(item)
    elif isinstance(value, dict):
        for item in value.values():
            _reject_non_jcs_numbers(item)


def jcs_bytes(value: Any) -> bytes:
    """Return RFC 8785-compatible bytes for the integer/string data profile.

    Schema v1 has no floating-point fields. Rejecting floats avoids pretending
    that Python's number formatting implements the entire ECMAScript algorithm.
    """

    _reject_non_jcs_numbers(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def jcs_sha256(value: Any) -> str:
    return sha256_bytes(jcs_bytes(value))


_KEY_ORDER = [
    "dataset",
    "schema_version",
    "id_namespace",
    "visual_relation_namespace",
    "taxonomy_version",
    "color_profile",
    "color_profile_sha256",
    "dedupe_profile",
    "dedupe_profile_sha256",
    "collection_dedupe_profile",
    "collection_dedupe_profile_sha256",
    "default_languages",
    "platforms",
    "canonical_repository",
    "licenses",
    "data",
    "code",
    "entity_type",
    "id",
    "platform",
    "kind",
    "native_namespace",
    "scope_id",
    "native_id",
    "identity_epoch",
    "title",
    "canonical_url",
    "availability",
    "item_count",
    "media",
    "fingerprints",
    "facets",
    "descriptions",
    "ru",
    "en",
    "text",
    "motion_status",
    "motion",
    "usage",
    "semantic_tags",
    "content",
    "rating",
    "warnings",
    "provenance",
    "origin",
    "provider",
    "model",
    "prompt_version",
    "pipeline_version",
    "description_profile",
    "model_revision",
    "prompt_sha256",
    "request_parameters_sha256",
    "qualification_id",
    "generation_stage",
    "routing_policy_version",
    "routing_reason_codes",
    "generated_at",
    "input_media_sha256",
    "created_at",
    "creator",
    "human_edits",
    "editor",
    "edited_at",
    "languages",
    "changed_paths",
    "tool",
    "name",
    "version",
    "review",
    "reviewed_at",
    "reviewer",
    "reviewed_content_sha256",
    "extensions",
    "telegram",
    "retrieved_via",
    "short_name",
    "sticker_type",
    "set_fingerprint_sha256",
    "stable_set_id",
    "custom_emoji_id",
    "file_unique_id",
    "fallback_emoji",
    "needs_repainting",
    "status",
    "first_seen_at",
    "last_changed_at",
    "last_verified_at",
    "reason_code",
    "set_by",
    "role",
    "variant_id",
    "format",
    "mime_type",
    "sha256",
    "byte_size",
    "width",
    "height",
    "animated",
    "duration_ms",
    "collection_id",
    "emoji_id",
    "position",
    "target_entity_type",
    "target_id",
    "withheld_at",
    "public_note",
    "subject_id",
    "object_id",
    "scope",
    "relation_type",
    "evidence",
    "subject_media_digest",
    "object_media_digest",
    "media_pairs",
    "signals",
    "reviewed_relation_sha256",
]
_KEY_RANK = {key: index for index, key in enumerate(_KEY_ORDER)}


def _context_order(value: dict[str, Any]) -> list[str] | None:
    entity_type = value.get("entity_type")
    if entity_type == "collection":
        return [
            "schema_version",
            "entity_type",
            "id",
            "platform",
            "kind",
            "native_namespace",
            "scope_id",
            "native_id",
            "identity_epoch",
            "title",
            "canonical_url",
            "availability",
            "item_count",
            "extensions",
        ]
    if entity_type == "emoji":
        return [
            "schema_version",
            "entity_type",
            "id",
            "platform",
            "native_namespace",
            "scope_id",
            "native_id",
            "identity_epoch",
            "availability",
            "media",
            "fingerprints",
            "descriptions",
            "facets",
            "semantic_tags",
            "content",
            "provenance",
            "review",
            "extensions",
        ]
    if entity_type == "membership":
        return [
            "schema_version",
            "entity_type",
            "id",
            "collection_id",
            "emoji_id",
            "status",
            "position",
            "first_seen_at",
            "last_changed_at",
        ]
    if entity_type == "tombstone":
        return [
            "schema_version",
            "entity_type",
            "target_entity_type",
            "target_id",
            "reason_code",
            "withheld_at",
            "public_note",
        ]
    if entity_type == "visual_relation":
        return [
            "schema_version",
            "entity_type",
            "id",
            "identity_epoch",
            "subject_id",
            "object_id",
            "scope",
            "relation_type",
            "evidence",
            "review",
        ]
    if {"taxonomy_version", "registries"}.issubset(value):
        return ["taxonomy_version", "registries"]
    taxonomy_registries = [
        "color_families",
        "content_types",
        "platform_contexts",
        "styles",
        "suggested_uses",
        "uncertainties",
    ]
    if value and set(value).issubset(taxonomy_registries):
        return taxonomy_registries
    if {"animated", "content_types", "literal_text", "media_kinds"}.issubset(value):
        return [
            "animated",
            "alpha_modes",
            "color_behaviors",
            "color_families",
            "content_types",
            "literal_text",
            "media_kinds",
            "styles",
            "suggested_uses",
            "text_status",
            "uncertainties",
        ]
    if {"group_type", "scope", "members"}.issubset(value):
        return [
            "id",
            "group_type",
            "scope",
            "profile",
            "content_digest",
            "source_sha256",
            "byte_size",
            "members",
        ]
    if {
        "taxonomy_version",
        "rendering",
        "text_content",
        "content_types",
    }.issubset(value):
        return [
            "taxonomy_version",
            "rendering",
            "text_content",
            "content_types",
            "styles",
            "suggested_uses",
            "uncertainties",
        ]
    if {"profile", "items"}.issubset(value) and set(value).issubset({"profile", "items"}):
        return ["profile", "items"]
    if {"status", "profile", "input_media_digest", "items"}.issubset(value):
        return ["status", "profile", "input_media_digest", "items"]
    if {"color_behavior", "palette_dynamics", "alpha_mode", "visible_area_bp"}.issubset(value):
        return [
            "role",
            "variant_id",
            "color_behavior",
            "palette_dynamics",
            "alpha_mode",
            "visible_area_bp",
            "dominant_colors",
            "adaptive_mask_source",
            "adaptive_mask_sha256",
        ]
    if {"hex", "family", "coverage_bp"}.issubset(value):
        return ["hex", "family", "coverage_bp"]
    if {"status", "dynamics", "items"}.issubset(value):
        return ["status", "dynamics", "items"]
    if {"value", "kind", "script", "temporal_scope", "media_refs"}.issubset(value):
        return ["value", "kind", "script", "language", "temporal_scope", "media_refs"]
    if {
        "decoded_payload_sha256",
        "canonical_render_sha256",
        "shape_sha256",
        "perceptual",
    }.issubset(value):
        return [
            "role",
            "variant_id",
            "decoded_payload_sha256",
            "canonical_render_sha256",
            "shape_sha256",
            "perceptual",
        ]
    if {"encoding", "sample_count", "layout_phash64", "content_phash64"}.issubset(value):
        return [
            "encoding",
            "sample_count",
            "layout_phash64",
            "content_phash64",
            "alpha_phash64",
            "edge_phash64",
            "temporal_energy_bp",
            "low_information",
        ]
    if {"dedupe_profile", "subject_media_digest", "object_media_digest"}.issubset(value):
        return [
            "dedupe_profile",
            "subject_media_digest",
            "object_media_digest",
            "media_pairs",
            "signals",
        ]
    if {"subject_role", "object_role"}.issubset(value):
        return [
            "subject_role",
            "subject_variant_id",
            "object_role",
            "object_variant_id",
        ]
    if "reviewed_relation_sha256" in value:
        return ["status", "reviewer", "reviewed_at", "reviewed_relation_sha256"]
    if "dataset" in value and "id_namespace" in value:
        return [
            "dataset",
            "schema_version",
            "id_namespace",
            "visual_relation_namespace",
            "taxonomy_version",
            "color_profile",
            "color_profile_sha256",
            "dedupe_profile",
            "dedupe_profile_sha256",
            "collection_dedupe_profile",
            "collection_dedupe_profile_sha256",
            "default_languages",
            "platforms",
            "canonical_repository",
            "licenses",
        ]
    if "git_commit" in value and "payload_sha256" in value:
        return [
            "dataset",
            "schema_version",
            "git_commit",
            "counts",
            "status_counts",
            "profiles",
            "quality_registry_sha256",
            "platform_registry_sha256",
            "payload_sha256",
        ]
    if {"status", "first_seen_at", "last_changed_at"}.issubset(value):
        return [
            "status",
            "first_seen_at",
            "last_changed_at",
            "last_verified_at",
            "reason_code",
            "set_by",
        ]
    if {"role", "kind", "sha256"}.issubset(value):
        return [
            "role",
            "variant_id",
            "kind",
            "format",
            "mime_type",
            "sha256",
            "byte_size",
            "width",
            "height",
            "animated",
            "duration_ms",
        ]
    if {"text", "motion_status", "usage"}.issubset(value):
        return ["text", "motion_status", "motion", "usage"]
    if {"rating", "warnings"}.issubset(value):
        return ["rating", "warnings"]
    if "origin" in value and "tool" in value:
        return [
            "origin",
            "provider",
            "model",
            "prompt_version",
            "pipeline_version",
            "description_profile",
            "model_revision",
            "prompt_sha256",
            "request_parameters_sha256",
            "qualification_id",
            "generation_stage",
            "routing_policy_version",
            "routing_reason_codes",
            "generated_at",
            "input_media_sha256",
            "created_at",
            "creator",
            "human_edits",
            "tool",
        ]
    if {"editor", "edited_at", "languages"}.issubset(value):
        return ["editor", "edited_at", "languages", "changed_paths"]
    if {"name", "version"}.issubset(value) and len(value) == 2:
        return ["name", "version"]
    if "status" in value and set(value).issubset(
        {"status", "reviewed_at", "reviewer", "reviewed_content_sha256"}
    ):
        return ["status", "reviewed_at", "reviewer", "reviewed_content_sha256"]
    if {"schema_version", "retrieved_via", "short_name"}.issubset(value):
        return [
            "schema_version",
            "retrieved_via",
            "short_name",
            "sticker_type",
            "set_fingerprint_sha256",
            "stable_set_id",
        ]
    if {"schema_version", "retrieved_via", "custom_emoji_id"}.issubset(value):
        return [
            "schema_version",
            "retrieved_via",
            "custom_emoji_id",
            "file_unique_id",
            "fallback_emoji",
            "needs_repainting",
        ]
    if {"emoji_id", "collection_ids", "text"}.issubset(value):
        return [
            "emoji_id",
            "platform",
            "native_namespace",
            "scope_id",
            "native_id",
            "collection_ids",
            "text",
            "motion",
            "usage",
            "semantic_tags",
            "review_status",
        ]
    if set(value).issubset({"data", "code"}):
        return ["data", "code"]
    if "ru" in value and "en" in value:
        return ["ru", "en"]
    return None


def ordered(value: Any) -> Any:
    if isinstance(value, dict):
        context = _context_order(value)
        rank = {key: index for index, key in enumerate(context)} if context else _KEY_RANK
        keys = sorted(value, key=lambda key: (rank.get(key, len(rank)), key))
        return {key: ordered(value[key]) for key in keys}
    if isinstance(value, list):
        return [ordered(item) for item in value]
    return value


def pretty_json(value: Any) -> str:
    return json.dumps(ordered(value), ensure_ascii=False, indent=2) + "\n"


def compact_json(value: Any) -> str:
    return json.dumps(ordered(value), ensure_ascii=False, separators=(",", ":"))


def normalize_component(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    if "\0" in normalized:
        raise DataError("identity components must not contain U+0000")
    return normalized


def expected_entity_id(record: dict[str, Any], namespace: uuid.UUID) -> str:
    entity_type = record["entity_type"]
    if entity_type == "membership":
        components = [record["collection_id"], record["emoji_id"]]
        prefix = "mxm_"
    elif entity_type in {"collection", "emoji"}:
        components = [
            record["platform"],
            entity_type,
            record["native_namespace"],
            record["scope_id"],
            record["native_id"],
            str(record["identity_epoch"]),
        ]
        prefix = "mxc_" if entity_type == "collection" else "mxe_"
    else:
        raise DataError(f"cannot derive ID for entity type {entity_type!r}")
    name = "\0".join(normalize_component(str(item)) for item in components)
    return prefix + str(uuid.uuid5(namespace, name))


def entity_shard(entity_id: str, length: int = 2) -> str:
    return sha256_bytes(entity_id.encode("utf-8"))[:length]


def projected_media(media: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    projection: list[dict[str, str]] = []
    for item in media:
        projected = {"role": item["role"]}
        if "variant_id" in item:
            projected["variant_id"] = item["variant_id"]
        projected["sha256"] = item["sha256"]
        projection.append(projected)
    return sorted(
        projection,
        key=lambda item: (item["role"], item.get("variant_id", ""), item["sha256"]),
    )


def media_digest(media: Iterable[dict[str, Any]]) -> str:
    return jcs_sha256(projected_media(media))


def reviewed_content_sha256(emoji: dict[str, Any]) -> str:
    payload = {
        "media": projected_media(emoji["media"]),
        "descriptions": emoji["descriptions"],
        "facets": emoji["facets"],
        "semantic_tags": emoji["semantic_tags"],
        "content": emoji["content"],
        "provenance": emoji["provenance"],
    }
    return jcs_sha256(payload)


def _relation_name_components(relation: dict[str, Any]) -> list[str]:
    subject_id = normalize_component(str(relation["subject_id"]))
    object_id = normalize_component(str(relation["object_id"]))
    scope = normalize_component(str(relation["scope"]))
    epoch = str(relation["identity_epoch"])
    if subject_id == object_id:
        raise DataError("a visual relation cannot relate an emoji to itself")

    subject_role = subject_variant = object_role = object_variant = ""
    if scope == "media-pair":
        pairs = relation["evidence"]["media_pairs"]
        if not isinstance(pairs, list) or len(pairs) != 1 or not isinstance(pairs[0], dict):
            raise DataError("media-pair relation must contain exactly one media pair")
        pair = pairs[0]
        subject_role = normalize_component(str(pair["subject_role"]))
        subject_variant = normalize_component(str(pair.get("subject_variant_id", "")))
        object_role = normalize_component(str(pair["object_role"]))
        object_variant = normalize_component(str(pair.get("object_variant_id", "")))
    elif scope != "entity":
        raise DataError(f"unsupported visual relation scope: {scope!r}")

    if subject_id < object_id:
        left = (subject_id, subject_role, subject_variant)
        right = (object_id, object_role, object_variant)
    else:
        left = (object_id, object_role, object_variant)
        right = (subject_id, subject_role, subject_variant)
    return [
        "visual-relation",
        left[0],
        right[0],
        scope,
        left[1],
        left[2],
        right[1],
        right[2],
        epoch,
    ]


def expected_visual_relation_id(relation: dict[str, Any], namespace: uuid.UUID) -> str:
    name = "\0".join(_relation_name_components(relation))
    return "mxr_" + str(uuid.uuid5(namespace, name))


def reviewed_relation_sha256(relation: dict[str, Any]) -> str:
    return jcs_sha256(
        {
            "identity_epoch": relation["identity_epoch"],
            "subject_id": relation["subject_id"],
            "object_id": relation["object_id"],
            "scope": relation["scope"],
            "relation_type": relation["relation_type"],
            "evidence": relation["evidence"],
        }
    )


def duplicate_group_id(
    namespace: uuid.UUID,
    group_type: str,
    scope: str,
    profile: str,
    content_digest: str,
) -> str:
    components = ["duplicate-group", group_type, scope, profile, content_digest]
    name = "\0".join(normalize_component(component) for component in components)
    return "mxdg_" + str(uuid.uuid5(namespace, name))


def reviewed_same_artwork_group_id(namespace: uuid.UUID, emoji_ids: Iterable[str]) -> str:
    members = sorted({normalize_component(emoji_id) for emoji_id in emoji_ids})
    if len(members) < 2:
        raise DataError("a reviewed same-artwork group requires at least two emoji IDs")
    name = "\0".join(["duplicate-group", "reviewed-same-artwork", "entity", "", *members])
    return "mxdg_" + str(uuid.uuid5(namespace, name))


def telegram_set_fingerprint(members: Iterable[dict[str, str]]) -> str:
    normalized = [
        {
            "custom_emoji_id": member["custom_emoji_id"],
            "file_unique_id": member["file_unique_id"],
        }
        for member in members
    ]
    normalized.sort(key=lambda item: (item["custom_emoji_id"], item["file_unique_id"]))
    return jcs_sha256(normalized)


@dataclass(frozen=True)
class LocatedRecord:
    path: Path
    line: int | None
    value: dict[str, Any]

    @property
    def location(self) -> str:
        return f"{self.path}:{self.line}" if self.line is not None else str(self.path)


@dataclass
class RepositoryRecords:
    collections: list[LocatedRecord]
    emojis: list[LocatedRecord]
    memberships: list[LocatedRecord]
    tombstones: list[LocatedRecord]
    visual_relations: list[LocatedRecord] = field(default_factory=list)


def discover_records(root: Path) -> RepositoryRecords:
    collections: list[LocatedRecord] = []
    emojis: list[LocatedRecord] = []
    memberships: list[LocatedRecord] = []
    tombstones: list[LocatedRecord] = []
    visual_relations: list[LocatedRecord] = []

    for path in sorted((root / "data").glob("*/collections/*/*/collection.json")):
        value = load_json(path)
        if not isinstance(value, dict):
            raise DataError(f"{path}: collection must be a JSON object")
        collections.append(LocatedRecord(path, None, value))

    for path in sorted((root / "data").glob("*/collections/*/*/memberships.jsonl")):
        for line, value in enumerate(load_jsonl(path), start=1):
            memberships.append(LocatedRecord(path, line, value))

    for path in sorted((root / "data").glob("*/emojis/*/*.jsonl")):
        for line, value in enumerate(load_jsonl(path), start=1):
            emojis.append(LocatedRecord(path, line, value))

    for path in sorted((root / "tombstones").glob("*/*.json")):
        value = load_json(path)
        if not isinstance(value, dict):
            raise DataError(f"{path}: tombstone must be a JSON object")
        tombstones.append(LocatedRecord(path, None, value))

    for path in sorted((root / "data" / "relations" / "visual").glob("*/*.jsonl")):
        for line, value in enumerate(load_jsonl(path), start=1):
            visual_relations.append(LocatedRecord(path, line, value))

    return RepositoryRecords(collections, emojis, memberships, tombstones, visual_relations)
