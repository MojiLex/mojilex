from __future__ import annotations

import copy
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from tests.helpers import copy_repository_contract, install_example_as_canonical
from tools.common import entity_shard, load_json
from tools.refresh_pull_requests import (
    RefreshError,
    dispatch_validation,
    ensure_data_only,
    merge_records,
    prepare_refresh,
    publish_refresh,
    read_records,
    refresh_open_prs,
    render_records,
)

ROOT = Path(__file__).resolve().parents[1]


class EntityMergeTests(unittest.TestCase):
    def test_distinct_records_from_same_legacy_bucket_are_preserved(self):
        left = {("emoji", "left"): {"id": "left", "description": "main"}}
        right = {("emoji", "right"): {"id": "right", "description": "PR"}}
        self.assertEqual(merge_records({}, right, left), left | right)

    def test_same_record_independent_edits_are_explicit_conflict(self):
        key = ("emoji", "same")
        with self.assertRaisesRegex(RefreshError, "conflicting changes"):
            merge_records({key: {"text": "old"}}, {key: {"text": "PR"}}, {key: {"text": "main"}})

    def test_identical_edits_and_unchanged_pr_are_safe(self):
        key = ("emoji", "same")
        base, changed = {key: {"text": "old"}}, {key: {"text": "new"}}
        self.assertEqual(merge_records(base, changed, changed), changed)
        self.assertEqual(merge_records(base, base, changed), changed)

    def test_delete_vs_edit_conflicts_but_uncontested_delete_applies(self):
        key = ("emoji", "same")
        base = {key: {"text": "old"}}
        self.assertEqual(merge_records(base, {}, base), {})
        with self.assertRaises(RefreshError):
            merge_records(base, {}, {key: {"text": "new"}})

    def test_renderer_uses_eight_hash_characters(self):
        emoji = load_json(ROOT / "examples/telegram/emoji.json")
        files = render_records({("emoji", emoji["id"]): emoji})
        digest = entity_shard(emoji["id"], 8)
        self.assertEqual(list(files), [f"data/telegram/emojis/{digest[:2]}/{digest[2:]}.jsonl"])

    def test_unsafe_platform_rejected_before_writing(self):
        with self.assertRaises(RefreshError):
            render_records({("emoji", "id"): {"id": "id", "platform": "../../tools"}})

    def test_empty_collection_keeps_empty_membership_file(self):
        collection = load_json(ROOT / "examples/telegram/collection.json")
        files = render_records({("collection", collection["id"]): collection})
        memberships = [
            content for path, content in files.items() if path.endswith("memberships.jsonl")
        ]
        self.assertEqual(memberships, [b""])

    def test_renderer_updates_catalog_from_merged_collections(self):
        collection = load_json(ROOT / "examples/telegram/collection.json")
        files = render_records({("collection", collection["id"]): collection}, include_catalog=True)
        catalog = files["data/telegram/collections/README.md"].decode("utf-8")
        self.assertIn(collection["title"], catalog)
        self.assertIn(f"({collection['id']}/)", catalog)

    def test_non_data_edits_and_symlinks_rejected(self):
        for path, mode in (
            ("tools/validate.py", "100644"),
            ("data/telegram/emojis/ab/cd.jsonl", "120000"),
            ("dataset.json", "100644"),
        ):
            with self.subTest(path=path, mode=mode), self.assertRaises(RefreshError):
                ensure_data_only({}, {path: (mode, "blob")})

    def test_legacy_and_new_data_paths_allowed(self):
        ensure_data_only(
            {},
            {
                "data/telegram/emojis/ab/cd.jsonl": ("100644", "old"),
                "data/telegram/emojis/ab/cdef01.jsonl": ("100644", "new"),
                "data/telegram/collections/README.md": ("100644", "catalog"),
            },
        )

    def test_duplicate_ids_in_different_files_rejected(self):
        raw = b'{"entity_type":"emoji","id":"same"}\n'
        with (
            patch("tools.refresh_pull_requests.blob_bytes", return_value=raw),
            self.assertRaisesRegex(RefreshError, "duplicate"),
        ):
            read_records(
                Path("."),
                {
                    "data/telegram/emojis/ab/cd.jsonl": ("100644", "one"),
                    "data/telegram/emojis/ef/01.jsonl": ("100644", "two"),
                },
            )

    def test_malformed_record_types_are_reported(self):
        with (
            patch("tools.refresh_pull_requests.blob_bytes", return_value=b'{"entity_type":[]}\n'),
            self.assertRaises(RefreshError),
        ):
            read_records(Path("."), {"data/telegram/emojis/ab/cd.jsonl": ("100644", "one")})
        with self.assertRaises(RefreshError):
            render_records({("membership", "id"): {"collection_id": []}})

    def test_malformed_membership_position_is_reported(self):
        collection = load_json(ROOT / "examples/telegram/collection.json")
        membership = load_json(ROOT / "examples/telegram/membership.json")
        membership["position"] = None
        with self.assertRaises(RefreshError):
            render_records(
                {
                    ("collection", collection["id"]): collection,
                    ("membership", membership["id"]): membership,
                }
            )


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.pr = {"number": 2, "state": "open", "head": {"sha": "a" * 40, "ref": "mojilex/test"}}
        self.latest = "b" * 40

    def api(self):
        calls = []

        def request(method, path, payload=None):
            calls.append((method, path, payload))
            if path == "/pulls/2":
                return copy.deepcopy(self.pr)
            if path == "/git/ref/heads/main":
                return {"object": {"sha": self.latest}}
            if path.startswith("/git/commits/"):
                return {"tree": {"sha": "c" * 40}}
            return {"sha": "d" * 40}

        return Mock(request=Mock(side_effect=request)), calls

    def test_merge_commit_has_both_parents_and_nonforce_update(self):
        api, calls = self.api()
        publish_refresh(
            api, self.pr, self.latest, {"data/telegram/emojis/ab/cdef01.jsonl": b"{}\n"}
        )
        commit = next(
            payload
            for method, path, payload in calls
            if method == "POST" and path == "/git/commits"
        )
        self.assertEqual(commit["parents"], [self.pr["head"]["sha"], self.latest])
        tree = next(
            payload for method, path, payload in calls if method == "POST" and path == "/git/trees"
        )
        self.assertEqual(tree["base_tree"], "c" * 40)
        self.assertEqual(
            calls[-1],
            ("PATCH", "/git/refs/heads/mojilex%2Ftest", {"sha": "d" * 40, "force": False}),
        )

    def test_changed_head_aborts_before_creating_tree(self):
        api, calls = self.api()
        original = copy.deepcopy(self.pr)
        self.pr["head"]["sha"] = "e" * 40
        with self.assertRaisesRegex(RefreshError, "head changed"):
            publish_refresh(api, original, self.latest, {})
        self.assertEqual(len(calls), 1)

    def test_fork_is_never_fetched_or_written(self):
        pr = copy.deepcopy(self.pr)
        pr["head"]["repo"] = {"full_name": "contributor/fork"}
        api = Mock(request=Mock(return_value=[pr]))
        with patch("tools.refresh_pull_requests.git") as git:
            self.assertEqual(refresh_open_prs(Path("."), api, "MojiLex/mojilex", dry_run=False), 0)
        git.assert_not_called()
        self.assertEqual(api.request.call_count, 1)

    def test_dispatch_failure_reports_updated_branch(self):
        api = Mock(request=Mock(side_effect=RefreshError("HTTP 403")))
        with patch("builtins.print") as output:
            self.assertFalse(dispatch_validation(api, self.pr))
        self.assertIn("branch is updated", output.call_args.args[0])

    def test_malformed_pr_does_not_prevent_next_pr(self):
        first = copy.deepcopy(self.pr)
        first["head"]["repo"] = {"full_name": "MojiLex/mojilex"}
        second = copy.deepcopy(first)
        second["number"] = 3
        api = Mock(
            request=Mock(
                side_effect=[
                    [first, second],
                    {"object": {"sha": self.latest}},
                    {"object": {"sha": self.latest}},
                ]
            )
        )
        with (
            patch("tools.refresh_pull_requests.git", return_value=b"c" * 40),
            patch(
                "tools.refresh_pull_requests.prepare_refresh",
                side_effect=[RefreshError("malformed data"), {}],
            ) as prepare,
            patch("builtins.print") as output,
        ):
            self.assertEqual(refresh_open_prs(Path("."), api, "MojiLex/mojilex", dry_run=True), 1)
        self.assertEqual(prepare.call_count, 2)
        self.assertTrue(
            any("PR #3: validated refresh ready" in call.args[0] for call in output.call_args_list)
        )

    def test_already_updated_bot_commit_retries_ci_dispatch(self):
        from tools.refresh_pull_requests import REFRESH_MESSAGE

        pr = copy.deepcopy(self.pr)
        pr["head"]["repo"] = {"full_name": "MojiLex/mojilex"}
        api = Mock(
            request=Mock(
                side_effect=[
                    [pr],
                    {"object": {"sha": self.latest}},
                    None,
                ]
            )
        )
        with patch(
            "tools.refresh_pull_requests.git",
            side_effect=[
                b"",
                b"",
                self.latest.encode(),
                REFRESH_MESSAGE.encode(),
            ],
        ):
            self.assertEqual(refresh_open_prs(Path("."), api, "MojiLex/mojilex", dry_run=False), 0)
        self.assertEqual(
            api.request.call_args.args[:2], ("POST", "/actions/workflows/validate.yml/dispatches")
        )


