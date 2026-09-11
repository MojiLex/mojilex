#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import binascii
import codecs
import contextlib
import hashlib
import os
import re
import stat
import subprocess
import sys
import tempfile
import unicodedata
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote_to_bytes

try:
    from jsonschema import Draft202012Validator, FormatChecker
    from referencing import Registry, Resource
except ImportError as exc:  # pragma: no cover - exercised by clean-install smoke checks
    raise SystemExit(
        "validation dependency missing; install with "
        "`python -m pip install -r requirements-dev.txt`"
    ) from exc

if __package__:
    from .common import (
        DataError,
        LocatedRecord,
        RepositoryRecords,
        compact_json,
        discover_records,
        duplicate_group_id,
        entity_shard,
        expected_entity_id,
        expected_visual_relation_id,
        jcs_bytes,
        load_json,
        media_digest,
        pretty_json,
        read_utf8,
        reviewed_content_sha256,
        reviewed_relation_sha256,
        reviewed_same_artwork_group_id,
        telegram_set_fingerprint,
    )
else:
    from common import (  # type: ignore[no-redef]
        DataError,
        LocatedRecord,
        RepositoryRecords,
        compact_json,
        discover_records,
        duplicate_group_id,
        entity_shard,
        expected_entity_id,
        expected_visual_relation_id,
        jcs_bytes,
        load_json,
        media_digest,
        pretty_json,
        read_utf8,
        reviewed_content_sha256,
        reviewed_relation_sha256,
        reviewed_same_artwork_group_id,
        telegram_set_fingerprint,
    )


SCHEMA_FILES = {
    "dataset": "dataset.schema.json",
    "collection": "collection.schema.json",
    "emoji": "emoji.schema.json",
    "membership": "membership.schema.json",
    "tombstone": "tombstone.schema.json",
    "visual_relation": "visual-relation.schema.json",
}

DISTRIBUTION_SCHEMA_FILES = {
    "agent-record.schema.json",
    "analysis-profile.schema.json",
    "artifact-descriptor.schema.json",
    "bundle-descriptor.schema.json",
    "bundling-profile-contract.schema.json",
    "cli-command-result.schema.json",
    "cli-jsonl-item.schema.json",
    "cli-jsonl-metadata.schema.json",
    "cli-jsonl-summary.schema.json",
    "cli-read-envelope.schema.json",
    "cli-request.schema.json",
    "cli-resolution-candidate.schema.json",
    "cli-similar-item.schema.json",
    "collection-facet.schema.json",
    "collection-dedupe-profile-contract.schema.json",
    "color-profile-contract.schema.json",
    "compression-profile-contract.schema.json",
    "concept-candidate-profile.schema.json",
    "concept.schema.json",
    "concepts-registry.schema.json",
    "distribution-common.schema.json",
    "delegated-profile.schema.json",
    "dedupe-profile-contract.schema.json",
    "distribution-profile-contract.schema.json",
    "duplicate-group-membership.schema.json",
    "duplicate-group.schema.json",
    "platform-profile.schema.json",
    "platform-profiles-registry.schema.json",
    "key-serialization-profile-contract.schema.json",
    "language-canonicalization-profile-contract.schema.json",
    "language-fallback-profile-contract.schema.json",
    "lexical-search-profile-contract.schema.json",
    "part-packing-profile-contract.schema.json",
    "partitioning-profile-contract.schema.json",
    "release-build-input.schema.json",
    "release-manifest.schema.json",
    "resource-descriptor.schema.json",
    "rights-profile.schema.json",
    "rights-profiles-registry.schema.json",
    "search-request.schema.json",
    "search-record.schema.json",
    "taxonomy-dictionary.schema.json",
    "taxonomy-registry.schema.json",
    "taxonomy-source.schema.json",
}

ANALYSIS_PROFILE_FILES: dict[str, tuple[str, str | None]] = {
    "bcp47-v1.json": (
        "language-canonicalization",
        "language-canonicalization-profile-contract.schema.json",
    ),
    "canonical-primary-key-v1.json": (
        "key-serialization",
        "key-serialization-profile-contract.schema.json",
    ),
    "collection-dedupe-v1.json": (
        "collection-dedupe",
        "collection-dedupe-profile-contract.schema.json",
    ),
    "color-v1.json": ("color", "color-profile-contract.schema.json"),
    "compression-catalog-v1.json": ("compression", "compression-profile-contract.schema.json"),
    "concept-candidates-v1.json": ("concept-candidate", None),
    "dedupe-v1.json": ("dedupe", "dedupe-profile-contract.schema.json"),
    "distribution-v1.json": ("distribution", "distribution-profile-contract.schema.json"),
    "language-fallback-v1.json": (
        "language-fallback",
        "language-fallback-profile-contract.schema.json",
    ),
    "lexical-search-v1.json": ("lexical-search", "lexical-search-profile-contract.schema.json"),
    "part-packing-v1.json": ("part-packing", "part-packing-profile-contract.schema.json"),
    "sha256-jcs-routing-v1.json": ("partitioning", "partitioning-profile-contract.schema.json"),
    "tar-zstd-bundle-v1.json": ("bundling", "bundling-profile-contract.schema.json"),
}

TAXONOMY_FILES = {
    "content_types": "content-types.json",
    "styles": "styles.json",
    "suggested_uses": "suggested-uses.json",
    "uncertainties": "uncertainties.json",
    "color_families": "color-families.json",
    "platform_contexts": "platform-contexts.json",
}
QUALITY_FILES = (
    "model-qualifications.json",
    "routing-reasons-v1.json",
    "review-reasons-v1.json",
    "review-routing-v1.json",
    "description-profiles/standard-v1.json",
)
CONTROLLED_SEMANTIC_TAGS = {
    "abstract",
    "activity",
    "animal",
    "anime",
    "app-interface",
    "badge",
    "body-part",
    "bot-interface",
    "branding",
    "button-icon",
    "cartoon",
    "character",
    "counter",
    "decoration",
    "detailed",
    "flag",
    "flat",
    "food-drink",
    "gradient",
    "hand-drawn",
    "label",
    "logo",
    "message-accent",
    "minimal",
    "nature",
    "navigation",
    "neon",
    "notification",
    "number",
    "object",
    "ornamental",
    "outline",
    "pattern",
    "person",
    "photorealistic",
    "pixel-art",
    "place",
    "plant",
    "profile-avatar",
    "profile-background",
    "reaction",
    "scene",
    "solid",
    "status",
    "sticker-like",
    "symbol",
    "technical-icon",
    "text",
    "three-dimensional",
    "topic-icon",
    "ui-icon",
    "vehicle",
}

IGNORED_TREES = {
    ".git",
    ".venv",
    ".testdeps",
    ".testprefix",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "dist",
    "work",
    ".mojilex",
    ".mojilex-atomic-write",
    ".mojilex-dedupe",
    ".mypy_cache",
}
LOCAL_TRANSACTION_TREES = {".mojilex", ".mojilex-atomic-write"}
FILE_SCAN_CHUNK_SIZE = 64 * 1024
FILE_SCAN_OVERLAP = 4 * 1024
MEDIA_MAGIC = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"\x1aE\xdf\xa3",
    b"\x1f\x8b",
)
FILE_SCAN_PREFIX_SIZE = max(
    len(b"version https://git-lfs.github.com/spec/v1"),
    12,
    *(len(magic) for magic in MEDIA_MAGIC),
)
BANNED_MEDIA_SUFFIXES = {
    ".webp",
    ".tgs",
    ".webm",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".avif",
    ".bmp",
    ".ico",
    ".svg",
    ".tif",
    ".tiff",
    ".mp4",
    ".mov",
    ".mkv",
    ".mp3",
    ".wav",
    ".pdf",
    ".zip",
    ".gz",
    ".7z",
    ".rar",
    ".npy",
    ".npz",
    ".db",
    ".sqlite",
    ".sqlite3",
}
SECRET_PATTERNS = {
    "Telegram bot token": re.compile(r"\b[0-9]{6,12}:[A-Za-z0-9_-]{30,}\b"),
    "GitHub token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    "OpenAI-compatible API key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private key": re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    "Bearer credential": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{20,}={0,2}\b"),
    "Telegram raw download URL": re.compile(
        r"https://api\.telegram\.org/file/bot[^\s\"'<>]+", re.IGNORECASE
    ),
    "credential in URL": re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.IGNORECASE),
}
BASE64_SECRET_CANDIDATE = re.compile(
    r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{24,4096}={0,2}(?![A-Za-z0-9+/_=-])"
)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def add(self, location: str | Path, message: str) -> None:
        self.errors.append(f"{location}: {message}")

    def extend(self, location: str | Path, messages: Iterable[str]) -> None:
        for message in messages:
            self.add(location, message)


def _schema_environment(
    root: Path, report: Report
) -> tuple[dict[str, Any], dict[str, Any], Registry[Any]]:
    schema_root = root / "schemas"
    schemas: dict[str, Any] = {}
    registry: Registry[Any] = Registry()
    for path in sorted(schema_root.rglob("*.schema.json")):
        try:
            schema = load_json(path)
            Draft202012Validator.check_schema(schema)
            resource = Resource.from_contents(schema)
            registry = registry.with_resource(schema["$id"], resource)
            schemas[path.name] = schema
        except Exception as exc:  # schema library exposes several specific subclasses
            report.add(path, f"invalid Draft 2020-12 schema: {exc}")
    required = {
        "common.schema.json",
        "telegram.schema.json",
        *SCHEMA_FILES.values(),
        *DISTRIBUTION_SCHEMA_FILES,
    }
    for missing in sorted(required - schemas.keys()):
        report.add(schema_root, f"required schema is missing: {missing}")
    return (
        schemas,
        {name: schemas.get(filename) for name, filename in SCHEMA_FILES.items()},
        registry,
    )


def _validate_schema(
    value: Any,
    entity_type: str,
    location: str,
    schema_by_type: dict[str, Any],
    schema_registry: Registry[Any],
    report: Report,
) -> bool:
    schema = schema_by_type.get(entity_type)
    if not schema:
        return False
    validator = Draft202012Validator(
        schema,
        registry=schema_registry,
        format_checker=FormatChecker(),
    )
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    for error in errors:
        pointer = "".join(f"/{part}" for part in error.absolute_path) or "/"
        report.add(location, f"schema {pointer}: {error.message}")
    return not errors


def _validate_document_schema(
    value: Any,
    schema_name: str,
    location: str | Path,
    schemas: dict[str, Any],
    registry: Registry[Any],
    report: Report,
) -> bool:
    schema = schemas.get(schema_name)
    if not schema:
        report.add(location, f"required schema is unavailable: {schema_name}")
        return False
    validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    for error in errors:
        pointer = "".join(f"/{part}" for part in error.absolute_path) or "/"
        report.add(location, f"schema {pointer}: {error.message}")
    return not errors


def _schema_references(value: Any) -> list[str]:
    references: list[str] = []
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str):
            references.append(reference)
        for child in value.values():
            references.extend(_schema_references(child))
    elif isinstance(value, list):
        for child in value:
            references.extend(_schema_references(child))
    return references


