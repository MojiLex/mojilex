#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import sys
import tempfile
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

if __package__:
    from .common import (
        DataError,
        compact_json,
        discover_records,
        duplicate_group_id,
        jcs_sha256,
        load_json,
        media_digest,
        pretty_json,
        reviewed_same_artwork_group_id,
        sha256_bytes,
        sha256_file,
    )
    from .git_provenance import resolve_head_revision, verify_release_source
else:
    from common import (  # type: ignore[no-redef]
        DataError,
        compact_json,
        discover_records,
        duplicate_group_id,
        jcs_sha256,
        load_json,
        media_digest,
        pretty_json,
        reviewed_same_artwork_group_id,
        sha256_bytes,
        sha256_file,
    )
    from git_provenance import resolve_head_revision, verify_release_source


PAYLOAD_NAMES = (
    "collections.jsonl",
    "emojis.jsonl",
    "memberships.jsonl",
    "tombstones.jsonl",
    "emojis-active.jsonl",
    "search-ru.jsonl",
    "search-en.jsonl",
    "collection-facets.jsonl",
    "duplicate-groups.jsonl",
    "visual-relations.jsonl",
    "taxonomy.json",
)

PROTECTED_DATASET_DIRECTORIES = {
    ".git",
    ".github",
    "data",
    "examples",
    "platforms",
    "quality",
    "schemas",
    "taxonomy",
    "tests",
    "tombstones",
    "tools",
}


def _is_link_or_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse_flag)


def _resolve_without_links_or_reparse(path: Path, *, label: str) -> Path:
    absolute = Path(os.path.abspath(path))
    for candidate in reversed((absolute, *absolute.parents)):
        if _is_link_or_reparse_point(candidate):
            raise ValueError(f"{label} path must not contain a link or reparse point: {candidate}")
    return absolute.resolve()


def _jsonl(records: Iterable[dict[str, Any]]) -> bytes:
    return "".join(f"{compact_json(record)}\n" for record in records).encode("utf-8")


def _eligible_for_public_index(emoji: dict[str, Any]) -> bool:
    if emoji["availability"]["status"] != "active":
        return False
    review_status = emoji["review"]["status"]
    return review_status in {"approved", "unreviewed"}


def _current_approved_relations(
    visual_relations: list[dict[str, Any]],
    emojis: dict[str, dict[str, Any]],
    tombstoned_ids: set[str],
) -> list[dict[str, Any]]:
    """Return approved relations whose evidence still matches current media."""

    current: list[dict[str, Any]] = []
    for relation in visual_relations:
        if relation["review"]["status"] != "approved":
            continue
        subject_id = relation["subject_id"]
        object_id = relation["object_id"]
        if subject_id in tombstoned_ids or object_id in tombstoned_ids:
            continue
        subject = emojis.get(subject_id)
        object_emoji = emojis.get(object_id)
        if subject is None or object_emoji is None:
            continue
        evidence = relation["evidence"]
        if evidence["subject_media_digest"] != media_digest(subject["media"]):
            continue
        if evidence["object_media_digest"] != media_digest(object_emoji["media"]):
            continue
        current.append(relation)
    return current


def _search_record(
    emoji: dict[str, Any],
    language: str,
    collection_ids: list[str],
    duplicate_group_ids: list[str],
) -> dict[str, Any]:
    description = emoji["descriptions"][language]
    result: dict[str, Any] = {
        "emoji_id": emoji["id"],
        "platform": emoji["platform"],
        "native_namespace": emoji["native_namespace"],
        "scope_id": emoji["scope_id"],
        "native_id": emoji["native_id"],
        "collection_ids": collection_ids,
        "text": description["text"],
    }
    if "motion" in description:
        result["motion"] = description["motion"]
    result["usage"] = description["usage"]
    result["semantic_tags"] = emoji["semantic_tags"]
    facets = emoji["facets"]
    rendering = facets["rendering"]["items"]
    result["facets"] = {
        "animated": any(item["animated"] for item in emoji["media"]),
        "media_kinds": sorted({item["kind"] for item in emoji["media"]}),
        "color_behaviors": sorted({item["color_behavior"] for item in rendering}),
        "alpha_modes": sorted({item["alpha_mode"] for item in rendering}),
        "color_families": sorted(
            {color["family"] for item in rendering for color in item.get("dominant_colors", [])}
        ),
        "text_status": facets["text_content"]["status"],
        "literal_text": [item["value"] for item in facets["text_content"]["items"]],
        "content_types": facets["content_types"],
        "styles": facets["styles"],
        "suggested_uses": facets["suggested_uses"],
        "uncertainties": facets["uncertainties"],
    }
    result["duplicate_group_ids"] = duplicate_group_ids
    result["review_status"] = emoji["review"]["status"]
    return result


