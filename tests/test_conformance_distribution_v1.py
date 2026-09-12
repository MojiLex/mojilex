from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from typing import Any

from tests.helpers import copy_repository_contract
from tools.build_index import build_index
from tools.common import compact_json, entity_shard, load_json, load_jsonl, pretty_json
from tools.validate import validate_repository
from tools.validate_distribution import validate_distribution

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "conformance" / "distribution" / "v1"
FIXTURE_PATH = FIXTURE_ROOT / "valid" / "snapshot-a-monolith" / "fixture.json"
EXPECTED_HASHES_PATH = FIXTURE_ROOT / "expected-hashes.json"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _load_fixture_records(fixture: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for descriptor in fixture["source_records"]:
        relative = PurePosixPath(descriptor["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise AssertionError(f"unsafe conformance source path: {relative}")
        source = ROOT / relative
        content = source.read_bytes()
        if _sha256(content) != descriptor["sha256"]:
            raise AssertionError(f"conformance source hash mismatch: {relative}")
        result[descriptor["role"]] = load_json(source)
    return result


def _install_fixture(repository: Path, records: dict[str, dict[str, Any]]) -> None:
    collection = records["collection"]
    emoji = records["emoji"]
    membership = records["membership"]
    collection_shard = entity_shard(collection["id"], 2)
    collection_dir = (
        repository
        / "data"
        / collection["platform"]
        / "collections"
        / collection_shard
        / collection["id"]
    )
    collection_dir.mkdir(parents=True)
    (collection_dir / "collection.json").write_text(
        pretty_json(collection), encoding="utf-8", newline=""
    )
    (collection_dir / "memberships.jsonl").write_text(
        compact_json(membership) + "\n", encoding="utf-8", newline=""
    )
    emoji_shard = entity_shard(emoji["id"], 4)
    emoji_dir = repository / "data" / emoji["platform"] / "emojis" / emoji_shard[:2]
    emoji_dir.mkdir(parents=True)
    (emoji_dir / f"{emoji_shard[2:]}.jsonl").write_text(
        compact_json(emoji) + "\n", encoding="utf-8", newline=""
    )


class StageABDistributionConformanceTests(unittest.TestCase):
    def test_synthetic_monolith_snapshot_end_to_end_and_exact_hashes(self) -> None:
        fixture = load_json(FIXTURE_PATH)
        expected = load_json(EXPECTED_HASHES_PATH)
        self.assertEqual(fixture["fixture_id"], expected["fixture_id"])
        self.assertEqual(
            fixture["origin"],
            {
                "kind": "synthetic-metadata",
                "media_bytes_included": False,
                "network_required": False,
            },
        )
        records = _load_fixture_records(fixture)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            repository = base / "repository"
            repository.mkdir()
            copy_repository_contract(ROOT, repository)
            _install_fixture(repository, records)
            source_report = validate_repository(
                repository, include_examples=True, check_build=False
            )
            self.assertEqual(source_report.errors, [], "\n".join(source_report.errors))

            output = base / "snapshot"
            manifest = build_index(repository, output, **fixture["build"])
            distribution_report = validate_distribution(repository, output)
            self.assertEqual(distribution_report.errors, [], "\n".join(distribution_report.errors))

            actual_hashes = {
                path.relative_to(output).as_posix(): _sha256(path.read_bytes())
                for path in output.rglob("*")
                if path.is_file()
            }
            self.assertEqual(actual_hashes, expected["files"])
            self.assertEqual(
                actual_hashes["manifest.json"], _sha256((output / "manifest.json").read_bytes())
            )

            search = load_jsonl(output / "search-en.jsonl")
            self.assertEqual(len(search), 1)
            search_record = search[0]
            emoji = next(
                row
                for row in load_jsonl(output / "emojis.jsonl")
                if row["id"] == search_record["emoji_id"]
            )
            membership = next(
                row
                for row in load_jsonl(output / "memberships.jsonl")
                if row["emoji_id"] == emoji["id"]
            )
            collection = next(
                row
                for row in load_jsonl(output / "collections.jsonl")
                if row["id"] == membership["collection_id"]
            )
            platform_registry = load_json(output / "platform-profiles.json")
            platform = next(
                row for row in platform_registry["entries"] if row["platform"] == emoji["platform"]
            )
            native_reference = search_record["native_references"][0]
            traversal = fixture["expected_traversal"]
            self.assertEqual(collection["id"], search_record["collection_ids"][0])
            self.assertEqual(platform["platform"], traversal["platform"])
            self.assertEqual(
                {
                    "platform": native_reference["platform"],
                    "native_namespace": native_reference["native_namespace"],
                    "scope_id": native_reference["scope_id"],
                    "native_id": native_reference["native_id"],
                },
                {
                    key: traversal[key]
                    for key in ("platform", "native_namespace", "scope_id", "native_id")
                },
            )

            rights_registry = load_json(output / "rights-profiles.json")
            rights_profile_id = search_record["rights"]["rights_profile_id"]
            rights_profile = next(
                row
                for row in rights_registry["profiles"]
                if row["rights_profile_id"] == rights_profile_id
            )
            self.assertEqual(rights_profile_id, traversal["rights_profile_id"])
            self.assertEqual(rights_profile_id, platform["default_rights_profile_id"])
            self.assertEqual(search_record["rights"]["distribution_status"], "allowed")
            for operation in fixture["rights"]["permitted_dataset_operations"]:
                self.assertEqual(rights_profile["operations"][operation]["decision"], "allow")

            self.assertEqual(manifest["bundles"], [])
            self.assertFalse(
                any(path.suffix in {".png", ".webm", ".tgs"} for path in output.rglob("*"))
            )


if __name__ == "__main__":
    unittest.main()