def _validate_analysis_profiles(
    root: Path,
    dataset: dict[str, Any],
    schemas: dict[str, Any],
    registry: Registry[Any],
    report: Report,
) -> None:
    profile_root = root / "analysis-profiles"
    actual_files = {path.name for path in profile_root.glob("*.json")}
    expected_files = set(ANALYSIS_PROFILE_FILES)
    if actual_files != expected_files:
        report.add(
            profile_root,
            "analysis profile file set is not the exact Stage-A/B path map "
            f"(missing={sorted(expected_files - actual_files)}, "
            f"extra={sorted(actual_files - expected_files)})",
        )

    values: dict[str, dict[str, Any]] = {}
    for filename, (profile_type, contract_filename) in ANALYSIS_PROFILE_FILES.items():
        path = profile_root / filename
        try:
            raw = path.read_bytes()
            value = load_json(path)
            if not isinstance(value, dict):
                raise DataError("analysis profile must be an object")
            values[filename] = value
            canonical = jcs_bytes(value)
            if raw != canonical:
                report.add(path, "authority analysis profile must be exact JCS bytes")
            _validate_document_schema(
                value,
                "analysis-profile.schema.json",
                path,
                schemas,
                registry,
                report,
            )
            expected_id = filename.removesuffix(".json")
            if value.get("profile_id") != expected_id:
                report.add(path, f"profile_id must equal {expected_id!r}")

            if contract_filename is None:
                _validate_document_schema(
                    value,
                    "concept-candidate-profile.schema.json",
                    path,
                    schemas,
                    registry,
                    report,
                )
                continue

            contract_path = root / "schemas" / "distribution" / "v1" / contract_filename
            contract_ref = f"mlx://schemas/distribution/v1/{contract_filename}"
            if value.get("profile_type") != profile_type:
                report.add(path, f"profile_type must equal {profile_type!r}")
            if value.get("contract_schema_ref") != contract_ref:
                report.add(path, "contract_schema_ref does not name the class contract")
            contract_bytes = contract_path.read_bytes()
            contract_sha256 = hashlib.sha256(contract_bytes).hexdigest()
            if value.get("contract_schema_sha256") != contract_sha256:
                report.add(path, "contract_schema_sha256 does not match exact schema bytes")
            contract = schemas.get(contract_filename)
            if not isinstance(contract, dict):
                report.add(path, f"contract schema is unavailable: {contract_filename}")
                continue
            if contract.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                report.add(contract_path, "profile contract must use Draft 2020-12")
            if contract.get("$id") != contract_ref:
                report.add(contract_path, "profile contract $id mismatch")
            if contract.get("unevaluatedProperties") is not False:
                report.add(
                    contract_path,
                    "profile contract must close body with unevaluatedProperties:false",
                )
            for reference in _schema_references(contract):
                if not re.fullmatch(r"#/\$defs/[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*", reference):
                    report.add(contract_path, f"forbidden non-fragment-local $ref {reference!r}")
            _validate_document_schema(
                value.get("body"),
                contract_filename,
                path,
                schemas,
                registry,
                report,
            )
        except (OSError, DataError, TypeError, ValueError) as exc:
            report.add(path, f"invalid analysis profile: {exc}")

    dataset_pins = {
        "color-v1.json": ("color_profile", "color_profile_sha256"),
        "dedupe-v1.json": ("dedupe_profile", "dedupe_profile_sha256"),
        "collection-dedupe-v1.json": (
            "collection_dedupe_profile",
            "collection_dedupe_profile_sha256",
        ),
    }
    for filename, (id_field, digest_field) in dataset_pins.items():
        value = values.get(filename)
        if value is None:
            continue
        expected_digest = hashlib.sha256(jcs_bytes(value)).hexdigest()
        if dataset.get(id_field) != value.get("profile_id"):
            report.add(root / "dataset.json", f"{id_field} does not match {filename}")
        if dataset.get(digest_field) != expected_digest:
            report.add(
                root / "dataset.json",
                f"{digest_field} does not pin SHA-256(JCS({filename}))",
            )


def _walk_strings(value: Any, pointer: str = "") -> Iterable[tuple[str, str]]:
    if isinstance(value, str):
        yield pointer or "/", value
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_strings(child, f"{pointer}/{index}")
    elif isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_strings(child, f"{pointer}/{key}")


def _check_unicode(value: Any, location: str, report: Report) -> None:
    for pointer, text in _walk_strings(value):
        if unicodedata.normalize("NFC", text) != text:
            report.add(location, f"{pointer}: string is not Unicode NFC")


def _parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def _check_times(record: dict[str, Any], location: str, report: Report) -> None:
    availability = record.get("availability")
    if isinstance(availability, dict):
        try:
            first = _parse_timestamp(availability["first_seen_at"])
            changed = _parse_timestamp(availability["last_changed_at"])
            if changed < first:
                report.add(location, "availability.last_changed_at precedes first_seen_at")
            if "last_verified_at" in availability:
                verified = _parse_timestamp(availability["last_verified_at"])
                if verified < first:
                    report.add(location, "availability.last_verified_at precedes first_seen_at")
        except (KeyError, TypeError, ValueError):
            pass
    if record.get("entity_type") == "membership":
        try:
            if _parse_timestamp(record["last_changed_at"]) < _parse_timestamp(
                record["first_seen_at"]
            ):
                report.add(location, "last_changed_at precedes first_seen_at")
        except (KeyError, TypeError, ValueError):
            pass


def _check_text_quality(emoji: dict[str, Any], location: str, report: Report) -> None:
    descriptions = emoji.get("descriptions", {})
    if not isinstance(descriptions, dict):
        return
    for language, description in descriptions.items():
        if not isinstance(description, dict):
            continue
        for field in ("text", "motion"):
            text = description.get(field)
            if isinstance(text, str) and (text != text.strip() or "  " in text):
                report.add(location, f"descriptions.{language}.{field} has non-normalized spaces")
        usage = description.get("usage", [])
        if isinstance(usage, list):
            for index, text in enumerate(usage):
                if isinstance(text, str) and (text != text.strip() or "  " in text):
                    report.add(
                        location,
                        f"descriptions.{language}.usage/{index} has non-normalized spaces",
                    )


def _media_key(item: dict[str, Any]) -> tuple[Any, Any]:
    return item.get("role"), item.get("variant_id")


def _check_phash(
    encoded: Any, sample_count: Any, location: str, pointer: str, report: Report
) -> None:
    if not isinstance(encoded, str) or not isinstance(sample_count, int):
        return
    if "=" in encoded:
        report.add(location, f"{pointer}: pHash64 padding is forbidden")
        return
    try:
        padding = "=" * ((4 - len(encoded) % 4) % 4)
        decoded = base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        report.add(location, f"{pointer}: invalid base64url pHash64")
        return
    if len(decoded) != sample_count * 8:
        report.add(
            location,
            f"{pointer}: decoded length must be sample_count * 8 ({sample_count * 8})",
        )
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if canonical != encoded:
        report.add(location, f"{pointer}: pHash64 is not canonical base64url without padding")


def _check_facets_and_fingerprints(
    emoji: dict[str, Any], dataset: dict[str, Any], location: str, report: Report
) -> None:
    media = emoji.get("media")
    facets = emoji.get("facets")
    fingerprints = emoji.get("fingerprints")
    if not isinstance(media, list) or not all(isinstance(item, dict) for item in media):
        return
    if not isinstance(facets, dict) or not isinstance(fingerprints, dict):
        return

    if facets.get("taxonomy_version") != dataset.get("taxonomy_version"):
        report.add(location, "facets.taxonomy_version does not match dataset taxonomy_version")
    rendering = facets.get("rendering")
    if isinstance(rendering, dict):
        if rendering.get("profile") != dataset.get("color_profile"):
            report.add(location, "facets.rendering.profile does not match dataset color_profile")
        items = rendering.get("items")
        if isinstance(items, list) and all(isinstance(item, dict) for item in items):
            media_keys = [_media_key(item) for item in media]
            render_keys = [_media_key(item) for item in items]
            if render_keys != media_keys:
                report.add(
                    location,
                    "facets.rendering.items must cover media one-to-one in canonical media order",
                )
            media_by_key = {_media_key(item): item for item in media}
            for index, item in enumerate(items):
                pointer = f"facets.rendering.items/{index}"
                native = media_by_key.get(_media_key(item))
                colors = item.get("dominant_colors")
                if isinstance(colors, list) and all(isinstance(color, dict) for color in colors):
                    expected = sorted(
                        colors,
                        key=lambda color: (
                            -int(color.get("coverage_bp", 0)),
                            str(color.get("family", "")),
                            str(color.get("hex", "")),
                        ),
                    )
                    if colors != expected:
                        report.add(location, f"{pointer}.dominant_colors has non-canonical order")
                    total = sum(
                        color.get("coverage_bp", 0)
                        for color in colors
                        if isinstance(color.get("coverage_bp"), int)
                    )
                    if total > 10000:
                        report.add(location, f"{pointer}.dominant_colors coverage exceeds 10000 bp")
                if (
                    native
                    and not native.get("animated")
                    and item.get("palette_dynamics") != "stable"
                ):
                    report.add(location, f"{pointer}: static media requires stable palette")

    text_content = facets.get("text_content")
    content_types = facets.get("content_types")
    uncertainties = facets.get("uncertainties")
    if isinstance(text_content, dict):
        if (
            all(not item.get("animated") for item in media)
            and text_content.get("dynamics") != "stable"
        ):
            report.add(location, "facets.text_content.dynamics must be stable for static media")
        media_keys = {_media_key(item) for item in media}
        for index, text_item in enumerate(text_content.get("items", [])):
            if not isinstance(text_item, dict):
                continue
            refs = text_item.get("media_refs")
            if isinstance(refs, list) and all(isinstance(ref, dict) for ref in refs):
                keys = [_media_key(ref) for ref in refs]
                if keys != sorted(keys, key=lambda key: (str(key[0]), str(key[1] or ""))):
                    report.add(
                        location,
                        f"facets.text_content.items/{index}/media_refs is not canonically sorted",
                    )
                if len(keys) != len(set(keys)):
                    report.add(
                        location,
                        f"facets.text_content.items/{index}/media_refs contains duplicates",
                    )
                for key in keys:
                    if key not in media_keys:
                        report.add(
                            location,
                            f"facets.text_content.items/{index}/media_refs references absent media",
                        )
    if isinstance(content_types, list) and content_types != sorted(content_types):
        report.add(location, "facets.content_types must be sorted lexicographically")
    for field in ("styles", "suggested_uses", "uncertainties"):
        values = facets.get(field)
        if isinstance(values, list) and values != sorted(values):
            report.add(location, f"facets.{field} must be sorted lexicographically")
    styles = facets.get("styles")
    if isinstance(styles, list) and isinstance(uncertainties, list):
        human_approved = emoji.get("review", {}).get("status") == "approved"
        if (
            {"minimal", "detailed"}.issubset(styles)
            and "style" not in uncertainties
            and not human_approved
        ):
            report.add(location, "minimal + detailed requires style uncertainty")
        if (
            {"outline", "solid"}.issubset(styles)
            and "style" not in uncertainties
            and not human_approved
        ):
            report.add(location, "outline + solid requires style uncertainty")
    if isinstance(uncertainties, list):
        for language, description in emoji.get("descriptions", {}).items():
            if (
                isinstance(description, dict)
                and description.get("motion_status") == "undetermined"
                and "motion" not in uncertainties
            ):
                report.add(
                    location,
                    f"descriptions.{language}.motion_status undetermined "
                    "requires motion uncertainty",
                )

    if emoji.get("platform") == "telegram" and isinstance(rendering, dict):
        extension = emoji.get("extensions", {}).get("telegram")
        items = rendering.get("items")
        if isinstance(extension, dict) and isinstance(items, list):
            primary = next(
                (
                    item
                    for item in items
                    if isinstance(item, dict)
                    and item.get("role") == "primary"
                    and "variant_id" not in item
                ),
                None,
            )
            if primary:
                expected = "platform-adaptive" if extension.get("needs_repainting") else "fixed"
                if primary.get("color_behavior") != expected:
                    report.add(
                        location,
                        "Telegram primary color_behavior does not match needs_repainting",
                    )

    semantic_tags = emoji.get("semantic_tags")
    if isinstance(semantic_tags, list):
        repeated = sorted(CONTROLLED_SEMANTIC_TAGS.intersection(semantic_tags))
        if repeated:
            report.add(
                location,
                "semantic_tags duplicates controlled facets: " + ", ".join(repeated),
            )

    status = fingerprints.get("status")
    if status == "partial":
        report.add(location, "fingerprints.status partial is forbidden in canonical data")
    if fingerprints.get("profile") != dataset.get("dedupe_profile"):
        report.add(location, "fingerprints.profile does not match dataset dedupe_profile")
    try:
        expected_digest = media_digest(media)
        if fingerprints.get("input_media_digest") != expected_digest:
            report.add(
                location,
                f"fingerprints.input_media_digest mismatch; expected {expected_digest}",
            )
    except (KeyError, TypeError, DataError):
        pass
    items = fingerprints.get("items")
    if isinstance(items, list) and all(isinstance(item, dict) for item in items):
        if status == "complete" and [_media_key(item) for item in items] != [
            _media_key(item) for item in media
        ]:
            report.add(
                location,
                "fingerprints.items must cover media one-to-one in canonical media order",
            )
        media_by_key = {_media_key(item): item for item in media}
        for index, item in enumerate(items):
            native = media_by_key.get(_media_key(item))
            perceptual = item.get("perceptual")
            if not isinstance(perceptual, dict):
                continue
            sample_count = perceptual.get("sample_count")
            if native:
                expected_samples = 16 if native.get("animated") else 1
                if sample_count != expected_samples:
                    report.add(
                        location,
                        f"fingerprints.items/{index}: expected sample_count {expected_samples}",
                    )
            for field in (
                "layout_phash64",
                "content_phash64",
                "alpha_phash64",
                "edge_phash64",
            ):
                _check_phash(
                    perceptual.get(field),
                    sample_count,
                    location,
                    f"fingerprints.items/{index}/perceptual/{field}",
                    report,
                )
    if status == "unavailable":
        if items:
            report.add(location, "unavailable fingerprints must have empty items")
        if emoji.get("availability", {}).get("status") == "active":
            report.add(location, "unavailable fingerprints require a non-active emoji")


