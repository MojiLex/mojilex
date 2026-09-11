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
    load_json,
    load_jsonl,
    pretty_json,
)
from tools.validate import validate_repository

ROOT = Path(__file__).resolve().parents[1]
REVISION = "0123456789abcdef0123456789abcdef01234567"


class BuildIndexTests(unittest.TestCase):
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
            base = Path(temporary)
            repository = base / "repository"
            repository.mkdir()
            copy_repository_contract(ROOT, repository)
            install_example_as_canonical(ROOT, repository)
            first, second = base / "first", base / "second"
            build_index(repository, first, revision=REVISION)
            build_index(repository, second, revision=REVISION)
            first_bytes = {
                path.relative_to(first): path.read_bytes()
                for path in first.iterdir()
                if path.is_file()
            }
            second_bytes = {
                path.relative_to(second): path.read_bytes()
                for path in second.iterdir()
                if path.is_file()
            }
            self.assertEqual(first_bytes, second_bytes)
            build_index(repository, first, revision=REVISION)
            rebuilt_bytes = {
                path.relative_to(first): path.read_bytes()
                for path in first.iterdir()
                if path.is_file()
            }
            self.assertEqual(first_bytes, rebuilt_bytes)

    def test_build_refuses_to_replace_an_unrecognized_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "important"
            output.mkdir()
            note = output / "notes.txt"
            note.write_text("keep me\n", encoding="utf-8", newline="")
            with self.assertRaisesRegex(ValueError, "non-build directory"):
                build_index(ROOT, output, revision=REVISION)
            self.assertEqual(note.read_text(encoding="utf-8"), "keep me\n")

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_build_rejects_output_junction_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            outside = base / "outside"
            output = base / "dist-link"
            outside.mkdir()
            sentinel = outside / "preserve.txt"
            sentinel.write_text("keep", encoding="utf-8")
            self._create_windows_junction(output, outside)

            with self.assertRaisesRegex(ValueError, "link or reparse point"):
                build_index(ROOT, output, revision=REVISION)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
            self.assertFalse((outside / "manifest.json").exists())

    def test_build_rejects_canonical_dataset_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repository"
            repository.mkdir()
            copy_repository_contract(ROOT, repository)
            install_example_as_canonical(ROOT, repository)
            output = repository / "data" / "generated-index"

            with self.assertRaisesRegex(ValueError, "canonical data"):
                build_index(repository, output, revision=REVISION)

            self.assertFalse(output.exists())

    def test_build_rejects_dataset_ancestor_without_deleting_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repository"
            repository.mkdir()
            copy_repository_contract(ROOT, repository)
            install_example_as_canonical(ROOT, repository)
            sentinel = base / "preserve.txt"
            sentinel.write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "contain the dataset root"):
                build_index(repository, base, revision=REVISION)

            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
            self.assertTrue((repository / "dataset.json").is_file())

    def test_active_and_search_indexes_follow_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repository"
            repository.mkdir()
            copy_repository_contract(ROOT, repository)
            expected = install_example_as_canonical(ROOT, repository)
            output = base / "dist"
            manifest = build_index(repository, output, revision=REVISION)
            active = load_jsonl(output / "emojis-active.jsonl")
            search_ru = load_jsonl(output / "search-ru.jsonl")
            self.assertEqual([item["id"] for item in active], [expected["emoji"]["id"]])
            self.assertEqual([item["emoji_id"] for item in search_ru], [expected["emoji"]["id"]])
            self.assertEqual(search_ru[0]["collection_ids"], [expected["collection"]["id"]])
            self.assertEqual(manifest["counts"]["active_emojis"], 1)

    def test_one_emoji_can_belong_to_two_collections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
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
            manifest = build_index(repository, output, revision=REVISION)
            search = load_jsonl(output / "search-en.jsonl")
            self.assertEqual(manifest["counts"]["collections"], 2)
            self.assertEqual(manifest["counts"]["emojis"], 1)
            self.assertEqual(
                search[0]["collection_ids"],
                sorted([values["collection"]["id"], second["id"]]),
            )

    def test_manifest_and_sha256sums_cover_every_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "dist"
            manifest = build_index(ROOT, output, revision=REVISION)
            self.assertEqual(set(manifest["payload_sha256"]), set(PAYLOAD_NAMES))
            for name in PAYLOAD_NAMES:
                actual = hashlib.sha256((output / name).read_bytes()).hexdigest()
                self.assertEqual(manifest["payload_sha256"][name], actual)
            sums = (output / "SHA256SUMS").read_text(encoding="ascii").splitlines()
            names = [line.split("  ", 1)[1] for line in sums]
            self.assertEqual(names, sorted([*PAYLOAD_NAMES, "manifest.json"]))
            self.assertNotIn("SHA256SUMS", names)

    def test_taxonomy_snapshot_defensively_accepts_repo_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
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
            build_index(repository, output, revision=REVISION)
            self.assertEqual(load_json(output / "taxonomy.json")["taxonomy_version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
