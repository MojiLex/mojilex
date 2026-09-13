from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from tests.helpers import copy_repository_contract, install_example_as_canonical
from tools.build_index import build_index
from tools.common import compact_json, load_json, load_jsonl
from tools.spec003_build import _literal_text
from tools.validate import validate_repository
from tools.validate_distribution import validate_distribution

ROOT = Path(__file__).resolve().parents[1]
BUILD_ARGS = {
    "revision": "0123456789abcdef0123456789abcdef01234567",
    "snapshot_id": "data-2026.09.11.1",
    "source_date_epoch": 1789171199,
}


class PendingSearchProjectionTests(unittest.TestCase):
    def test_every_canonical_text_kind_projects_to_existing_search_contract(self) -> None:
        expected = {
            "letter": "symbol",
            "number": "number",
            "word": "word",
            "phrase": "phrase",
            "punctuation": "symbol",
            "code": "mixed",
            "symbol": "symbol",
            "other": "mixed",
        }
        canonical = load_json(ROOT / "schemas/v1/facets.schema.json")
        self.assertEqual(
            set(expected), set(canonical["$defs"]["textItem"]["properties"]["kind"]["enum"])
        )
        distribution = load_json(ROOT / "schemas/distribution/v1/distribution-common.schema.json")
        validator = Draft202012Validator(distribution["$defs"]["literalText"])
        for kind, projected_kind in expected.items():
            with self.subTest(kind=kind):
                item = {
                    "value": "A",
                    "kind": kind,
                    "script": "Latn",
                    "temporal_scope": "persistent",
                    "media_refs": [{"role": "primary"}],
                }
                emoji = {"facets": {"text_content": {"items": [item]}}}
                before = copy.deepcopy(emoji)
                projected = _literal_text(emoji)
                self.assertEqual(
                    projected,
                    [
                        {
                            "value": "A",
                            "kind": projected_kind,
                            "script": "Latn",
                            "temporal_scope": "persistent",
                        }
                    ],
                )
                self.assertEqual(list(validator.iter_errors(projected[0])), [])
                self.assertEqual(emoji, before)

    def test_pending_mapping_preserves_active_records_and_only_defers_search(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            repository = base / "repository"
            repository.mkdir()
            copy_repository_contract(ROOT, repository)
            emoji = install_example_as_canonical(ROOT, repository)["emoji"]
            complete_concepts = list(emoji["concept_ids"])
            emoji["review"] = {"status": "unreviewed"}
            emoji["content"]["warnings"] = ["flashing"]
            self.assertNotIn("qualification_id", emoji["provenance"])
            bucket = next((repository / "data/telegram/emojis").rglob("*.jsonl"))
            for status, concept_ids in (("pending", []), ("complete", complete_concepts)):
                with self.subTest(status=status):
                    emoji["concept_mapping_status"] = status
                    emoji["concept_ids"] = concept_ids
                    before = copy.deepcopy(emoji)
                    bucket.write_text(compact_json(emoji) + "\n", encoding="utf-8", newline="")
                    report = validate_repository(
                        repository, include_examples=True, check_build=False
                    )
                    self.assertEqual(report.errors, [], "\n".join(report.errors))
                    output = base / status
                    build_index(repository, output, **BUILD_ARGS)
                    checked = validate_distribution(repository, output)
                    self.assertEqual(checked.errors, [], "\n".join(checked.errors))
                    self.assertEqual(load_jsonl(output / "emojis.jsonl"), [before])
                    self.assertEqual(load_jsonl(output / "emojis-active.jsonl"), [before])
                    self.assertEqual(len(load_jsonl(output / "memberships.jsonl")), 1)
                    for language in ("ru", "en"):
                        search = load_jsonl(output / f"search-{language}.jsonl")
                        self.assertEqual(len(search), int(status == "complete"))
                    self.assertEqual(load_jsonl(bucket), [before])

            # The existing pending/complete canonical schema is still strict.
            emoji["concept_mapping_status"] = "pending"
            bucket.write_text(compact_json(emoji) + "\n", encoding="utf-8", newline="")
            report = validate_repository(repository, include_examples=True, check_build=False)
            self.assertTrue(report.errors)