def _check_media_and_provenance(emoji: dict[str, Any], location: str, report: Report) -> None:
    media = emoji.get("media")
    if not isinstance(media, list) or not all(isinstance(item, dict) for item in media):
        return
    try:
        expected_order = sorted(
            media,
            key=lambda item: (item["role"], item.get("variant_id", ""), item["sha256"]),
        )
        if media != expected_order:
            report.add(location, "media is not sorted by role, variant_id, sha256")
        variant_keys = [(item["role"], item.get("variant_id")) for item in media]
        if len(variant_keys) != len(set(variant_keys)):
            report.add(location, "media role + variant_id must be unique")

        current_hashes = sorted({item["sha256"] for item in media})
        provenance_hashes = emoji.get("provenance", {}).get("input_media_sha256")
        if provenance_hashes is not None and provenance_hashes != current_hashes:
            report.add(
                location,
                "provenance.input_media_sha256 must equal sorted unique current media hashes",
            )

        semantic_tags = emoji.get("semantic_tags")
        if isinstance(semantic_tags, list) and semantic_tags != sorted(semantic_tags):
            report.add(location, "semantic_tags must be sorted lexicographically")
        content = emoji.get("content")
        warnings = content.get("warnings") if isinstance(content, dict) else None
        if isinstance(warnings, list) and warnings != sorted(warnings):
            report.add(location, "content.warnings must be sorted lexicographically")
        provenance = emoji.get("provenance")
        if isinstance(provenance, dict):
            routing_reasons = provenance.get("routing_reason_codes")
            if isinstance(routing_reasons, list) and routing_reasons != sorted(routing_reasons):
                report.add(location, "provenance.routing_reason_codes must be sorted")
            if provenance.get("generation_stage") == "escalated" and not routing_reasons:
                report.add(location, "escalated provenance requires a routing reason")
            for index, edit in enumerate(provenance.get("human_edits", [])):
                if not isinstance(edit, dict):
                    continue
                for field in ("languages", "changed_paths"):
                    values = edit.get(field)
                    if (
                        isinstance(values, list)
                        and all(isinstance(value, str) for value in values)
                        and values != sorted(set(values))
                    ):
                        report.add(
                            location,
                            f"provenance.human_edits/{index}/{field} must be sorted unique",
                        )

        all_static = all(not item["animated"] for item in media)
        for language, description in emoji.get("descriptions", {}).items():
            status = description.get("motion_status")
            if all_static and status != "not_applicable":
                report.add(
                    location, f"descriptions.{language}: static media requires not_applicable"
                )
            if not all_static and status == "not_applicable":
                report.add(
                    location,
                    f"descriptions.{language}: animated media cannot use not_applicable",
                )
    except (KeyError, TypeError):
        return


def _check_review_and_policy(emoji: dict[str, Any], location: str, report: Report) -> None:
    review = emoji.get("review")
    content = emoji.get("content")
    if not isinstance(review, dict) or not isinstance(content, dict):
        return
    status = review.get("status")
    if status in {"approved", "changes_requested", "rejected"}:
        try:
            expected = reviewed_content_sha256(emoji)
            if review.get("reviewed_content_sha256") != expected:
                report.add(location, f"reviewed_content_sha256 mismatch; expected {expected}")
        except (KeyError, TypeError, DataError) as exc:
            report.add(location, f"cannot calculate reviewed_content_sha256: {exc}")
    rating = content.get("rating")
    warnings = content.get("warnings")
    if (rating in {"sensitive", "adult", "unknown"} or warnings) and status != "approved":
        report.add(location, "non-general or warned content must be approved before publication")


