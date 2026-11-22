"""Resolve and verify the exact browser release this API serves.

A release is published by ``apps/web/scripts/publish-release.mjs`` into
``apps/web/releases/<id>/`` and described by ``apps/web/dist/release.json``. The
running API resolves that directory *once*, at import time, and mounts only that
immutable directory. A later build writes a new release directory and a new
manifest; it never replaces the files of the release a running instance serves.

Schema-2 manifests list every release file with its size and SHA-256 and a tree
digest. The resolver verifies them, so a manifest that points at missing or
altered files is reported as broken instead of being served silently. A checkout
built before this mechanism has no file list; it is served from ``dist`` and
reported as ``legacy``.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

MANIFEST = "release.json"
RELEASES = "releases"
ENTRY_PATTERN = re.compile(r'<script[^>]+src="([^"]+\.js)"')
CSS_PATTERN = re.compile(r'<link[^>]+href="([^"]+\.css)"')


@dataclass(frozen=True)
class Release:
    """One immutable browser build and the API generation it expects."""

    directory: Path
    entry: str
    css: str
    id: str
    api: int
    built: str
    legacy: bool = False
    valid: bool = True
    broken: str = ""
    files: int = 0
    tree: str = ""

    def as_health(self) -> dict:
        return {
            "release": self.id,
            "frontend": self.entry,
            "css": self.css,
            "releaseBuilt": self.built,
            "releaseLegacy": self.legacy,
            "releaseValid": self.valid,
            "releaseFiles": self.files,
            **({"releaseProblem": self.broken} if self.broken else {}),
        }


def _entry_from_html(index: Path) -> tuple[str, str]:
    try:
        html = index.read_text(encoding="utf-8")
    except OSError:
        return "", ""
    entry = ENTRY_PATTERN.search(html)
    css = CSS_PATTERN.search(html)
    return (
        Path(entry.group(1)).name if entry else "",
        Path(css.group(1)).name if css else "",
    )


def _tree_hash(files) -> str:
    text = "\n".join(f"{f['path']}:{f['size']}:{f['sha256']}" for f in files)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _verify(directory: Path, data: dict) -> tuple[bool, str, int, str]:
    """Verify a published release against its complete file manifest."""
    listed = data.get("files")
    tree = str(data.get("tree") or "")
    if not isinstance(listed, list) or not listed or not tree:
        # Schema-1 release: no file list. Required entry files still must exist.
        entry = str(data.get("entry") or "")
        css = str(data.get("css") or "")
        if entry and not (directory / "assets" / entry).is_file():
            return False, f"entry {entry} is missing", 0, ""
        if css and not (directory / "assets" / css).is_file():
            return False, f"stylesheet {css} is missing", 0, ""
        return True, "", 0, ""
    actual = []
    for item in listed:
        if not isinstance(item, dict):
            return False, "manifest contains an invalid file entry", len(listed), tree
        rel = str(item.get("path") or "")
        if not rel or rel.startswith(("/", "..")) or ".." in Path(rel).parts:
            return False, f"unsafe manifest path {rel!r}", len(listed), tree
        path = directory / rel
        if not path.is_file():
            return False, f"published file {rel} is missing", len(listed), tree
        size = path.stat().st_size
        if size != int(item.get("size", -1)):
            return False, f"published file {rel} has the wrong size", len(listed), tree
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != str(item.get("sha256")):
            return False, f"published file {rel} failed its checksum", len(listed), tree
        actual.append({"path": rel, "size": size, "sha256": digest})
    actual.sort(key=lambda f: f["path"])
    if _tree_hash(actual) != tree:
        return False, "release tree digest does not match its manifest", len(listed), tree
    return True, "", len(listed), tree


def resolve(web: Path, override: Path | None = None) -> Release:
    """Return the release to serve, verifying a schema-2 file manifest."""
    dist = Path(override) if override else web / "dist"
    manifest = dist / MANIFEST
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        release_id = str(data.get("id") or "")
        entry = str(data.get("entry") or "")
        # Releases live beside `dist`, not inside it: `vite build` empties the
        # output directory, and must not delete the release a server is using.
        directory = web / RELEASES / release_id
        if release_id and entry and (directory / "index.html").is_file():
            valid, broken, count, tree = _verify(directory, data)
            return Release(
                directory=directory,
                entry=entry,
                css=str(data.get("css") or ""),
                id=release_id,
                api=int(data.get("api") or 0),
                built=str(data.get("built") or ""),
                valid=valid,
                broken=broken,
                files=count,
                tree=tree,
            )
    entry, css = _entry_from_html(dist / "index.html")
    return Release(
        directory=dist,
        entry=entry,
        css=css,
        id="legacy:" + entry if entry else "legacy",
        api=0,
        built="",
        legacy=True,
    )
