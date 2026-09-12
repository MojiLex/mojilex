from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from tests.helpers import copy_repository_contract, install_example_as_canonical
from tools.common import compact_json
from tools.validate import _diagnostic_source_epoch, validate_repository

ROOT = Path(__file__).resolve().parents[1]


class ValidationEpochTests(unittest.TestCase):
    def test_diagnostic_build_accepts_new_evidence_after_initial_snapshot_date(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            copy_repository_contract(ROOT, root)
            records = install_example_as_canonical(ROOT, root)
            emoji = records["emoji"]
            emoji["availability"]["last_verified_at"] = "2026-10-01T12:34:56Z"
            shard = root / "data" / "telegram" / "emojis" / "a8" / "3e.jsonl"
            shard.write_text(compact_json(emoji) + "\n", encoding="utf-8", newline="")
            expected = int(datetime(2026, 10, 1, 12, 34, 56, tzinfo=UTC).timestamp())
            self.assertEqual(_diagnostic_source_epoch(root), expected)
            report = validate_repository(root, include_examples=True, check_build=True)
            self.assertEqual(report.errors, [], "\n".join(report.errors))


if __name__ == "__main__":
    unittest.main()