def _load_contract_registries(
    root: Path,
    dataset: dict[str, Any],
    schemas: dict[str, Any],
    schema_registry: Registry[Any],
    report: Report,
) -> tuple[
    dict[str, set[str]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    taxonomy: dict[str, set[str]] = {}
    taxonomy_root = root / "taxonomy" / "v1"
    try:
        manifest = load_json(taxonomy_root / "taxonomy.json")
        if not isinstance(manifest, dict):
            raise DataError("taxonomy manifest must be an object")
        _validate_document_schema(
            manifest,
            "taxonomy-source.schema.json",
            taxonomy_root / "taxonomy.json",
            schemas,
            schema_registry,
            report,
        )
        if manifest.get("taxonomy_version") != dataset.get("taxonomy_version"):
            report.add(
                taxonomy_root / "taxonomy.json", "taxonomy version differs from dataset.json"
            )
        if manifest.get("status") != "active":
            report.add(taxonomy_root / "taxonomy.json", "taxonomy status must be active")
        registries = manifest.get("registries")
        if not isinstance(registries, list):
            raise DataError("taxonomy registries must be an array")
        pairs: list[tuple[Any, Any]] = []
        for index, entry in enumerate(registries):
            if not isinstance(entry, dict) or set(entry) != {
                "dictionary_id",
                "path",
                "sha256",
            }:
                report.add(
                    taxonomy_root / "taxonomy.json",
                    f"registries/{index} must contain dictionary_id, path, and sha256",
                )
                continue
            facet_name, relative_path = entry.get("dictionary_id"), entry.get("path")
            if not isinstance(facet_name, str) or not isinstance(relative_path, str):
                report.add(
                    taxonomy_root / "taxonomy.json",
                    f"registries/{index} facet and path must be strings",
                )
                continue
            pairs.append((facet_name, relative_path))
            source_path = taxonomy_root / relative_path
            try:
                actual_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
                if entry.get("sha256") != actual_sha256:
                    report.add(
                        taxonomy_root / "taxonomy.json",
                        f"registries/{index}/sha256 mismatch; expected {actual_sha256}",
                    )
            except OSError as exc:
                report.add(source_path, f"cannot hash taxonomy dictionary: {exc}")
        ids = [facet for facet, _path in pairs]
        if ids != sorted(ids, key=str.encode):
            report.add(taxonomy_root / "taxonomy.json", "dictionary IDs must be bytewise sorted")
        expected_pairs = sorted(TAXONOMY_FILES.items(), key=lambda item: item[0].encode())
        if pairs != expected_pairs:
            report.add(
                taxonomy_root / "taxonomy.json",
                "registry dictionary/path set is incomplete",
            )
    except (OSError, DataError, AttributeError) as exc:
        report.add(taxonomy_root / "taxonomy.json", f"invalid taxonomy manifest: {exc}")

    for facet, filename in TAXONOMY_FILES.items():
        path = taxonomy_root / filename
        try:
            registry = load_json(path)
            if not isinstance(registry, dict):
                raise DataError("registry must be an object")
            _validate_document_schema(
                registry,
                "taxonomy-dictionary.schema.json",
                path,
                schemas,
                schema_registry,
                report,
            )
            if set(registry) != {"taxonomy_version", "facet", "entries"}:
                report.add(path, "taxonomy registry contains missing or unknown top-level fields")
            if registry.get("taxonomy_version") != dataset.get("taxonomy_version"):
                report.add(path, "taxonomy version differs from dataset.json")
            if registry.get("facet") != facet:
                report.add(path, f"facet must equal {facet!r}")
            entries = registry.get("entries")
            if not isinstance(entries, list):
                raise DataError("entries must be an array")
            ids: list[str] = []
            by_id: dict[str, dict[str, Any]] = {}
            required = {
                "id",
                "name_ru",
                "name_en",
                "definition_ru",
                "definition_en",
                "positive_examples",
                "negative_examples",
                "status",
            }
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    report.add(path, f"entries/{index} must be an object")
                    continue
                missing = required - set(entry)
                if missing:
                    report.add(path, f"entries/{index} missing: {', '.join(sorted(missing))}")
                    continue
                extra = set(entry) - (required | {"replaced_by"})
                if extra:
                    report.add(
                        path,
                        f"entries/{index} has unknown fields: {', '.join(sorted(extra))}",
                    )
                identifier = entry.get("id")
                if not isinstance(identifier, str) or not re.fullmatch(
                    r"[a-z0-9]+(?:-[a-z0-9]+)*", identifier
                ):
                    report.add(path, f"entries/{index}/id must be lowercase kebab-case")
                    continue
                ids.append(identifier)
                by_id[identifier] = entry
                if entry.get("status") not in {"active", "deprecated"}:
                    report.add(path, f"entries/{index}/status is invalid")
                if entry.get("status") == "deprecated" and not entry.get("replaced_by"):
                    report.add(path, f"entries/{index}: deprecated ID requires replaced_by")
                if entry.get("status") == "active" and "replaced_by" in entry:
                    report.add(path, f"entries/{index}: active ID cannot have replaced_by")
                for text_field in ("name_ru", "name_en", "definition_ru", "definition_en"):
                    text = entry.get(text_field)
                    if not isinstance(text, str) or not text.strip():
                        report.add(path, f"entries/{index}/{text_field} must be non-empty text")
                for examples_field in ("positive_examples", "negative_examples"):
                    examples = entry.get(examples_field)
                    if (
                        not isinstance(examples, list)
                        or not examples
                        or any(
                            not isinstance(value, str) or not value.strip() for value in examples
                        )
                    ):
                        report.add(
                            path,
                            f"entries/{index}/{examples_field} must be non-empty text entries",
                        )
            if ids != sorted(ids):
                report.add(path, "entries must be sorted by id")
            if len(ids) != len(set(ids)):
                report.add(path, "entry IDs must be unique")
            for entry in by_id.values():
                replacement = entry.get("replaced_by")
                if replacement and (
                    replacement not in by_id or by_id[replacement].get("status") != "active"
                ):
                    report.add(path, f"replacement {replacement!r} must name an active entry")
            taxonomy[facet] = set(ids)
        except (OSError, DataError) as exc:
            report.add(path, f"invalid taxonomy registry: {exc}")

    try:
        facets_schema = load_json(root / "schemas" / "v1" / "facets.schema.json")
        schema_taxonomy = {
            "content_types": set(facets_schema["properties"]["content_types"]["items"]["enum"]),
            "styles": set(facets_schema["properties"]["styles"]["items"]["enum"]),
            "suggested_uses": set(facets_schema["properties"]["suggested_uses"]["items"]["enum"]),
            "uncertainties": set(facets_schema["properties"]["uncertainties"]["items"]["enum"]),
            "color_families": set(
                facets_schema["$defs"]["dominantColor"]["properties"]["family"]["enum"]
            ),
        }
        for facet, identifiers in schema_taxonomy.items():
            if taxonomy.get(facet) != identifiers:
                report.add(
                    root / "schemas" / "v1" / "facets.schema.json",
                    f"{facet} enum differs from taxonomy registry",
                )
        telegram_schema = load_json(root / "schemas" / "v1" / "extensions" / "telegram.schema.json")
        context_ids = set(
            telegram_schema["$defs"]["emoji"]["properties"]["context_observations"]["items"][
                "properties"
            ]["context"]["enum"]
        )
        if taxonomy.get("platform_contexts") != context_ids:
            report.add(
                root / "schemas" / "v1" / "extensions" / "telegram.schema.json",
                "platform context enum differs from taxonomy registry",
            )
    except (OSError, DataError, KeyError, TypeError) as exc:
        report.add(root / "schemas" / "v1", f"cannot compare schema and taxonomy: {exc}")

    concepts_by_id: dict[str, dict[str, Any]] = {}
    concepts_path = taxonomy_root / "concepts.json"
    try:
        concepts_registry = load_json(concepts_path)
        if not isinstance(concepts_registry, dict):
            raise DataError("concept registry must be an object")
        _validate_document_schema(
            concepts_registry,
            "concepts-registry.schema.json",
            concepts_path,
            schemas,
            schema_registry,
            report,
        )
        registry_id = concepts_registry.get("registry_id")
        if not isinstance(registry_id, str) or not re.fullmatch(
            r"concepts-v1\.[0-9]{4}-[0-9]{2}-[0-9]{2}\.[1-9][0-9]*",
            registry_id,
        ):
            report.add(concepts_path, "registry_id must be a content-versioned concepts-v1 ID")
        concepts = concepts_registry.get("concepts")
        if not isinstance(concepts, list):
            raise DataError("concepts must be an array")
        concept_ids = [item.get("id") for item in concepts if isinstance(item, dict)]
        if (
            len(concept_ids) != len(concepts)
            or any(not isinstance(identifier, str) for identifier in concept_ids)
            or concept_ids != sorted(concept_ids, key=str.encode)
            or len(concept_ids) != len(set(concept_ids))
        ):
            report.add(concepts_path, "concept IDs must be bytewise sorted and unique")
        concepts_by_id = {
            str(item["id"]): item
            for item in concepts
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        for identifier, concept in concepts_by_id.items():
            for language, aliases in concept.get("aliases", {}).items():
                if isinstance(aliases, list) and aliases != sorted(aliases, key=str.encode):
                    report.add(
                        concepts_path,
                        f"concept {identifier!r} aliases/{language} must be bytewise sorted",
                    )
            parents = concept.get("parent_ids", [])
            if isinstance(parents, list):
                if parents != sorted(parents, key=str.encode):
                    report.add(
                        concepts_path,
                        f"concept {identifier!r} parent_ids must be bytewise sorted",
                    )
                for parent in parents:
                    if parent == identifier or parent not in concepts_by_id:
                        report.add(
                            concepts_path,
                            f"concept {identifier!r} has an invalid parent {parent!r}",
                        )
            replacement = concept.get("replaced_by")
            if replacement is not None and (
                replacement not in concepts_by_id
                or concepts_by_id[replacement].get("status") != "active"
            ):
                report.add(
                    concepts_path,
                    f"concept {identifier!r} replacement must name an active concept",
                )

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit_concept(identifier: str) -> None:
            if identifier in visiting:
                raise DataError(f"concept hierarchy contains a cycle at {identifier!r}")
            if identifier in visited:
                return
            visiting.add(identifier)
            for parent in concepts_by_id[identifier].get("parent_ids", []):
                if parent in concepts_by_id:
                    visit_concept(parent)
            visiting.remove(identifier)
            visited.add(identifier)

        for identifier in sorted(concepts_by_id, key=str.encode):
            visit_concept(identifier)
    except (OSError, DataError, AttributeError, TypeError) as exc:
        report.add(concepts_path, f"invalid concept registry: {exc}")

    rights_profiles: dict[str, dict[str, Any]] = {}
    rights_path = root / "rights" / "profiles.json"
    try:
        rights_registry = load_json(rights_path)
        if not isinstance(rights_registry, dict):
            raise DataError("rights registry must be an object")
        _validate_document_schema(
            rights_registry,
            "rights-profiles-registry.schema.json",
            rights_path,
            schemas,
            schema_registry,
            report,
        )
        registry_id = rights_registry.get("registry_id")
        if not isinstance(registry_id, str) or not re.fullmatch(
            r"rights-profiles-v1\.[0-9]{4}-[0-9]{2}-[0-9]{2}\.[1-9][0-9]*",
            registry_id,
        ):
            report.add(rights_path, "registry_id must be a content-versioned rights-v1 ID")
        profiles = rights_registry.get("profiles")
        if not isinstance(profiles, list):
            raise DataError("rights profiles must be an array")
        profile_ids = [item.get("rights_profile_id") for item in profiles if isinstance(item, dict)]
        if (
            len(profile_ids) != len(profiles)
            or any(not isinstance(identifier, str) for identifier in profile_ids)
            or profile_ids != sorted(profile_ids, key=str.encode)
            or len(profile_ids) != len(set(profile_ids))
        ):
            report.add(rights_path, "rights profile IDs must be bytewise sorted and unique")
        rights_profiles = {
            str(item["rights_profile_id"]): item
            for item in profiles
            if isinstance(item, dict) and isinstance(item.get("rights_profile_id"), str)
        }
        default_id = rights_registry.get("project_default_profile_id")
        default_profile = rights_profiles.get(str(default_id))
        if (
            default_id != dataset.get("rights_defaults", {}).get("project_profile_id")
            or default_profile is None
            or default_profile.get("status") != "active"
            or default_profile.get("applies_to") != {"project": "mojilex"}
        ):
            report.add(rights_path, "project default must resolve to the active project profile")
        for profile_id, profile in rights_profiles.items():
            start = _parse_timestamp(profile["effective_from"])
            if (
                "effective_until" in profile
                and _parse_timestamp(profile["effective_until"]) <= start
            ):
                report.add(rights_path, f"rights profile {profile_id!r} has an invalid interval")
            for operation, decision in profile.get("operations", {}).items():
                conditions = decision.get("conditions", []) if isinstance(decision, dict) else []
                if isinstance(conditions, list) and conditions != sorted(
                    conditions, key=str.encode
                ):
                    report.add(
                        rights_path,
                        f"rights profile {profile_id!r} {operation} conditions are not sorted",
                    )
            for basis in profile.get("basis", []):
                if not isinstance(basis, dict) or basis.get("kind") != "project-policy":
                    continue
                document = basis.get("document")
                if not isinstance(document, str) or PurePosixPath(document).parts != (document,):
                    report.add(rights_path, f"rights profile {profile_id!r} has unsafe basis path")
                    continue
                try:
                    digest = hashlib.sha256((root / document).read_bytes()).hexdigest()
                    if basis.get("document_sha256") != digest:
                        report.add(
                            rights_path,
                            f"rights profile {profile_id!r} basis digest mismatch",
                        )
                except OSError as exc:
                    report.add(rights_path, f"cannot resolve rights basis {document!r}: {exc}")
    except (OSError, DataError, AttributeError, KeyError, TypeError, ValueError) as exc:
        report.add(rights_path, f"invalid rights registry: {exc}")

    for platform in dataset.get("platforms", []):
        path = root / "platforms" / f"{platform}.json"
        try:
            registry = load_json(path)
            if not isinstance(registry, dict) or registry.get("platform") != platform:
                raise DataError("platform registry identity mismatch")
            _validate_document_schema(
                registry,
                "platform-profile.schema.json",
                path,
                schemas,
                schema_registry,
                report,
            )
            capabilities = registry.get("capabilities")
            if not isinstance(capabilities, list):
                raise DataError("platform capabilities must be an array")
            capability_ids = [
                item.get("capability_id") for item in capabilities if isinstance(item, dict)
            ]
            if (
                len(capability_ids) != len(capabilities)
                or any(not isinstance(identifier, str) for identifier in capability_ids)
                or capability_ids != sorted(capability_ids, key=str.encode)
                or len(capability_ids) != len(set(capability_ids))
            ):
                report.add(path, "platform capabilities must be bytewise sorted and unique")
            for index, capability in enumerate(capabilities):
                if not isinstance(capability, dict):
                    continue
                if capability.get("authority_class") in {
                    "official-api",
                    "official-documentation",
                } and not str(capability.get("evidence_url", "")).startswith(
                    "https://core.telegram.org/"
                ):
                    report.add(
                        path,
                        f"capabilities/{index}: official Telegram evidence must use "
                        "core.telegram.org",
                    )
            default_id = registry.get("default_rights_profile_id")
            if isinstance(default_id, str):
                selected = rights_profiles.get(default_id)
                if (
                    selected is None
                    or selected.get("status") != "active"
                    or selected.get("applies_to") != {"platform": platform}
                ):
                    report.add(path, "platform rights default must resolve to its active profile")
            _check_unicode(registry, str(path), report)
        except (OSError, DataError) as exc:
            report.add(path, f"invalid platform registry: {exc}")

    quality_root = root / "quality"
    for filename in QUALITY_FILES:
        path = quality_root / filename
        try:
            value = load_json(path)
            if not isinstance(value, dict):
                raise DataError("registry must be an object")
            if value.get("schema_version") != dataset.get("schema_version"):
                report.add(path, "schema_version differs from dataset")
            _check_unicode(value, str(path), report)
        except (OSError, DataError) as exc:
            report.add(path, f"invalid quality registry: {exc}")

    expected_routing_reasons = {
        "character-or-brand",
        "complex-motion",
        "facet-conflict",
        "low-visibility",
        "ocr-conflict",
        "partial-text",
        "quality-control-sample",
        "schema-retry-exhausted",
        "sensitive-content",
        "unqualified-model",
    }
    expected_review_reasons = {
        "exact-group-description-conflict",
        "moderation-uncertainty",
        "motion-uncertainty",
        "ocr-conflict",
        "unknown-character-or-brand",
        "unqualified-model",
    }
    for filename, registry_id, expected_ids in (
        ("routing-reasons-v1.json", "routing-reasons-v1", expected_routing_reasons),
        ("review-reasons-v1.json", "review-reasons-v1", expected_review_reasons),
    ):
        path = quality_root / filename
        try:
            registry = load_json(path)
            if not isinstance(registry, dict):
                raise DataError("reason registry must be an object")
            if set(registry) != {"schema_version", "registry_id", "entries"}:
                report.add(path, "reason registry contains missing or unknown top-level fields")
            if registry.get("registry_id") != registry_id:
                report.add(path, f"registry_id must equal {registry_id}")
            entries = registry.get("entries", [])
            if not isinstance(entries, list):
                raise DataError("reason entries must be an array")
            ids = [entry.get("id") for entry in entries if isinstance(entry, dict)]
            valid_ids = all(isinstance(identifier, str) for identifier in ids)
            if (
                len(ids) != len(entries)
                or not valid_ids
                or ids != sorted(expected_ids)
                or set(ids) != expected_ids
            ):
                report.add(path, "controlled reason IDs are incomplete or unsorted")
            for index, entry in enumerate(entries):
                if not isinstance(entry, dict) or set(entry) != {"id", "definition"}:
                    report.add(path, f"entries/{index} must contain only id and definition")
                    continue
                if not isinstance(entry.get("definition"), str) or not entry["definition"].strip():
                    report.add(path, f"entries/{index}/definition must be non-empty text")
        except (OSError, DataError, AttributeError) as exc:
            report.add(path, f"invalid reason registry: {exc}")

    policy_path = quality_root / "review-routing-v1.json"
    try:
        policy = load_json(policy_path)
        if not isinstance(policy, dict):
            raise DataError("review policy must be an object")
        if set(policy) != {
            "schema_version",
            "policy_id",
            "priority_order",
            "rules",
        }:
            report.add(policy_path, "review policy contains missing or unknown top-level fields")
        if policy.get("policy_id") != "review-routing-v1":
            report.add(policy_path, "policy_id must equal review-routing-v1")
        if policy.get("priority_order") != ["blocking", "high", "normal", "low"]:
            report.add(policy_path, "priority_order differs from the normative order")
        if not isinstance(policy.get("rules"), list):
            raise DataError("review policy rules must be an array")
        rules = {
            rule.get("reason_code"): rule
            for rule in policy.get("rules", [])
            if isinstance(rule, dict)
        }
        expected_priorities = {
            "unqualified-model": "blocking",
            "moderation-uncertainty": "blocking",
            "motion-uncertainty": "high",
            "ocr-conflict": "high",
            "unknown-character-or-brand": "high",
            "exact-group-description-conflict": "normal",
        }
        if set(rules) != expected_review_reasons:
            report.add(policy_path, "review policy reason set is incomplete")
        if len(rules) != len(policy.get("rules", [])):
            report.add(policy_path, "review policy reason codes must be unique")
        for index, rule in enumerate(policy.get("rules", [])):
            if not isinstance(rule, dict) or set(rule) != {"reason_code", "priority", "condition"}:
                report.add(
                    policy_path,
                    f"rules/{index} must contain reason_code, priority, and condition",
                )
                continue
            reason = rule.get("reason_code")
            if rule.get("priority") != expected_priorities.get(reason):
                report.add(policy_path, f"{reason} has an invalid priority")
            if not isinstance(rule.get("condition"), str) or not rule["condition"].strip():
                report.add(policy_path, f"rules/{index}/condition must be non-empty text")
    except (OSError, DataError, AttributeError) as exc:
        report.add(policy_path, f"invalid review-routing policy: {exc}")

    description_path = quality_root / "description-profiles" / "standard-v1.json"
    try:
        profile = load_json(description_path)
        if not isinstance(profile, dict):
            raise DataError("description profile must be an object")
        if set(profile) != {
            "schema_version",
            "profile_id",
            "languages",
            "recommended_text_length_codepoints",
            "hard_text_limit_codepoints",
            "requirements",
        }:
            report.add(
                description_path,
                "description profile contains missing or unknown top-level fields",
            )
        if profile.get("profile_id") != "standard-v1":
            report.add(description_path, "profile_id must equal standard-v1")
        if profile.get("languages") != dataset.get("default_languages"):
            report.add(description_path, "languages must equal dataset default_languages")
        recommended = profile.get("recommended_text_length_codepoints", {})
        if recommended != {"minimum": 40, "maximum": 220}:
            report.add(description_path, "recommended text length must be 40..220")
        if profile.get("hard_text_limit_codepoints") != 280:
            report.add(description_path, "hard text limit must be 280")
        requirements = profile.get("requirements")
        if (
            not isinstance(requirements, list)
            or not requirements
            or any(
                not isinstance(value, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value)
                for value in requirements
            )
            or requirements != list(dict.fromkeys(requirements))
        ):
            report.add(description_path, "requirements must be unique lowercase kebab-case IDs")
    except (OSError, DataError, AttributeError) as exc:
        report.add(description_path, f"invalid description profile: {exc}")

    qualifications: dict[str, dict[str, Any]] = {}
    qualification_path = quality_root / "model-qualifications.json"
    try:
        registry = load_json(qualification_path)
        if not isinstance(registry, dict):
            raise DataError("qualification registry must be an object")
        if set(registry) != {"schema_version", "registry_id", "entries"}:
            report.add(
                qualification_path,
                "qualification registry contains missing or unknown top-level fields",
            )
        if registry.get("registry_id") != "model-qualifications-v1":
            report.add(qualification_path, "registry_id must equal model-qualifications-v1")
        if registry.get("schema_version") != dataset.get("schema_version"):
            report.add(qualification_path, "schema_version differs from dataset")
        entries = registry.get("entries", [])
        if not isinstance(entries, list):
            raise DataError("entries must be an array")
        previous = ""
        required = {
            "qualification_id",
            "provider",
            "model",
            "description_profile",
            "prompt_sha256",
            "request_parameters_sha256",
            "schema_version",
            "taxonomy_version",
            "pipeline_version",
            "routing_policy_version",
            "languages",
            "benchmark_id",
            "benchmark_sha256",
            "split_id",
            "split_sha256",
            "report_sha256",
            "valid_from",
            "status",
        }
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                report.add(qualification_path, f"entries/{index} must be an object")
                continue
            missing = required - set(entry)
            if missing:
                report.add(
                    qualification_path,
                    f"entries/{index} missing: {', '.join(sorted(missing))}",
                )
                continue
            identifier = entry.get("qualification_id")
            if not isinstance(identifier, str) or not re.fullmatch(
                r"mq_[a-z0-9]+(?:[-_.][a-z0-9]+)*", identifier
            ):
                report.add(qualification_path, f"entries/{index}/qualification_id is invalid")
                continue
            allowed = required | {"model_revision", "valid_until"}
            extra = set(entry) - allowed
            if extra:
                report.add(
                    qualification_path,
                    f"entries/{index} has unknown fields: {', '.join(sorted(extra))}",
                )
            if identifier <= previous:
                report.add(qualification_path, "qualification entries must be sorted and unique")
            previous = identifier
            qualifications[identifier] = entry
            if entry.get("status") not in {"active", "revoked"}:
                report.add(qualification_path, f"entries/{index}/status is invalid")
            for text_field in (
                "provider",
                "model",
                "description_profile",
                "benchmark_id",
                "split_id",
            ):
                text = entry.get(text_field)
                if not isinstance(text, str) or not text.strip():
                    report.add(
                        qualification_path,
                        f"entries/{index}/{text_field} must be non-empty text",
                    )
            for version_field in (
                "schema_version",
                "taxonomy_version",
                "pipeline_version",
                "routing_policy_version",
            ):
                if not re.fullmatch(
                    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)",
                    str(entry.get(version_field, "")),
                ):
                    report.add(
                        qualification_path,
                        f"entries/{index}/{version_field} must be SemVer core",
                    )
            for hash_field in (
                "prompt_sha256",
                "request_parameters_sha256",
                "benchmark_sha256",
                "split_sha256",
                "report_sha256",
            ):
                if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get(hash_field, ""))):
                    report.add(
                        qualification_path,
                        f"entries/{index}/{hash_field} must be lowercase SHA-256",
                    )
            if "model_revision" not in entry and "valid_until" not in entry:
                report.add(
                    qualification_path,
                    f"entries/{index}: valid_until required without model_revision",
                )
            if "model_revision" in entry and (
                not isinstance(entry["model_revision"], str)
                or not entry["model_revision"].strip()
                or any(
                    ord(character) < 32 or ord(character) == 127
                    for character in entry["model_revision"]
                )
            ):
                report.add(
                    qualification_path,
                    f"entries/{index}/model_revision must be non-empty safe text",
                )
            languages = entry.get("languages")
            if (
                not isinstance(languages, list)
                or not languages
                or any(
                    not isinstance(language, str)
                    or not re.fullmatch(r"(?:[A-Za-z]{2,3})(?:-[A-Za-z0-9]{2,8})*", language)
                    for language in languages
                )
                or languages != sorted(set(languages))
            ):
                report.add(
                    qualification_path,
                    f"entries/{index}/languages must be non-empty sorted unique BCP 47 tags",
                )
            try:
                start = _parse_timestamp(entry["valid_from"])
                if "valid_until" in entry and _parse_timestamp(entry["valid_until"]) <= start:
                    report.add(qualification_path, f"entries/{index}: invalid validity interval")
            except (KeyError, TypeError, ValueError):
                report.add(qualification_path, f"entries/{index}: invalid validity timestamp")
    except (OSError, DataError, AttributeError) as exc:
        report.add(qualification_path, f"invalid qualification registry: {exc}")
    return taxonomy, qualifications, concepts_by_id