def _status_counts(records: Any) -> dict[str, Any]:
    return {
        "collections": dict(
            sorted(
                Counter(
                    item.value["availability"]["status"] for item in records.collections
                ).items()
            )
        ),
        "emojis": dict(
            sorted(Counter(item.value["availability"]["status"] for item in records.emojis).items())
        ),
        "memberships": dict(
            sorted(Counter(item.value["status"] for item in records.memberships).items())
        ),
        "reviews": dict(
            sorted(Counter(item.value["review"]["status"] for item in records.emojis).items())
        ),
        "ratings": dict(
            sorted(Counter(item.value["content"]["rating"] for item in records.emojis).items())
        ),
    }


def _media_reference(emoji: dict[str, Any], media: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"emoji_id": emoji["id"], "role": media["role"]}
    if "variant_id" in media:
        result["variant_id"] = media["variant_id"]
    return result


def _build_duplicate_groups(
    emojis: list[dict[str, Any]],
    visual_relations: list[dict[str, Any]],
    namespace: uuid.UUID,
) -> list[dict[str, Any]]:
    binary_media: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    decoded_media: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    binary_entities: dict[str, list[str]] = defaultdict(list)
    decoded_entities: dict[str, list[str]] = defaultdict(list)

    for emoji in emojis:
        fingerprint_by_key = {
            (item["role"], item.get("variant_id")): item for item in emoji["fingerprints"]["items"]
        }
        binary_signature: list[dict[str, Any]] = []
        decoded_signature: list[dict[str, Any]] = []
        for media in emoji["media"]:
            reference = _media_reference(emoji, media)
            binary_media[(media["sha256"], media["byte_size"])].append(reference)
            binary_item: dict[str, Any] = {
                "role": media["role"],
                "sha256": media["sha256"],
                "byte_size": media["byte_size"],
            }
            if "variant_id" in media:
                binary_item["variant_id"] = media["variant_id"]
            binary_signature.append(binary_item)

            fingerprint = fingerprint_by_key[(media["role"], media.get("variant_id"))]
            profile = emoji["fingerprints"]["profile"]
            decoded_media[(profile, fingerprint["decoded_payload_sha256"])].append(reference)
            decoded_item: dict[str, Any] = {
                "role": media["role"],
                "decoded_payload_sha256": fingerprint["decoded_payload_sha256"],
            }
            if "variant_id" in media:
                decoded_item["variant_id"] = media["variant_id"]
            decoded_signature.append(decoded_item)

        binary_entities[jcs_sha256(binary_signature)].append(emoji["id"])
        decoded_entities[jcs_sha256(decoded_signature)].append(emoji["id"])

    groups: list[dict[str, Any]] = []
    for (media_sha256, byte_size), members in sorted(binary_media.items()):
        if len(members) < 2:
            continue
        members.sort(key=lambda item: (item["emoji_id"], item["role"], item.get("variant_id", "")))
        content_digest = jcs_sha256({"byte_size": byte_size, "sha256": media_sha256})
        groups.append(
            {
                "id": duplicate_group_id(namespace, "binary-exact", "media", "", content_digest),
                "group_type": "binary-exact",
                "scope": "media",
                "content_digest": content_digest,
                "source_sha256": media_sha256,
                "byte_size": byte_size,
                "members": members,
            }
        )
    for (profile, decoded_sha256), members in sorted(decoded_media.items()):
        if len(members) < 2:
            continue
        members.sort(key=lambda item: (item["emoji_id"], item["role"], item.get("variant_id", "")))
        groups.append(
            {
                "id": duplicate_group_id(
                    namespace, "decoded-exact", "media", profile, decoded_sha256
                ),
                "group_type": "decoded-exact",
                "scope": "media",
                "profile": profile,
                "content_digest": decoded_sha256,
                "members": members,
            }
        )
    for content_digest, members in sorted(binary_entities.items()):
        if len(members) < 2:
            continue
        groups.append(
            {
                "id": duplicate_group_id(namespace, "binary-exact", "entity", "", content_digest),
                "group_type": "binary-exact",
                "scope": "entity",
                "content_digest": content_digest,
                "members": sorted(members),
            }
        )
    for content_digest, members in sorted(decoded_entities.items()):
        if len(members) < 2:
            continue
        profile = emojis[0]["fingerprints"]["profile"] if emojis else ""
        groups.append(
            {
                "id": duplicate_group_id(
                    namespace, "decoded-exact", "entity", profile, content_digest
                ),
                "group_type": "decoded-exact",
                "scope": "entity",
                "profile": profile,
                "content_digest": content_digest,
                "members": sorted(members),
            }
        )

    graph: dict[str, set[str]] = defaultdict(set)
    for relation in visual_relations:
        if relation["relation_type"] == "same-artwork" and relation["scope"] == "entity":
            graph[relation["subject_id"]].add(relation["object_id"])
            graph[relation["object_id"]].add(relation["subject_id"])
    seen: set[str] = set()
    for start in sorted(graph):
        if start in seen:
            continue
        pending = [start]
        component: list[str] = []
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            component.append(current)
            pending.extend(sorted(graph[current] - seen, reverse=True))
        members = sorted(component)
        groups.append(
            {
                "id": reviewed_same_artwork_group_id(namespace, members),
                "group_type": "reviewed-same-artwork",
                "scope": "entity",
                "members": members,
            }
        )
    return sorted(groups, key=lambda item: item["id"])


