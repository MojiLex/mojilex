from __future__ import annotations

import copy
import hashlib
import os
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path

from tests.helpers import copy_repository_contract, install_example_as_canonical
from tools.build_index import PAYLOAD_NAMES, build_index
from tools.common import (
    compact_json,
    entity_shard,
    expected_entity_id,
    jcs_bytes,
    jcs_sha256,
    load_json,
    load_jsonl,
    pretty_json,
)
from tools.validate import validate_repository
from tools.validate_distribution import validate_distribution

ROOT = Path(__file__).resolve().parents[1]
REVISION = "0123456789abcdef0123456789abcdef01234567"
BUILD_ARGS = {
    "revision": REVISION,
    "snapshot_id": "data-2026.09.11.1",
    "source_date_epoch": 1789171199,
}


class BuildIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        cls.fixture_root = Path(temporary.name).resolve()
        # A fixed release epoch must use fixed evidence, not newly submitted packs.
        copy_repository_contract(ROOT, cls.fixture_root)
        install_example_as_canonical(ROOT, cls.fixture_root)

    @staticmethod
    def _create_windows_junction(link: Path, target: Path) -> None:
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if completed.returncode != 0:
            raise unittest.SkipTest(f"junction creation is unavailable: {completed.stderr.strip()}")

    def test_build_is_byte_for_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            repository = base / "repository"
            repository.mkdir()
            copy_repository_contract(ROOT, repository)
            install_example_as_canonical(ROOT, repository)
            first, second = base / "first", base / "second"
            build_index(repository, first, **BUILD_ARGS)
            build_index(repository, second, **BUILD_ARGS)
            first_bytes = {
                path.relative_to(first): path.read_bytes()
                for path in first.rglob("*")
                if path.is_file()
            }
            second_bytes = {
                path.relative_to(second): path.read_bytes()
                for path in second.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_bytes, second_bytes)
            build_index(repository, first, **BUILD_ARGS)
            rebuilt_bytes = {
                path.relative_to(first): path.read_bytes()
                for path in first.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_bytes, rebuilt_bytes)

    def test_build_refuses_to_replace_an_unrecognized_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "important"
            output.mkdir()
            note = output / "notes.txt"
            note.write_text("keep me\n", encoding="utf-8", newline="")
            with self.assertRaisesRegex(ValueError, "non-build directory"):
                build_index(self.fixture_root, output, **BUILD_ARGS)
            self.assertEqual(note.read_text(encoding="utf-8"), "keep me\n")

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_build_rejects_output_junction_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            outside = base / "outside"
            output = base / "dist-link"
            outside.mkdir()
            sentinel = outside / "preserve.txt"
            sentinel.write_text("keep", encoding="utf-8")
            self._create_windows_junction(output, outside)

            with self.assertRaisesRegex(ValueError, "link or reparse point"):
                build_index(self.fixture_root, output, **BUILD_ARGS)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
            self.assertFalse((outside / "manifest.json").exists())

    def test_build_rejects_canonical_dataset_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            repository = base / "repository"
            repository.mkdir()
            copy_repository_contract(ROOT, repository)
            install_example_as_canonical(ROOT, repository)
            output = repository / "data" / "generated-index"

            with self.assertRaisesRegex(ValueError, "canonical data"):
                build_index(repository, output, **BUILD_ARGS)

            self.assertFalse(output.exists())

    def test_build_rejects_dataset_ancestor_without_deleting_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            repository = base / "repository"
            repository.mkdir()
            copy_repository_contract(ROOT, repository)
            install_example_as_canonical(ROOT, repository)
            sentinel = base / "preserve.txt"
            sentinel.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "contain the dataset root"):
                build_index(repository, base, **BUILD_ARGS)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
            self.assertTrue((repository / "dataset.json").is_file())

    def test_active_and_search_indexes_follow_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            repository = base / "repository"
            repository.mkdir()
            copy_repository_contract(ROOT, repository)
            expected = install_example_as_canonical(ROOT, repository)
            output = base / "dist"
            manifest = build_index(repository, output, **BUILD_ARGS)
            active = load_jsonl(output / "emojis-active.jsonl")
            search_ru = load_jsonl(output / "search-ru.jsonl")
            self.assertEqual([item["id"] for item in active], [expected["emoji"]["id"]])
            self.assertEqual([item["emoji_id"] for item in search_ru], [expected["emoji"]["id"]])
            self.assertEqual(search_ru[0]["collection_ids"], [expected["collection"]["id"]])
            self.assertEqual(manifest["counts"]["active_emojis"], 1)

    def test_one_emoji_can_belong_to_two_collections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            repository = base / "repository"
            repository.mkdir()
            copy_repository_contract(ROOT, repository)
            values = install_example_as_canonical(ROOT, repository)
            namespace = uuid.UUID(load_json(repository / "dataset.json")["id_namespace"])

            second = copy.deepcopy(values["collection"])
            second["native_id"] = "SuspiciousCatsTwo"
            second["title"] = "Suspicious Cats Two"
            second["canonical_url"] = "https://t.me/addemoji/SuspiciousCatsTwo"
            second["extensions"]["telegram"]["short_name"] = "SuspiciousCatsTwo"
            second["id"] = expected_entity_id(second, namespace)
            second_membership = copy.deepcopy(values["membership"])
            second_membership["collection_id"] = second["id"]
            second_membership["id"] = expected_entity_id(second_membership, namespace)

            second_dir = (
                repository
                / "data"
                / "telegram"
                / "collections"
                / entity_shard(second["id"])
                / second["id"]
            )
            second_dir.mkdir(parents=True)
            (second_dir / "collection.json").write_text(
                pretty_json(second), encoding="utf-8", newline=""
            )
            (second_dir / "memberships.jsonl").write_text(
                compact_json(second_membership) + "\n", encoding="utf-8", newline=""
            )

            report = validate_repository(repository, include_examples=True, check_build=False)
            self.assertEqual(report.errors, [], "\n".join(report.errors))
            output = base / "dist"
            manifest = build_index(repository, output, **BUILD_ARGS)
            search = load_jsonl(output / "search-en.jsonl")
            self.assertEqual(manifest["counts"]["collections"], 2)
            self.assertEqual(manifest["counts"]["emojis"], 1)
            self.assertEqual(
                search[0]["collection_ids"],
                sorted([values["collection"]["id"], second["id"]]),
            )

    def test_manifest_and_sha256sums_cover_every_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "dist"
            manifest = build_index(self.fixture_root, output, **BUILD_ARGS)
            descriptors = {item["path"]: item for item in manifest["artifacts"]}
            self.assertEqual(set(descriptors), set(PAYLOAD_NAMES))
            for name, descriptor in descriptors.items():
                actual = hashlib.sha256((output / name).read_bytes()).hexdigest()
                self.assertEqual(descriptor["payload_sha256"], actual)
            sums = (output / "SHA256SUMS").read_text(encoding="ascii").splitlines()
            names = [line.split("  ", 1)[1] for line in sums]
            physical_paths = [
                item["path"]
                for item in manifest["resources"]
                if item["resource_kind"] == "physical"
            ]
            self.assertEqual(names, sorted([*PAYLOAD_NAMES, *physical_paths, "manifest.json"]))
            self.assertNotIn("SHA256SUMS", names)
            self.assertEqual((output / "manifest.json").read_bytes(), jcs_bytes(manifest))
            self.assertFalse((output / "manifest.json").read_bytes().endswith(b"\n"))
            report = validate_distribution(self.fixture_root, output)
            self.assertEqual(report.errors, [], "\n".join(report.errors))

            embedded_schema = next(
                item
                for item in manifest["resources"]
                if item.get("source_path")
                == "schemas/distribution/v1/cli-read-envelope.schema.json"
            )
            (output / embedded_schema["path"]).write_bytes(b"{}")
            tampered = validate_distribution(self.fixture_root, output)
            self.assertTrue(
                any(
                    "resource hash mismatch" in error
                    or "resource bytes differ from canonical source_path" in error
                    for error in tampered.errors
                ),
                "\n".join(tampered.errors),
            )

    def test_canonical_state_root_uses_exact_policy_entry_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manifest = build_index(
                self.fixture_root, Path(temporary).resolve() / "dist", **BUILD_ARGS
            )
        entries = []
        for descriptor in manifest["artifacts"]:
            if descriptor["semantic_role"] not in {"canonical", "normative"}:
                continue
            recordset = descriptor["content_model"] == "recordset-jsonl"
            entries.append(
                {
                    "entry_type": "artifact",
                    "entry_name": descriptor["logical_name"],
                    "semantic_role": descriptor["semantic_role"],
                    "digest_kind": "table-root" if recordset else "payload",
                    "sha256": (
                        descriptor["table_root_sha256"]
                        if recordset
                        else descriptor["payload_sha256"]
                    ),
                }
            )
        for field, selector in manifest["profiles"].items():
            if selector["root_scope"] == "canonical":
                entries.append(
                    {
                        "entry_type": "input",
                        "entry_name": f"profile:{field}:{selector['id']}",
                        "semantic_role": "normative",
                        "digest_kind": "input",
                        "sha256": selector["sha256"],
                    }
                )
        for field, selector in manifest["policies"].items():
            if selector["root_scope"] == "canonical":
                entries.append(
                    {
                        "entry_type": "input",
                        "entry_name": f"policy:{field}",
                        "semantic_role": "normative",
                        "digest_kind": "input",
                        "sha256": selector["sha256"],
                    }
                )
        entries.sort(
            key=lambda entry: jcs_bytes(
                [entry["semantic_role"], entry["entry_type"], entry["entry_name"]]
            )
        )
        self.assertEqual(
            manifest["canonical_state_root_sha256"],
            jcs_sha256({"profile": "state-roots-v1", "entries": entries}),
        )

    def test_build_requires_immutable_release_identity_inputs(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaisesRegex(ValueError, "snapshot_id and source_date_epoch"),
        ):
            build_index(self.fixture_root, Path(temporary).resolve() / "dist", revision=REVISION)

    def test_build_rejects_impossible_snapshot_calendar_date(self) -> None:
        with (
            tempfile.TemporaryDirectory() as temporary,
            self.assertRaisesRegex(ValueError, "invalid UTC calendar date"),
        ):
            build_index(
                self.fixture_root,
                Path(temporary).resolve() / "dist",
                revision=REVISION,
                snapshot_id="data-2026.02.31.1",
                source_date_epoch=BUILD_ARGS["source_date_epoch"],
            )

    def test_taxonomy_snapshot_defensively_accepts_repo_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            repository = base / "repository"
            repository.mkdir()
            copy_repository_contract(ROOT, repository)
            taxonomy_manifest_path = repository / "taxonomy" / "v1" / "taxonomy.json"
            taxonomy_manifest = load_json(taxonomy_manifest_path)
            for entry in taxonomy_manifest["registries"]:
                entry["path"] = f"taxonomy/v1/{entry['path']}"
            taxonomy_manifest_path.write_text(
                pretty_json(taxonomy_manifest), encoding="utf-8", newline=""
            )
            output = base / "dist"
            build_index(repository, output, **BUILD_ARGS)
            self.assertEqual(load_json(output / "taxonomy.json")["registry_type"], "facet-taxonomy")


if __name__ == "__main__":
    unittest.main()