def _qualification_matches(
    emoji: dict[str, Any], qualification: dict[str, Any], dataset: dict[str, Any]
) -> bool:
    provenance = emoji.get("provenance", {})
    expected = {
        "provider": provenance.get("provider"),
        "model": provenance.get("model"),
        "description_profile": provenance.get("description_profile"),
        "prompt_sha256": provenance.get("prompt_sha256"),
        "request_parameters_sha256": provenance.get("request_parameters_sha256"),
        "schema_version": emoji.get("schema_version"),
        "taxonomy_version": emoji.get("facets", {}).get("taxonomy_version"),
        "pipeline_version": provenance.get("pipeline_version"),
        "routing_policy_version": provenance.get("routing_policy_version"),
        "languages": sorted(emoji.get("descriptions", {})),
    }
    if any(qualification.get(key) != value for key, value in expected.items()):
        return False
    if qualification.get("model_revision") != provenance.get("model_revision"):
        return False
    if qualification.get("status") != "active":
        return False
    try:
        generated = _parse_timestamp(provenance["generated_at"])
        if generated < _parse_timestamp(qualification["valid_from"]):
            return False
        if "valid_until" in qualification and generated >= _parse_timestamp(
            qualification["valid_until"]
        ):
            return False
    except (KeyError, TypeError, ValueError):
        return False
    return dataset.get("taxonomy_version") == expected["taxonomy_version"]


def _validate_record_schemas(
    records: RepositoryRecords,
    schema_by_type: dict[str, Any],
    registry: Registry[Any],
    report: Report,
) -> set[str]:
    valid: set[str] = set()
    groups = (
        ("collection", records.collections),
        ("emoji", records.emojis),
        ("membership", records.memberships),
        ("tombstone", records.tombstones),
        ("visual_relation", records.visual_relations),
    )
    for entity_type, group in groups:
        for record in group:
            if _validate_schema(
                record.value, entity_type, record.location, schema_by_type, registry, report
            ):
                valid.add(record.location)
            _check_unicode(record.value, record.location, report)
            _check_times(record.value, record.location, report)
    return valid


def _check_paths_and_canonical(root: Path, records: RepositoryRecords, report: Report) -> None:
    expected_json_paths = {
        record.path.resolve() for record in records.collections + records.tombstones
    }
    expected_jsonl_paths = (
        {path.resolve() for path in (root / "data").glob("*/collections/*/*/memberships.jsonl")}
        | {path.resolve() for path in (root / "data").glob("*/emojis/*/*.jsonl")}
        | {path.resolve() for path in (root / "data" / "relations" / "visual").glob("*/*.jsonl")}
    )
    expected_paths = expected_json_paths | expected_jsonl_paths

    for base in (root / "data", root / "tombstones"):
        for path in sorted(base.rglob("*")) if base.exists() else []:
            if (
                path.is_file()
                and path.suffix in {".json", ".jsonl"}
                and path.resolve() not in expected_paths
            ):
                report.add(path, "JSON/JSONL file is outside the canonical path layout")

    try:
        dataset_path = root / "dataset.json"
        dataset = load_json(dataset_path)
        if read_utf8(dataset_path) != pretty_json(dataset):
            report.add(
                dataset_path, "manifest does not use canonical two-space formatting/key order"
            )
    except DataError as exc:
        report.add(root / "dataset.json", str(exc))

    for record in records.collections:
        parts = record.path.relative_to(root).parts
        platform, shard, directory_id = parts[1], parts[3], parts[4]
        value = record.value
        if value.get("platform") != platform:
            report.add(record.path, "record platform does not match path platform")
        if value.get("id") != directory_id:
            report.add(record.path, "collection ID does not match directory name")
        if isinstance(value.get("id"), str) and entity_shard(value["id"]) != shard:
            report.add(record.path, "collection shard does not match SHA-256(id)")
        if not (record.path.parent / "memberships.jsonl").is_file():
            report.add(record.path, "collection directory is missing memberships.jsonl")
        try:
            if read_utf8(record.path) != pretty_json(value):
                report.add(record.path, "collection is not canonically formatted")
        except DataError as exc:
            report.add(record.path, str(exc))

    emoji_files: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for record in records.emojis:
        emoji_files[record.path].append(record.value)
        parts = record.path.relative_to(root).parts
        platform, shard_1, shard_2 = parts[1], parts[3], record.path.stem
        value = record.value
        if value.get("platform") != platform:
            report.add(record.location, "record platform does not match path platform")
        if isinstance(value.get("id"), str) and entity_shard(value["id"], 4) != shard_1 + shard_2:
            report.add(record.location, "emoji bucket path does not match SHA-256(id)")
    for path, values in emoji_files.items():
        if values != sorted(values, key=lambda value: value.get("id", "")):
            report.add(path, "emoji bucket is not sorted by id")
        expected = "".join(f"{compact_json(value)}\n" for value in values)
        try:
            if read_utf8(path) != expected:
                report.add(path, "emoji JSONL is not canonical compact JSON")
        except DataError as exc:
            report.add(path, str(exc))
    for path in sorted((root / "data").glob("*/emojis/*/*.jsonl")):
        if path.stat().st_size == 0:
            report.add(path, "empty emoji bucket files are forbidden")

    membership_files: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for record in records.memberships:
        membership_files[record.path].append(record.value)
        parts = record.path.relative_to(root).parts
        collection_id = parts[4]
        if record.value.get("collection_id") != collection_id:
            report.add(record.location, "membership collection_id does not match directory")
    for path, values in membership_files.items():
        sorted_values = sorted(
            values,
            key=lambda value: (
                value.get("status", ""),
                value.get("position", -1),
                value.get("id", ""),
            ),
        )
        if values != sorted_values:
            report.add(path, "memberships are not sorted by status, position, id")
        expected = "".join(f"{compact_json(value)}\n" for value in values)
        try:
            if read_utf8(path) != expected:
                report.add(path, "membership JSONL is not canonical compact JSON")
        except DataError as exc:
            report.add(path, str(exc))

    for record in records.tombstones:
        parts = record.path.relative_to(root).parts
        shard, filename_id = parts[1], record.path.stem
        target_id = record.value.get("target_id")
        if target_id != filename_id:
            report.add(record.path, "tombstone target_id does not match filename")
        if isinstance(target_id, str) and entity_shard(target_id) != shard:
            report.add(record.path, "tombstone shard does not match SHA-256(target_id)")
        try:
            if read_utf8(record.path) != pretty_json(record.value):
                report.add(record.path, "tombstone is not canonically formatted")
        except DataError as exc:
            report.add(record.path, str(exc))

    relation_files: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for record in records.visual_relations:
        relation_files[record.path].append(record.value)
        parts = record.path.relative_to(root).parts
        shard_1, shard_2 = parts[3], record.path.stem
        relation_id = record.value.get("id")
        if isinstance(relation_id, str) and entity_shard(relation_id, 4) != shard_1 + shard_2:
            report.add(record.location, "visual relation bucket path does not match SHA-256(id)")
    for path, values in relation_files.items():
        if values != sorted(values, key=lambda value: value.get("id", "")):
            report.add(path, "visual relation bucket is not sorted by id")
        expected = "".join(f"{compact_json(value)}\n" for value in values)
        try:
            if read_utf8(path) != expected:
                report.add(path, "visual relation JSONL is not canonical compact JSON")
        except DataError as exc:
            report.add(path, str(exc))
    for path in sorted((root / "data" / "relations" / "visual").glob("*/*.jsonl")):
        if path.stat().st_size == 0:
            report.add(path, "empty visual relation bucket files are forbidden")


