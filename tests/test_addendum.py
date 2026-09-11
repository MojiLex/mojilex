from __future__ import annotations

import copy
import tempfile
import unittest
import uuid
from pathlib import Path

from tests.helpers import copy_repository_contract, install_example_as_canonical
from tools.build_index import build_index
from tools.common import (
    compact_json,
    entity_shard,
    expected_entity_id,
    expected_visual_relation_id,
    load_json,
    load_jsonl,
    media_digest,
    pretty_json,
    reviewed_content_sha256,
    reviewed_relation_sha256,
)
from tools.validate import validate_repository

ROOT = Path(__file__).resolve().parents[1]
REVISION = "fedcba9876543210fedcba9876543210fedcba98"


def _write_emoji(root: Path, emoji: dict) -> None:
    shard = entity_shard(emoji["id"], 4)
    path = root / "data" / emoji["platform"] / "emojis" / shard[:2] / f"{shard[2:]}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    values = load_jsonl(path) if path.exists() else []
    values = [value for value in values if value["id"] != emoji["id"]]
    values.append(emoji)
    values.sort(key=lambda value: value["id"])
    path.write_text(
        "".join(compact_json(value) + "\n" for value in values),
        encoding="utf-8",
        newline="",
    )


def _second_emoji(root: Path, first: dict) -> dict:
    dataset = load_json(root / "dataset.json")
    value = copy.deepcopy(first)
    value["native_id"] = "5368324170671202287"
    value["extensions"]["telegram"]["custom_emoji_id"] = value["native_id"]
    value["extensions"]["telegram"]["file_unique_id"] = "AgADExampleUniqueIdTwo"
    value["id"] = expected_entity_id(value, uuid.UUID(dataset["id_namespace"]))
    _write_emoji(root, value)
    return value


def _write_relation(root: Path, left: dict, right: dict) -> dict:
    dataset = load_json(root / "dataset.json")
    subject, object_ = sorted([left, right], key=lambda value: value["id"])
    relation = {
        "schema_version": "1.0.0",
        "entity_type": "visual_relation",
        "id": "",
        "identity_epoch": 0,
        "subject_id": subject["id"],
        "object_id": object_["id"],
        "scope": "entity",
        "relation_type": "same-artwork",
        "evidence": {
            "dedupe_profile": "dedupe-v1",
            "subject_media_digest": media_digest(subject["media"]),
            "object_media_digest": media_digest(object_["media"]),
            "media_pairs": [{"subject_role": "primary", "object_role": "primary"}],
            "signals": ["canonical-render-match"],
        },
        "review": {
            "status": "approved",
            "reviewer": "example-reviewer",
            "reviewed_at": "2026-09-11T12:00:00Z",
            "reviewed_relation_sha256": "",
        },
    }
    namespace = uuid.UUID(dataset["visual_relation_namespace"])
    relation["id"] = expected_visual_relation_id(relation, namespace)
    relation["review"]["reviewed_relation_sha256"] = reviewed_relation_sha256(relation)
    shard = entity_shard(relation["id"], 4)
    path = root / "data" / "relations" / "visual" / shard[:2] / f"{shard[2:]}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(compact_json(relation) + "\n", encoding="utf-8", newline="")
    return relation


