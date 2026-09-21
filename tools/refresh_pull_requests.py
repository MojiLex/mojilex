"""Refresh data-only PRs using trusted base code and an entity-level three-way merge.

PR trees are read as blobs, never checked out or executed. The workflow invoking this
tool must check out trusted main, install its dependencies, and supply GITHUB_TOKEN.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

from tools.collection_catalog import render_catalog
from tools.common import compact_json, entity_shard, parse_json, pretty_json
from tools.validate import validate_repository

RecordKey = tuple[str, str]
Records = dict[RecordKey, dict[str, Any]]
DATA_PATH = re.compile(
    r"(?:data/[a-z0-9_-]+/(?:emojis/[0-9a-f]{2}/(?:[0-9a-f]{2}|[0-9a-f]{6})\.jsonl"
    r"|collections/(?:[0-9a-f]{2}/)?mxc_[a-z0-9-]+/(?:collection\.json|memberships\.jsonl))"
    r"|data/telegram/collections/README\.md"
    r"|data/relations/visual/[0-9a-f]{2}/(?:[0-9a-f]{2}|[0-9a-f]{6})\.jsonl"
    r"|tombstones/[0-9a-f]{2}/[a-z0-9_-]+\.json)\Z"
)
KINDS = {"collection", "emoji", "membership", "visual_relation", "tombstone"}
SAFE_SEGMENT = re.compile(r"[a-z0-9_-]+\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_BLOB_BYTES = 16 * 1024 * 1024
MAX_DATA_BYTES = 256 * 1024 * 1024
REFRESH_MESSAGE = "data: refresh PR against main by entity identity"


class RefreshError(ValueError):
    """Unsafe or conflicting PR; leave its branch unchanged."""


def git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, check=False, timeout=120
    )
    if result.returncode:
        raise RefreshError(f"git {args[0]} failed (exit {result.returncode})")
    return result.stdout


def tree_files(root: Path, revision: str) -> dict[str, tuple[str, str]]:
    if not SHA.fullmatch(revision):
        raise RefreshError("expected an exact commit SHA")
    result = {}
    for entry in git(root, "ls-tree", "-rz", revision).split(b"\0"):
        if not entry:
            continue
        header, encoded_path = entry.split(b"\t", 1)
        mode, kind, blob = header.decode("ascii").split()
        path = encoded_path.decode("utf-8")
        if kind != "blob":
            raise RefreshError("submodules are not supported")
        result[path] = (mode, blob)
    return result


def blob_bytes(root: Path, blob: str) -> bytes:
    size = int(git(root, "cat-file", "-s", blob))
    if size > MAX_BLOB_BYTES:
        raise RefreshError("data blob exceeds the refresh size limit")
    return git(root, "cat-file", "blob", blob)


def ensure_data_only(base: dict[str, tuple[str, str]], head: dict[str, tuple[str, str]]) -> None:
    for path in base.keys() | head.keys():
        if base.get(path) == head.get(path):
            continue
        if not DATA_PATH.fullmatch(path):
            raise RefreshError(f"PR changes a non-data path: {path}")
        if path in head and head[path][0] != "100644":
            raise RefreshError("PR data must be ordinary non-executable files")


def read_records(root: Path, files: dict[str, tuple[str, str]]) -> Records:
    records: Records = {}
    total = 0
    for path, (mode, blob) in sorted(files.items()):
        if not DATA_PATH.fullmatch(path):
            continue
        if path == "data/telegram/collections/README.md":
            continue
        if mode != "100644":
            raise RefreshError("data must be ordinary non-executable files")
        raw = blob_bytes(root, blob)
        total += len(raw)
        if total > MAX_DATA_BYTES:
            raise RefreshError("data tree exceeds the refresh size limit")
        text = raw.decode("utf-8")
        values = (
            [parse_json(line, source=path) for line in text.splitlines()]
            if path.endswith(".jsonl")
            else [parse_json(text, source=path)]
        )
        for value in values:
            if (
                not isinstance(value, dict)
                or not isinstance(value.get("entity_type"), str)
                or value["entity_type"] not in KINDS
            ):
                raise RefreshError("unrecognized data record")
            kind = value["entity_type"]
            identity = value.get("target_id" if kind == "tombstone" else "id")
            if not isinstance(identity, str) or not SAFE_SEGMENT.fullmatch(identity):
                raise RefreshError("invalid record identity")
            key = kind, identity
            if key in records:
                raise RefreshError("duplicate entity identity")
            records[key] = value
    return records


def merge_records(base: Records, head: Records, latest: Records) -> Records:
    merged = dict(latest)
    for key in sorted(base.keys() | head.keys()):
        before, proposed, current = base.get(key), head.get(key), latest.get(key)
        if before == proposed:
            continue
        if current != before and current != proposed:
            # Do not print model descriptions or potentially sensitive record contents.
            raise RefreshError(f"conflicting changes to the same {key[0]} record")
        if proposed is None:
            merged.pop(key, None)
        else:
            merged[key] = proposed
    return merged


def render_records(records: Records, *, include_catalog: bool = False) -> dict[str, bytes]:
    paths: dict[str, list[dict[str, Any]]] = defaultdict(list)
    collections = {
        identity: value for (kind, identity), value in records.items() if kind == "collection"
    }
    for (kind, identity), value in records.items():
        shard = entity_shard(identity, 8)
        if kind == "tombstone":
            path = f"tombstones/{shard[:2]}/{identity}.json"
        elif kind == "visual_relation":
            path = f"data/relations/visual/{shard[:2]}/{shard[2:]}.jsonl"
        else:
            if kind == "membership" and not isinstance(value.get("collection_id"), str):
                raise RefreshError("membership has no valid collection identity")
            owner = collections.get(value.get("collection_id")) if kind == "membership" else value
            platform = owner.get("platform") if owner else None
            if not isinstance(platform, str) or not SAFE_SEGMENT.fullmatch(platform):
                raise RefreshError("record has no valid platform or owning collection")
            if kind == "emoji":
                path = f"data/{platform}/emojis/{shard[:2]}/{shard[2:]}.jsonl"
            else:
                collection_id = value["collection_id"] if kind == "membership" else identity
                folder = f"data/{platform}/collections/{collection_id}"
                name = "memberships.jsonl" if kind == "membership" else "collection.json"
                path = f"{folder}/{name}"
        if not DATA_PATH.fullmatch(path):
            raise RefreshError("record produces an invalid canonical path")
        paths[path].append(value)
        if kind == "collection":
            paths.setdefault(path.removesuffix("collection.json") + "memberships.jsonl", [])
    result = {}
    for path, values in paths.items():
        if path.endswith("memberships.jsonl"):
            if any(
                not isinstance(value.get("status"), str)
                or type(value.get("position", -1)) is not int
                for value in values
            ):
                raise RefreshError("membership has invalid ordering fields")
            values.sort(
                key=lambda value: (value.get("status", ""), value.get("position", -1), value["id"])
            )
        else:
            values.sort(key=lambda value: value.get("id", ""))
        text = (
            "".join(compact_json(value) + "\n" for value in values)
            if path.endswith(".jsonl")
            else pretty_json(values[0])
        )
        result[path] = text.encode("utf-8")
    if include_catalog:
        result["data/telegram/collections/README.md"] = render_catalog(
            value
            for (kind, _), value in records.items()
            if kind == "collection" and value.get("platform") == "telegram"
        )
    return result


def prepare_refresh(root: Path, base: str, head: str, latest: str) -> dict[str, bytes | None]:
    base_files, head_files, latest_files = (tree_files(root, sha) for sha in (base, head, latest))
    ensure_data_only(base_files, head_files)
    try:
        merged = merge_records(
            *(read_records(root, files) for files in (base_files, head_files, latest_files))
        )
        rendered = render_records(
            merged,
            include_catalog=any(
                "data/telegram/collections/README.md" in files
                for files in (head_files, latest_files)
            ),
        )
    except (TypeError, KeyError) as exc:
        raise RefreshError("malformed data record; refresh skipped") from exc
    changes: dict[str, bytes | None] = {}
    for path, (_, blob) in latest_files.items():
        if DATA_PATH.fullmatch(path) and path not in rendered:
            changes[path] = None
        elif path in rendered and blob_bytes(root, blob) != rendered[path]:
            changes[path] = rendered[path]
    changes.update(
        {path: content for path, content in rendered.items() if path not in latest_files}
    )

    with tempfile.TemporaryDirectory(prefix="mojilex-refresh-") as temporary:
        candidate = Path(temporary)
        for path, (mode, blob) in latest_files.items():
            # Only trusted main files are materialized; the PR only contributes parsed records.
            destination = candidate / path
            if not destination.resolve().is_relative_to(candidate.resolve()) or "\\" in path:
                raise RefreshError("unsafe main tree path")
            if mode not in {"100644", "100755"}:
                raise RefreshError("main tree contains a symlink or unsupported file")
            if DATA_PATH.fullmatch(path):
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(blob_bytes(root, blob))
        for path, content in rendered.items():
            destination = candidate / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        # Runs this process's trusted validator. Build checks remain enabled.
        report = validate_repository(candidate)
        if report.errors:
            raise RefreshError(
                f"merged dataset fails strict validation ({len(report.errors)} errors)"
            )
    return changes


class GitHub:
    def __init__(self, repository: str, token: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise RefreshError("invalid repository name")
        self.prefix = f"https://api.github.com/repos/{repository}"
        self.token = token

    def request(self, method: str, path: str, payload: Any = None) -> Any:
        request = urllib.request.Request(
            self.prefix + path,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            raise RefreshError(f"GitHub {method} request failed (HTTP {exc.code})") from None


def publish_refresh(
    api: GitHub, pr: dict[str, Any], latest: str, changes: dict[str, bytes | None]
) -> str:
    number, expected_head = pr["number"], pr["head"]["sha"]
    current = api.request("GET", f"/pulls/{number}")
    if current["state"] != "open" or current["head"]["sha"] != expected_head:
        raise RefreshError("PR head changed; retry on the next refresh")
    if api.request("GET", "/git/ref/heads/main")["object"]["sha"] != latest:
        raise RefreshError("main changed; retry on the next refresh")
    latest_tree = api.request("GET", f"/git/commits/{latest}")["tree"]["sha"]
    tree = api.request(
        "POST",
        "/git/trees",
        {
            "base_tree": latest_tree,
            "tree": [
                {
                    "path": path,
                    "mode": "100644",
                    "type": "blob",
                    **({"sha": None} if content is None else {"content": content.decode("utf-8")}),
                }
                for path, content in sorted(changes.items())
            ],
        },
    )
    commit = api.request(
        "POST",
        "/git/commits",
        {
            "message": REFRESH_MESSAGE,
            "tree": tree["sha"],
            "parents": [expected_head, latest],
        },
    )
    branch = urllib.parse.quote(pr["head"]["ref"], safe="")
    # A non-force update cannot overwrite a concurrent commit absent from our parents.
    api.request("PATCH", f"/git/refs/heads/{branch}", {"sha": commit["sha"], "force": False})
    return commit["sha"]


def dispatch_validation(api: GitHub, pr: dict[str, Any]) -> bool:
    try:
        api.request(
            "POST", "/actions/workflows/validate.yml/dispatches", {"ref": pr["head"]["ref"]}
        )
    except (RefreshError, OSError) as exc:
        print(
            f"PR #{pr['number']}: branch is updated, but CI dispatch failed: {exc}; rerun refresh"
        )
        return False
    print(f"PR #{pr['number']}: full validation workflow requested")
    return True


def refresh_open_prs(root: Path, api: GitHub, repository: str, *, dry_run: bool) -> int:
    failures = 0
    page = 1
    while True:
        prs = api.request("GET", f"/pulls?state=open&base=main&per_page=100&page={page}")
        for pr in prs:
            number = pr["number"]
            if (pr["head"].get("repo") or {}).get("full_name") != repository:
                print(f"PR #{number}: skipped fork; its author must refresh the branch")
                continue
            try:
                latest = api.request("GET", "/git/ref/heads/main")["object"]["sha"]
                head = pr["head"]["sha"]
                for sha in (latest, head):
                    if not SHA.fullmatch(sha):
                        raise RefreshError("invalid commit SHA")
                    git(root, "fetch", "--no-tags", "origin", sha)
                base = git(root, "merge-base", latest, head).decode("ascii").strip()
                if base == latest:
                    print(f"PR #{number}: already based on current main")
                    message = git(root, "show", "-s", "--format=%s", head).decode("utf-8").strip()
                    if not dry_run and message == REFRESH_MESSAGE:
                        failures += not dispatch_validation(api, pr)
                    continue
                changes = prepare_refresh(root, base, head, latest)
                if dry_run:
                    print(f"PR #{number}: validated refresh ready ({len(changes)} paths)")
                    continue
                publish_refresh(api, pr, latest, changes)
                print(f"PR #{number}: branch refreshed")
                # Token pushes do not trigger push CI; request read-only validation explicitly.
                failures += not dispatch_validation(api, pr)
            except (RefreshError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
                failures += 1
                print(f"PR #{number}: unchanged or requires attention: {exc}")
        if len(prs) < 100:
            break
        page += 1
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    if not args.repository or not token:
        parser.error("GITHUB_REPOSITORY and GITHUB_TOKEN are required")
    return refresh_open_prs(
        args.root.resolve(), GitHub(args.repository, token), args.repository, dry_run=args.dry_run
    )


if __name__ == "__main__":
    raise SystemExit(main())