def _check_identity_and_integrity(
    dataset: dict[str, Any],
    records: RepositoryRecords,
    valid_locations: set[str],
    qualifications: dict[str, dict[str, Any]],
    concepts_by_id: dict[str, dict[str, Any]],
    report: Report,
) -> None:
    try:
        namespace = uuid.UUID(dataset["id_namespace"])
    except (KeyError, ValueError, TypeError):
        return
    expected_relation_namespace = uuid.uuid5(namespace, "visual-relations")
    try:
        relation_namespace = uuid.UUID(dataset["visual_relation_namespace"])
        if relation_namespace != expected_relation_namespace:
            report.add(
                "dataset.json",
                f"visual_relation_namespace mismatch; expected {expected_relation_namespace}",
            )
    except (KeyError, ValueError, TypeError):
        relation_namespace = expected_relation_namespace

    primary = records.collections + records.emojis + records.memberships
    ids: dict[str, LocatedRecord] = {}
    native_keys: dict[tuple[Any, ...], LocatedRecord] = {}
    for record in primary:
        value = record.value
        entity_id = value.get("id")
        if isinstance(entity_id, str):
            if entity_id in ids:
                report.add(
                    record.location,
                    f"duplicate internal ID; first seen at {ids[entity_id].location}",
                )
            else:
                ids[entity_id] = record
        if record.location in valid_locations:
            try:
                expected = expected_entity_id(value, namespace)
                if entity_id != expected:
                    report.add(record.location, f"internal ID mismatch; expected {expected}")
            except (KeyError, TypeError, DataError) as exc:
                report.add(record.location, f"cannot derive internal ID: {exc}")
        if value.get("entity_type") in {"collection", "emoji"}:
            key = (
                value.get("entity_type"),
                value.get("platform"),
                value.get("native_namespace"),
                value.get("scope_id"),
                value.get("native_id"),
                value.get("identity_epoch"),
            )
            if key in native_keys:
                report.add(
                    record.location,
                    f"duplicate native identity; first seen at {native_keys[key].location}",
                )
            else:
                native_keys[key] = record

    for record in records.emojis:
        emoji = record.value
        concept_ids = emoji.get("concept_ids")
        if not isinstance(concept_ids, list):
            continue
        if concept_ids != sorted(concept_ids, key=str.encode):
            report.add(record.location, "concept_ids must be bytewise sorted")
        for concept_id in concept_ids:
            concept = concepts_by_id.get(concept_id) if isinstance(concept_id, str) else None
            if concept is None:
                report.add(record.location, f"unknown concept_id: {concept_id!r}")
            elif (
                emoji.get("availability", {}).get("status") == "active"
                and concept.get("status") != "active"
            ):
                report.add(record.location, f"active emoji uses inactive concept: {concept_id!r}")
        if (
            emoji.get("availability", {}).get("status") == "active"
            and emoji.get("concept_mapping_status") != "complete"
        ):
            report.add(record.location, "active emoji requires complete concept mapping")

    collections = {record.value.get("id"): record for record in records.collections}
    emojis = {record.value.get("id"): record for record in records.emojis}
    pairs: dict[tuple[Any, Any], LocatedRecord] = {}
    active_positions: dict[Any, dict[Any, LocatedRecord]] = defaultdict(dict)
    active_by_collection: Counter[Any] = Counter()
    memberships_by_collection: dict[Any, list[LocatedRecord]] = defaultdict(list)
    for record in records.memberships:
        value = record.value
        collection_id, emoji_id = value.get("collection_id"), value.get("emoji_id")
        if collection_id not in collections:
            report.add(record.location, f"dangling collection_id: {collection_id}")
        if emoji_id not in emojis:
            report.add(record.location, f"dangling emoji_id: {emoji_id}")
        collection_record = collections.get(collection_id)
        emoji_record = emojis.get(emoji_id)
        if (
            collection_record
            and emoji_record
            and collection_record.value.get("platform") != emoji_record.value.get("platform")
        ):
            report.add(record.location, "collection and emoji platforms must match")
        pair = (collection_id, emoji_id)
        if pair in pairs:
            report.add(
                record.location,
                f"duplicate collection/emoji pair; first seen at {pairs[pair].location}",
            )
        else:
            pairs[pair] = record
        memberships_by_collection[collection_id].append(record)
        if value.get("status") == "active":
            active_by_collection[collection_id] += 1
            position = value.get("position")
            if position in active_positions[collection_id]:
                first_location = active_positions[collection_id][position].location
                report.add(
                    record.location,
                    f"duplicate active position; first seen at {first_location}",
                )
            else:
                active_positions[collection_id][position] = record

    for collection_id, collection_record in collections.items():
        collection = collection_record.value
        if collection.get("platform") not in dataset.get("platforms", []):
            report.add(collection_record.location, "platform is not declared in dataset.json")
        if collection.get("item_count") != active_by_collection[collection_id]:
            report.add(
                collection_record.location,
                f"item_count mismatch; expected {active_by_collection[collection_id]}",
            )
        telegram = collection.get("extensions", {}).get("telegram")
        if collection.get("platform") == "telegram" and isinstance(telegram, dict):
            if telegram.get("short_name") != collection.get("native_id"):
                report.add(collection_record.location, "Telegram short_name must equal native_id")
            expected_url = f"https://t.me/addemoji/{collection.get('native_id')}"
            if collection.get("canonical_url") != expected_url:
                report.add(
                    collection_record.location, f"Telegram canonical_url must equal {expected_url}"
                )
            fingerprint_members: list[dict[str, str]] = []
            for membership in memberships_by_collection[collection_id]:
                if membership.value.get("status") != "active":
                    continue
                emoji = emojis.get(membership.value.get("emoji_id"))
                extension = emoji.value.get("extensions", {}).get("telegram") if emoji else None
                if (
                    isinstance(extension, dict)
                    and isinstance(extension.get("custom_emoji_id"), str)
                    and isinstance(extension.get("file_unique_id"), str)
                ):
                    fingerprint_members.append(extension)
            try:
                expected = telegram_set_fingerprint(fingerprint_members)
                if telegram.get("set_fingerprint_sha256") != expected:
                    report.add(
                        collection_record.location,
                        f"Telegram set_fingerprint_sha256 mismatch; expected {expected}",
                    )
            except (KeyError, TypeError, DataError) as exc:
                report.add(
                    collection_record.location, f"cannot calculate Telegram fingerprint: {exc}"
                )

    for record in records.emojis:
        emoji = record.value
        if emoji.get("platform") not in dataset.get("platforms", []):
            report.add(record.location, "platform is not declared in dataset.json")
        extension = emoji.get("extensions", {}).get("telegram")
        if (
            emoji.get("platform") == "telegram"
            and isinstance(extension, dict)
            and extension.get("custom_emoji_id") != emoji.get("native_id")
        ):
            report.add(record.location, "Telegram custom_emoji_id must equal native_id")
        _check_media_and_provenance(emoji, record.location, report)
        _check_facets_and_fingerprints(emoji, dataset, record.location, report)
        _check_text_quality(emoji, record.location, report)
        _check_review_and_policy(emoji, record.location, report)
        provenance = emoji.get("provenance")
        review = emoji.get("review")
        if (
            isinstance(provenance, dict)
            and provenance.get("origin") in {"ai", "mixed"}
            and isinstance(review, dict)
            and review.get("status") != "approved"
        ):
            qualification_id = provenance.get("qualification_id")
            qualification = qualifications.get(qualification_id)
            if not qualification or not _qualification_matches(emoji, qualification, dataset):
                report.add(
                    record.location,
                    "blocking review reason unqualified-model: exact active qualification required",
                )

    live_ids = set(ids)
    target_ids: dict[Any, LocatedRecord] = {}
    for record in records.tombstones:
        target_id = record.value.get("target_id")
        if target_id in target_ids:
            report.add(
                record.location,
                f"duplicate target_id; first seen at {target_ids[target_id].location}",
            )
        else:
            target_ids[target_id] = record
        if target_id in live_ids:
            report.add(record.location, "tombstoned target still exists in public data")

    relation_ids: dict[str, LocatedRecord] = {}
    relation_keys: dict[tuple[Any, ...], LocatedRecord] = {}
    for record in records.visual_relations:
        relation = record.value
        relation_id = relation.get("id")
        if isinstance(relation_id, str):
            if relation_id in relation_ids:
                first_location = relation_ids[relation_id].location
                report.add(
                    record.location,
                    f"duplicate visual relation ID; first seen at {first_location}",
                )
            relation_ids[relation_id] = record
        try:
            expected_id = expected_visual_relation_id(relation, relation_namespace)
            if relation_id != expected_id:
                report.add(record.location, f"visual relation ID mismatch; expected {expected_id}")
        except (KeyError, TypeError, DataError) as exc:
            report.add(record.location, f"cannot derive visual relation ID: {exc}")

        subject_id = relation.get("subject_id")
        object_id = relation.get("object_id")
        subject = emojis.get(subject_id)
        object_ = emojis.get(object_id)
        if not subject:
            report.add(record.location, f"dangling visual relation subject_id: {subject_id}")
        if not object_:
            report.add(record.location, f"dangling visual relation object_id: {object_id}")
        relation_type = relation.get("relation_type")
        if relation_type in {"same-artwork", "not-duplicate", "related-series"} and (
            not isinstance(subject_id, str)
            or not isinstance(object_id, str)
            or subject_id >= object_id
        ):
            report.add(
                record.location,
                "symmetric visual relation requires subject_id < object_id",
            )
        evidence = relation.get("evidence")
        if isinstance(evidence, dict):
            signals = evidence.get("signals")
            if isinstance(signals, list) and signals != sorted(signals):
                report.add(record.location, "visual relation signals must be sorted")
            if subject:
                expected = media_digest(subject.value.get("media", []))
                if evidence.get("subject_media_digest") != expected:
                    report.add(record.location, "stale visual relation subject_media_digest")
            if object_:
                expected = media_digest(object_.value.get("media", []))
                if evidence.get("object_media_digest") != expected:
                    report.add(record.location, "stale visual relation object_media_digest")
            pairs = evidence.get("media_pairs")
            if isinstance(pairs, list) and subject and object_:
                expected_pairs = sorted(
                    pairs,
                    key=lambda pair: (
                        (
                            str(pair.get("subject_role", "")),
                            str(pair.get("subject_variant_id", "")),
                            str(pair.get("object_role", "")),
                            str(pair.get("object_variant_id", "")),
                        )
                        if isinstance(pair, dict)
                        else ("", "", "", "")
                    ),
                )
                if pairs != expected_pairs:
                    report.add(record.location, "visual relation media_pairs must be sorted")
                subject_keys = {_media_key(item) for item in subject.value.get("media", [])}
                object_keys = {_media_key(item) for item in object_.value.get("media", [])}
                mapped_subject: list[tuple[Any, Any]] = []
                mapped_object: list[tuple[Any, Any]] = []
                for index, pair in enumerate(pairs):
                    if not isinstance(pair, dict):
                        continue
                    subject_key = pair.get("subject_role"), pair.get("subject_variant_id")
                    object_key = pair.get("object_role"), pair.get("object_variant_id")
                    mapped_subject.append(subject_key)
                    mapped_object.append(object_key)
                    if subject_key not in subject_keys:
                        report.add(record.location, f"evidence.media_pairs/{index} invalid subject")
                    if object_key not in object_keys:
                        report.add(record.location, f"evidence.media_pairs/{index} invalid object")
                if relation.get("scope") == "entity" and (
                    set(mapped_subject) != subject_keys
                    or set(mapped_object) != object_keys
                    or len(mapped_subject) != len(subject_keys)
                    or len(mapped_object) != len(object_keys)
                ):
                    report.add(
                        record.location,
                        "entity relation media_pairs must be a full one-to-one media mapping",
                    )
        review = relation.get("review")
        if isinstance(review, dict):
            try:
                expected_hash = reviewed_relation_sha256(relation)
                if review.get("reviewed_relation_sha256") != expected_hash:
                    report.add(
                        record.location,
                        f"reviewed_relation_sha256 mismatch; expected {expected_hash}",
                    )
            except (KeyError, TypeError, DataError) as exc:
                report.add(record.location, f"cannot calculate reviewed relation hash: {exc}")
        if subject and object_ and relation_type == "same-artwork":
            subject_review = subject.value.get("review", {}).get("status")
            object_review = object_.value.get("review", {}).get("status")
            if subject_review == object_review == "approved":
                left_text = {
                    item.get("value")
                    for item in subject.value.get("facets", {})
                    .get("text_content", {})
                    .get("items", [])
                    if isinstance(item, dict)
                }
                right_text = {
                    item.get("value")
                    for item in object_.value.get("facets", {})
                    .get("text_content", {})
                    .get("items", [])
                    if isinstance(item, dict)
                }
                if left_text != right_text:
                    report.add(
                        record.location,
                        "same-artwork is forbidden for approved records with different "
                        "literal text",
                    )
        key = (
            min(str(subject_id), str(object_id)),
            max(str(subject_id), str(object_id)),
            relation.get("scope"),
            tuple(
                sorted(
                    (
                        pair.get("subject_role"),
                        pair.get("subject_variant_id"),
                        pair.get("object_role"),
                        pair.get("object_variant_id"),
                    )
                    for pair in relation.get("evidence", {}).get("media_pairs", [])
                    if isinstance(pair, dict)
                )
            ),
            relation.get("identity_epoch"),
        )
        if key in relation_keys:
            report.add(
                record.location,
                f"duplicate visual relation decision; first seen at {relation_keys[key].location}",
            )
        relation_keys[key] = record


