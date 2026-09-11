from __future__ import annotations

import copy
import hashlib
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from tools.common import jcs_bytes, load_json
from tools.spec003_build import (
    DELEGATED_PROFILE_TYPES,
    PROFILE_CONTRACT_SCHEMA_FILES,
    PROFILE_FILES,
)

ROOT = Path(__file__).resolve().parents[1]


class AnalysisProfileContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schemas: dict[str, dict[str, Any]] = {}
        cls.registry: Registry[Any] = Registry()
        for path in sorted(ROOT.glob("schemas/**/*.schema.json")):
            schema = load_json(path)
            uri = schema["$id"]
            cls.schemas[uri] = schema
            cls.registry = cls.registry.with_resource(uri, Resource.from_contents(schema))

    @classmethod
    def errors(cls, schema_ref: str, value: Any) -> list[str]:
        validator = Draft202012Validator(
            cls.schemas[schema_ref],
            registry=cls.registry,
            format_checker=FormatChecker(),
        )
        return [error.message for error in validator.iter_errors(value)]

    def test_all_profiles_are_exact_jcs_and_resolve_offline_contracts(self) -> None:
        analysis_ref = "mlx://schemas/distribution/v1/analysis-profile.schema.json"
        dataset = load_json(ROOT / "dataset.json")
        pinned = {
            "color": ("color_profile", "color_profile_sha256"),
            "dedupe": ("dedupe_profile", "dedupe_profile_sha256"),
            "collection_dedupe": (
                "collection_dedupe_profile",
                "collection_dedupe_profile_sha256",
            ),
        }
        for field, (filename, _scope) in PROFILE_FILES.items():
            with self.subTest(profile=field):
                path = ROOT / "analysis-profiles" / filename
                profile = load_json(path)
                payload = path.read_bytes()
                self.assertEqual(payload, jcs_bytes(profile))
                self.assertEqual(self.errors(analysis_ref, profile), [])
                if field == "concept_candidates":
                    continue
                contract_filename = PROFILE_CONTRACT_SCHEMA_FILES[field]
                contract_ref = f"mlx://schemas/distribution/v1/{contract_filename}"
                contract_path = ROOT / "schemas" / "distribution" / "v1" / contract_filename
                self.assertEqual(profile["profile_type"], DELEGATED_PROFILE_TYPES[field])
                self.assertEqual(profile["contract_schema_ref"], contract_ref)
                self.assertEqual(
                    profile["contract_schema_sha256"],
                    hashlib.sha256(contract_path.read_bytes()).hexdigest(),
                )
                self.assertIs(self.schemas[contract_ref]["unevaluatedProperties"], False)
                self.assertEqual(self.errors(contract_ref, profile["body"]), [])
                if field in pinned:
                    id_field, digest_field = pinned[field]
                    self.assertEqual(dataset[id_field], profile["profile_id"])
                    self.assertEqual(dataset[digest_field], hashlib.sha256(payload).hexdigest())

    def test_nested_unknown_missing_wrong_default_and_order_are_rejected(self) -> None:
        profile = load_json(ROOT / "analysis-profiles" / "distribution-v1.json")
        contract_ref = profile["contract_schema_ref"]

        unknown = copy.deepcopy(profile["body"])
        unknown["semantic_roles"]["unknown"] = ["invented"]
        self.assertTrue(self.errors(contract_ref, unknown))

        missing = copy.deepcopy(profile["body"])
        del missing["jsonl"]["encoding"]
        self.assertTrue(self.errors(contract_ref, missing))

        wrong_default = copy.deepcopy(profile["body"])
        wrong_default["inline_limits"]["native_references"] = 31
        self.assertTrue(self.errors(contract_ref, wrong_default))

        wrong_order = copy.deepcopy(profile["body"])
        wrong_order["layout_profiles"].reverse()
        self.assertTrue(self.errors(contract_ref, wrong_order))

        open_wrapper = copy.deepcopy(profile)
        open_wrapper["runtime_default"] = True
        self.assertTrue(
            self.errors("mlx://schemas/distribution/v1/analysis-profile.schema.json", open_wrapper)
        )

    def test_distribution_v1_role_map_is_the_normative_superset(self) -> None:
        body = load_json(ROOT / "analysis-profiles" / "distribution-v1.json")["body"]
        self.assertEqual(body["layout_profiles"], ["monolith-v1", "partitioned-v1"])
        self.assertIn("agent-{lang}", body["semantic_roles"]["derived"])
        self.assertIn("availability-verifications", body["semantic_roles"]["canonical"])
        self.assertIn("observation-profiles", body["semantic_roles"]["normative"])
        self.assertIn("locator-{logical_name}", body["semantic_roles"]["derived"])


if __name__ == "__main__":
    unittest.main()