def _taxonomy_snapshot(root: Path, version: str) -> dict[str, Any]:
    taxonomy_root = root / "taxonomy" / "v1"
    manifest = load_json(taxonomy_root / "taxonomy.json")
    registries: dict[str, Any] = {}
    for entry in manifest["registries"]:
        relative = Path(entry["path"])
        candidate = (
            root / relative
            if relative.parts[:2] == ("taxonomy", "v1")
            else taxonomy_root / relative
        ).resolve()
        if candidate.parent != taxonomy_root.resolve():
            raise DataError(f"taxonomy registry path escapes taxonomy/v1: {entry['path']!r}")
        registry = load_json(candidate)
        registries[entry["facet"]] = registry["entries"]
    return {"taxonomy_version": version, "registries": dict(sorted(registries.items()))}


def _collection_facet_records(
    collections: list[dict[str, Any]],
    memberships: list[dict[str, Any]],
    emojis: dict[str, dict[str, Any]],
    group_ids_by_emoji: dict[str, list[str]],
    groups_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    emoji_ids_by_collection: dict[str, list[str]] = defaultdict(list)
    for membership in memberships:
        emoji_ids_by_collection[membership["collection_id"]].append(membership["emoji_id"])
    result: list[dict[str, Any]] = []
    for collection in collections:
        emoji_ids = sorted(emoji_ids_by_collection.get(collection["id"], []))
        values = [emojis[emoji_id] for emoji_id in emoji_ids if emoji_id in emojis]
        media_kinds: Counter[str] = Counter()
        content_types: Counter[str] = Counter()
        styles: Counter[str] = Counter()
        suggested_uses: Counter[str] = Counter()
        color_families: Counter[str] = Counter()
        adaptive = fixed = recognized_text = numbers = 0
        collection_groups: set[str] = set()
        for emoji in values:
            primary = next(item for item in emoji["media"] if item["role"] == "primary")
            media_kinds[primary["kind"]] += 1
            facets = emoji["facets"]
            content_types.update(facets["content_types"])
            styles.update(facets["styles"])
            suggested_uses.update(facets["suggested_uses"])
            rendering = facets["rendering"]["items"]
            behaviors = {item["color_behavior"] for item in rendering}
            if behaviors.intersection({"platform-adaptive", "mixed"}):
                adaptive += 1
            if "fixed" in behaviors:
                fixed += 1
            families = {
                color["family"] for item in rendering for color in item.get("dominant_colors", [])
            }
            color_families.update(families)
            if facets["text_content"]["status"] in {"recognized", "partially-recognized"}:
                recognized_text += 1
            if "number" in facets["content_types"]:
                numbers += 1
            collection_groups.update(group_ids_by_emoji.get(emoji["id"], []))
        count = len(values)
        exact_groups = sum(
            groups_by_id[group_id]["group_type"] in {"binary-exact", "decoded-exact"}
            for group_id in collection_groups
        )
        reviewed_groups = sum(
            groups_by_id[group_id]["group_type"] == "reviewed-same-artwork"
            for group_id in collection_groups
        )
        result.append(
            {
                "collection_id": collection["id"],
                "active_memberships": count,
                "media_kind_counts": dict(sorted(media_kinds.items())),
                "adaptive_share_bp": round(adaptive * 10000 / count) if count else 0,
                "fixed_share_bp": round(fixed * 10000 / count) if count else 0,
                "content_type_counts": dict(sorted(content_types.items())),
                "style_counts": dict(sorted(styles.items())),
                "recognized_text_count": recognized_text,
                "number_count": numbers,
                "color_family_counts": dict(sorted(color_families.items())),
                "suggested_use_counts": dict(sorted(suggested_uses.items())),
                "exact_duplicate_group_count": exact_groups,
                "reviewed_visual_duplicate_group_count": reviewed_groups,
            }
        )
    return result


def _write_staged(output: Path, files: dict[str, bytes]) -> None:
    output = _resolve_without_links_or_reparse(output, label="output")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output == output.parent or (output / "dataset.json").exists():
        raise ValueError(f"refusing unsafe output directory: {output}")
    if output.exists():
        if output.is_symlink() or not output.is_dir():
            raise ValueError(f"output must be a real directory: {output}")
        children = list(output.iterdir())
        if children:
            allowed_names = {*PAYLOAD_NAMES, "manifest.json", "SHA256SUMS"}
            if any(
                _is_link_or_reparse_point(child)
                or not child.is_file()
                or child.name not in allowed_names
                for child in children
            ):
                raise ValueError(f"refusing to replace non-build directory: {output}")
            manifest_path = output / "manifest.json"
            try:
                previous_manifest = load_json(manifest_path)
            except (OSError, DataError) as exc:
                raise ValueError(f"refusing unrecognized output directory: {output}") from exc
            if (
                not isinstance(previous_manifest, dict)
                or previous_manifest.get("dataset") != "mojilex"
                or not isinstance(previous_manifest.get("payload_sha256"), dict)
            ):
                raise ValueError(f"refusing unrecognized output directory: {output}")
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        for name, content in files.items():
            path = staging / name
            path.write_bytes(content)
        if output.exists():
            if _is_link_or_reparse_point(output):
                raise ValueError(f"output must be a real directory: {output}")
            shutil.rmtree(output)
        os.replace(staging, output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def build_index(root: Path, output: Path, *, revision: str) -> dict[str, Any]:
    root = _resolve_without_links_or_reparse(root, label="dataset root")
    output = _resolve_without_links_or_reparse(output, label="output")
    if output == root or root.is_relative_to(output):
        raise ValueError("output must not equal or contain the dataset root")
    for name in PROTECTED_DATASET_DIRECTORIES:
        protected = (root / name).resolve()
        if output == protected or output.is_relative_to(protected):
            raise ValueError(f"output must not be inside canonical {name}/")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("revision must be a full 40-character lowercase Git commit SHA")
    records = discover_records(root)
    dataset = load_json(root / "dataset.json")

    collections = sorted((item.value for item in records.collections), key=lambda item: item["id"])
    emojis = sorted((item.value for item in records.emojis), key=lambda item: item["id"])
    memberships = sorted((item.value for item in records.memberships), key=lambda item: item["id"])
    tombstones = sorted(
        (item.value for item in records.tombstones), key=lambda item: item["target_id"]
    )

    active_collections = {
        item["id"] for item in collections if item["availability"]["status"] == "active"
    }
    eligible_emojis = {item["id"]: item for item in emojis if _eligible_for_public_index(item)}
    active_memberships = [
        item
        for item in memberships
        if item["status"] == "active"
        and item["collection_id"] in active_collections
        and item["emoji_id"] in eligible_emojis
    ]
    collection_ids_by_emoji: dict[str, list[str]] = defaultdict(list)
    for membership in active_memberships:
        collection_ids_by_emoji[membership["emoji_id"]].append(membership["collection_id"])
    for collection_ids in collection_ids_by_emoji.values():
        collection_ids.sort()

    active_emojis = [eligible_emojis[emoji_id] for emoji_id in sorted(collection_ids_by_emoji)]
    all_visual_relations = sorted(
        (item.value for item in records.visual_relations), key=lambda item: item["id"]
    )
    all_emojis = {item["id"]: item for item in emojis}
    tombstoned_ids = {item["target_id"] for item in tombstones}
    visual_relations = _current_approved_relations(
        all_visual_relations,
        all_emojis,
        tombstoned_ids,
    )
    relation_namespace = uuid.UUID(dataset["visual_relation_namespace"])
    duplicate_groups = _build_duplicate_groups(
        sorted(eligible_emojis.values(), key=lambda item: item["id"]),
        visual_relations,
        relation_namespace,
    )
    group_ids_by_emoji: dict[str, list[str]] = defaultdict(list)
    groups_by_id = {group["id"]: group for group in duplicate_groups}
    for group in duplicate_groups:
        for member in group["members"]:
            emoji_id = member if isinstance(member, str) else member["emoji_id"]
            group_ids_by_emoji[emoji_id].append(group["id"])
    for group_ids in group_ids_by_emoji.values():
        group_ids.sort()

    search: dict[str, list[dict[str, Any]]] = {"ru": [], "en": []}
    for emoji in active_emojis:
        for language in search:
            if language in emoji["descriptions"]:
                search[language].append(
                    _search_record(
                        emoji,
                        language,
                        collection_ids_by_emoji[emoji["id"]],
                        group_ids_by_emoji.get(emoji["id"], []),
                    )
                )

    public_collections = [item for item in collections if item["id"] in active_collections]
    collection_facets = _collection_facet_records(
        public_collections,
        active_memberships,
        eligible_emojis,
        group_ids_by_emoji,
        groups_by_id,
    )
    taxonomy = _taxonomy_snapshot(root, dataset["taxonomy_version"])
    taxonomy_bytes = pretty_json(taxonomy).encode("utf-8")

    payloads = {
        "collections.jsonl": _jsonl(collections),
        "emojis.jsonl": _jsonl(emojis),
        "memberships.jsonl": _jsonl(memberships),
        "tombstones.jsonl": _jsonl(tombstones),
        "emojis-active.jsonl": _jsonl(active_emojis),
        "search-ru.jsonl": _jsonl(search["ru"]),
        "search-en.jsonl": _jsonl(search["en"]),
        "collection-facets.jsonl": _jsonl(collection_facets),
        "duplicate-groups.jsonl": _jsonl(duplicate_groups),
        "visual-relations.jsonl": _jsonl(visual_relations),
        "taxonomy.json": taxonomy_bytes,
    }
    payload_hashes = {name: sha256_bytes(payloads[name]) for name in PAYLOAD_NAMES}
    manifest = {
        "dataset": dataset["dataset"],
        "schema_version": dataset["schema_version"],
        "git_commit": revision,
        "counts": {
            "collections": len(collections),
            "emojis": len(emojis),
            "memberships": len(memberships),
            "tombstones": len(tombstones),
            "active_emojis": len(active_emojis),
            "active_memberships": len(active_memberships),
            "search_ru": len(search["ru"]),
            "search_en": len(search["en"]),
            "collection_facets": len(collection_facets),
            "duplicate_groups": len(duplicate_groups),
            "visual_relations": len(visual_relations),
        },
        "status_counts": _status_counts(records),
        "profiles": {
            "taxonomy": {
                "version": dataset["taxonomy_version"],
                "sha256": sha256_bytes(taxonomy_bytes),
            },
            "color": {
                "id": dataset["color_profile"],
                "sha256": dataset["color_profile_sha256"],
            },
            "dedupe": {
                "id": dataset["dedupe_profile"],
                "sha256": dataset["dedupe_profile_sha256"],
            },
            "collection_dedupe": {
                "id": dataset["collection_dedupe_profile"],
                "sha256": dataset["collection_dedupe_profile_sha256"],
            },
            "description": {"id": "standard-v1"},
        },
        "quality_registry_sha256": {
            "model_qualifications": sha256_file(root / "quality" / "model-qualifications.json"),
            "review_reasons": sha256_file(root / "quality" / "review-reasons-v1.json"),
            "review_routing": sha256_file(root / "quality" / "review-routing-v1.json"),
            "routing_reasons": sha256_file(root / "quality" / "routing-reasons-v1.json"),
        },
        "platform_registry_sha256": {"telegram": sha256_file(root / "platforms" / "telegram.json")},
        "payload_sha256": dict(sorted(payload_hashes.items())),
    }
    manifest_bytes = pretty_json(manifest).encode("utf-8")
    all_hashes = {**payload_hashes, "manifest.json": sha256_bytes(manifest_bytes)}
    sums = "".join(f"{digest}  {name}\n" for name, digest in sorted(all_hashes.items())).encode(
        "ascii"
    )
    _write_staged(
        output,
        {
            **payloads,
            "manifest.json": manifest_bytes,
            "SHA256SUMS": sums,
        },
    )
    return manifest


# SPEC-003 owns the public builder contract.  The legacy helpers above remain temporarily
# importable for migration diagnostics, while all callers of build_index/PAYLOAD_NAMES use
# the closed Stage-A implementation.
if __package__:
    from .spec003_build import PAYLOAD_NAMES, build_index
else:
    from spec003_build import PAYLOAD_NAMES, build_index  # type: ignore[assignment,no-redef]


def _git_revision(root: Path) -> str:
    return resolve_head_revision(root).commit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic SPEC-003 snapshot")
    parser.add_argument("root", nargs="?", default=".", type=Path)
    parser.add_argument("--output", type=Path, default=Path("dist"))
    parser.add_argument("--revision", help="full lowercase Git SHA (defaults to HEAD)")
    parser.add_argument("--snapshot-id", help="immutable data-YYYY.MM.DD.N snapshot identity")
    parser.add_argument("--source-date-epoch", type=int, help="immutable release/tag UTC epoch")
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="build without the normal strict repository validation",
    )
    args = parser.parse_args(argv)
    root = Path(os.path.abspath(args.root))
    output = args.output if args.output.is_absolute() else root / args.output
    if args.snapshot_id is None or args.source_date_epoch is None:
        parser.error("--snapshot-id and --source-date-epoch are required immutable release inputs")
    try:
        revision = args.revision if args.revision else _git_revision(root)
        provenance = verify_release_source(root, revision)
    except (OSError, ValueError) as exc:
        print(f"build-index failed: {exc}", file=sys.stderr)
        return 1
    if not args.skip_validation:
        if __package__:
            from .validate import validate_repository
        else:
            from validate import validate_repository  # type: ignore[no-redef]

        report = validate_repository(root, include_examples=True, check_build=False)
        if report.errors:
            print("refusing to build an invalid repository:", file=sys.stderr)
            for error in report.errors:
                print(f"- {error}", file=sys.stderr)
            return 1
    try:
        manifest = build_index(
            root,
            output,
            revision=revision,
            snapshot_id=args.snapshot_id,
            source_date_epoch=args.source_date_epoch,
        )
        verify_release_source(root, revision)
        if (
            manifest["git"].get("commit") != provenance.commit
            or manifest["git"].get("object_format") != provenance.object_format
        ):
            raise ValueError("manifest Git provenance differs from verified source commit")
    except (OSError, ValueError, KeyError) as exc:
        print(f"build-index failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"Built {output} for {manifest['git']['commit']} "
        f"({manifest['counts']['emojis']} emoji records)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
