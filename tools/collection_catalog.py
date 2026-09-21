"""Build the human-readable collection index from canonical collection records."""

from __future__ import annotations

import argparse
import html
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from tools.common import load_json

CATALOG_NAME = "README.md"


def _cell(value: object) -> str:
    return html.escape(str(value).replace("\r", " ").replace("\n", " "), quote=False).replace(
        "|", "\\|"
    )


def render_catalog(collections: Iterable[dict[str, Any]]) -> bytes:
    rows = sorted(
        collections,
        key=lambda row: (row["title"].casefold(), row["native_id"].casefold(), row["id"]),
    )
    lines = [
        "# Каталог паков Telegram / Telegram pack catalog",
        "",
        "Названия берутся из карточек паков. Каталог не является источником данных.",
        "Titles come from `collection.json`; the records remain the source of truth.",
        "",
        f"Паков / Packs: {len(rows)}",
        "",
        "| Название / Title | Имя Telegram / Telegram name | Эмодзи / Emojis |",
        "|---|---|---:|",
    ]
    for row in rows:
        identifier = row["id"]
        lines.append(
            f"| {_cell(row['title'])} | "
            f"[{_cell(row['native_id'])}]({identifier}/) | {row['item_count']} |"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def catalog_bytes(root: Path) -> bytes:
    collection_root = root / "data" / "telegram" / "collections"
    records = [load_json(path) for path in sorted(collection_root.glob("*/collection.json"))]
    return render_catalog(records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Fail if the catalog is stale")
    mode.add_argument("--write", action="store_true", help="Regenerate the catalog")
    args = parser.parse_args()
    path = args.root / "data" / "telegram" / "collections" / CATALOG_NAME
    expected = catalog_bytes(args.root)
    if args.check:
        if not path.is_file() or path.read_bytes() != expected:
            parser.exit(1, f"Collection catalog is missing or stale: {path}\n")
        return 0
    path.write_bytes(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