def _check_examples(
    root: Path,
    dataset: dict[str, Any],
    schema_by_type: dict[str, Any],
    registry: Registry[Any],
    report: Report,
) -> None:
    example_root = root / "examples"
    named = {
        "collection": example_root / "telegram" / "collection.json",
        "emoji": example_root / "telegram" / "emoji.json",
        "membership": example_root / "telegram" / "membership.json",
        "tombstone": example_root / "tombstone.json",
        "visual_relation": example_root / "visual-relation.json",
    }
    examples: dict[str, dict[str, Any]] = {}
    for entity_type, path in named.items():
        try:
            value = load_json(path)
            if isinstance(value, dict):
                examples[entity_type] = value
                _validate_schema(value, entity_type, str(path), schema_by_type, registry, report)
                _check_unicode(value, str(path), report)
            else:
                report.add(path, "example must be an object")
        except (OSError, DataError) as exc:
            report.add(path, str(exc))

    facet_example_root = example_root / "facets"
    try:
        namespace = uuid.UUID(dataset["id_namespace"])
    except (KeyError, TypeError, ValueError):
        namespace = None
    for path in sorted(facet_example_root.glob("*.json")):
        try:
            value = load_json(path)
            if not isinstance(value, dict):
                report.add(path, "facet example must be an object")
                continue
            _validate_schema(value, "emoji", str(path), schema_by_type, registry, report)
            _check_unicode(value, str(path), report)
            _check_facets_and_fingerprints(value, dataset, str(path), report)
            _check_media_and_provenance(value, str(path), report)
            _check_review_and_policy(value, str(path), report)
            if namespace is not None:
                expected = expected_entity_id(value, namespace)
                if value.get("id") != expected:
                    report.add(path, f"internal ID mismatch; expected {expected}")
        except (OSError, DataError, KeyError, TypeError) as exc:
            report.add(path, f"invalid facet example: {exc}")

    vector_path = example_root / "test-vectors.json"
    try:
        vectors = load_json(vector_path)
        namespace = uuid.UUID(vectors["namespace"])
        prefixes = {"collection": "mxc_", "emoji": "mxe_", "membership": "mxm_"}
        for index, vector in enumerate(vectors["uuid_v5"]):
            components = vector["components"]
            raw = "\0".join(components).encode("utf-8")
            location = f"{vector_path}:/uuid_v5/{index}"
            if raw.hex() != vector["nul_joined_utf8_hex"]:
                report.add(location, "NUL-joined UTF-8 bytes differ from the vector")
            expected = prefixes[vector["entity_type"]] + str(
                uuid.uuid5(namespace, raw.decode("utf-8"))
            )
            if expected != vector["expected_id"]:
                report.add(location, f"UUIDv5 mismatch; calculated {expected}")
        fingerprint = vectors["telegram_set_fingerprint"]
        fingerprint_bytes = jcs_bytes(
            sorted(
                fingerprint["members"],
                key=lambda item: (item["custom_emoji_id"], item["file_unique_id"]),
            )
        )
        if fingerprint_bytes.hex() != fingerprint["jcs_utf8_hex"]:
            report.add(vector_path, "Telegram fingerprint JCS bytes differ from vector")
        calculated = hashlib.sha256(fingerprint_bytes).hexdigest()
        if calculated != fingerprint["expected_sha256"]:
            report.add(vector_path, f"Telegram fingerprint mismatch; calculated {calculated}")
        digest = media_digest(vectors["media_digest"]["media"])
        if digest != vectors["media_digest"]["expected_sha256"]:
            report.add(vector_path, f"media_digest mismatch; calculated {digest}")
        if "emoji" in examples:
            review_hash = reviewed_content_sha256(examples["emoji"])
            if review_hash != vectors["reviewed_content"]["expected_sha256"]:
                report.add(vector_path, f"reviewed-content hash mismatch; calculated {review_hash}")
            _check_facets_and_fingerprints(examples["emoji"], dataset, str(named["emoji"]), report)
        visual_vector = vectors["visual_relation_uuid_v5"]
        relation = load_json(example_root / visual_vector["source"])
        relation_namespace = uuid.UUID(visual_vector["namespace"])
        calculated_id = expected_visual_relation_id(relation, relation_namespace)
        if calculated_id != visual_vector["expected_id"]:
            report.add(vector_path, f"visual relation UUIDv5 mismatch; calculated {calculated_id}")
        name_parts = [
            "visual-relation",
            min(relation["subject_id"], relation["object_id"]),
            max(relation["subject_id"], relation["object_id"]),
            relation["scope"],
            "",
            "",
            "",
            "",
            str(relation["identity_epoch"]),
        ]
        if "\0".join(name_parts).encode("utf-8").hex() != visual_vector["nul_joined_utf8_hex"]:
            report.add(vector_path, "visual relation UUIDv5 name bytes differ from vector")
        relation_hash = reviewed_relation_sha256(relation)
        if relation_hash != visual_vector["expected_reviewed_relation_sha256"]:
            report.add(vector_path, f"reviewed relation hash mismatch; calculated {relation_hash}")
        for index, phash in enumerate(vectors["phash64"]):
            try:
                padding = "=" * ((4 - len(phash["encoded"]) % 4) % 4)
                decoded = base64.b64decode(
                    phash["encoded"] + padding, altchars=b"-_", validate=True
                )
                if decoded.hex() != phash["decoded_hex"]:
                    report.add(vector_path, f"phash64/{index}: decoded bytes differ")
                if len(decoded) != phash["sample_count"] * 8:
                    report.add(vector_path, f"phash64/{index}: decoded length differs")
            except (KeyError, TypeError, ValueError, binascii.Error) as exc:
                report.add(vector_path, f"phash64/{index}: invalid vector: {exc}")
        group_vectors = vectors["duplicate_group_ids"]
        group_namespace = uuid.UUID(group_vectors["namespace"])
        group_cases = {
            "binary_media": (
                [
                    "duplicate-group-v1",
                    "binary-exact",
                    "media",
                    {"present": False},
                    group_vectors["binary_media"]["source_sha256"],
                    group_vectors["binary_media"]["byte_size"],
                ],
                {
                    "source_sha256": group_vectors["binary_media"]["source_sha256"],
                    "source_byte_size": group_vectors["binary_media"]["byte_size"],
                },
            ),
            "decoded_media": (
                [
                    "duplicate-group-v1",
                    "decoded-exact",
                    "media",
                    {
                        "present": True,
                        "value": group_vectors["decoded_media"]["decoded_profile_id"],
                    },
                    group_vectors["decoded_media"]["decoded_payload_sha256"],
                    {"present": False},
                ],
                {
                    "decoded_profile_id": group_vectors["decoded_media"]["decoded_profile_id"],
                    "decoded_payload_sha256": group_vectors["decoded_media"][
                        "decoded_payload_sha256"
                    ],
                },
            ),
            "binary_entity": (
                [
                    "duplicate-group-v1",
                    "binary-exact",
                    "entity",
                    {"present": False},
                    group_vectors["binary_entity"]["media_set_root_sha256"],
                    {"present": False},
                ],
                {"media_set_root_sha256": group_vectors["binary_entity"]["media_set_root_sha256"]},
            ),
            "decoded_entity": (
                [
                    "duplicate-group-v1",
                    "decoded-exact",
                    "entity",
                    {
                        "present": True,
                        "value": group_vectors["decoded_entity"]["decoded_profile_id"],
                    },
                    group_vectors["decoded_entity"]["media_set_root_sha256"],
                    {"present": False},
                ],
                {
                    "decoded_profile_id": group_vectors["decoded_entity"]["decoded_profile_id"],
                    "media_set_root_sha256": group_vectors["decoded_entity"][
                        "media_set_root_sha256"
                    ],
                },
            ),
            "reviewed_same_artwork": (
                [
                    "duplicate-group-v1",
                    "reviewed-same-artwork",
                    "entity",
                    {"present": False},
                    {"present": False},
                    sorted(group_vectors["reviewed_same_artwork"]["members"]),
                ],
                {"members": group_vectors["reviewed_same_artwork"]["members"]},
            ),
        }
        for key, (preimage, arguments) in group_cases.items():
            vector = group_vectors[key]
            if jcs_bytes(preimage).hex() != vector["preimage_jcs_utf8_hex"]:
                report.add(vector_path, f"{key} duplicate group preimage bytes differ")
            calculated = duplicate_group_id(
                group_namespace,
                group_type=vector["group_type"],
                scope=vector["scope"],
                **arguments,
            )
            if calculated != vector["expected_id"]:
                report.add(vector_path, f"{key} duplicate group ID mismatch; {calculated}")
        reviewed = group_vectors["reviewed_same_artwork"]
        calculated = reviewed_same_artwork_group_id(group_namespace, reviewed["members"])
        if calculated != reviewed["expected_id"]:
            report.add(vector_path, f"reviewed group ID mismatch; calculated {calculated}")
    except (OSError, DataError, KeyError, TypeError, ValueError) as exc:
        report.add(vector_path, f"invalid normative vectors: {exc}")

    if all(key in examples for key in ("collection", "emoji", "membership")):
        collection = examples["collection"]
        emoji = examples["emoji"]
        membership = examples["membership"]
        if membership.get("collection_id") != collection.get("id"):
            report.add(named["membership"], "example collection reference is inconsistent")
        if membership.get("emoji_id") != emoji.get("id"):
            report.add(named["membership"], "example emoji reference is inconsistent")
        extension = emoji.get("extensions", {}).get("telegram", {})
        fingerprint = telegram_set_fingerprint([extension])
        actual = collection.get("extensions", {}).get("telegram", {}).get("set_fingerprint_sha256")
        if fingerprint != actual:
            report.add(named["collection"], "example Telegram fingerprint is inconsistent")


def _git_ls_files(
    root: Path,
    *,
    include_untracked: bool,
) -> tuple[PurePosixPath, ...] | None:
    arguments = [
        "git",
        "-c",
        f"safe.directory={root}",
        "-C",
        str(root),
        "ls-files",
        "--cached",
    ]
    if include_untracked:
        arguments.extend(("--others", "--exclude-standard"))
    arguments.extend(("-z", "--", "."))
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            check=False,
            shell=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        return tuple(
            PurePosixPath(value.decode("utf-8")) for value in result.stdout.split(b"\0") if value
        )
    except UnicodeDecodeError:
        return None


def _git_index_entries(root: Path) -> tuple[tuple[str, PurePosixPath], ...] | None:
    arguments = [
        "git",
        "-c",
        f"safe.directory={root}",
        "-C",
        str(root),
        "ls-files",
        "--stage",
        "-z",
        "--",
        ".",
    ]
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            check=False,
            shell=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    entries: list[tuple[str, PurePosixPath]] = []
    try:
        for record in result.stdout.split(b"\0"):
            if not record:
                continue
            metadata, encoded_path = record.split(b"\t", 1)
            mode = metadata.split(b" ", 1)[0].decode("ascii")
            relative = PurePosixPath(encoded_path.decode("utf-8"))
            if relative.is_absolute() or ".." in relative.parts:
                return None
            entries.append((mode, relative))
    except (UnicodeDecodeError, ValueError):
        return None
    return tuple(entries)


