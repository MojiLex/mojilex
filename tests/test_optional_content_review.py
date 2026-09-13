from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from tests.helpers import copy_repository_contract, install_example_as_canonical
from tools.build_index import _eligible_for_public_index, build_index
from tools.common import compact_json, load_jsonl
from tools.spec003_build import _eligible_review
from tools.validate import validate_repository
from tools.validate_distribution import validate_distribution

ROOT = Path(__file__).resolve().parents[1]
BUILD_ARGS = {
    "revision": "0123456789abcdef0123456789abcdef01234567",
    "snapshot_id": "data-2026.09.11.1",
    "source_date_epoch": 1789171199,
}


class OptionalContentReviewTests(unittest.TestCase):
    def test_unreviewed_ratings_and_warnings_survive_validation_and_distribution(self) -> None:
        for rating, warnings in (
            ("general", []),
            ("general", ["flashing"]),
            ("sensitive", ["flashing"]),
            ("adult", ["nudity", "sexual-content"]),
            ("unknown", ["other-sensitive"]),
        ):
            with (
                self.subTest(rating=rating, warnings=warnings),
                tempfile.TemporaryDirectory() as temporary,
            ):
                base = Path(temporary).resolve()
                repository = base / "repository"
                repository.mkdir()
                copy_repository_contract(ROOT, repository)
                values = install_example_as_canonical(ROOT, repository)
                emoji = values["emoji"]
                emoji["content"] = {"rating": rating, "warnings": warnings}
                emoji["review"] = {"status": "unreviewed"}
                self.assertNotIn("qualification_id", emoji["provenance"])
                before = copy.deepcopy(emoji)
                bucket = next((repository / "data" / "telegram" / "emojis").rglob("*.jsonl"))
                bucket.write_text(compact_json(emoji) + "\n", encoding="utf-8", newline="")
                report = validate_repository(repository, include_examples=True, check_build=False)
                self.assertEqual(report.errors, [], "\n".join(report.errors))

                output = base / "dist"
                build_index(repository, output, **BUILD_ARGS)
                distribution_report = validate_distribution(repository, output)
                self.assertEqual(
                    distribution_report.errors, [], "\n".join(distribution_report.errors)
                )
                active = load_jsonl(output / "emojis-active.jsonl")
                self.assertEqual(active, [before])
                for language in ("ru", "en"):
                    search = load_jsonl(output / f"search-{language}.jsonl")
                    self.assertEqual(len(search), 1)
                    self.assertEqual(search[0]["content"], before["content"])
                    self.assertEqual(search[0]["review"]["status"], "unreviewed")
                self.assertEqual(load_jsonl(bucket), [before])

    def test_explicit_negative_review_decisions_remain_excluded(self) -> None:
        for status in ("changes_requested", "rejected"):
            with self.subTest(status=status):
                emoji = {
                    "availability": {"status": "active"},
                    "review": {"status": status},
                    "content": {"rating": "adult", "warnings": ["sexual-content"]},
                }
                self.assertFalse(_eligible_for_public_index(emoji))
                self.assertFalse(_eligible_review(emoji))

    def test_inactive_unreviewed_records_remain_excluded(self) -> None:
        emoji = {
            "availability": {"status": "unavailable"},
            "review": {"status": "unreviewed"},
            "content": {"rating": "general", "warnings": []},
        }
        self.assertFalse(_eligible_for_public_index(emoji))
