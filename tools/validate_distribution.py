#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

if __package__:
    from .common import DataError, compact_json, jcs_bytes, jcs_sha256, load_json, parse_json
    from .spec003_build import (
        CANONICAL_DISTRIBUTION_SCHEMA_NAMES,
        DELEGATED_PROFILE_TYPES,
        DERIVED_SCHEMA_NAMES,
        MANIFEST_VERSION,
        PAYLOAD_NAMES,
        PROFILE_CONTRACT_SCHEMA_FILES,
        PROFILE_FILES,
        REQUIRED_FEATURES,
        _collection_facets,
        _eligible_review,
        _media_set_root,
        _members_root,
        _present,
        _rights_summary,
        _search_record,
        duplicate_group_id,
        effective_sort_key,
        state_root,
        table_root,
    )
else:
    from common import (  # type: ignore[no-redef]
        DataError,
        compact_json,
        jcs_bytes,
        jcs_sha256,
        load_json,
        parse_json,
    )
    from spec003_build import (  # type: ignore[no-redef]
        CANONICAL_DISTRIBUTION_SCHEMA_NAMES,
        DELEGATED_PROFILE_TYPES,
        DERIVED_SCHEMA_NAMES,
        MANIFEST_VERSION,
        PAYLOAD_NAMES,
        PROFILE_CONTRACT_SCHEMA_FILES,
        PROFILE_FILES,
        REQUIRED_FEATURES,
        _collection_facets,
        _eligible_review,
        _media_set_root,
        _members_root,
        _present,
        _rights_summary,
        _search_record,
        duplicate_group_id,
        effective_sort_key,
        state_root,
        table_root,
    )


@dataclass
class DistributionReport:
    errors: list[str] = field(default_factory=list)

    def add(self, location: str | Path, message: str) -> None:
        self.errors.append(f"{location}: {message}")


MAX_MANIFEST_BYTES = 64 * 1024 * 1024
MAX_RESOURCE_BYTES = 8 * 1024 * 1024