def _git_root_is_exact_worktree(root: Path) -> bool | None:
    arguments = [
        "git",
        "-c",
        f"safe.directory={root}",
        "-C",
        str(root),
        "rev-parse",
        "--show-toplevel",
    ]
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            check=False,
            shell=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        top_level = Path(result.stdout.decode("utf-8").rstrip("\r\n")).resolve()
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return os.path.normcase(str(top_level)) == os.path.normcase(str(root))


def _check_tracked_transaction_artifacts(root: Path, report: Report) -> bool:
    entries = _git_index_entries(root)
    if entries is None:
        git_marker = root / ".git"
        if git_marker.exists() or git_marker.is_symlink():
            report.add(root, "Git index policy could not be checked safely")
            return True
        return False
    rejected = False
    for mode, relative in entries:
        if relative.parts and relative.parts[0].casefold() in LOCAL_TRANSACTION_TREES:
            report.add(relative, "tracked runtime transaction artifact is forbidden")
            rejected = True
        if mode == "120000":
            report.add(relative, "tracked symbolic links are forbidden in the data repository")
            rejected = True
        elif mode == "160000":
            report.add(relative, "tracked Git submodules are forbidden in the data repository")
            rejected = True
    return rejected


def _is_link_or_reparse_point(path: Path) -> bool:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode):
        return True
    attributes = int(getattr(metadata, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse_flag)


def _walk_repository_without_ignored_trees(
    root: Path,
) -> tuple[list[Path], list[Path], list[Path], list[OSError]]:
    candidates: list[Path] = []
    nested_git_markers: list[Path] = []
    structural_entries: list[Path] = []
    walk_errors: list[OSError] = []
    ignored = {name.casefold() for name in IGNORED_TREES}
    for current, directory_names, file_names in os.walk(
        root,
        topdown=True,
        onerror=walk_errors.append,
        followlinks=False,
    ):
        directory = Path(current)
        at_root = directory == root
        retained: list[str] = []
        for name in directory_names:
            path = directory / name
            if name.casefold() == ".git":
                if not at_root:
                    nested_git_markers.append(path)
                continue
            try:
                if _is_link_or_reparse_point(path):
                    structural_entries.append(path)
                    continue
            except OSError as exc:
                walk_errors.append(exc)
                continue
            if name.casefold() in ignored:
                continue
            candidates.append(path)
            retained.append(name)
        directory_names[:] = retained
        for name in file_names:
            path = directory / name
            if name.casefold() == ".git":
                if not at_root:
                    nested_git_markers.append(path)
                continue
            try:
                if _is_link_or_reparse_point(path):
                    structural_entries.append(path)
                    continue
            except OSError as exc:
                walk_errors.append(exc)
                continue
            candidates.append(path)
    return candidates, nested_git_markers, structural_entries, walk_errors


def _check_repository_file_contents(path: Path, relative: PurePosixPath, report: Report) -> None:
    prefix = bytearray()
    tail = b""
    overlap = ""
    total_size = 0
    contains_nul = False
    contains_cr = False
    invalid_utf8 = False
    detected_secrets: set[str] = set()
    decoder = codecs.getincrementaldecoder("utf-8")("strict")

    def scan_text(text: str) -> None:
        nonlocal overlap
        window = overlap + text
        views = [window]
        if re.search(r"%[0-9A-Fa-f]{2}", window):
            with contextlib.suppress(UnicodeEncodeError, ValueError):
                views.append(unquote_to_bytes(window).decode("utf-8", errors="ignore"))
        decoded: list[str] = []
        for view in views:
            for match in BASE64_SECRET_CANDIDATE.finditer(view):
                candidate = match.group(0).encode("ascii")
                try:
                    padding = b"=" * ((4 - len(candidate) % 4) % 4)
                    value = base64.b64decode(candidate + padding, altchars=b"-_", validate=True)
                except (ValueError, binascii.Error):
                    continue
                if len(value) >= 16:
                    decoded.append(value.decode("utf-8", errors="ignore"))
        for name, pattern in SECRET_PATTERNS.items():
            if name not in detected_secrets and any(
                pattern.search(view) for view in (*views, *decoded)
            ):
                detected_secrets.add(name)
        overlap = window[-FILE_SCAN_OVERLAP:]

    try:
        with path.open("rb") as source:
            while True:
                chunk = source.read(FILE_SCAN_CHUNK_SIZE)
                if not chunk:
                    break
                total_size += len(chunk)
                if len(prefix) < FILE_SCAN_PREFIX_SIZE:
                    prefix.extend(chunk[: FILE_SCAN_PREFIX_SIZE - len(prefix)])
                tail = (tail + chunk)[-2:]
                contains_nul = contains_nul or b"\0" in chunk
                contains_cr = contains_cr or b"\r" in chunk
                if not invalid_utf8:
                    try:
                        scan_text(decoder.decode(chunk, final=False))
                    except UnicodeDecodeError:
                        invalid_utf8 = True
        if not invalid_utf8:
            try:
                scan_text(decoder.decode(b"", final=True))
            except UnicodeDecodeError:
                invalid_utf8 = True
    except OSError as exc:
        report.add(relative, f"could not read repository file: {exc}")
        return

    header = bytes(prefix)
    if header.startswith(b"version https://git-lfs.github.com/spec/v1"):
        report.add(relative, "Git LFS pointer is forbidden")
    is_webp = header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    if contains_nul or is_webp or any(header.startswith(magic) for magic in MEDIA_MAGIC):
        report.add(relative, "binary/media file is forbidden")
    if header.startswith(b"\xef\xbb\xbf"):
        report.add(relative, "UTF-8 BOM is forbidden")
    if contains_cr:
        report.add(relative, "CR/CRLF line endings are forbidden")
    is_canonical_analysis_profile = (
        relative.parts[:1] == ("analysis-profiles",) and relative.name in ANALYSIS_PROFILE_FILES
    )
    if total_size and not tail.endswith(b"\n") and not is_canonical_analysis_profile:
        report.add(relative, "text file must end with exactly one LF")
    elif not is_canonical_analysis_profile and tail.endswith(b"\n\n"):
        report.add(relative, "text file has more than one final LF")
    if invalid_utf8:
        report.add(relative, "non-UTF-8/binary file is forbidden")
    for name in sorted(detected_secrets):
        report.add(relative, f"possible {name} detected")


def _check_repository_files(root: Path, report: Report) -> None:
    tracked = _git_ls_files(root, include_untracked=False)
    listed = _git_ls_files(root, include_untracked=True)
    exact_worktree = _git_root_is_exact_worktree(root)
    walked, nested_git_markers, structural_entries, walk_errors = (
        _walk_repository_without_ignored_trees(root)
    )
    for marker in sorted(nested_git_markers):
        report.add(
            PurePosixPath(marker.relative_to(root).as_posix()),
            "nested Git repository marker is forbidden",
        )
    for entry in sorted(structural_entries):
        report.add(
            PurePosixPath(entry.relative_to(root).as_posix()),
            "symbolic links and filesystem reparse points are forbidden",
        )
    structural_relatives = {
        PurePosixPath(entry.relative_to(root).as_posix()) for entry in structural_entries
    }
    for error in walk_errors:
        report.add(error.filename or root, f"repository walk failed: {error}")
    if exact_worktree is None and ((root / ".git").exists() or (root / ".git").is_symlink()):
        report.add(root, "Git repository root could not be checked safely")

    tracked_set = set(tracked or ())
    if exact_worktree is True and listed is not None and tracked is not None:
        relatives = set(listed)
    else:
        relatives = {PurePosixPath(path.relative_to(root).as_posix()) for path in walked}
    relatives.update(tracked_set)
    ignored = {name.casefold() for name in IGNORED_TREES}
    for relative in sorted(relatives, key=str):
        if any(
            relative == structural or structural in relative.parents
            for structural in structural_relatives
        ):
            continue
        path = root.joinpath(*relative.parts)
        in_ignored_tree = any(part.casefold() in ignored for part in relative.parts)
        if relative in tracked_set and in_ignored_tree:
            report.add(relative, "tracked ignored/runtime/generated artifact is forbidden")
            continue
        if in_ignored_tree:
            continue
        if path.is_symlink():
            report.add(relative, "symbolic links are forbidden in the data repository")
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() in BANNED_MEDIA_SUFFIXES:
            report.add(relative, "binary media/archive extension is forbidden")
        if path.name in {".env", ".env.local", "credentials.json", "secrets.json"}:
            report.add(relative, "credential file is forbidden")
        lowered_parts = [part.lower() for part in relative.parts]
        forbidden_markers = ("candidate", "preview", "comparison", "lsh", "decoded")
        normative_marker_paths = {
            "analysis-profiles/concept-candidates-v1.json",
            "schemas/distribution/v1/cli-resolution-candidate.schema.json",
            "schemas/distribution/v1/concept-candidate-profile.schema.json",
        }
        if relative.as_posix() not in normative_marker_paths and any(
            any(marker in part for marker in forbidden_markers) for part in lowered_parts
        ):
            report.add(relative, "local dedupe candidate/preview/index artifact is forbidden")
        _check_repository_file_contents(path, relative, report)


def _check_deterministic_build(root: Path, report: Report) -> None:
    try:
        if __package__:
            from .build_index import build_index
        else:
            from build_index import build_index  # type: ignore[no-redef]
            from validate_distribution import validate_distribution  # type: ignore[no-redef]

        if __package__:
            from .validate_distribution import validate_distribution

        with tempfile.TemporaryDirectory(prefix="mojilex-index-check-") as temporary:
            base = Path(temporary)
            first = base / "first"
            second = base / "second"
            fixed_revision = "0" * 40
            build_args = {
                "revision": fixed_revision,
                "snapshot_id": "data-2026.09.11.1",
                "source_date_epoch": 1789171199,
            }
            build_index(root, first, **build_args)
            build_index(root, second, **build_args)
            first_files = {
                path.relative_to(first): path.read_bytes()
                for path in first.rglob("*")
                if path.is_file()
            }
            second_files = {
                path.relative_to(second): path.read_bytes()
                for path in second.rglob("*")
                if path.is_file()
            }
            if first_files != second_files:
                report.add(root, "build-index is not byte-for-byte deterministic")
            distribution = validate_distribution(root, first)
            for error in distribution.errors:
                report.add(root, f"distribution conformance: {error}")
    except Exception as exc:
        report.add(root, f"build-index check failed: {exc}")


def validate_repository(
    root: Path, *, include_examples: bool = True, check_build: bool = True
) -> Report:
    root = root.resolve()
    report = Report()
    if _check_tracked_transaction_artifacts(root, report):
        return report
    schemas, schema_by_type, registry = _schema_environment(root, report)

    dataset: dict[str, Any] = {}
    try:
        loaded = load_json(root / "dataset.json")
        if isinstance(loaded, dict):
            dataset = loaded
            _validate_schema(
                dataset, "dataset", str(root / "dataset.json"), schema_by_type, registry, report
            )
            _check_unicode(dataset, str(root / "dataset.json"), report)
        else:
            report.add(root / "dataset.json", "manifest must be an object")
    except (OSError, DataError) as exc:
        report.add(root / "dataset.json", str(exc))

    _validate_analysis_profiles(root, dataset, schemas, registry, report)

    _, qualifications, concepts_by_id = _load_contract_registries(
        root, dataset, schemas, registry, report
    )

    try:
        records = discover_records(root)
    except (OSError, DataError) as exc:
        report.add(root, str(exc))
        records = RepositoryRecords([], [], [], [])

    valid_locations = _validate_record_schemas(records, schema_by_type, registry, report)
    _check_paths_and_canonical(root, records, report)
    _check_identity_and_integrity(
        dataset,
        records,
        valid_locations,
        qualifications,
        concepts_by_id,
        report,
    )
    if include_examples:
        _check_examples(root, dataset, schema_by_type, registry, report)
    _check_repository_files(root, report)
    if check_build:
        _check_deterministic_build(root, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a MojiLex data repository offline")
    parser.add_argument("root", nargs="?", default=".", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="accepted for CLI compatibility; all checks are strict by default",
    )
    parser.add_argument(
        "--skip-examples", action="store_true", help="skip normative example/test-vector checks"
    )
    parser.add_argument(
        "--skip-build-check", action="store_true", help="skip the double build-index comparison"
    )
    args = parser.parse_args(argv)
    report = validate_repository(
        args.root,
        include_examples=not args.skip_examples,
        check_build=not args.skip_build_check,
    )
    if report.errors:
        print(f"validation failed with {len(report.errors)} error(s):", file=sys.stderr)
        for error in report.errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("MojiLex dataset validation passed (offline, strict).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
