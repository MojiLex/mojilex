from __future__ import annotations

import hashlib
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from tests.helpers import copy_repository_contract, install_example_as_canonical
from tools.collection_catalog import (
    catalog_bytes,
    generated_pages,
    main,
    render_catalog,
    render_pack_page,
)
from tools.common import load_json

ROOT = Path(__file__).resolve().parents[1]


class CollectionCatalogTests(unittest.TestCase):
    def test_repository_catalog_matches_collection_records(self) -> None:
        path = ROOT / "data" / "telegram" / "collections" / "README.md"
        self.assertEqual(path.read_bytes(), catalog_bytes(ROOT))

    def test_repository_pack_pages_match_canonical_records(self) -> None:
        pages = generated_pages(ROOT)
        collection_root = ROOT / "data" / "telegram" / "collections"
        expected_paths = {collection_root / "README.md"}
        expected_paths.update(
            path.with_name("README.md") for path in collection_root.glob("*/collection.json")
        )
        self.assertEqual({ROOT / path for path in pages}, expected_paths)
        for relative_path, expected in pages.items():
            with self.subTest(path=relative_path):
                self.assertEqual((ROOT / relative_path).read_bytes(), expected)

    def test_catalog_escapes_titles_and_links_by_stable_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            copy_repository_contract(ROOT, target)
            values = install_example_as_canonical(ROOT, target)
            collection = values["collection"]
            collection["title"] = "Cats | dogs <3"
            output = render_catalog([collection]).decode("utf-8")
            self.assertIn("Cats \\| dogs &lt;3", output)
            self.assertIn(f"({collection['id']}/README.md)", output)
            self.assertIn(collection["native_id"], output)
            self.assertEqual(output, render_catalog([collection]).decode("utf-8"))

    def test_catalog_reflects_current_record_not_folder_name(self) -> None:
        collection = load_json(ROOT / "examples" / "telegram" / "collection.json")
        first = render_catalog([collection])
        collection["title"] = "A new title"
        self.assertNotEqual(first, render_catalog([collection]))

    def test_pack_page_links_full_hash_and_escapes_untrusted_descriptions(self) -> None:
        collection = load_json(ROOT / "examples" / "telegram" / "collection.json")
        emoji = load_json(ROOT / "examples" / "telegram" / "emoji.json")
        membership = load_json(ROOT / "examples" / "telegram" / "membership.json")
        collection["title"] = "Cats <script> | #new"
        emoji["descriptions"]["ru"]["text"] = "Текст | [ссылка](https://evil.test) <img>\n $x$"
        emoji["descriptions"]["en"]["text"] = "Look ![image](https://evil.test) :smile:"
        inactive = dict(membership)
        inactive["id"] = "mxm_inactive"
        inactive["status"] = "removed_from_collection"
        inactive["position"] = 0
        membership["position"] = 1
        digest = hashlib.sha256(emoji["id"].encode("utf-8")).hexdigest()

        output = render_pack_page(collection, [inactive, membership], {emoji["id"]: emoji}).decode(
            "utf-8"
        )

        self.assertIn(f"(../../emojis/{digest}.jsonl)", output)
        self.assertIn(emoji["native_id"], output)
        self.assertIn("Cats &lt;script&gt; \\| #new", output)
        self.assertIn(
            "Текст \\| \\[ссылка\\](https://evil.test) &lt;img&gt;",
            output,
        )
        self.assertIn("\\$x\\$", output)
        self.assertIn("\\!\\[image\\](https://evil.test)", output)
        self.assertNotIn("<script>", output)
        self.assertNotIn("<img>", output)
        self.assertNotIn("![image]", output)
        self.assertLess(
            output.index("| 1 | active |"),
            output.index("| 0 | removed\\_from\\_collection |"),
        )

    def test_pack_page_rejects_missing_emoji(self) -> None:
        collection = load_json(ROOT / "examples" / "telegram" / "collection.json")
        membership = load_json(ROOT / "examples" / "telegram" / "membership.json")
        with self.assertRaises(KeyError):
            render_pack_page(collection, [membership], {})

    def test_check_detects_stale_pack_page_and_write_repairs_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            copy_repository_contract(ROOT, target)
            values = install_example_as_canonical(ROOT, target)
            arguments = ["collection_catalog", str(target)]

            with patch.object(sys, "argv", [*arguments, "--write"]):
                self.assertEqual(main(), 0)
            pack_page = target / "data" / "telegram" / "collections"
            pack_page = pack_page / values["collection"]["id"] / "README.md"
            pack_page.write_bytes(pack_page.read_bytes() + b"stale\n")
            with (
                patch.object(sys, "argv", [*arguments, "--check"]),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as raised,
            ):
                main()
            self.assertEqual(raised.exception.code, 1)
            with patch.object(sys, "argv", [*arguments, "--write"]):
                self.assertEqual(main(), 0)
            with patch.object(sys, "argv", [*arguments, "--check"]):
                self.assertEqual(main(), 0)
