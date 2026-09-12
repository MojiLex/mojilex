from __future__ import annotations

import unittest
from pathlib import Path

from tools.common import load_json
from tools.spec003_build import _rights_summary

ROOT = Path(__file__).resolve().parents[1]


class RightsSummaryTests(unittest.TestCase):
    def test_restriction_precedes_unknown_or_missing_operation(self) -> None:
        for restriction in ("deny", "conditional", "not-granted"):
            for unknown in ("unknown", None):
                with self.subTest(restriction=restriction, unknown=unknown):
                    rights = load_json(ROOT / "rights" / "profiles.json")
                    platform = load_json(ROOT / "platforms" / "telegram.json")
                    profile = next(
                        value
                        for value in rights["profiles"]
                        if value["rights_profile_id"] == platform["default_rights_profile_id"]
                    )
                    profile["operations"]["publish-metadata"] = {"decision": restriction}
                    if unknown is None:
                        del profile["operations"]["publish-generated-annotations"]
                    else:
                        profile["operations"]["publish-generated-annotations"] = {
                            "decision": unknown
                        }
                    summary = _rights_summary(
                        {"platform": "telegram"}, {"telegram": platform}, rights, 1789171199
                    )
                    self.assertEqual(summary["distribution_status"], "restricted")


if __name__ == "__main__":
    unittest.main()
