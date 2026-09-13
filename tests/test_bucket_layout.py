from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import copy_repository_contract, install_example_as_canonical
from tests.test_addendum import _second_emoji, _write_relation
from tools.common import bucket_shard_matches, entity_shard, load_jsonl
from tools.validate import validate_repository

ROOT = Path(__file__).resolve().parents[1]


def _extend_bucket_paths(root: Path) -> None:
    paths = list((root / "data").glob("*/emojis/*/*.jsonl"))
    paths += list((root / "data/relations/visual").glob("*/*.jsonl"))
    for path in paths:
        values = load_jsonl(path)
        if len(values) != 1:
            raise AssertionError("this fixture expects one record per bucket")
        shard = entity_shard(values[0]["id"], 8)
        target = path.parent.parent / shard[:2] / f"{shard[2:]}.jsonl"
        target.write_bytes(path.read_bytes())
        path.unlink()


class BucketLayoutTests(unittest.TestCase):
    def test_only_supported_widths_and_exact_prefixes_are_accepted(self) -> None:
        entity_id = "synthetic-emoji"
        digest = entity_shard(entity_id, 64)
        for width in (4, 8):
            self.assertTrue(bucket_shard_matches(entity_id, digest[:2], digest[2:width]))
        for width in (2, 3, 5, 6, 7, 9, 64):
            self.assertFalse(bucket_shard_matches(entity_id, digest[:2], digest[2:width]))
        self.assertFalse(bucket_shard_matches(entity_id, digest[:1], digest[1:8]))
        self.assertFalse(bucket_shard_matches(entity_id, digest[:3], digest[3:8]))
        replacement = "0" if digest[7] != "0" else "1"
        self.assertFalse(bucket_shard_matches(entity_id, digest[:2], digest[2:7] + replacement))

    def test_current_and_legacy_emoji_and_relation_layouts_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            copy_repository_contract(ROOT, root)
            first = install_example_as_canonical(ROOT, root)["emoji"]
            second = _second_emoji(root, first)
            _write_relation(root, first, second)
            legacy_report = validate_repository(root, include_examples=False, check_build=False)
            self.assertEqual(legacy_report.errors, [])
            _extend_bucket_paths(root)
            report = validate_repository(root, include_examples=False, check_build=False)
            self.assertEqual(report.errors, [])

    def test_same_id_in_legacy_and_current_paths_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            copy_repository_contract(ROOT, root)
            emoji = install_example_as_canonical(ROOT, root)["emoji"]
            legacy = next((root / "data").glob("*/emojis/*/*.jsonl"))
            shard = entity_shard(emoji["id"], 8)
            (legacy.parent / f"{shard[2:]}.jsonl").write_bytes(legacy.read_bytes())
            report = validate_repository(root, include_examples=False, check_build=False)
            self.assertTrue(any("duplicate internal ID" in error for error in report.errors))

    def test_wrong_current_bucket_hash_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            copy_repository_contract(ROOT, root)
            emoji = install_example_as_canonical(ROOT, root)["emoji"]
            legacy = next((root / "data").glob("*/emojis/*/*.jsonl"))
            shard = entity_shard(emoji["id"], 8)
            replacement = "0" if shard[-1] != "0" else "1"
            legacy.rename(legacy.parent / f"{shard[2:-1]}{replacement}.jsonl")
            report = validate_repository(root, include_examples=False, check_build=False)
            self.assertTrue(any("bucket path does not match" in error for error in report.errors))


if __name__ == "__main__":
    unittest.main()
