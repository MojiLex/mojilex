"""Build human-readable navigation from canonical Telegram records."""

from __future__ import annotations

import argparse
import hashlib
import html
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from tools.common import DataError, load_json, load_jsonl

CATALOG_NAME = "README.md"
_MARKDOWN_ESCAPES = frozenset(r"\`*_[]!|~$")


def _cell(value: object) -> str:
    plain = html.escape(" ".join(str(value).split()), quote=False)
    return "".join(f"\\{char}" if char in _MARKDOWN_ESCAPES else char for char in plain)


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
        f"Паков / Packs: {len(rows)}<br>",
        f"Эмодзи в паках / Emojis across packs: {sum(row['item_count'] for row in rows)}",
        "",
        "| Название / Title | Имя Telegram / Telegram name | Эмодзи / Emojis |",
        "|---|---|---:|",
    ]
    for row in rows:
        identifier = row["id"]
        lines.append(
            f"| {_cell(row['title'])} | "
            f"[{_cell(row['native_id'])}]({identifier}/README.md) | {row['item_count']} |"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_pack_page(
    collection: dict[str, Any],
    memberships: Iterable[dict[str, Any]],
    emojis_by_id: Mapping[str, dict[str, Any]],
) -> bytes:
    """Render one pack index without changing its canonical JSON/JSONL records."""
    rows = sorted(
        memberships,
        key=lambda row: (
            row["status"] != "active",
            row["position"],
            row["status"],
            row["emoji_id"],
            row["id"],
        ),
    )
    lines = [
        f"# {_cell(collection['title'])}",
        "",
        "[Каталог паков / Pack catalog](../README.md)",
        "",
        f"Пак Telegram / Telegram pack: {_cell(collection['native_id'])}",
        "",
        "Описания — навигационный указатель; канонические данные находятся в "
        "[collection.json](collection.json), [memberships.jsonl](memberships.jsonl) "
        "и записях эмодзи.",
        "Descriptions are a navigation aid; canonical records are the linked JSON/JSONL files.",
        "",
        "| Позиция / Position | Статус / Status | Telegram ID | Emoji ID | "
        "Описание (RU) | Description (EN) |",
        "|---:|---|---|---|---|---|",
    ]
    for row in rows:
        emoji_id = row["emoji_id"]
        emoji = emojis_by_id[emoji_id]
        digest = hashlib.sha256(emoji_id.encode("utf-8")).hexdigest()
        lines.append(
            f"| {row['position']} | {_cell(row['status'])} | {_cell(emoji['native_id'])} | "
            f"[{_cell(emoji_id)}](../../emojis/{digest}.jsonl) | "
            f"{_cell(emoji['descriptions']['ru']['text'])} | "
            f"{_cell(emoji['descriptions']['en']['text'])} |"
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def catalog_bytes(root: Path) -> bytes:
    collection_root = root / "data" / "telegram" / "collections"
    records = [load_json(path) for path in sorted(collection_root.glob("*/collection.json"))]
    return render_catalog(records)


def generated_pages(root: Path) -> dict[Path, bytes]:
    """Return generated README bytes keyed by paths relative to the repository."""
    collection_root = root / "data" / "telegram" / "collections"
    collections = [load_json(path) for path in sorted(collection_root.glob("*/collection.json"))]
    emojis_by_id: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "data" / "telegram" / "emojis").glob("*.jsonl")):
        for emoji in load_jsonl(path):
            emoji_id = emoji["id"]
            digest = hashlib.sha256(emoji_id.encode("utf-8")).hexdigest()
            if path.stem != digest:
                raise DataError(f"emoji catalog source has a noncanonical path: {path}")
            if emoji_id in emojis_by_id:
                raise DataError(f"duplicate emoji ID in catalog source: {emoji_id}")
            emojis_by_id[emoji_id] = emoji
    pages = {Path("data/telegram/collections/README.md"): render_catalog(collections)}
    for collection in collections:
        directory = collection_root / collection["id"]
        memberships = load_jsonl(directory / "memberships.jsonl")
        pages[(directory / "README.md").relative_to(root)] = render_pack_page(
            collection, memberships, emojis_by_id
        )
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path("."))
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="Fail if the catalog is stale")
    mode.add_argument("--write", action="store_true", help="Regenerate the catalog")
    args = parser.parse_args()
    pages = generated_pages(args.root)
    if args.check:
        for relative_path, expected in pages.items():
            path = args.root / relative_path
            if not path.is_file() or path.read_bytes() != expected:
                parser.exit(1, f"Collection page is missing or stale: {path}\n")
        return 0
    for relative_path, expected in pages.items():
        path = args.root / relative_path
        if not path.is_file() or path.read_bytes() != expected:
            path.write_bytes(expected)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
