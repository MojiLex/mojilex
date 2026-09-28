from __future__ import annotations

import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import git_provenance
from tools.build_index import main as build_main
from tools.git_provenance import resolve_head_revision, verify_release_source


class GitProvenanceTests(unittest.TestCase):
    @staticmethod
    def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "git",
                "-c",
                f"safe.directory={root.as_posix()}",
                "-C",
                str(root),
                *arguments,
            ],
            check=check,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def _repository(self, base: Path, *, object_format: str = "sha1") -> tuple[Path, str]:
        root = base / "repository"
        root.mkdir()
        initialized = self._git(
            root,
            "init",
            "--initial-branch=main",
            f"--object-format={object_format}",
            check=False,
        )
        if initialized.returncode:
            self.skipTest(f"Git {object_format} repositories are unavailable")
        self._git(root, "config", "user.name", "MojiLex Tests")
        self._git(root, "config", "user.email", "tests@example.invalid")
        files = {
            "dataset.json": b"{}\n",
            "requirements-dev.txt": b"jsonschema==4.25.1\n",
            "tools/build_index.py": b"# fixture\n",
            "tools/common.py": b"# fixture\n",
            "tools/git_provenance.py": b"# fixture\n",
            "tools/spec003_build.py": b"# fixture\n",
            "schemas/v1/common.schema.json": b"{}\n",
            "schemas/distribution/v1/release-manifest.schema.json": b"{}\n",
            "analysis-profiles/distribution-v1.json": b"{}\n",
            "platforms/telegram.json": b"{}\n",
            "rights/profiles.json": b"{}\n",
            "taxonomy/v1/taxonomy.json": b"{}\n",
            "data/telegram/emojis/00/00.jsonl": b"{}\n",
            "data/telegram/collections/README.md": b"# Catalog\n\nMore lines\n",
            "data/telegram/collections/example/collection.json": b"{}\n",
            "data/telegram/collections/example/memberships.jsonl": b"",
            "data/relations/visual/00/00.jsonl": b"{}\n",
            "examples/test-vectors.json": b"{}\n",
            "quality/model-qualifications.json": b"{}\n",
            "quality/description-profiles/standard-v1.json": b"{}\n",
            "tombstones/00/example.json": b"{}\n",
        }
        for relative, content in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self._git(root, "add", "--all")
        self._git(root, "commit", "-m", "fixture")
        revision = self._git(root, "rev-parse", "HEAD").stdout.strip()
        return root, revision

    def test_accepts_exact_committed_source_and_reports_object_format(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, revision = self._repository(Path(temporary).resolve())
            actual = verify_release_source(root, revision)
        self.assertEqual(actual.commit, revision)
        self.assertEqual(actual.object_format, "sha1")

    def test_reads_exact_blob_bytes_across_batches(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, revision = self._repository(Path(temporary).resolve())
            source_count = len(git_provenance._walk_source_candidates(root))
            with (
                patch.object(git_provenance, "_BLOB_BATCH_SIZE", 3),
                patch.object(git_provenance, "_git", wraps=git_provenance._git) as git,
            ):
                self.assertEqual(verify_release_source(root, revision).commit, revision)
            batch_calls = [
                call for call in git.call_args_list if call.args[1:3] == ("cat-file", "--batch")
            ]
        self.assertGreater(len(batch_calls), 1)
        self.assertEqual(len(batch_calls), (source_count + 2) // 3)

    def test_resolves_sha256_repository_when_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, revision = self._repository(Path(temporary).resolve(), object_format="sha256")
            actual = resolve_head_revision(root)
            verified = verify_release_source(root, revision)
        self.assertEqual(len(actual.commit), 64)
        self.assertEqual(actual.object_format, "sha256")
        self.assertEqual(verified, actual)

    def test_rejects_modified_tracked_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, revision = self._repository(Path(temporary).resolve())
            (root / "dataset.json").write_bytes(b'{"changed":true}\n')
            with self.assertRaisesRegex(ValueError, "differs from commit"):
                verify_release_source(root, revision)

    def test_rejects_modified_blob_with_unchanged_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, revision = self._repository(Path(temporary).resolve())
            (root / "quality/model-qualifications.json").write_bytes(b"[]\n")
            with self.assertRaisesRegex(ValueError, "differs from commit"):
                verify_release_source(root, revision)

    def test_rejects_linked_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, revision = self._repository(Path(temporary).resolve())
            path = root / "data/telegram/collections/example/collection.json"
            path.unlink()
            try:
                os.symlink(root / "dataset.json", path)
            except (NotImplementedError, OSError) as exc:
                self.skipTest(f"symlinks are unavailable: {exc}")
            with self.assertRaisesRegex(ValueError, "link or reparse point"):
                verify_release_source(root, revision)

    def test_rejects_modified_collection_and_validation_inputs(self) -> None:
        paths = (
            "data/telegram/collections/example/collection.json",
            "data/telegram/collections/example/memberships.jsonl",
            "data/telegram/collections/README.md",
            "quality/model-qualifications.json",
            "quality/description-profiles/standard-v1.json",
            "examples/test-vectors.json",
        )
        for relative in paths:
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as temporary:
                root, revision = self._repository(Path(temporary).resolve())
                (root / relative).write_bytes(b"changed\n")
                with self.assertRaisesRegex(ValueError, "differs from commit"):
                    verify_release_source(root, revision)

    def test_rejects_untracked_flat_collection_and_quality_inputs(self) -> None:
        paths = (
            "data/telegram/collections/another/collection.json",
            "quality/another-policy.json",
        )
        for relative in paths:
            with self.subTest(path=relative), tempfile.TemporaryDirectory() as temporary:
                root, revision = self._repository(Path(temporary).resolve())
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"{}\n")
                with self.assertRaisesRegex(ValueError, "absent from commit"):
                    verify_release_source(root, revision)

    def test_rejects_untracked_allowlisted_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, revision = self._repository(Path(temporary).resolve())
            (root / "platforms" / "untracked.json").write_bytes(b"{}\n")
            with self.assertRaisesRegex(ValueError, "absent from commit"):
                verify_release_source(root, revision)

    def test_rejects_missing_tracked_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, revision = self._repository(Path(temporary).resolve())
            (root / "requirements-dev.txt").unlink()
            with self.assertRaisesRegex(ValueError, "missing from the worktree"):
                verify_release_source(root, revision)

    def test_rejects_wrong_existing_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, first_revision = self._repository(Path(temporary).resolve())
            (root / "dataset.json").write_bytes(b'{"version":2}\n')
            self._git(root, "add", "dataset.json")
            self._git(root, "commit", "-m", "change source")
            with self.assertRaisesRegex(ValueError, "differs from commit"):
                verify_release_source(root, first_revision)

    def test_rejects_nonexistent_full_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, _revision = self._repository(Path(temporary).resolve())
            with self.assertRaisesRegex(ValueError, "Git provenance check failed"):
                verify_release_source(root, "0" * 40)

    def test_rejects_repository_subdirectory_as_dataset_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, revision = self._repository(Path(temporary).resolve())
            with self.assertRaisesRegex(ValueError, "exact Git worktree top"):
                verify_release_source(root / "data", revision)

    def test_production_command_checks_source_before_building(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, revision = self._repository(Path(temporary).resolve())
            (root / "dataset.json").write_bytes(b'{"changed":true}\n')
            output = Path(temporary).resolve() / "dist"
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                result = build_main(
                    [
                        str(root),
                        "--output",
                        str(output),
                        "--revision",
                        revision,
                        "--snapshot-id",
                        "data-2026.09.11.1",
                        "--source-date-epoch",
                        "1789171199",
                        "--skip-validation",
                    ]
                )
            self.assertEqual(result, 1)
            self.assertIn("differs from commit", stderr.getvalue())
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
