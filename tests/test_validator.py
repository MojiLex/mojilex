from __future__ import annotations

import base64
import copy
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from tests.helpers import copy_repository_contract, install_example_as_canonical
from tools.common import (
    compact_json,
    pretty_json,
    reviewed_content_sha256,
    telegram_set_fingerprint,
)
from tools.validate import validate_repository

ROOT = Path(__file__).resolve().parents[1]


def _initialize_git_repository(root: Path) -> None:
    (root / ".gitignore").write_text(
        "/.mojilex/\n/.mojilex-atomic-write/\n",
        encoding="utf-8",
        newline="",
    )
    subprocess.run(
        ["git", "init", "--quiet", str(root)],
        check=True,
        capture_output=True,
        shell=False,
    )


def _configure_git_identity(root: Path) -> None:
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "audit@example.invalid"],
        check=True,
        capture_output=True,
        shell=False,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "MojiLex audit"],
        check=True,
        capture_output=True,
        shell=False,
    )


class RepositoryValidatorTests(unittest.TestCase):
    def test_clean_repository_passes_strict_validation(self) -> None:
        report = validate_repository(ROOT, include_examples=True, check_build=True)
        self.assertEqual(report.errors, [], "\n".join(report.errors))

    def test_complete_canonical_example_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            copy_repository_contract(ROOT, target)
            install_example_as_canonical(ROOT, target)
            report = validate_repository(target, include_examples=True, check_build=True)
            self.assertEqual(report.errors, [], "\n".join(report.errors))

    def test_ignored_runtime_transaction_tree_is_not_scanned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            copy_repository_contract(ROOT, target)
            install_example_as_canonical(ROOT, target)
            _initialize_git_repository(target)
            payload = target / ".mojilex" / "locks" / "active.lock"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"ignored\0github_" + b"pat_" + b"x" * 40)

            report = validate_repository(target, include_examples=True, check_build=False)

            self.assertEqual(report.errors, [], "\n".join(report.errors))

    def test_force_tracked_transaction_artifact_is_rejected_before_file_reads(self) -> None:
        for tree in (".mojilex", ".mojilex-atomic-write"):
            with self.subTest(tree=tree), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary).resolve()
                copy_repository_contract(ROOT, target)
                install_example_as_canonical(ROOT, target)
                _initialize_git_repository(target)
                payload = target / tree / "transaction" / "payload"
                payload.parent.mkdir(parents=True)
                payload.write_bytes(b"must-not-be-read\0")
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(target),
                        "add",
                        "--force",
                        "--",
                        payload.relative_to(target),
                    ],
                    check=True,
                    capture_output=True,
                    shell=False,
                )

                with mock.patch(
                    "tools.validate._schema_environment",
                    side_effect=AssertionError("tracked payload reached repository reads"),
                ):
                    report = validate_repository(target, include_examples=True, check_build=False)

                self.assertEqual(len(report.errors), 1, "\n".join(report.errors))
                self.assertIn(payload.relative_to(target).as_posix(), report.errors[0])
                self.assertIn("tracked runtime transaction artifact", report.errors[0])

    def test_repository_scan_does_not_inherit_ancestor_git_excludes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            ancestor = Path(temporary).resolve()
            (ancestor / ".gitignore").write_text("/dataset/\n", encoding="utf-8", newline="")
            subprocess.run(
                ["git", "init", "--quiet", str(ancestor)],
                check=True,
                capture_output=True,
                shell=False,
            )
            target = ancestor / "dataset"
            target.mkdir()
            copy_repository_contract(ROOT, target)
            install_example_as_canonical(ROOT, target)
            (target / "leaked-preview.png").write_bytes(b"\0synthetic binary")
            (target / "notes.txt").write_bytes(
                b"synthetic " + b"123456789" + b":" + b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi\n"
            )

            report = validate_repository(target, include_examples=True, check_build=False)

            self.assertTrue(
                any("binary media/archive extension" in error for error in report.errors),
                "\n".join(report.errors),
            )
            self.assertTrue(
                any("possible Telegram bot token" in error for error in report.errors),
                "\n".join(report.errors),
            )

    def test_force_tracked_ignored_generated_tree_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            copy_repository_contract(ROOT, target)
            install_example_as_canonical(ROOT, target)
            _initialize_git_repository(target)
            payload = target / "dist" / "payload.txt"
            payload.parent.mkdir()
            payload.write_text("generated\n", encoding="utf-8", newline="")
            subprocess.run(
                ["git", "-C", str(target), "add", "--force", "--", payload.relative_to(target)],
                check=True,
                capture_output=True,
                shell=False,
            )

            report = validate_repository(target, include_examples=True, check_build=False)

            self.assertTrue(
                any(
                    "dist/payload.txt" in error
                    and "tracked ignored/runtime/generated artifact" in error
                    for error in report.errors
                ),
                "\n".join(report.errors),
            )

    def test_textual_svg_is_rejected_by_no_media_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            copy_repository_contract(ROOT, target)
            install_example_as_canonical(ROOT, target)
            payload = target / "payload.svg"
            payload.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n',
                encoding="utf-8",
                newline="",
            )

            report = validate_repository(target, include_examples=True, check_build=False)

            self.assertTrue(
                any(
                    "payload.svg" in error and "media/archive extension" in error
                    for error in report.errors
                ),
                "\n".join(report.errors),
            )

    def test_forbidden_git_index_modes_are_rejected(self) -> None:
        for mode, expected in (
            ("120000", "tracked symbolic links"),
            ("160000", "tracked Git submodules"),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary).resolve()
                copy_repository_contract(ROOT, target)
                install_example_as_canonical(ROOT, target)
                _initialize_git_repository(target)
                _configure_git_identity(target)
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(target),
                        "commit",
                        "--quiet",
                        "--allow-empty",
                        "-m",
                        "base",
                    ],
                    check=True,
                    capture_output=True,
                    shell=False,
                )
                if mode == "120000":
                    object_id = (
                        subprocess.run(
                            ["git", "-C", str(target), "hash-object", "-w", "--stdin"],
                            input=b"target\n",
                            check=True,
                            capture_output=True,
                            shell=False,
                        )
                        .stdout.decode("ascii")
                        .strip()
                    )
                else:
                    object_id = subprocess.run(
                        ["git", "-C", str(target), "rev-parse", "HEAD"],
                        check=True,
                        capture_output=True,
                        shell=False,
                        text=True,
                    ).stdout.strip()
                subprocess.run(
                    [
                        "git",
                        "-C",
                        str(target),
                        "update-index",
                        "--add",
                        "--cacheinfo",
                        f"{mode},{object_id},nested-entry",
                    ],
                    check=True,
                    capture_output=True,
                    shell=False,
                )

                report = validate_repository(target, include_examples=True, check_build=False)

                self.assertTrue(
                    any(expected in error and "nested-entry" in error for error in report.errors),
                    "\n".join(report.errors),
                )

    def test_nested_git_repository_marker_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            copy_repository_contract(ROOT, target)
            install_example_as_canonical(ROOT, target)
            _initialize_git_repository(target)
            nested = target / "nested"
            nested.mkdir()
            subprocess.run(
                ["git", "init", "--quiet", str(nested)],
                check=True,
                capture_output=True,
                shell=False,
            )

            report = validate_repository(target, include_examples=True, check_build=False)

            self.assertTrue(
                any(
                    "nested/.git" in error and "nested Git repository marker" in error
                    for error in report.errors
                ),
                "\n".join(report.errors),
            )

    def test_linked_worktree_git_file_preserves_transaction_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve() / "base"
            base.mkdir()
            _initialize_git_repository(base)
            _configure_git_identity(base)
            subprocess.run(
                ["git", "-C", str(base), "commit", "--quiet", "--allow-empty", "-m", "base"],
                check=True,
                capture_output=True,
                shell=False,
            )
            worktree = Path(temporary).resolve() / "worktree"
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(base),
                    "worktree",
                    "add",
                    "--quiet",
                    "-b",
                    "audit",
                    str(worktree),
                ],
                check=True,
                capture_output=True,
                shell=False,
            )
            copy_repository_contract(ROOT, worktree)
            install_example_as_canonical(ROOT, worktree)
            (worktree / ".gitignore").write_text(
                "/.mojilex/\n/.mojilex-atomic-write/\n",
                encoding="utf-8",
                newline="",
            )
            payload = worktree / ".mojilex" / "transactions" / "payload"
            payload.parent.mkdir(parents=True)
            payload.write_bytes(b"tracked\0")
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(worktree),
                    "add",
                    "--force",
                    "--",
                    payload.relative_to(worktree),
                ],
                check=True,
                capture_output=True,
                shell=False,
            )

            report = validate_repository(worktree, include_examples=True, check_build=False)

            self.assertTrue((worktree / ".git").is_file())
            self.assertTrue(
                any(
                    ".mojilex/transactions/payload" in error
                    and "tracked runtime transaction artifact" in error
                    for error in report.errors
                ),
                "\n".join(report.errors),
            )

    def test_large_files_are_streamed_and_secret_scanned(self) -> None:
        for tracked in (False, True):
            with self.subTest(tracked=tracked), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary).resolve()
                copy_repository_contract(ROOT, target)
                install_example_as_canonical(ROOT, target)
                _initialize_git_repository(target)
                payload = target / "large-notes.txt"
                token = b"123456789" + b":" + b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
                with payload.open("wb") as output:
                    output.write(b"x" * (5 * 1024 * 1024 + 64 * 1024 - 6))
                    output.write(b"\n" + token + b"\n")
                if tracked:
                    subprocess.run(
                        ["git", "-C", str(target), "add", "--", payload.relative_to(target)],
                        check=True,
                        capture_output=True,
                        shell=False,
                    )
                original_read_bytes = Path.read_bytes

                def guarded_read_bytes(
                    path: Path, expected=payload, original=original_read_bytes
                ) -> bytes:
                    if path == expected:
                        raise AssertionError("large repository files must not be read wholesale")
                    return original(path)

                with mock.patch.object(Path, "read_bytes", guarded_read_bytes):
                    report = validate_repository(target, include_examples=True, check_build=False)

                self.assertTrue(
                    any(
                        "large-notes.txt" in error and "possible Telegram bot token" in error
                        for error in report.errors
                    ),
                    "\n".join(report.errors),
                )

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression is Windows-specific")
    def test_untracked_junction_is_rejected_without_following_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            target = base / "dataset"
            target.mkdir()
            outside = base / "outside"
            outside.mkdir()
            sentinel = outside / "sentinel.txt"
            sentinel.write_text("outside remains untouched\n", encoding="utf-8", newline="")
            copy_repository_contract(ROOT, target)
            install_example_as_canonical(ROOT, target)
            _initialize_git_repository(target)
            junction = target / "junction"
            subprocess.run(
                ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
                check=True,
                capture_output=True,
                shell=False,
            )

            report = validate_repository(target, include_examples=True, check_build=False)

            self.assertTrue(
                any(
                    "junction" in error and "filesystem reparse points" in error
                    for error in report.errors
                ),
                "\n".join(report.errors),
            )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside remains untouched\n")

    def test_empty_membership_file_is_valid_for_empty_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            copy_repository_contract(ROOT, target)
            values = install_example_as_canonical(ROOT, target)
            collection = values["collection"]
            collection["item_count"] = 0
            collection["extensions"]["telegram"]["set_fingerprint_sha256"] = (
                telegram_set_fingerprint([])
            )
            collection_dir = target / "data" / "telegram" / "collections" / "02" / collection["id"]
            (collection_dir / "collection.json").write_text(
                pretty_json(collection), encoding="utf-8", newline=""
            )
            (collection_dir / "memberships.jsonl").write_bytes(b"")
            report = validate_repository(target, include_examples=True, check_build=True)
            self.assertEqual(report.errors, [], "\n".join(report.errors))

    def test_review_hash_is_recomputed_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            copy_repository_contract(ROOT, target)
            values = install_example_as_canonical(ROOT, target)
            emoji = copy.deepcopy(values["emoji"])
            emoji["review"] = {
                "status": "approved",
                "reviewed_at": "2026-09-10T20:00:00Z",
                "reviewer": "reviewer-one",
                "reviewed_content_sha256": reviewed_content_sha256(emoji),
                "review_hash_profile_id": "semantic-review-content-v3",
            }
            bucket = target / "data" / "telegram" / "emojis" / "a8" / "3e.jsonl"
            bucket.write_text(compact_json(emoji) + "\n", encoding="utf-8", newline="")
            clean = validate_repository(target, include_examples=True, check_build=False)
            self.assertEqual(clean.errors, [], "\n".join(clean.errors))

            emoji["descriptions"]["en"]["text"] = "Changed after review."
            bucket.write_text(compact_json(emoji) + "\n", encoding="utf-8", newline="")
            report = validate_repository(target, include_examples=True, check_build=False)
            self.assertTrue(
                any("reviewed_content_sha256 mismatch" in item for item in report.errors)
            )

    def test_unreviewed_sensitive_content_has_no_content_approval_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            copy_repository_contract(ROOT, target)
            values = install_example_as_canonical(ROOT, target)
            emoji = values["emoji"]
            emoji["content"]["rating"] = "sensitive"
            emoji["review"] = {"status": "unreviewed"}
            bucket = target / "data" / "telegram" / "emojis" / "a8" / "3e.jsonl"
            bucket.write_text(compact_json(emoji) + "\n", encoding="utf-8", newline="")
            report = validate_repository(target, include_examples=True, check_build=False)
            self.assertFalse(any("must be approved" in item for item in report.errors))
            self.assertTrue(any("unqualified-model" in item for item in report.errors))

    def test_approved_sensitive_content_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            copy_repository_contract(ROOT, target)
            values = install_example_as_canonical(ROOT, target)
            emoji = values["emoji"]
            emoji["content"] = {"rating": "sensitive", "warnings": ["flashing"]}
            emoji["review"] = {
                "status": "approved",
                "reviewed_at": "2026-09-10T20:00:00Z",
                "reviewer": "reviewer-one",
                "reviewed_content_sha256": reviewed_content_sha256(emoji),
                "review_hash_profile_id": "semantic-review-content-v3",
            }
            bucket = target / "data" / "telegram" / "emojis" / "a8" / "3e.jsonl"
            bucket.write_text(compact_json(emoji) + "\n", encoding="utf-8", newline="")
            report = validate_repository(target, include_examples=True, check_build=False)
            self.assertEqual(report.errors, [], "\n".join(report.errors))

    def test_duplicate_active_position_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            copy_repository_contract(ROOT, target)
            values = install_example_as_canonical(ROOT, target)
            collection_dir = (
                target / "data" / "telegram" / "collections" / "02" / values["collection"]["id"]
            )
            line = compact_json(values["membership"])
            (collection_dir / "memberships.jsonl").write_text(
                f"{line}\n{line}\n", encoding="utf-8", newline=""
            )
            values["collection"]["item_count"] = 2
            (collection_dir / "collection.json").write_text(
                pretty_json(values["collection"]), encoding="utf-8", newline=""
            )
            report = validate_repository(target, include_examples=True, check_build=False)
            self.assertTrue(any("duplicate active position" in item for item in report.errors))

    def test_tombstone_requires_current_tree_cascade(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary).resolve()
            copy_repository_contract(ROOT, target)
            values = install_example_as_canonical(ROOT, target)
            tombstone = {
                "schema_version": "1.0.0",
                "entity_type": "tombstone",
                "target_entity_type": "emoji",
                "target_id": values["emoji"]["id"],
                "reason_code": "privacy",
                "withheld_at": "2026-09-10T21:00:00Z",
                "public_note": "Record withheld under the MojiLex takedown policy.",
            }
            tombstone_dir = target / "tombstones" / "a8"
            tombstone_dir.mkdir(parents=True)
            (tombstone_dir / f"{tombstone['target_id']}.json").write_text(
                pretty_json(tombstone), encoding="utf-8", newline=""
            )
            report = validate_repository(target, include_examples=True, check_build=False)
            self.assertTrue(any("still exists in public data" in item for item in report.errors))

    def test_encoded_credentials_are_detected_without_echoing_values(self) -> None:
        cases = {
            "base64": base64.b64encode(("github" + "_pat_" + "A" * 40).encode()).decode(),
            "percent": quote("123456" + ":" + "A" * 32, safe=""),
        }
        for label, payload in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary).resolve()
                copy_repository_contract(ROOT, target)
                install_example_as_canonical(ROOT, target)
                (target / "encoded.txt").write_text(payload + "\n", encoding="ascii", newline="")

                report = validate_repository(target, include_examples=True, check_build=False)

                findings = [item for item in report.errors if "encoded.txt" in item]
                self.assertEqual(len(findings), 1, findings)
                self.assertIn("possible", findings[0])
                self.assertNotIn(payload, findings[0])


if __name__ == "__main__":
    unittest.main()