class RefreshIntegrationTests(unittest.TestCase):
    def test_legacy_pr_replayed_on_current_main_passes_real_strict_validation(self):
        with tempfile.TemporaryDirectory(prefix="mlx-pr-") as temporary:
            root = Path(temporary)
            copy_repository_contract(ROOT, root)

            def git(*args):
                return (
                    subprocess.check_output(
                        ["git", "-C", str(root), *args], stderr=subprocess.DEVNULL
                    )
                    .decode()
                    .strip()
                )

            git("init", "-q")
            git("config", "user.name", "MojiLex test")
            git("config", "user.email", "test@example.invalid")
            git("config", "core.autocrlf", "false")
            git("add", ".")
            git("commit", "-qm", "base contract")
            base = git("rev-parse", "HEAD")
            values = install_example_as_canonical(ROOT, root)
            git("add", "data")
            git("commit", "-qm", "legacy data PR")
            head = git("rev-parse", "HEAD")
            git("checkout", "-q", "-b", "updated-main", base)
            (root / "README.md").write_text("Updated main\n", encoding="utf-8", newline="")
            git("add", "README.md")
            git("commit", "-qm", "main advanced")
            latest = git("rev-parse", "HEAD")
            changes = prepare_refresh(root, base, head, latest)
            digest = entity_shard(values["emoji"]["id"], 8)
            self.assertIn(f"data/telegram/emojis/{digest[:2]}/{digest[2:]}.jsonl", changes)
            self.assertNotIn("README.md", changes)


if __name__ == "__main__":
    unittest.main()
