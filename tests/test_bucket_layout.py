from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import copy_repository_contract, install_example_as_canonical
from tests.test_addendum import _second_emoji, _write_relation
from tools.common import (
    bucket_shard_matches,
    compact_json,
    emoji_filename_matches,
    entity_shard,
    load_jsonl,
)
from tools.validate import validate_repository

ROOT = Path(__file__).resolve().parents[1]


class BucketLayoutTests(unittest.TestCase):
    def test_emoji_filename_requires_full_exact_digest(self) -> None:
        entity_id = "synthetic-emoji"
        digest = entity_shard(entity_id, 64)
        self.assertTrue(emoji_filename_matches(entity_id, digest))
        for width in (2, 4, 8, 63):
            self.assertFalse(emoji_filename_matches(entity_id, digest[:width]))
        replacement = "0" if digest[-1] != "0" else "1"
        self.assertFalse(emoji_filename_matches(entity_id, digest[:-1] + replacement))

    def test_relation_buckets_keep_supported_widths_and_exact_prefixes(self) -> None:
        entity_id = "synthetic-relation"
        digest = entity_shard(entity_id, 64)
        for width in (4, 8):
            self.assertTrue(bucket_shard_matches(entity_id, digest[:2], digest[2:width]))
        for width in (2, 3, 5, 6, 7, 9, 64):
            self.assertFalse(bucket_shard_matches(entity_id, digest[:2], digest[2:width]))
        replacement = "0" if digest[7] != "0" else "1"
        self.assertFalse(bucket_shard_matches(entity_id, digest[:2], digest[2:7] + replacement))

    def test_full_emoji_and_legacy_relation_paths_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            copy_repository_contract(ROOT, root)
            first = install_example_as_canonical(ROOT, root)["emoji"]
            second = _second_emoji(root, first)
            _write_relation(root, first, second)
            legacy_report = validate_repository(root, include_examples=False, check_build=False)
            self.assertEqual(legacy_report.errors, [])

            relation = next((root / "data/relations/visual").glob("*/*.jsonl"))
            relation_id = load_jsonl(relation)[0]["id"]
            digest = entity_shard(relation_id, 8)
            current = relation.parent.parent / digest[:2] / f"{digest[2:]}.jsonl"
            current.write_bytes(relation.read_bytes())
            relation.unlink()
            report = validate_repository(root, include_examples=False, check_build=False)
            self.assertEqual(report.errors, [])

    def test_truncated_sharded_emoji_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            copy_repository_contract(ROOT, root)
            emoji = install_example_as_canonical(ROOT, root)["emoji"]
            canonical = next((root / "data/telegram/emojis").glob("*.jsonl"))
            digest = entity_shard(emoji["id"], 64)
            legacy = canonical.parent / digest[:2] / f"{digest[2:8]}.jsonl"
            legacy.parent.mkdir()
            canonical.rename(legacy)
            report = validate_repository(root, include_examples=False, check_build=False)
            self.assertTrue(
                any("outside the canonical path layout" in error for error in report.errors),
                "\n".join(report.errors),
            )

    def test_truncated_flat_emoji_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            copy_repository_contract(ROOT, root)
            emoji = install_example_as_canonical(ROOT, root)["emoji"]
            canonical = next((root / "data/telegram/emojis").glob("*.jsonl"))
            canonical.rename(canonical.with_name(f"{entity_shard(emoji['id'], 8)}.jsonl"))
            report = validate_repository(root, include_examples=False, check_build=False)
            self.assertTrue(
                any(
                    "emoji filename does not match full SHA-256(id)" in error
                    for error in report.errors
                ),
                "\n".join(report.errors),
            )

    def test_two_records_in_one_emoji_file_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            copy_repository_contract(ROOT, root)
            first = install_example_as_canonical(ROOT, root)["emoji"]
            second = _second_emoji(root, first)
            first_path = root / "data/telegram/emojis" / f"{entity_shard(first['id'], 64)}.jsonl"
            second_path = root / "data/telegram/emojis" / f"{entity_shard(second['id'], 64)}.jsonl"
            second_path.unlink()
            first_path.write_text(
                compact_json(first) + "\n" + compact_json(second) + "\n",
                encoding="utf-8",
                newline="",
            )
            report = validate_repository(root, include_examples=False, check_build=False)
            self.assertTrue(
                any(
                    "emoji file must contain exactly one record" in error for error in report.errors
                ),
                "\n".join(report.errors),
            )

    def test_wrong_full_emoji_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            copy_repository_contract(ROOT, root)
            install_example_as_canonical(ROOT, root)
            canonical = next((root / "data/telegram/emojis").glob("*.jsonl"))
            digest = canonical.stem
            replacement = "0" if digest[-1] != "0" else "1"
            canonical.rename(canonical.with_name(f"{digest[:-1]}{replacement}.jsonl"))
            report = validate_repository(root, include_examples=False, check_build=False)
            self.assertTrue(
                any(
                    "emoji filename does not match full SHA-256(id)" in error
                    for error in report.errors
                ),
                "\n".join(report.errors),
            )


if __name__ == "__main__":
    unittest.main()
