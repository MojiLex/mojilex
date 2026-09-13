from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from tests.helpers import copy_repository_contract, install_example_as_canonical
from tools.build_index import build_index
from tools.common import compact_json, load_json, load_jsonl
from tools.validate import Report, _schema_environment, validate_repository
from tools.validate_distribution import validate_distribution

ROOT = Path(__file__).resolve().parents[1]


class FragmentTagTests(unittest.TestCase):
    def test_canonical_and_search_tags_share_fragment_limits(self) -> None:
        canonical = load_json(ROOT / "schemas/v1/common.schema.json")["$defs"]["semanticTags"]
        search = load_json(ROOT / "schemas/distribution/v1/search-record.schema.json")
        search_tags = search["properties"]["semantic"]["properties"]["semantic_tags"]
        concrete = [f"object-{index}" for index in range(12)]
        cases = [
            ("one concrete", ["tree"], True),
            ("twelve concrete", concrete, True),
            ("one concrete and fragment", ["fragment", "tree"], True),
            ("twelve concrete and fragment", [*concrete, "fragment"], True),
            ("thirteen concrete", [*concrete, "extra"], False),
            ("thirteen concrete and fragment", [*concrete, "extra", "fragment"], False),
            ("duplicate fragment", ["fragment", "fragment", "tree"], False),
            ("duplicate concrete", ["fragment", "tree", "tree"], False),
            ("fragment alone", ["fragment"], False),
            ("no tags", [], False),
        ]
        for schema_name, schema in (("canonical", canonical), ("search", search_tags)):
            validator = Draft202012Validator(schema)
            for case, tags, expected in cases:
                with self.subTest(schema=schema_name, case=case):
                    self.assertEqual(validator.is_valid(tags), expected)

    def test_full_emoji_record_accepts_twelve_concrete_tags_and_fragment(self) -> None:
        report = Report()
        _, schemas, registry = _schema_environment(ROOT, report)
        self.assertEqual(report.errors, [])
        emoji = copy.deepcopy(load_json(ROOT / "examples/telegram/emoji.json"))
        emoji["semantic_tags"] = sorted([*(f"object-{i}" for i in range(12)), "fragment"])
        validator = Draft202012Validator(schemas["emoji"], registry=registry)
        self.assertEqual(list(validator.iter_errors(emoji)), [])

    def test_fragment_survives_canonical_validation_and_distribution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            repository = base / "repository"
            repository.mkdir()
            copy_repository_contract(ROOT, repository)
            emoji = install_example_as_canonical(ROOT, repository)["emoji"]
            emoji["semantic_tags"] = sorted([*(f"object-{i}" for i in range(12)), "fragment"])
            emoji["review"] = {"status": "unreviewed"}
            expected_tags = list(emoji["semantic_tags"])
            bucket = next((repository / "data/telegram/emojis").rglob("*.jsonl"))
            bucket.write_text(compact_json(emoji) + "\n", encoding="utf-8", newline="")
            report = validate_repository(repository, include_examples=True, check_build=False)
            self.assertEqual(report.errors, [], "\n".join(report.errors))

            output = base / "dist"
            build_index(
                repository,
                output,
                revision="0123456789abcdef0123456789abcdef01234567",
                snapshot_id="data-2026.09.11.1",
                source_date_epoch=1789171199,
            )
            distribution_report = validate_distribution(repository, output)
            self.assertEqual(distribution_report.errors, [], "\n".join(distribution_report.errors))
            self.assertEqual(
                load_jsonl(output / "emojis-active.jsonl")[0]["semantic_tags"], expected_tags
            )
            for language in ("ru", "en"):
                search = load_jsonl(output / f"search-{language}.jsonl")
                self.assertEqual(search[0]["semantic"]["semantic_tags"], expected_tags)
            self.assertEqual(load_jsonl(bucket)[0]["semantic_tags"], expected_tags)
