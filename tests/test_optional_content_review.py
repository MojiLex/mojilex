from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from tests.helpers import copy_repository_contract, install_example_as_canonical
from tools.build_index import _eligible_for_public_index, build_index
from tools.common import compact_json, load_json, load_jsonl, pretty_json
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
                # Keep the independent AI qualification gate satisfied with
                # a synthetic exact fixture, never fabricated production evidence.
                provenance = emoji["provenance"]
                provenance["qualification_id"] = "mq_standard-v1_example-001"
                binding = {
                    "concept_registry_id": "concepts-v1.synthetic-test",
                    "concept_registry_sha256": "6" * 64,
                    "concept_candidate_set_sha256": "7" * 64,
                    "concept_candidate_profile_id": "concept-candidates-v1",
                    "concept_candidate_profile_sha256": "8" * 64,
                    "model_routing_policy_id": "model-routing-local-v1",
                    "model_routing_policy_sha256": "9" * 64,
                }
                provenance.update(binding)
                qualification = {
                    **binding,
                    **{
                        field: provenance[field]
                        for field in (
                            "qualification_id",
                            "provider",
                            "model",
                            "prompt_sha256",
                            "request_parameters_sha256",
                            "pipeline_version",
                        )
                    },
                    "description_profile": "standard-v1",
                    "schema_version": "1.0.0",
                    "taxonomy_version": "1.0.0",
                    "routing_policy_version": "1.0.0",
                    "languages": ["en", "ru"],
                    "benchmark_id": "golden-v1",
                    "benchmark_sha256": "3" * 64,
                    "split_id": "holdout-v1",
                    "split_sha256": "4" * 64,
                    "report_sha256": "5" * 64,
                    "valid_from": "2026-09-01T00:00:00Z",
                    "valid_until": "2026-10-01T00:00:00Z",
                    "status": "active",
                }
                registry_path = repository / "quality" / "model-qualifications.json"
                registry = load_json(registry_path)
                registry["entries"] = [qualification]
                registry_path.write_text(pretty_json(registry), encoding="utf-8", newline="")
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