def _safe_release_path(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        bool(value)
        and not path.is_absolute()
        and "\\" not in value
        and "%" not in value
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _is_link(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def _release_file(root: Path, relative: str) -> Path:
    if not _safe_release_path(relative):
        raise DataError("unsafe release path")
    current = root
    for part in PurePosixPath(relative).parts:
        current /= part
        if _is_link(current):
            raise DataError(f"release path contains a link or reparse point: {relative}")
    resolved = current.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise DataError(f"release path is not a regular in-root file: {relative}")
    return resolved


def _schema_reference_targets(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str) and not reference.startswith("#"):
            target = reference.split("#", 1)[0]
            if target:
                result.add(target)
        for child in value.values():
            result.update(_schema_reference_targets(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_schema_reference_targets(child))
    return result


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


def _validate_profile_contract(
    *,
    profile_field: str,
    document: Any,
    payload: bytes,
    schemas: dict[str, Any],
    registry: Registry[Any],
    resource_payloads: dict[str, bytes],
    location: str,
    report: DistributionReport,
) -> None:
    if not isinstance(document, dict):
        report.add(location, "analysis profile is not an object")
        return
    try:
        canonical = jcs_bytes(document)
    except (DataError, TypeError, ValueError) as exc:
        report.add(location, f"analysis profile cannot be canonicalized: {exc}")
        return
    if payload != canonical:
        report.add(location, "analysis profile resource is not exact JCS bytes")
    if profile_field == "concept_candidates":
        return

    profile_type = DELEGATED_PROFILE_TYPES.get(profile_field)
    contract_filename = PROFILE_CONTRACT_SCHEMA_FILES.get(profile_field)
    if profile_type is None or contract_filename is None:
        report.add(location, "delegated profile class is not allowlisted")
        return
    contract_ref = f"mlx://schemas/distribution/v1/{contract_filename}"
    if document.get("profile_type") != profile_type:
        report.add(location, "delegated profile_type does not match manifest selector")
    if document.get("contract_schema_ref") != contract_ref:
        report.add(location, "delegated contract_schema_ref is not the class contract")

    contract_payload = resource_payloads.get(contract_ref)
    contract = schemas.get(contract_ref)
    if contract_payload is None or not isinstance(contract, dict):
        report.add(location, "delegated contract schema is not an embedded physical resource")
        return
    contract_sha256 = hashlib.sha256(contract_payload).hexdigest()
    if document.get("contract_schema_sha256") != contract_sha256:
        report.add(location, "delegated contract_schema_sha256 mismatch")
    if contract.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        report.add(location, "delegated contract is not Draft 2020-12")
    if contract.get("$id") != contract_ref:
        report.add(location, "delegated contract $id mismatch")
    if contract.get("unevaluatedProperties") is not False:
        report.add(location, "delegated contract must close body with unevaluatedProperties:false")
    for reference in _schema_references(contract):
        if not re.fullmatch(r"#/\$defs/[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*", reference):
            report.add(location, f"delegated contract has forbidden $ref {reference!r}")
    try:
        for message in _schema_errors(document.get("body"), contract_ref, schemas, registry):
            report.add(location, f"delegated body contract: {message}")
    except Exception as exc:  # noqa: BLE001 - fail closed on referenced contract
        report.add(location, f"delegated body contract resolution failed: {exc}")


def _schema_scope(relative: str) -> str:
    path = PurePosixPath(relative)
    if path.parts[:2] == ("schemas", "v1"):
        return "canonical"
    if path.name in DERIVED_SCHEMA_NAMES:
        return "derived"
    if path.name in CANONICAL_DISTRIBUTION_SCHEMA_NAMES:
        return "canonical"
    return "transport"


def _schemas(root: Path, report: DistributionReport) -> tuple[dict[str, Any], Registry[Any]]:
    schemas: dict[str, Any] = {}
    registry: Registry[Any] = Registry()
    for path in sorted(root.glob("schemas/**/*.json")):
        try:
            schema = load_json(path)
            Draft202012Validator.check_schema(schema)
            uri = schema["$id"]
            if uri in schemas:
                raise DataError(f"duplicate schema $id {uri!r}")
            schemas[uri] = schema
            registry = registry.with_resource(uri, Resource.from_contents(schema))
        except Exception as exc:  # noqa: BLE001 - aggregate all contract failures
            report.add(path, f"invalid schema resource: {exc}")
    return schemas, registry


def _schema_errors(
    document: Any,
    schema_ref: str,
    schemas: dict[str, Any],
    registry: Registry[Any],
) -> list[str]:
    schema = schemas.get(schema_ref)
    if schema is None:
        return [f"unresolved schema_ref {schema_ref!r}"]
    validator = Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
    return [error.message for error in validator.iter_errors(document)]


def _read_jsonl(path: Path, report: DistributionReport) -> list[dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        report.add(path, f"cannot read artifact: {exc}")
        return []
    if raw and not raw.endswith(b"\n"):
        report.add(path, "JSONL payload lacks final LF")
    if b"\r" in raw or raw.startswith(b"\xef\xbb\xbf"):
        report.add(path, "JSONL must be UTF-8 without BOM/CR")
    records: list[dict[str, Any]] = []
    for index, line in enumerate(raw.splitlines(keepends=True), 1):
        if len(line) > 1024 * 1024:
            report.add(f"{path}:{index}", "JSONL line exceeds 1 MiB")
        if not line.endswith(b"\n"):
            continue
        try:
            value = parse_json(line[:-1].decode("utf-8"), source=f"{path}:{index}")
            if not isinstance(value, dict):
                raise DataError("JSONL row is not an object")
            if line != compact_json(value).encode("utf-8") + b"\n":
                report.add(f"{path}:{index}", "row is not in canonical compact formatter")
            records.append(value)
        except (UnicodeDecodeError, DataError) as exc:
            report.add(f"{path}:{index}", f"invalid JSONL row: {exc}")
    return records


def _manifest_pointer(manifest: dict[str, Any], pointer: str) -> tuple[bool, Any]:
    current: Any = manifest
    for raw in pointer[1:].split("/"):
        part = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _build_input(manifest: dict[str, Any]) -> dict[str, Any]:
    build = manifest["build"]
    return {
        "build_input_profile_id": "release-build-input-v1",
        "manifest_header": {
            key: manifest[key]
            for key in (
                "manifest_version",
                "dataset",
                "snapshot_id",
                "schema_version",
                "layout_profile",
                "trust_stage",
                "minimum_reader_version",
                "required_features",
                "git",
                "languages",
                "storage",
            )
        },
        "selectors": {"profiles": manifest["profiles"], "policies": manifest["policies"]},
        "lineage": {
            "previous_snapshot": _present(
                manifest.get("previous_snapshot"), exists="previous_snapshot" in manifest
            ),
            "change_set_batch": _present(
                manifest.get("change_set_batch"), exists="change_set_batch" in manifest
            ),
            "migration_inputs_root_sha256": build["migration_inputs_root_sha256"],
        },
        "builder": {
            key: build[key]
            for key in (
                "tool",
                "tool_version",
                "tool_repository",
                "tool_commit",
                "dependency_lock_sha256",
                "distribution_profile",
                "parameters",
                "parameters_sha256",
                "evidence_inputs_root_sha256",
                "source_date_epoch",
            )
        },
    }


def _selector_entries(manifest: dict[str, Any]) -> list[tuple[str, str, str, dict[str, Any]]]:
    return [
        *(
            ("profile", key, value["root_scope"], value)
            for key, value in manifest["profiles"].items()
        ),
        *(
            ("policy", key, value["root_scope"], value)
            for key, value in manifest["policies"].items()
        ),
    ]


def _validate_derived_from(
    descriptor: dict[str, Any],
    manifest: dict[str, Any],
    descriptors: dict[str, dict[str, Any]],
    report: DistributionReport,
) -> None:
    dependency = descriptor.get("derived_from")
    if not isinstance(dependency, dict):
        report.add(
            descriptor.get("logical_name", "artifact"), "derived artifact lacks derived_from"
        )
        return
    if dependency.get("source_canonical_state_root_sha256") != manifest.get(
        "canonical_state_root_sha256"
    ):
        report.add(descriptor["logical_name"], "derived_from canonical root mismatch")
    for item in dependency.get("manifest_inputs", []):
        exists, value = _manifest_pointer(manifest, item.get("manifest_pointer", ""))
        if not exists or jcs_sha256(value) != item.get("value_sha256"):
            report.add(descriptor["logical_name"], "derived_from manifest input mismatch")
    for item in dependency.get("selectors", []):
        exists, value = _manifest_pointer(manifest, item.get("manifest_pointer", ""))
        if not exists or jcs_sha256(value) != item.get("selector_value_sha256"):
            report.add(descriptor["logical_name"], "derived_from selector mismatch")
    for item in dependency.get("derived_artifacts", []):
        source = descriptors.get(item.get("logical_name"))
        if source is None:
            report.add(descriptor["logical_name"], "derived_from artifact is missing")
            continue
        is_recordset = source.get("content_model") == "recordset-jsonl"
        expected_kind = "table-root" if is_recordset else "payload"
        expected_hash = source.get("table_root_sha256" if is_recordset else "payload_sha256")
        if item.get("digest_kind") != expected_kind or item.get("sha256") != expected_hash:
            report.add(descriptor["logical_name"], "derived_from artifact digest mismatch")

    logical_name = descriptor.get("logical_name")
    contracts: dict[str, tuple[list[str], list[str], list[str]]] = {
        "emojis-active": (
            ["/build/source_date_epoch"],
            ["/policies/platform_profiles", "/policies/rights_profiles"],
            [],
        ),
        "duplicate-groups": (
            ["/build/source_date_epoch"],
            [
                "/policies/platform_profiles",
                "/policies/rights_profiles",
                "/profiles/dedupe",
            ],
            [],
        ),
        "duplicate-group-memberships": (
            ["/build/source_date_epoch"],
            [
                "/policies/platform_profiles",
                "/policies/rights_profiles",
                "/profiles/dedupe",
            ],
            [],
        ),
        "collection-facets": (
            ["/build/source_date_epoch"],
            [
                "/policies/platform_profiles",
                "/policies/rights_profiles",
                "/profiles/collection_dedupe",
            ],
            ["duplicate-groups", "duplicate-group-memberships"],
        ),
        "search-en": (
            ["/build/source_date_epoch", "/languages"],
            [
                "/policies/platform_profiles",
                "/policies/rights_profiles",
                "/profiles/lexical_search",
            ],
            ["duplicate-groups", "duplicate-group-memberships"],
        ),
        "search-ru": (
            ["/build/source_date_epoch", "/languages"],
            [
                "/policies/platform_profiles",
                "/policies/rights_profiles",
                "/profiles/lexical_search",
            ],
            ["duplicate-groups", "duplicate-group-memberships"],
        ),
    }
    contract = contracts.get(str(logical_name))
    if contract is None:
        report.add(str(logical_name), "derived artifact has no exact Stage-A dependency contract")
        return
    manifest_pointers, selector_pointers, artifact_names = contract
    expected_manifest_inputs = []
    for pointer in manifest_pointers:
        exists, value = _manifest_pointer(manifest, pointer)
        if exists:
            expected_manifest_inputs.append(
                {"manifest_pointer": pointer, "value_sha256": jcs_sha256(value)}
            )
    expected_selectors = []
    for pointer in selector_pointers:
        exists, value = _manifest_pointer(manifest, pointer)
        if exists:
            expected_selectors.append(
                {
                    "selector_kind": "profile" if pointer.startswith("/profiles/") else "policy",
                    "manifest_pointer": pointer,
                    "selector_value_sha256": jcs_sha256(value),
                }
            )
    expected_artifacts = []
    for name in artifact_names:
        source = descriptors.get(name)
        if source is None:
            continue
        is_recordset = source.get("content_model") == "recordset-jsonl"
        expected_artifacts.append(
            {
                "logical_name": name,
                "digest_kind": "table-root" if is_recordset else "payload",
                "sha256": source.get("table_root_sha256" if is_recordset else "payload_sha256"),
            }
        )
    expected_artifacts.sort(key=lambda item: item["logical_name"])
    expected = {
        "profile": "derived-from-v1",
        "source_canonical_state_root_sha256": manifest.get("canonical_state_root_sha256"),
        "manifest_inputs": expected_manifest_inputs,
        "selectors": expected_selectors,
        "derived_artifacts": expected_artifacts,
        "physical_input_roots": [],
    }
    if dependency != expected:
        report.add(
            str(logical_name),
            "derived_from is not the exact declared Stage-A dependency set",
        )


def _group_preimage(group: dict[str, Any], members: list[dict[str, Any]]) -> list[Any]:
    group_type = group["group_type"]
    key = group["group_key"]
    scope = key["scope"]
    if group_type == "binary-exact" and scope == "media":
        return [
            "duplicate-group-v1",
            group_type,
            scope,
            _present(exists=False),
            key["source_sha256"],
            key["byte_size"],
        ]
    if group_type == "binary-exact":
        return [
            "duplicate-group-v1",
            group_type,
            scope,
            _present(exists=False),
            key["media_set_root_sha256"],
            _present(exists=False),
        ]
    if group_type == "decoded-exact" and scope == "media":
        return [
            "duplicate-group-v1",
            group_type,
            scope,
            _present(key["decoded_profile_id"]),
            key["decoded_payload_sha256"],
            _present(exists=False),
        ]
    if group_type == "decoded-exact":
        return [
            "duplicate-group-v1",
            group_type,
            scope,
            _present(key["decoded_profile_id"]),
            key["media_set_root_sha256"],
            _present(exists=False),
        ]
    return [
        "duplicate-group-v1",
        "reviewed-same-artwork",
        "entity",
        _present(exists=False),
        _present(exists=False),
        sorted(item["emoji_id"] for item in members),
    ]


def _validate_groups(
    groups: list[dict[str, Any]],
    memberships: list[dict[str, Any]],
    emojis: dict[str, dict[str, Any]],
    namespace: uuid.UUID,
    report: DistributionReport,
) -> None:
    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for member in memberships:
        by_group[member.get("group_id", "")].append(member)
    summaries = {group.get("group_id"): group for group in groups}
    if set(by_group) != set(summaries):
        report.add("duplicate-groups", "summary/membership group ID coverage differs")
    for group_id, group in summaries.items():
        members = by_group.get(group_id, [])
        reviewed = group.get("group_type") == "reviewed-same-artwork"
        if group.get("member_count") != len(members):
            report.add(group_id or "duplicate-group", "member_count mismatch")
        if group.get("members_root_sha256") != _members_root(members, reviewed=reviewed):
            report.add(group_id or "duplicate-group", "members_root_sha256 mismatch")
        try:
            expected_id = duplicate_group_id(namespace, _group_preimage(group, members))
        except (KeyError, TypeError, ValueError) as exc:
            report.add(group_id or "duplicate-group", f"cannot reconstruct group ID: {exc}")
            continue
        if group_id != expected_id:
            report.add(group_id or "duplicate-group", f"group_id mismatch; expected {expected_id}")
        key = group.get("group_key", {})
        for member in members:
            emoji = emojis.get(member.get("emoji_id"))
            if emoji is None:
                report.add(group_id or "duplicate-group", "membership references missing emoji")
                continue
            if key.get("scope") == "entity" and not reviewed:
                expected_root, profile = _media_set_root(
                    emoji, decoded=group.get("group_type") == "decoded-exact"
                )
                if key.get("media_set_root_sha256") != expected_root:
                    report.add(group_id or "duplicate-group", "entity media-set root mismatch")
                if profile is not None and key.get("decoded_profile_id") != profile:
                    report.add(group_id or "duplicate-group", "decoded profile mismatch")
            elif key.get("scope") == "media":
                role = member.get("role", {}).get("value")
                variant = member.get("variant", {})
                variant_id = variant.get("value") if variant.get("present") else None
                media = next(
                    (
                        item
                        for item in emoji["media"]
                        if item["role"] == role and item.get("variant_id") == variant_id
                    ),
                    None,
                )
                if media is None:
                    report.add(group_id or "duplicate-group", "media membership does not resolve")
                    continue
                if group.get("group_type") == "binary-exact":
                    if media["sha256"] != key.get("source_sha256") or media["byte_size"] != key.get(
                        "byte_size"
                    ):
                        report.add(group_id or "duplicate-group", "binary media key mismatch")
                else:
                    fingerprints = {
                        (item["role"], item.get("variant_id")): item
                        for item in emoji["fingerprints"]["items"]
                    }
                    fingerprint = fingerprints[(role, variant_id)]
                    if emoji["fingerprints"]["profile"] != key.get(
                        "decoded_profile_id"
                    ) or fingerprint["decoded_payload_sha256"] != key.get("decoded_payload_sha256"):
                        report.add(group_id or "duplicate-group", "decoded media key mismatch")


def _validate_search(
    records: dict[str, list[dict[str, Any]]],
    manifest: dict[str, Any],
    source_dataset: dict[str, Any],
    report: DistributionReport,
) -> None:
    emojis = {item["id"]: item for item in records.get("emojis", [])}
    collections = {item["id"]: item for item in records.get("collections", [])}
    tombstoned = {item["target_id"] for item in records.get("tombstones", [])}
    platform_registry = load_json_from_records(records, "platform-profiles")
    rights_registry = load_json_from_records(records, "rights-profiles")
    if not platform_registry or not rights_registry:
        report.add("search", "normative platform/rights singleton missing")
        return
    platforms = {item["platform"]: item for item in platform_registry["entries"]}
    rights = {
        emoji_id: _rights_summary(
            emoji,
            platforms,
            rights_registry,
            manifest["build"]["source_date_epoch"],
        )
        for emoji_id, emoji in emojis.items()
    }
    active_collections = {
        item_id
        for item_id, item in collections.items()
        if item["availability"]["status"] == "active" and item_id not in tombstoned
    }
    eligible_pre_membership = {
        emoji_id
        for emoji_id, emoji in emojis.items()
        if emoji_id not in tombstoned
        and emoji["availability"]["status"] == "active"
        and _eligible_review(emoji)
        and rights[emoji_id]["distribution_status"] == "allowed"
    }
    collections_by_emoji: dict[str, list[str]] = defaultdict(list)
    for membership in records.get("memberships", []):
        if (
            membership["status"] == "active"
            and membership["collection_id"] in active_collections
            and membership["emoji_id"] in eligible_pre_membership
            and membership["id"] not in tombstoned
        ):
            collections_by_emoji[membership["emoji_id"]].append(membership["collection_id"])
    groups_by_emoji: dict[str, list[str]] = defaultdict(list)
    for member in records.get("duplicate-group-memberships", []):
        groups_by_emoji[member["emoji_id"]].append(member["group_id"])
    capabilities = {
        platform: sorted(
            [
                item["capability_id"]
                for item in profile["capabilities"]
                if item["status"] == "supported" and item["applies_to"] == "custom_emoji"
            ],
            key=str.encode,
        )
        for platform, profile in platforms.items()
    }
    expected_ids = set(collections_by_emoji)
    for language in manifest["languages"]["required"]:
        actual = records.get(f"search-{language}", [])
        if {row.get("emoji_id") for row in actual} != expected_ids:
            report.add(f"search-{language}", "eligible emoji coverage mismatch")
            continue
        for row in actual:
            emoji = emojis[row["emoji_id"]]
            expected = _search_record(
                emoji,
                language=language,
                collection_ids=collections_by_emoji[row["emoji_id"]],
                duplicate_group_ids=groups_by_emoji.get(row["emoji_id"], []),
                rights=rights[row["emoji_id"]],
                capability_ids=capabilities[emoji["platform"]],
            )
            if row != expected:
                report.add(f"search-{language}:{row['emoji_id']}", "projection mismatch")
            review = row.get("review", {})
            if (
                emoji["review"]["status"] == "unreviewed"
                and emoji["provenance"]["origin"] == "ai"
                and (
                    review.get("attested") is not False
                    or review.get("model_qualification_status") != "missing"
                    or review.get("generation_attestation_status") != "missing"
                )
            ):
                report.add(row["emoji_id"], "unattested AI row makes an unsafe qualification claim")


def load_json_from_records(records: dict[str, Any], logical_name: str) -> dict[str, Any] | None:
    value = records.get(logical_name)
    return value if isinstance(value, dict) else None


def validate_distribution(source_root: Path, distribution_root: Path) -> DistributionReport:
    report = DistributionReport()
    source_root = Path(os.path.abspath(source_root))
    distribution_root = Path(os.path.abspath(distribution_root))
    if _is_link(source_root):
        report.add(source_root, "source root must not be a link or reparse point")
        return report
    if _is_link(distribution_root):
        report.add(distribution_root, "distribution root must not be a link or reparse point")
        return report
    source_root = source_root.resolve()
    distribution_root = distribution_root.resolve()
    try:
        source_dataset = load_json(source_root / "dataset.json")
    except (OSError, DataError) as exc:
        report.add(source_root / "dataset.json", f"cannot read source dataset contract: {exc}")
        return report
    manifest_path = distribution_root / "manifest.json"
    try:
        if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            raise DataError("manifest exceeds the 64 MiB hard limit")
        manifest_raw = manifest_path.read_bytes()
        manifest = parse_json(manifest_raw.decode("utf-8"), source=str(manifest_path))
        if not isinstance(manifest, dict):
            raise DataError("manifest must be an object")
    except (OSError, UnicodeDecodeError, DataError) as exc:
        report.add(manifest_path, f"cannot parse manifest: {exc}")
        return report
    if manifest_raw != jcs_bytes(manifest):
        report.add(manifest_path, "manifest bytes are not exact JCS without trailing LF")

    source_schemas, source_registry = _schemas(source_root, report)
    manifest_schema = "mlx://schemas/distribution/v1/release-manifest.schema.json"
    try:
        manifest_schema_errors = _schema_errors(
            manifest, manifest_schema, source_schemas, source_registry
        )
        for message in manifest_schema_errors:
            report.add(manifest_path, message)
        if manifest_schema_errors:
            return report
    except Exception as exc:  # noqa: BLE001 - schema resolution must fail closed
        report.add(manifest_path, f"manifest schema resolution failed: {exc}")
        return report
    snapshot_match = re.fullmatch(
        r"data-([0-9]{4}\.[0-9]{2}\.[0-9]{2})\.[1-9][0-9]*",
        manifest["snapshot_id"],
    )
    try:
        if snapshot_match is None:
            raise ValueError("snapshot ID pattern mismatch")
        datetime.strptime(snapshot_match.group(1), "%Y.%m.%d")
    except ValueError:
        report.add(manifest_path, "snapshot_id contains an invalid UTC calendar date")
    required = {
        "artifacts",
        "resources",
        "bundles",
        "profiles",
        "policies",
        "build",
        "counts",
        "languages",
    }
    if not required <= set(manifest):
        return report
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        report.add(manifest_path, "unsupported manifest version")
    if manifest.get("required_features") != REQUIRED_FEATURES:
        report.add(manifest_path, "required_features are not the exact Stage-A set")
    if manifest.get("trust_stage") != "pre-enforcement":
        report.add(manifest_path, "Stage A must use trust_stage=pre-enforcement")
    if "signed-snapshots-v1" in manifest.get("required_features", []):
        report.add(manifest_path, "pre-enforcement manifest claims signed-snapshots-v1")
    if manifest.get("dataset") != source_dataset.get("dataset") or manifest.get(
        "schema_version"
    ) != source_dataset.get("schema_version"):
        report.add(manifest_path, "manifest dataset/schema identity differs from source")
    if manifest.get("layout_profile") != "monolith-v1":
        report.add(manifest_path, "Stage A builder supports only monolith-v1")
    if manifest.get("minimum_reader_version") != "0.2.0":
        report.add(manifest_path, "minimum_reader_version is not the Stage-A contract")
    if manifest.get("storage") != {"mode": "git-native"}:
        report.add(manifest_path, "Stage A storage must be exact git-native mode")
    if manifest.get("migrations") != [] or manifest.get("bundles") != []:
        report.add(manifest_path, "Stage A migrations and bundles must be empty")
    git_identity = manifest.get("git", {})
    build_identity = manifest.get("build", {})
    canonical_repository = source_dataset.get("canonical_repository")
    git_commit = git_identity.get("commit")
    if git_identity.get("repository") != canonical_repository:
        report.add(manifest_path, "Git repository identity differs from canonical source")
    if isinstance(git_commit, str):
        expected_object_format = "sha1" if len(git_commit) == 40 else "sha256"
        if git_identity.get("object_format") != expected_object_format:
            report.add(manifest_path, "Git object_format does not match commit length")
    if (
        build_identity.get("tool_repository") == canonical_repository
        and build_identity.get("tool_commit") != git_commit
    ):
        report.add(manifest_path, "in-repository builder commit differs from data commit")
    source_languages = sorted(source_dataset.get("default_languages", []), key=str.encode)
    language_contract = manifest.get("languages", {})
    if (
        language_contract.get("required") != ["en", "ru"]
        or language_contract.get("available") != source_languages
        or language_contract.get("canonicalization_profile") != "bcp47-v1"
        or language_contract.get("fallback_profile") != "language-fallback-v1"
    ):
        report.add(manifest_path, "language availability/fallback contract mismatch")

    artifacts = manifest["artifacts"]
    resources = manifest["resources"]
    if not isinstance(artifacts, list) or not isinstance(resources, list):
        report.add(manifest_path, "artifacts/resources must be arrays")
        return report
    if artifacts != sorted(
        artifacts, key=lambda item: (item["logical_name"].encode(), item["path"].encode())
    ):
        report.add(manifest_path, "artifact descriptors are not canonically sorted")
    if resources != sorted(resources, key=lambda item: item["uri"].encode()):
        report.add(manifest_path, "resource descriptors are not sorted by URI")

    declared_paths: dict[str, str] = {}
    for kind, descriptor in [
        *(("artifact", item) for item in artifacts),
        *(("resource", item) for item in resources if item.get("resource_kind") == "physical"),
    ]:
        path_text = descriptor.get("path")
        if not isinstance(path_text, str) or not _safe_release_path(path_text):
            report.add(kind, "descriptor has an unsafe or missing physical path")
            continue
        folded = path_text.casefold()
        prior = declared_paths.get(folded)
        if prior is not None:
            report.add(path_text, f"duplicate or case-colliding physical path with {prior!r}")
        else:
            declared_paths[folded] = path_text

    physical_resources: list[dict[str, Any]] = []
    resource_payloads: dict[str, bytes] = {}
    resource_uris: set[str] = set()
    embedded_schemas: dict[str, Any] = {}
    embedded_registry: Registry[Any] = Registry()
    actual_source_paths: set[str] = set()
    for resource in resources:
        uri = resource.get("uri")
        if not isinstance(uri, str) or uri in resource_uris:
            report.add("resources", "resource URI is missing or duplicated")
            continue
        resource_uris.add(uri)
        if resource.get("resource_kind") != "physical":
            continue
        physical_resources.append(resource)
        path_text = resource.get("path", "")
        if not isinstance(path_text, str) or not _safe_release_path(path_text):
            continue
        try:
            path = _release_file(distribution_root, path_text)
            if path.stat().st_size > MAX_RESOURCE_BYTES:
                raise DataError("standalone resource exceeds the 8 MiB hard limit")
            payload = path.read_bytes()
        except (OSError, DataError) as exc:
            report.add(uri, f"resource is unreadable or unsafe: {exc}")
            continue
        resource_payloads[uri] = payload
        digest = hashlib.sha256(payload).hexdigest()
        if resource.get("payload_sha256") != digest or resource.get("object_sha256") != digest:
            report.add(uri, "resource hash mismatch")
        if resource.get("uncompressed_byte_size") != len(payload) or resource.get(
            "object_byte_size"
        ) != len(payload):
            report.add(uri, "resource byte size mismatch")
        if resource.get("compression") != "none":
            report.add(uri, "Stage-A physical resource must be uncompressed")
        source_path = resource.get("source_path")
        if not isinstance(source_path, str) or not _safe_release_path(source_path):
            report.add(uri, "resource has an unsafe or missing source_path")
        else:
            if source_path in actual_source_paths:
                report.add(uri, "duplicate physical resource source_path")
            actual_source_paths.add(source_path)
            try:
                source_file = _release_file(source_root, source_path)
                if source_file.read_bytes() != payload:
                    report.add(uri, "resource bytes differ from canonical source_path")
            except (OSError, DataError) as exc:
                report.add(uri, f"canonical source_path cannot be verified: {exc}")
        if resource.get("media_type") == "application/schema+json":
            try:
                schema = parse_json(payload.decode("utf-8"), source=path_text)
                if not isinstance(schema, dict):
                    raise DataError("schema resource is not an object")
                Draft202012Validator.check_schema(schema)
                if schema.get("$id") != uri:
                    raise DataError("schema $id does not equal descriptor URI")
                if uri in embedded_schemas:
                    raise DataError("duplicate embedded schema URI")
                embedded_schemas[uri] = schema
                embedded_registry = embedded_registry.with_resource(
                    uri, Resource.from_contents(schema)
                )
            except Exception as exc:  # noqa: BLE001 - fail closed on schema bytes
                report.add(uri, f"invalid embedded schema resource: {exc}")

    for uri, schema in embedded_schemas.items():
        for target in sorted(_schema_reference_targets(schema)):
            if target not in embedded_schemas:
                report.add(uri, f"schema reference is not offline-resolved: {target}")
    if set(embedded_schemas) != set(source_schemas):
        report.add("resources", "embedded schema URI set differs from canonical source schemas")
    schemas, registry = embedded_schemas, embedded_registry
    try:
        for message in _schema_errors(manifest, manifest_schema, schemas, registry):
            report.add(manifest_path, f"embedded manifest schema: {message}")
    except Exception as exc:  # noqa: BLE001
        report.add(manifest_path, f"embedded manifest schema resolution failed: {exc}")

    expected_source_paths = {
        path.relative_to(source_root).as_posix()
        for path in [
            *source_root.glob("schemas/v1/**/*.json"),
            *source_root.glob("schemas/distribution/v1/*.json"),
            *source_root.glob("platforms/*.json"),
        ]
    }
    expected_source_paths.update(
        f"analysis-profiles/{filename}" for filename, _scope in PROFILE_FILES.values()
    )
    try:
        taxonomy_source = load_json(source_root / "taxonomy/v1/taxonomy.json")
        expected_source_paths.add("taxonomy/v1/taxonomy.json")
        for item in taxonomy_source["registries"]:
            parts = PurePosixPath(item["path"]).parts
            relative = (
                PurePosixPath(*parts[2:])
                if parts[:2] == ("taxonomy", "v1")
                else PurePosixPath(*parts)
            )
            expected_source_paths.add(f"taxonomy/v1/{relative.as_posix()}")
    except (OSError, KeyError, TypeError, DataError) as exc:
        report.add("resources", f"cannot determine taxonomy source bundle: {exc}")
    if actual_source_paths != expected_source_paths:
        missing = sorted(expected_source_paths - actual_source_paths)
        extra = sorted(actual_source_paths - expected_source_paths)
        report.add(
            "resources",
            f"physical source_path set mismatch (missing={missing}, extra={extra})",
        )

    dataset_profile_pins = {
        "color": ("color_profile", "color_profile_sha256"),
        "dedupe": ("dedupe_profile", "dedupe_profile_sha256"),
        "collection_dedupe": (
            "collection_dedupe_profile",
            "collection_dedupe_profile_sha256",
        ),
    }
    for profile_field, (id_field, sha_field) in dataset_profile_pins.items():
        selector = manifest.get("profiles", {}).get(profile_field, {})
        if selector.get("id") != source_dataset.get(id_field) or selector.get(
            "sha256"
        ) != source_dataset.get(sha_field):
            report.add(
                profile_field,
                "manifest selector differs from exact dataset profile pin",
            )

    descriptor_by_name: dict[str, dict[str, Any]] = {}
    resolved: dict[str, Any] = {}
    expected_files = {"manifest.json", "SHA256SUMS"}
    for descriptor in artifacts:
        logical_name = descriptor.get("logical_name", "<unknown>")
        if logical_name in descriptor_by_name:
            report.add(logical_name, "duplicate logical_name in monolith manifest")
        descriptor_by_name[logical_name] = descriptor
        path_text = descriptor.get("path", "")
        if not isinstance(path_text, str) or not _safe_release_path(path_text):
            report.add(logical_name, "unsafe artifact path")
            continue
        expected_files.add(path_text)
        try:
            path = _release_file(distribution_root, path_text)
            if (
                descriptor.get("content_model") == "singleton-json"
                and path.stat().st_size > MAX_RESOURCE_BYTES
            ):
                raise DataError("singleton JSON exceeds the 8 MiB hard limit")
            payload = path.read_bytes()
        except (OSError, DataError) as exc:
            report.add(path_text, f"artifact is unreadable or unsafe: {exc}")
            continue
        digest = hashlib.sha256(payload).hexdigest()
        if descriptor.get("payload_sha256") != digest or descriptor.get("object_sha256") != digest:
            report.add(path_text, "artifact payload/object hash mismatch")
        if descriptor.get("uncompressed_byte_size") != len(payload) or descriptor.get(
            "object_byte_size"
        ) != len(payload):
            report.add(path_text, "artifact byte size mismatch")
        if descriptor.get("compression") != "none":
            report.add(path_text, "Stage-A monolith artifact must be uncompressed")
        if descriptor.get("content_model") == "recordset-jsonl":
            rows = _read_jsonl(path, report)
            resolved[logical_name] = rows
            for index, row in enumerate(rows, 1):
                try:
                    messages = _schema_errors(row, descriptor["schema_ref"], schemas, registry)
                except Exception as exc:  # noqa: BLE001
                    messages = [f"row schema resolution failed: {exc}"]
                for message in messages:
                    report.add(f"{path_text}:{index}", message)
            primary_key = descriptor.get("primary_key", [])
            sort_key = descriptor.get("sort_key", [])
            if rows != sorted(rows, key=lambda row: effective_sort_key(row, sort_key, primary_key)):
                report.add(path_text, "rows do not follow canonical-sort-key-v1")
            try:
                root = table_root(rows, primary_key)
                if descriptor.get("table_root_sha256") != root:
                    report.add(path_text, "table_root_sha256 mismatch")
            except (KeyError, TypeError, ValueError) as exc:
                report.add(path_text, f"cannot recompute table root: {exc}")
            if descriptor.get("record_count") != len(rows) or descriptor.get(
                "logical_record_count"
            ) != len(rows):
                report.add(path_text, "record counts do not match physical rows")
        elif descriptor.get("content_model") == "singleton-json":
            try:
                body = parse_json(payload.decode("utf-8"), source=path_text)
                resolved[logical_name] = body
                if payload != jcs_bytes(body):
                    report.add(path_text, "singleton JSON is not exact JCS")
                for message in _schema_errors(body, descriptor["schema_ref"], schemas, registry):
                    report.add(path_text, message)
            except Exception as exc:  # noqa: BLE001
                report.add(path_text, f"invalid singleton JSON: {exc}")
        else:
            report.add(path_text, "unsupported Stage-A content model")

    expected_logical_names = {
        name.removesuffix(".jsonl").removesuffix(".json") for name in PAYLOAD_NAMES
    }
    if set(descriptor_by_name) != expected_logical_names:
        report.add(
            "artifacts",
            "Stage-A logical artifact set is not exact "
            f"(missing={sorted(expected_logical_names - set(descriptor_by_name))}, "
            f"extra={sorted(set(descriptor_by_name) - expected_logical_names)})",
        )

    membership_key = [
        "/group_id",
        "/member_scope",
        "/emoji_id",
        "/role/present",
        "/role/value",
        "/variant/present",
        "/variant/value",
    ]
    artifact_contracts: dict[
        str, tuple[str, str, str, str, list[str] | None, list[str] | None, list[str] | None]
    ] = {
        "collections": (
            "canonical",
            "recordset-jsonl",
            "collections.jsonl",
            "https://schemas.mojilex.org/v1/collection.schema.json",
            ["/id"],
            ["/id"],
            None,
        ),
        "emojis": (
            "canonical",
            "recordset-jsonl",
            "emojis.jsonl",
            "https://schemas.mojilex.org/v1/emoji.schema.json",
            ["/id"],
            ["/id"],
            None,
        ),
        "memberships": (
            "canonical",
            "recordset-jsonl",
            "memberships.jsonl",
            "https://schemas.mojilex.org/v1/membership.schema.json",
            ["/id"],
            ["/collection_id", "/status", "/position", "/id"],
            None,
        ),
        "tombstones": (
            "canonical",
            "recordset-jsonl",
            "tombstones.jsonl",
            "https://schemas.mojilex.org/v1/tombstone.schema.json",
            ["/target_entity_type", "/target_id"],
            ["/target_entity_type", "/target_id"],
            None,
        ),
        "visual-relations": (
            "canonical",
            "recordset-jsonl",
            "visual-relations.jsonl",
            "https://schemas.mojilex.org/v1/visual-relation.schema.json",
            ["/id"],
            ["/id"],
            None,
        ),
        "platform-profiles": (
            "normative",
            "singleton-json",
            "platform-profiles.json",
            "mlx://schemas/distribution/v1/platform-profiles-registry.schema.json",
            None,
            None,
            None,
        ),
        "rights-profiles": (
            "normative",
            "singleton-json",
            "rights-profiles.json",
            "mlx://schemas/distribution/v1/rights-profiles-registry.schema.json",
            None,
            None,
            None,
        ),
        "taxonomy": (
            "normative",
            "singleton-json",
            "taxonomy.json",
            "mlx://schemas/distribution/v1/taxonomy-registry.schema.json",
            None,
            None,
            None,
        ),
        "concepts": (
            "normative",
            "singleton-json",
            "concepts.json",
            "mlx://schemas/distribution/v1/concepts-registry.schema.json",
            None,
            None,
            None,
        ),
        "emojis-active": (
            "derived",
            "recordset-jsonl",
            "emojis-active.jsonl",
            "https://schemas.mojilex.org/v1/emoji.schema.json",
            ["/id"],
            ["/id"],
            None,
        ),
        "duplicate-groups": (
            "derived",
            "recordset-jsonl",
            "duplicate-groups.jsonl",
            "mlx://schemas/distribution/v1/duplicate-group.schema.json",
            ["/group_type", "/group_id"],
            ["/group_type", "/group_id"],
            None,
        ),
        "duplicate-group-memberships": (
            "derived",
            "recordset-jsonl",
            "duplicate-group-memberships.jsonl",
            "mlx://schemas/distribution/v1/duplicate-group-membership.schema.json",
            membership_key,
            membership_key,
            ["/group_id"],
        ),
        "collection-facets": (
            "derived",
            "recordset-jsonl",
            "collection-facets.jsonl",
            "mlx://schemas/distribution/v1/collection-facet.schema.json",
            ["/collection_id"],
            ["/collection_id"],
            None,
        ),
        "search-en": (
            "derived",
            "recordset-jsonl",
            "search-en.jsonl",
            "mlx://schemas/distribution/v1/search-record.schema.json",
            ["/emoji_id"],
            ["/emoji_id"],
            None,
        ),
        "search-ru": (
            "derived",
            "recordset-jsonl",
            "search-ru.jsonl",
            "mlx://schemas/distribution/v1/search-record.schema.json",
            ["/emoji_id"],
            ["/emoji_id"],
            None,
        ),
    }
    common_descriptor_fields = {
        "compression",
        "content_model",
        "logical_name",
        "media_type",
        "object_byte_size",
        "object_sha256",
        "path",
        "payload_sha256",
        "schema_ref",
        "semantic_role",
        "uncompressed_byte_size",
    }
    recordset_fields = {
        "logical_record_count",
        "primary_key",
        "record_count",
        "sort_key",
        "table_root_sha256",
    }
    for name, contract in artifact_contracts.items():
        descriptor = descriptor_by_name.get(name)
        if descriptor is None:
            continue
        role, model, path_text, schema_ref, primary_key, sort_key, routing_key = contract
        expected_projection = {
            "semantic_role": role,
            "content_model": model,
            "path": path_text,
            "media_type": (
                "application/x-ndjson" if model == "recordset-jsonl" else "application/json"
            ),
            "schema_ref": schema_ref,
            "compression": "none",
        }
        if any(descriptor.get(key) != value for key, value in expected_projection.items()):
            report.add(name, "artifact descriptor contract fields are not exact")
        expected_fields = set(common_descriptor_fields)
        if model == "recordset-jsonl":
            expected_fields.update(recordset_fields)
            if (
                descriptor.get("primary_key") != primary_key
                or descriptor.get("sort_key") != sort_key
            ):
                report.add(name, "artifact primary/sort key contract is not exact")
            if routing_key is None:
                if "routing_key" in descriptor:
                    report.add(name, "artifact has an undeclared routing key")
            else:
                expected_fields.add("routing_key")
                if descriptor.get("routing_key") != routing_key:
                    report.add(name, "artifact routing key contract is not exact")
        if role == "derived":
            expected_fields.add("derived_from")
        if set(descriptor) != expected_fields:
            report.add(name, "artifact descriptor field set is not exact for Stage A")

    for resource in resources:
        uri = resource.get("uri")
        if not isinstance(uri, str):
            continue
        if resource.get("resource_kind") == "artifact-alias":
            target = descriptor_by_name.get(resource.get("artifact_logical_name"))
            if (
                target is None
                or target.get("content_model") != "singleton-json"
                or resource.get("payload_sha256") != target.get("payload_sha256")
            ):
                report.add(uri, "artifact alias does not resolve to one singleton payload")
            continue
        path_text = resource.get("path", "")
        if not isinstance(path_text, str) or not _safe_release_path(path_text):
            continue
        expected_files.add(path_text)
        payload = resource_payloads.get(uri)
        if payload is None:
            continue
        schema_ref = resource.get("content_schema_ref")
        if schema_ref:
            if schema_ref not in schemas:
                report.add(uri, "content_schema_ref is not an embedded offline schema")
                continue
            try:
                body = parse_json(payload.decode("utf-8"), source=path_text)
                for message in _schema_errors(body, schema_ref, schemas, registry):
                    report.add(uri, message)
            except Exception as exc:  # noqa: BLE001
                report.add(uri, f"resource content schema check failed: {exc}")

    for descriptor in artifacts:
        if descriptor.get("schema_ref") not in resource_uris:
            report.add(
                descriptor.get("logical_name", "artifact"),
                "schema_ref is not offline-resolved",
            )
        if descriptor.get("semantic_role") == "derived":
            _validate_derived_from(descriptor, manifest, descriptor_by_name, report)
        elif "derived_from" in descriptor:
            report.add(
                descriptor.get("logical_name", "artifact"),
                "non-derived artifact has derived_from",
            )

    analysis_fields = {
        f"analysis-profiles/{filename}": field
        for field, (filename, _scope) in PROFILE_FILES.items()
    }
    for resource in physical_resources:
        source_path = resource.get("source_path")
        if source_path in analysis_fields:
            profile_field = analysis_fields[str(source_path)]
            profile_payload = resource_payloads.get(str(resource.get("uri")))
            if profile_payload is not None:
                try:
                    profile_document = parse_json(
                        profile_payload.decode("utf-8"), source=str(source_path)
                    )
                    _validate_profile_contract(
                        profile_field=profile_field,
                        document=profile_document,
                        payload=profile_payload,
                        schemas=schemas,
                        registry=registry,
                        resource_payloads=resource_payloads,
                        location=str(resource.get("uri")),
                        report=report,
                    )
                except (UnicodeDecodeError, DataError) as exc:
                    report.add(str(resource.get("uri")), f"invalid analysis profile: {exc}")
        expected_binding: dict[str, Any] | None = None
        expected_uri: str | None = None
        expected_path: str | None = None
        expected_media_type: str | None = None
        expected_content_schema: str | None = None
        if isinstance(source_path, str) and source_path.startswith("schemas/"):
            expected_binding = {
                "kind": "aggregate-member",
                "manifest_pointer": f"/profiles/{_schema_scope(source_path)}_schemas/sha256",
            }
            expected_uri = resource.get("uri")
            expected_path = f"resources/{source_path}"
            expected_media_type = "application/schema+json"
        elif source_path in analysis_fields:
            profile_field = analysis_fields[source_path]
            expected_binding = {
                "kind": "exact-content",
                "manifest_pointer": f"/profiles/{profile_field}/sha256",
            }
            selector = manifest["profiles"][profile_field]
            expected_uri = (
                f"mlx://profiles/{profile_field.replace('_', '-')}/{selector['id']}/"
                f"{resource.get('payload_sha256')}.json"
            )
            expected_path = f"resources/profiles/{PurePosixPath(str(source_path)).name}"
            expected_media_type = "application/json"
            expected_content_schema = (
                "mlx://schemas/distribution/v1/concept-candidate-profile.schema.json"
                if profile_field == "concept_candidates"
                else "mlx://schemas/distribution/v1/delegated-profile.schema.json"
            )
        elif isinstance(source_path, str) and source_path.startswith("taxonomy/v1/"):
            expected_binding = {
                "kind": "source-bundle-member",
                "manifest_pointer": "/profiles/taxonomy/source_bundle_sha256",
            }
            source_name = PurePosixPath(source_path).name
            expected_uri = (
                f"mlx://registries/taxonomy-source/{PurePosixPath(source_path).stem}/"
                f"{resource.get('payload_sha256')}.json"
            )
            expected_path = f"resources/registries/taxonomy-sources/{source_name}"
            expected_media_type = "application/json"
            expected_content_schema = (
                "mlx://schemas/distribution/v1/taxonomy-source.schema.json"
                if source_name == "taxonomy.json"
                else "mlx://schemas/distribution/v1/taxonomy-dictionary.schema.json"
            )
        elif isinstance(source_path, str) and source_path.startswith("platforms/"):
            expected_binding = {
                "kind": "source-bundle-member",
                "manifest_pointer": "/policies/platform_profiles/source_bundle_sha256",
            }
            try:
                body = parse_json(
                    resource_payloads[str(resource.get("uri"))].decode("utf-8"),
                    source=source_path,
                )
                version = body["profile_version"]
            except (KeyError, TypeError, UnicodeDecodeError, DataError):
                version = "<invalid>"
            expected_uri = (
                f"mlx://registries/platform-profile/{version}/{resource.get('payload_sha256')}.json"
            )
            expected_path = (
                f"resources/registries/platform-sources/{PurePosixPath(source_path).name}"
            )
            expected_media_type = "application/json"
            expected_content_schema = "mlx://schemas/distribution/v1/platform-profile.schema.json"
        if expected_binding is None or resource.get("bindings") != [expected_binding]:
            report.add(
                resource.get("uri", "resource"),
                "physical resource does not have its one exact canonical binding",
            )
        expected_projection = {
            "uri": expected_uri,
            "source_path": source_path,
            "path": expected_path,
            "media_type": expected_media_type,
            "compression": "none",
        }
        if any(resource.get(key) != value for key, value in expected_projection.items()):
            report.add(
                resource.get("uri", "resource"),
                "physical resource URI/path/media contract is not exact",
            )
        expected_fields = {
            "bindings",
            "compression",
            "media_type",
            "object_byte_size",
            "object_sha256",
            "path",
            "payload_sha256",
            "resource_kind",
            "source_path",
            "uncompressed_byte_size",
            "uri",
        }
        if expected_content_schema is not None:
            expected_fields.add("content_schema_ref")
            if resource.get("content_schema_ref") != expected_content_schema:
                report.add(
                    resource.get("uri", "resource"),
                    "physical resource content_schema_ref is not exact",
                )
        elif "content_schema_ref" in resource:
            report.add(
                resource.get("uri", "resource"),
                "JSON Schema resource must not declare content_schema_ref",
            )
        if set(resource) != expected_fields:
            report.add(
                resource.get("uri", "resource"),
                "physical resource descriptor field set is not exact for Stage A",
            )

    alias_contracts = {
        "platform-profiles": (
            "policy",
            "platform_profiles",
            "platform-profiles",
        ),
        "rights-profiles": ("policy", "rights_profiles", "rights-profiles"),
        "taxonomy": ("profile", "taxonomy", "facet-taxonomy"),
        "concepts": ("profile", "concepts", "concepts"),
    }
    aliases_by_name: dict[str, dict[str, Any]] = {}
    for resource in resources:
        if resource.get("resource_kind") != "artifact-alias":
            continue
        name = resource.get("artifact_logical_name")
        if not isinstance(name, str) or name in aliases_by_name:
            report.add(resource.get("uri", "resource"), "duplicate or invalid artifact alias")
            continue
        aliases_by_name[name] = resource
    if set(aliases_by_name) != set(alias_contracts):
        report.add("resources", "registry artifact-alias set is not exact")
    for name, (kind, selector_field, registry_type) in alias_contracts.items():
        alias = aliases_by_name.get(name)
        target = descriptor_by_name.get(name)
        selectors = manifest.get("policies" if kind == "policy" else "profiles", {})
        selector = selectors.get(selector_field) if isinstance(selectors, dict) else None
        if alias is None or target is None or not isinstance(selector, dict):
            continue
        pointer = (
            f"/policies/{selector_field}/sha256"
            if kind == "policy"
            else f"/profiles/{selector_field}/sha256"
        )
        expected_alias = {
            "uri": (
                f"mlx://registries/{registry_type}/{selector.get('id')}/"
                f"{target.get('payload_sha256')}.json"
            ),
            "resource_kind": "artifact-alias",
            "artifact_logical_name": name,
            "payload_sha256": target.get("payload_sha256"),
            "bindings": [{"kind": "exact-content", "manifest_pointer": pointer}],
        }
        if alias != expected_alias:
            report.add(alias.get("uri", name), "registry artifact alias is not exact")

    binding_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for resource in resources:
        for binding in resource.get("bindings", []):
            pointer = binding.get("manifest_pointer")
            if binding.get("kind") in {"aggregate-member", "source-bundle-member"}:
                binding_groups[pointer].append(resource)
            elif binding.get("kind") == "exact-content":
                exists, value = _manifest_pointer(manifest, pointer or "")
                if not exists or value != resource.get("payload_sha256"):
                    report.add(resource.get("uri", "resource"), "exact-content binding mismatch")
    expected_binding_groups = {
        "/profiles/canonical_schemas/sha256",
        "/profiles/derived_schemas/sha256",
        "/profiles/transport_schemas/sha256",
        "/profiles/taxonomy/source_bundle_sha256",
        "/policies/platform_profiles/source_bundle_sha256",
    }
    if set(binding_groups) != expected_binding_groups:
        report.add("resources", "aggregate/source-bundle binding pointer set is not exact")
    for pointer, members in binding_groups.items():
        exists, value = _manifest_pointer(manifest, pointer)
        calculated = jcs_sha256(
            sorted(
                [
                    {"path": item["source_path"], "sha256": item["payload_sha256"]}
                    for item in members
                ],
                key=lambda item: item["path"].encode(),
            )
        )
        if not exists or value != calculated:
            report.add(pointer, "aggregate/source-bundle resource binding mismatch")

    actual_files: set[str] = set()
    for path in distribution_root.rglob("*"):
        relative = path.relative_to(distribution_root).as_posix()
        if _is_link(path):
            report.add(relative, "release contains a link or reparse point")
        elif path.is_file():
            actual_files.add(relative)
        elif not path.is_dir():
            report.add(relative, "release contains a non-regular filesystem entry")
    if actual_files != expected_files:
        report.add(distribution_root, "physical file set differs from manifest/SHA256SUMS")
    if manifest.get("artifact_set_sha256") != jcs_sha256(
        {"artifacts": artifacts, "resources": resources, "bundles": manifest["bundles"]}
    ):
        report.add(manifest_path, "artifact_set_sha256 mismatch")

    selectors = _selector_entries(manifest)
    expected_canonical = state_root(artifacts, selectors, derived=False)
    if manifest.get("canonical_state_root_sha256") != expected_canonical:
        report.add(manifest_path, "canonical_state_root_sha256 mismatch")
    expected_derived = state_root(
        artifacts, selectors, derived=True, canonical_root=expected_canonical
    )
    if manifest.get("derived_views_root_sha256") != expected_derived:
        report.add(manifest_path, "derived_views_root_sha256 mismatch")

    build = manifest["build"]
    try:
        build_time = datetime.fromtimestamp(build["source_date_epoch"], tz=UTC)

        def check_future(record: dict[str, Any], field_name: str, value: str | None) -> None:
            if value is None:
                return
            observed_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if observed_at > build_time:
                report.add(
                    record.get("id", record.get("target_id", "canonical evidence")),
                    f"{field_name} is future evidence for source_date_epoch",
                )

        for entity in [*resolved.get("collections", []), *resolved.get("emojis", [])]:
            availability = entity["availability"]
            for field_name in ("first_seen_at", "last_changed_at", "last_verified_at"):
                check_future(entity, f"availability/{field_name}", availability.get(field_name))
        for emoji in resolved.get("emojis", []):
            check_future(emoji, "provenance/generated_at", emoji["provenance"].get("generated_at"))
            check_future(emoji, "review/reviewed_at", emoji["review"].get("reviewed_at"))
        for membership in resolved.get("memberships", []):
            check_future(membership, "first_seen_at", membership.get("first_seen_at"))
            check_future(membership, "last_changed_at", membership.get("last_changed_at"))
        for tombstone in resolved.get("tombstones", []):
            check_future(tombstone, "withheld_at", tombstone.get("withheld_at"))
        for relation in resolved.get("visual-relations", []):
            check_future(relation, "review/reviewed_at", relation["review"].get("reviewed_at"))
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        report.add(manifest_path, f"cannot validate canonical availability time: {exc}")
    parameters = build.get("parameters", {})
    expected_parameters = {
        "distribution_profile": manifest["profiles"]["distribution"]["id"],
        "layout_profile": manifest["layout_profile"],
        "storage_mode": manifest["storage"]["mode"],
        "compression_profile": "none",
        "part_packing_profile": manifest["profiles"]["part_packing"]["id"],
        "bundle_mode": "none",
        "bundle_profile": manifest["profiles"]["bundling"]["id"],
        "partition_overrides": {},
    }
    if parameters != expected_parameters or build.get("parameters_sha256") != jcs_sha256(
        parameters
    ):
        report.add(manifest_path, "closed build parameters or parameters hash mismatch")
    if build.get("evidence_inputs_root_sha256") != jcs_sha256([]):
        report.add(manifest_path, "Stage-A evidence input root is not empty")
    if build.get("migration_inputs_root_sha256") != jcs_sha256(manifest.get("migrations")):
        report.add(manifest_path, "migration input root mismatch")
    if build.get("build_inputs_sha256") != jcs_sha256(_build_input(manifest)):
        report.add(manifest_path, "release-build-input-v1 hash mismatch")

    checksum_lines = "".join(
        f"{hashlib.sha256((distribution_root / path).read_bytes()).hexdigest()}  {path}\n"
        for path in sorted(expected_files - {"SHA256SUMS"})
        if (distribution_root / path).is_file()
    ).encode("ascii")
    try:
        if (distribution_root / "SHA256SUMS").read_bytes() != checksum_lines:
            report.add("SHA256SUMS", "checksum file is incomplete, unsorted, or incorrect")
    except OSError as exc:
        report.add("SHA256SUMS", f"cannot read checksum file: {exc}")

    if resolved:
        try:
            _validate_groups(
                resolved.get("duplicate-groups", []),
                resolved.get("duplicate-group-memberships", []),
                {item["id"]: item for item in resolved.get("emojis", [])},
                uuid.UUID(source_dataset["duplicate_group_namespace"]),
                report,
            )
            _validate_search(resolved, manifest, source_dataset, report)
            expected_facets = _collection_facets(
                [
                    item
                    for item in resolved.get("collections", [])
                    if item["availability"]["status"] == "active"
                ],
                [
                    item
                    for item in resolved.get("memberships", [])
                    if item["status"] == "active"
                    and item["emoji_id"]
                    in {emoji["id"] for emoji in resolved.get("emojis-active", [])}
                ],
                {item["id"]: item for item in resolved.get("emojis-active", [])},
                defaultdict(
                    list,
                    {
                        emoji_id: sorted(
                            {
                                member["group_id"]
                                for member in resolved.get("duplicate-group-memberships", [])
                                if member["emoji_id"] == emoji_id
                            }
                        )
                        for emoji_id in {item["id"] for item in resolved.get("emojis-active", [])}
                    },
                ),
                {item["group_id"]: item for item in resolved.get("duplicate-groups", [])},
                descriptor_by_name["memberships"]["table_root_sha256"],
                manifest["profiles"]["collection_dedupe"]["id"],
            )
            if resolved.get("collection-facets") != expected_facets:
                report.add("collection-facets", "aggregate projection mismatch")
        except (KeyError, TypeError, ValueError, DataError) as exc:
            report.add("cross-field", f"cannot complete semantic validation: {exc}")

    counts = manifest["counts"]
    collections = resolved.get("collections", [])
    emojis = resolved.get("emojis", [])
    memberships = resolved.get("memberships", [])
    tombstones = resolved.get("tombstones", [])
    count_expectations = {
        "collections": len(collections),
        "emojis": len(emojis),
        "memberships": len(memberships),
        "tombstones": len(tombstones),
        "active_emojis": sum(item["availability"]["status"] == "active" for item in emojis),
        "availability_by_status": {
            "collections": {
                status: sum(item["availability"]["status"] == status for item in collections)
                for status in ["active", "unavailable", "private", "deleted", "unknown"]
            },
            "emojis": {
                status: sum(item["availability"]["status"] == status for item in emojis)
                for status in ["active", "unavailable", "private", "deleted", "unknown"]
            },
        },
        "emoji_review_by_status": {
            status: sum(item["review"]["status"] == status for item in emojis)
            for status in ["unreviewed", "approved", "changes_requested", "rejected"]
        },
        "memberships_by_status": {
            status: sum(item["status"] == status for item in memberships)
            for status in ["active", "removed_from_collection", "unknown"]
        },
    }
    if counts != count_expectations:
        report.add("counts", "counts and status histograms do not exactly match artifacts")

    non_tombstoned_emojis = [
        item for item in emojis if item["id"] not in {row["target_id"] for row in tombstones}
    ]
    expected_languages = {
        language: {
            "described": sum(
                isinstance(item.get("descriptions", {}).get(language), dict)
                and bool(item["descriptions"][language].get("text"))
                for item in non_tombstoned_emojis
            ),
            "total": len(non_tombstoned_emojis),
        }
        for language in sorted(source_dataset.get("default_languages", []), key=str.encode)
    }
    if manifest.get("languages", {}).get("coverage") != expected_languages:
        report.add("languages", "coverage is not the exact canonical non-tombstoned coverage")
    if source_dataset.get("rights_defaults", {}).get("project_profile_id") != resolved.get(
        "rights-profiles", {}
    ).get("project_default_profile_id"):
        report.add("rights", "dataset/project rights default mismatch")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a built SPEC-003 distribution")
    parser.add_argument("source_root", nargs="?", type=Path, default=Path("."))
    parser.add_argument("distribution_root", type=Path)
    args = parser.parse_args(argv)
    report = validate_distribution(args.source_root, args.distribution_root)
    if report.errors:
        for error in report.errors:
            print(error, file=sys.stderr)
        return 1
    print("SPEC-003 distribution validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
