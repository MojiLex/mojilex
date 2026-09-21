from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.helpers import copy_repository_contract, install_example_as_canonical
from tools.collection_catalog import catalog_bytes, render_catalog
from tools.common import load_json

ROOT = Path(__file__).resolve().parents[1]


class CollectionCatalogTests(unittest.TestCase):
    def test_repository_catalog_matches_collection_records(self) -> None:
        path = ROOT / "data" / "telegram" / "collections" / "README.md"
        self.assertEqual(path.read_bytes(), catalog_bytes(ROOT))

    def test_catalog_escapes_titles_and_links_by_stable_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            copy_repository_contract(ROOT, target)
            values = install_example_as_canonical(ROOT, target)
            collection = values["collection"]
            collection["title"] = "Cats | dogs <3"
            output = render_catalog([collection]).decode("utf-8")
            self.assertIn("Cats \\| dogs &lt;3", output)
            self.assertIn(f"({collection['id']}/)", output)
            self.assertIn(collection["native_id"], output)
            self.assertEqual(output, render_catalog([collection]).decode("utf-8"))

    def test_catalog_reflects_current_record_not_folder_name(self) -> None:
        collection = load_json(ROOT / "examples" / "telegram" / "collection.json")
        first = render_catalog([collection])
        collection["title"] = "A new title"
        self.assertNotEqual(first, render_catalog([collection]))