class AddendumValidationTests(unittest.TestCase):
    def test_example_has_complete_bound_analysis(self) -> None:
        emoji = load_json(ROOT / "examples" / "telegram" / "emoji.json")
        self.assertEqual(
            [(item["role"], item.get("variant_id")) for item in emoji["media"]],
            [
                (item["role"], item.get("variant_id"))
                for item in emoji["facets"]["rendering"]["items"]
            ],
        )
        self.assertEqual(
            [(item["role"], item.get("variant_id")) for item in emoji["media"]],
            [(item["role"], item.get("variant_id")) for item in emoji["fingerprints"]["items"]],
        )
        self.assertEqual(emoji["fingerprints"]["input_media_digest"], media_digest(emoji["media"]))

    def test_missing_rendering_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository_contract(ROOT, root)
            values = install_example_as_canonical(ROOT, root)
            emoji = values["emoji"]
            emoji["facets"]["rendering"]["items"] = []
            _write_emoji(root, emoji)
            report = validate_repository(root, include_examples=True, check_build=False)
            self.assertTrue(any("rendering.items" in item for item in report.errors))

    def test_telegram_adaptive_mapping_and_palette_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository_contract(ROOT, root)
            values = install_example_as_canonical(ROOT, root)
            emoji = values["emoji"]
            emoji["extensions"]["telegram"]["needs_repainting"] = True
            _write_emoji(root, emoji)
            report = validate_repository(root, include_examples=True, check_build=False)
            self.assertTrue(any("needs_repainting" in item for item in report.errors))

            rendering = emoji["facets"]["rendering"]["items"][0]
            rendering["color_behavior"] = "platform-adaptive"
            _write_emoji(root, emoji)
            report = validate_repository(root, include_examples=True, check_build=False)
            self.assertTrue(any("dominant_colors" in item for item in report.errors))

    def test_static_text_dynamics_and_motion_uncertainty_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository_contract(ROOT, root)
            values = install_example_as_canonical(ROOT, root)
            emoji = values["emoji"]
            emoji["media"][0].update(
                {
                    "kind": "static",
                    "format": "webp",
                    "mime_type": "image/webp",
                    "animated": False,
                }
            )
            del emoji["media"][0]["duration_ms"]
            emoji["descriptions"]["ru"] = {
                "text": "Жёлтый кот с приподнятой бровью.",
                "motion_status": "undetermined",
                "usage": ["сомнение"],
            }
            emoji["descriptions"]["en"] = {
                "text": "A yellow cat with one raised eyebrow.",
                "motion_status": "not_applicable",
                "usage": ["doubt"],
            }
            emoji["facets"]["text_content"]["dynamics"] = "changing"
            emoji["fingerprints"]["input_media_digest"] = media_digest(emoji["media"])
            emoji["fingerprints"]["items"][0]["perceptual"]["sample_count"] = 1
            for key in ("layout_phash64", "content_phash64", "alpha_phash64", "edge_phash64"):
                emoji["fingerprints"]["items"][0]["perceptual"][key] = "AAAAAAAAAAA"
            _write_emoji(root, emoji)
            report = validate_repository(root, include_examples=True, check_build=False)
            self.assertTrue(any("text_content.dynamics" in item for item in report.errors))
            self.assertTrue(any("requires motion uncertainty" in item for item in report.errors))

    def test_stale_partial_and_malformed_fingerprints_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository_contract(ROOT, root)
            values = install_example_as_canonical(ROOT, root)
            emoji = values["emoji"]
            emoji["fingerprints"]["status"] = "partial"
            emoji["fingerprints"]["input_media_digest"] = "0" * 64
            emoji["fingerprints"]["items"][0]["perceptual"]["layout_phash64"] = "AAAA"
            _write_emoji(root, emoji)
            report = validate_repository(root, include_examples=True, check_build=False)
            self.assertTrue(any("partial is forbidden" in item for item in report.errors))
            self.assertTrue(any("input_media_digest mismatch" in item for item in report.errors))
            self.assertTrue(any("decoded length" in item for item in report.errors))

    def test_facet_change_invalidates_approved_review_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository_contract(ROOT, root)
            values = install_example_as_canonical(ROOT, root)
            emoji = values["emoji"]
            emoji["facets"]["styles"] = ["cartoon", "flat", "minimal"]
            _write_emoji(root, emoji)
            report = validate_repository(root, include_examples=True, check_build=False)
            self.assertTrue(
                any("reviewed_content_sha256 mismatch" in item for item in report.errors)
            )

    def test_approved_review_can_confirm_intentional_style_contrast(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository_contract(ROOT, root)
            values = install_example_as_canonical(ROOT, root)
            emoji = values["emoji"]
            emoji["facets"]["styles"] = ["cartoon", "detailed", "flat", "minimal"]
            emoji["review"]["reviewed_content_sha256"] = reviewed_content_sha256(emoji)
            _write_emoji(root, emoji)
            report = validate_repository(root, include_examples=True, check_build=False)
            self.assertFalse(any("minimal + detailed" in item for item in report.errors))

    def test_controlled_facet_is_not_repeated_in_semantic_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository_contract(ROOT, root)
            values = install_example_as_canonical(ROOT, root)
            emoji = values["emoji"]
            emoji["semantic_tags"].append("reaction")
            emoji["semantic_tags"].sort()
            _write_emoji(root, emoji)
            report = validate_repository(root, include_examples=True, check_build=False)
            self.assertTrue(any("duplicates controlled facets" in item for item in report.errors))

    def test_unqualified_ai_is_blocking_until_human_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository_contract(ROOT, root)
            values = install_example_as_canonical(ROOT, root)
            emoji = values["emoji"]
            emoji["review"] = {"status": "unreviewed"}
            _write_emoji(root, emoji)
            report = validate_repository(root, include_examples=True, check_build=False)
            self.assertTrue(
                any("blocking review reason unqualified-model" in item for item in report.errors)
            )

    def test_exact_active_qualification_allows_unreviewed_ai(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository_contract(ROOT, root)
            values = install_example_as_canonical(ROOT, root)
            emoji = values["emoji"]
            emoji["review"] = {"status": "unreviewed"}
            emoji["provenance"]["qualification_id"] = "mq_standard-v1_example-001"
            _write_emoji(root, emoji)
            qualification = {
                "qualification_id": "mq_standard-v1_example-001",
                "provider": emoji["provenance"]["provider"],
                "model": emoji["provenance"]["model"],
                "description_profile": "standard-v1",
                "prompt_sha256": emoji["provenance"]["prompt_sha256"],
                "request_parameters_sha256": emoji["provenance"]["request_parameters_sha256"],
                "schema_version": "1.0.0",
                "taxonomy_version": "1.0.0",
                "pipeline_version": emoji["provenance"]["pipeline_version"],
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
            registry = load_json(root / "quality" / "model-qualifications.json")
            registry["entries"] = [qualification]
            (root / "quality" / "model-qualifications.json").write_text(
                pretty_json(registry), encoding="utf-8", newline=""
            )
            report = validate_repository(root, include_examples=True, check_build=False)
            self.assertEqual(report.errors, [], "\n".join(report.errors))

    def test_visual_relation_stale_evidence_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository_contract(ROOT, root)
            values = install_example_as_canonical(ROOT, root)
            second = _second_emoji(root, values["emoji"])
            relation = _write_relation(root, values["emoji"], second)
            relation["evidence"]["subject_media_digest"] = "0" * 64
            relation["review"]["reviewed_relation_sha256"] = reviewed_relation_sha256(relation)
            shard = entity_shard(relation["id"], 4)
            path = root / "data" / "relations" / "visual" / shard[:2] / f"{shard[2:]}.jsonl"
            path.write_text(compact_json(relation) + "\n", encoding="utf-8", newline="")
            report = validate_repository(root, include_examples=True, check_build=False)
            self.assertTrue(any("stale visual relation" in item for item in report.errors))

    def test_same_artwork_rejects_empty_text_against_approved_literal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository_contract(ROOT, root)
            values = install_example_as_canonical(ROOT, root)
            second = _second_emoji(root, values["emoji"])
            second["facets"]["text_content"] = {
                "status": "recognized",
                "dynamics": "stable",
                "items": [
                    {
                        "value": "404",
                        "kind": "number",
                        "script": "Zyyy",
                        "temporal_scope": "persistent",
                        "media_refs": [{"role": "primary"}],
                    }
                ],
            }
            second["facets"]["content_types"] = sorted(
                {*second["facets"]["content_types"], "number", "text"}
            )
            second["review"]["reviewed_content_sha256"] = reviewed_content_sha256(second)
            _write_emoji(root, second)
            _write_relation(root, values["emoji"], second)

            report = validate_repository(root, include_examples=True, check_build=False)

            self.assertTrue(
                any(
                    "same-artwork is forbidden for approved records with different literal text"
                    in item
                    for item in report.errors
                )
            )

    def test_build_emits_facets_groups_relations_and_taxonomy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "repository"
            root.mkdir()
            copy_repository_contract(ROOT, root)
            values = install_example_as_canonical(ROOT, root)
            second = _second_emoji(root, values["emoji"])
            _write_relation(root, values["emoji"], second)
            output = base / "dist"
            manifest = build_index(root, output, revision=REVISION)
            self.assertGreaterEqual(manifest["counts"]["duplicate_groups"], 4)
            self.assertEqual(manifest["counts"]["visual_relations"], 1)
            self.assertTrue((output / "collection-facets.jsonl").is_file())
            self.assertTrue((output / "duplicate-groups.jsonl").is_file())
            self.assertTrue((output / "visual-relations.jsonl").is_file())
            self.assertEqual(load_json(output / "taxonomy.json")["taxonomy_version"], "1.0.0")
            collection_facets = load_jsonl(output / "collection-facets.jsonl")[0]
            self.assertEqual(collection_facets["media_kind_counts"], {"video": 1})
            self.assertEqual(collection_facets["fixed_share_bp"], 10000)
            self.assertEqual(collection_facets["content_type_counts"], {"animal": 1, "reaction": 1})
            self.assertGreaterEqual(collection_facets["exact_duplicate_group_count"], 4)
            self.assertEqual(collection_facets["reviewed_visual_duplicate_group_count"], 1)
            search = load_jsonl(output / "search-en.jsonl")
            self.assertEqual(search[0]["facets"]["content_types"], ["animal", "reaction"])
            self.assertTrue(search[0]["duplicate_group_ids"])

    def test_deprecated_taxonomy_id_has_unambiguous_replacement(self) -> None:
        registry = load_json(ROOT / "taxonomy" / "v1" / "content-types.json")
        entries = {entry["id"]: entry for entry in registry["entries"]}
        self.assertEqual(entries["ui-icon"]["status"], "deprecated")
        self.assertEqual(entries["ui-icon"]["replaced_by"], "technical-icon")
        self.assertEqual(entries["technical-icon"]["status"], "active")

    def test_taxonomy_and_platform_registry_contracts_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_repository_contract(ROOT, root)
            taxonomy = load_json(root / "taxonomy" / "v1" / "taxonomy.json")
            taxonomy["registries"][0]["facet"] = "styles"
            (root / "taxonomy" / "v1" / "taxonomy.json").write_text(
                pretty_json(taxonomy), encoding="utf-8", newline=""
            )
            telegram = load_json(root / "platforms" / "telegram.json")
            telegram["item_facts"]["needs_repainting"]["mapping"]["true"] = "fixed"
            (root / "platforms" / "telegram.json").write_text(
                pretty_json(telegram), encoding="utf-8", newline=""
            )
            report = validate_repository(root, include_examples=True, check_build=False)
            self.assertTrue(any("facet/path set" in item for item in report.errors))
            self.assertTrue(any("needs_repainting mapping" in item for item in report.errors))


if __name__ == "__main__":
    unittest.main()
