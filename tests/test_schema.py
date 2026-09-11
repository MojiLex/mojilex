from __future__ import annotations

import copy
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from tests.helpers import set_pointer
from tools.common import load_json
from tools.validate import Report, _schema_environment

ROOT = Path(__file__).resolve().parents[1]


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        report = Report()
        _, cls.schemas, cls.registry = _schema_environment(ROOT, report)
        if report.errors:
            raise AssertionError("\n".join(report.errors))

    def validator(self, entity_type: str) -> Draft202012Validator:
        return Draft202012Validator(
            self.schemas[entity_type],
            registry=self.registry,
            format_checker=FormatChecker(),
        )

    def test_normative_examples_conform(self) -> None:
        paths = [
            ("collection", ROOT / "examples" / "telegram" / "collection.json"),
            ("emoji", ROOT / "examples" / "telegram" / "emoji.json"),
            ("membership", ROOT / "examples" / "telegram" / "membership.json"),
            ("tombstone", ROOT / "examples" / "tombstone.json"),
            ("visual_relation", ROOT / "examples" / "visual-relation.json"),
            ("emoji", ROOT / "examples" / "facets" / "adaptive-icon.json"),
            ("emoji", ROOT / "examples" / "facets" / "number-404.json"),
        ]
        for entity_type, path in paths:
            with self.subTest(entity_type=entity_type, path=path.name):
                errors = list(self.validator(entity_type).iter_errors(load_json(path)))
                self.assertEqual(errors, [], "\n".join(error.message for error in errors))

    def test_mutation_fixtures_are_rejected(self) -> None:
        fixtures = load_json(ROOT / "tests" / "fixtures" / "invalid" / "mutation-cases.json")
        for fixture in fixtures:
            with self.subTest(case=fixture["name"]):
                document = copy.deepcopy(load_json(ROOT / fixture["source"]))
                if "delete_pointer" in fixture:
                    set_pointer(document, fixture["delete_pointer"], delete=True)
                else:
                    set_pointer(document, fixture["pointer"], fixture["value"])
                messages = [
                    error.message for error in self.validator("emoji").iter_errors(document)
                ]
                self.assertTrue(
                    any(fixture["expected_fragment"] in message for message in messages), messages
                )

    def test_tombstone_cannot_leak_native_identifier(self) -> None:
        fixture = load_json(
            ROOT / "tests" / "fixtures" / "invalid" / "tombstone-with-native-id.json"
        )
        messages = [error.message for error in self.validator("tombstone").iter_errors(fixture)]
        self.assertTrue(any("Additional properties are not allowed" in item for item in messages))

    def test_profile_id_to_sha_mapping_is_immutable(self) -> None:
        manifest = load_json(ROOT / "dataset.json")
        manifest["dedupe_profile_sha256"] = "0" * 64
        messages = [error.message for error in self.validator("dataset").iter_errors(manifest)]
        self.assertTrue(any("was expected" in message for message in messages), messages)

    def test_human_edit_accepts_changed_paths_only_inside_the_edit(self) -> None:
        emoji = copy.deepcopy(load_json(ROOT / "examples" / "telegram" / "emoji.json"))
        emoji["provenance"]["origin"] = "mixed"
        emoji["provenance"]["human_edits"] = [
            {
                "editor": "example-reviewer",
                "edited_at": "2026-09-11T00:00:00Z",
                "languages": ["en", "ru"],
                "changed_paths": ["/facets/styles"],
            }
        ]
        self.assertEqual(list(self.validator("emoji").iter_errors(emoji)), [])

        emoji["provenance"]["changed_paths"] = ["/facets/styles"]
        messages = [error.message for error in self.validator("emoji").iter_errors(emoji)]
        self.assertTrue(any("Additional properties are not allowed" in item for item in messages))


if __name__ == "__main__":
    unittest.main()
