from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from tools.common import compact_json, load_json, pretty_json


def copy_repository_contract(source_root: Path, target_root: Path) -> None:
    shutil.copytree(source_root / "schemas", target_root / "schemas")
    shutil.copytree(source_root / "examples", target_root / "examples")
    shutil.copytree(source_root / "tools", target_root / "tools")
    shutil.copytree(source_root / "taxonomy", target_root / "taxonomy")
    shutil.copytree(source_root / "platforms", target_root / "platforms")
    shutil.copytree(source_root / "quality", target_root / "quality")
    shutil.copytree(source_root / "analysis-profiles", target_root / "analysis-profiles")
    shutil.copytree(source_root / "rights", target_root / "rights")
    shutil.copy2(source_root / "dataset.json", target_root / "dataset.json")
    shutil.copy2(source_root / "LICENSING.md", target_root / "LICENSING.md")
    shutil.copy2(source_root / "requirements-dev.txt", target_root / "requirements-dev.txt")
    (target_root / "data").mkdir()
    (target_root / "data" / "relations" / "visual").mkdir(parents=True)
    (target_root / "tombstones").mkdir()


def install_example_as_canonical(source_root: Path, target_root: Path) -> dict[str, Any]:
    collection = load_json(source_root / "examples" / "telegram" / "collection.json")
    emoji = load_json(source_root / "examples" / "telegram" / "emoji.json")
    membership = load_json(source_root / "examples" / "telegram" / "membership.json")

    collection_dir = target_root / "data" / "telegram" / "collections" / "02" / collection["id"]
    collection_dir.mkdir(parents=True)
    (collection_dir / "collection.json").write_text(
        pretty_json(collection), encoding="utf-8", newline=""
    )
    (collection_dir / "memberships.jsonl").write_text(
        compact_json(membership) + "\n", encoding="utf-8", newline=""
    )
    emoji_dir = target_root / "data" / "telegram" / "emojis" / "a8"
    emoji_dir.mkdir(parents=True)
    (emoji_dir / "3e.jsonl").write_text(compact_json(emoji) + "\n", encoding="utf-8", newline="")
    return {"collection": collection, "emoji": emoji, "membership": membership}


def set_pointer(document: Any, pointer: str, value: Any = None, *, delete: bool = False) -> None:
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]]
    target = document
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    final = parts[-1]
    if delete:
        if isinstance(target, list):
            del target[int(final)]
        else:
            del target[final]
    elif isinstance(target, list):
        target[int(final)] = value
    else:
        target[final] = value
