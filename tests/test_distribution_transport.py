from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from tools.build_index import build_index
from tools.common import load_json
from tools.spec003_build import PROFILE_CONTRACT_SCHEMA_FILES

ROOT = Path(__file__).resolve().parents[1]
REVISION = "0123456789abcdef0123456789abcdef01234567"
BUILD_ARGS = {
    "revision": REVISION,
    "snapshot_id": "data-2026.09.11.1",
    "source_date_epoch": 1789171199,
}
TRANSPORT_SCHEMAS = {
    "agent-record.schema.json",
    "cli-command-result.schema.json",
    "cli-jsonl-item.schema.json",
    "cli-jsonl-metadata.schema.json",
    "cli-jsonl-summary.schema.json",
    "cli-read-envelope.schema.json",
    "cli-request.schema.json",
    "cli-resolution-candidate.schema.json",
    "cli-similar-item.schema.json",
    "search-request.schema.json",
}


class DistributionTransportSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schemas: dict[str, dict[str, Any]] = {}
        cls.registry: Registry[Any] = Registry()
        for path in sorted(ROOT.glob("schemas/**/*.json")):
            schema = load_json(path)
            uri = schema["$id"]
            cls.schemas[uri] = schema
            cls.registry = cls.registry.with_resource(uri, Resource.from_contents(schema))

    @classmethod
    def errors(cls, schema_name: str, value: Any) -> list[str]:
        uri = f"mlx://schemas/distribution/v1/{schema_name}"
        validator = Draft202012Validator(
            cls.schemas[uri],
            registry=cls.registry,
            format_checker=FormatChecker(),
        )
        return [error.message for error in validator.iter_errors(value)]

    def test_transport_schemas_are_embedded_as_exact_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "dist"
            manifest = build_index(ROOT, output, **BUILD_ARGS)
            resources = {
                item["source_path"]: item
                for item in manifest["resources"]
                if item["resource_kind"] == "physical"
            }
            expected_paths = {f"schemas/distribution/v1/{name}" for name in TRANSPORT_SCHEMAS}
            contract_paths = {
                "schemas/distribution/v1/analysis-profile.schema.json",
                "schemas/distribution/v1/delegated-profile.schema.json",
                *(
                    f"schemas/distribution/v1/{filename}"
                    for filename in PROFILE_CONTRACT_SCHEMA_FILES.values()
                ),
            }
            self.assertTrue(expected_paths <= set(resources))
            self.assertTrue(contract_paths <= set(resources))
            for source_path in expected_paths:
                resource = resources[source_path]
                self.assertEqual(resource["media_type"], "application/schema+json")
                self.assertEqual(
                    (output / resource["path"]).read_bytes(),
                    (ROOT / source_path).read_bytes(),
                )
            for source_path in contract_paths:
                self.assertEqual(
                    resources[source_path]["bindings"],
                    [
                        {
                            "kind": "aggregate-member",
                            "manifest_pointer": "/profiles/transport_schemas/sha256",
                        }
                    ],
                )
            profile_resources = {
                source_path: resource
                for source_path, resource in resources.items()
                if source_path.startswith("analysis-profiles/")
            }
            for source_path, resource in profile_resources.items():
                expected_schema = (
                    "mlx://schemas/distribution/v1/concept-candidate-profile.schema.json"
                    if source_path.endswith("/concept-candidates-v1.json")
                    else "mlx://schemas/distribution/v1/delegated-profile.schema.json"
                )
                self.assertEqual(resource["content_schema_ref"], expected_schema)

    def test_representative_envelope_and_jsonl_records_conform(self) -> None:
        dataset = {
            "snapshot_id": "data-2026.09.11.1",
            "manifest_sha256": "a" * 64,
            "release_verification_status": "integrity-only-unsigned",
            "catalog_status": "unknown",
            "revocation_status": "unknown",
            "control_state_status": "offline-unknown",
            "errata_status": "unknown",
            "catalog_checkpoint": {"present": False},
        }
        envelope = {
            "schema_version": "1",
            "ok": True,
            "command": "snapshot-verify",
            "status": "succeeded",
            "run_id": "0" * 26,
            "dataset": dataset,
            "result": {
                "overall_status": "integrity-only-unsigned",
                "manifest_sha256": "a" * 64,
                "checks": [{"check_id": "manifest-jcs", "status": "passed"}],
            },
            "warnings": [],
            "errors": [],
        }
        self.assertEqual(self.errors("cli-read-envelope.schema.json", envelope), [])

        metadata = {
            "schema_version": "1",
            "record_type": "metadata",
            "command": "snapshots",
            "view": "snapshot",
            "dataset": {"present": False},
            "request_sha256": "b" * 64,
        }
        item = {
            "schema_version": "1",
            "record_type": "item",
            "ordinal": 0,
            "item": {
                "snapshot_id": "data-2026.09.11.1",
                "manifest_sha256": "a" * 64,
                "channel": "stable",
                "catalog_status": "current",
            },
        }
        summary = {
            "schema_version": "1",
            "record_type": "summary",
            "ok": True,
            "status": "succeeded",
            "item_count": 1,
            "next_cursor": {"present": False},
            "warnings": [],
            "errors": [],
        }
        self.assertEqual(self.errors("cli-jsonl-metadata.schema.json", metadata), [])
        self.assertEqual(self.errors("cli-jsonl-item.schema.json", item), [])
        self.assertEqual(self.errors("cli-jsonl-summary.schema.json", summary), [])

        request = {
            "request_profile_id": "cli-request-v1",
            "command": "snapshots",
            "dataset": {"present": False},
            "arguments": {"channel": "stable", "limit": 20, "cursor": None},
        }
        self.assertEqual(self.errors("cli-request.schema.json", request), [])

    def test_wire_contract_rejects_aliases_and_open_nested_records(self) -> None:
        request = {
            "schema_version": "1",
            "query": "cat",
            "language": "en",
            "filters": {},
            "pagination": {"limit": 20, "cursor": None},
            "sort": "relevance",
            "view": "agent",
        }
        self.assertEqual(self.errors("search-request.schema.json", request), [])
        legacy = copy.deepcopy(request)
        legacy["schema_version"] = "1.0.0"
        self.assertTrue(self.errors("search-request.schema.json", legacy))

        free_record_result = {
            "collection": {
                "record": {"arbitrary": True},
                "runtime_trust": {
                    "control_state_status": "offline-unknown",
                    "review_attestation_status": "unverified",
                    "review_hash_profile_status": "mismatch",
                    "model_qualification_status": "missing",
                    "generation_attestation_status": "missing",
                    "safe_eligible": False,
                },
            },
            "memberships": [],
            "next_cursor": {"present": False},
        }
        self.assertTrue(self.errors("cli-command-result.schema.json", free_record_result))

    def test_manifest_histograms_require_every_closed_status_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = build_index(ROOT, Path(temporary) / "dist", **BUILD_ARGS)
        self.assertEqual(self.errors("release-manifest.schema.json", manifest), [])

        bogus = copy.deepcopy(manifest)
        bogus["counts"]["availability_by_status"]["emojis"]["bogus"] = 1
        self.assertTrue(self.errors("release-manifest.schema.json", bogus))

        missing = copy.deepcopy(manifest)
        del missing["counts"]["emoji_review_by_status"]["rejected"]
        self.assertTrue(self.errors("release-manifest.schema.json", missing))


if __name__ == "__main__":
    unittest.main()
