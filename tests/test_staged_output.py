from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.build_index import _write_staged
from tools.spec003_build import MANIFEST_VERSION, write_staged


class StagedOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.manifest = json.dumps(
            {
                "dataset": "mojilex",
                "manifest_version": MANIFEST_VERSION,
                "artifacts": [{"path": "emojis.jsonl"}],
                "resources": [],
                "payload_sha256": {},
            }
        ).encode()

    def files(self, value: bytes) -> dict[str, bytes]:
        return {"manifest.json": self.manifest, "emojis.jsonl": value}

    def test_success_replaces_both_builders_without_backup_residue(self) -> None:
        for index, writer in enumerate((write_staged, _write_staged)):
            with self.subTest(writer=writer.__module__):
                output = self.root / str(index)
                writer(output, self.files(b"old"))
                writer(output, self.files(b"new"))
                self.assertEqual((output / "emojis.jsonl").read_bytes(), b"new")
                self.assertEqual(list(self.root.glob(f".{index}-*")), [])

    def test_failed_install_restores_previous_bytes_for_both_builders(self) -> None:
        replace = os.replace
        for index, writer in enumerate((write_staged, _write_staged)):
            with self.subTest(writer=writer.__module__):
                output = self.root / str(index)
                writer(output, self.files(b"old"))

                def fail_install(source: Path, destination: Path, output: Path = output) -> None:
                    if destination == output and source.name != "previous":
                        raise PermissionError("installation blocked")
                    replace(source, destination)

                with (
                    patch("tools.staged_output.os.replace", side_effect=fail_install),
                    self.assertRaisesRegex(PermissionError, "installation blocked"),
                ):
                    writer(output, self.files(b"new"))
                self.assertEqual((output / "emojis.jsonl").read_bytes(), b"old")
                self.assertEqual(list(self.root.glob(f".{index}-*")), [])

    def test_failed_backup_move_leaves_original_in_place(self) -> None:
        output = self.root / "snapshot"
        write_staged(output, self.files(b"old"))
        with (
            patch("tools.staged_output.os.replace", side_effect=PermissionError("locked")),
            self.assertRaises(PermissionError),
        ):
            write_staged(output, self.files(b"new"))
        self.assertEqual((output / "emojis.jsonl").read_bytes(), b"old")
        self.assertEqual(list(self.root.glob(".snapshot-*")), [])

    def test_failed_rollback_keeps_old_snapshot_and_reports_recovery_path(self) -> None:
        output = self.root / "snapshot"
        write_staged(output, self.files(b"old"))
        replace = os.replace

        def fail_install_and_restore(source: Path, destination: Path) -> None:
            if destination == output:
                raise PermissionError("destination locked")
            replace(source, destination)

        with (
            patch("tools.staged_output.os.replace", side_effect=fail_install_and_restore),
            self.assertRaisesRegex(OSError, "rollback failed") as failure,
        ):
            write_staged(output, self.files(b"new"))
        backups = list(self.root.glob(".snapshot-backup-*/previous"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "emojis.jsonl").read_bytes(), b"old")
        self.assertIn(str(backups[0]), str(failure.exception))
        self.assertFalse(output.exists())

    def test_interrupted_completed_backup_move_preserves_previous_snapshot(self) -> None:
        output = self.root / "snapshot"
        write_staged(output, self.files(b"old"))
        replace = os.replace

        def interrupt_after_move(source: Path, destination: Path) -> None:
            replace(source, destination)
            if source == output:
                raise KeyboardInterrupt("interrupted after completed backup rename")

        with (
            patch("tools.staged_output.os.replace", side_effect=interrupt_after_move),
            self.assertRaisesRegex(OSError, "backup move was interrupted") as failure,
        ):
            write_staged(output, self.files(b"new"))
        backup = next(self.root.glob(".snapshot-backup-*/previous"))
        self.assertEqual((backup / "emojis.jsonl").read_bytes(), b"old")
        self.assertIn(str(backup), str(failure.exception))

    def test_cleanup_failure_keeps_new_output_and_reports_backup(self) -> None:
        output = self.root / "snapshot"
        write_staged(output, self.files(b"old"))
        from tools import staged_output

        rmtree = staged_output.shutil.rmtree

        def fail_backup_cleanup(path: Path, **kwargs: object) -> None:
            if path.name.startswith(".snapshot-backup-"):
                raise PermissionError("backup locked")
            rmtree(path, **kwargs)

        with (
            patch("tools.staged_output.shutil.rmtree", side_effect=fail_backup_cleanup),
            self.assertRaisesRegex(OSError, "new snapshot installed") as failure,
        ):
            write_staged(output, self.files(b"new"))
        self.assertEqual((output / "emojis.jsonl").read_bytes(), b"new")
        backup = next(self.root.glob(".snapshot-backup-*"))
        self.assertEqual((backup / "previous/emojis.jsonl").read_bytes(), b"old")
        self.assertIn(str(backup), str(failure.exception))

    def test_concurrent_output_is_not_overwritten_during_rollback(self) -> None:
        output = self.root / "snapshot"
        write_staged(output, self.files(b"old"))
        replace = os.replace

        def concurrent_install(source: Path, destination: Path) -> None:
            if destination == output:
                output.mkdir()
                (output / "concurrent.txt").write_bytes(b"keep")
                raise PermissionError("concurrent writer")
            replace(source, destination)

        with (
            patch("tools.staged_output.os.replace", side_effect=concurrent_install),
            self.assertRaisesRegex(OSError, "previous snapshot preserved"),
        ):
            write_staged(output, self.files(b"new"))
        self.assertEqual((output / "concurrent.txt").read_bytes(), b"keep")
        backup = next(self.root.glob(".snapshot-backup-*/previous"))
        self.assertEqual((backup / "emojis.jsonl").read_bytes(), b"old")
