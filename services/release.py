"""Resolve the exact browser release this API serves.

A release is published by ``apps/web/scripts/publish-release.mjs`` into
``apps/web/dist/releases/<id>/`` and described by ``apps/web/dist/release.json``.
The running API resolves that directory *once*, at import time, and mounts only
that immutable directory. A later build writes a new release directory and a new
manifest; it never replaces the files of the release a running instance serves.

A checkout that was built before releases existed has no manifest. It is served
from ``dist`` directly and reported as ``legacy`` so the compatibility check can
say so instead of pretending the pair is matched.
"""

from __future__ import annotations

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

    def as_health(self) -> dict:
        return {
            "release": self.id,
            "frontend": self.entry,
            "css": self.css,
            "releaseBuilt": self.built,
            "releaseLegacy": self.legacy,
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


def resolve(web: Path, override: Path | None = None) -> Release:
    """Return the release to serve, preferring an explicit dist override.

    ``ABAQUS_QOL_WEB_DIST`` lets an isolated acceptance run serve its own build
    without touching the publisher's live ``dist`` directory.
    """
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
            return Release(
                directory=directory,
                entry=entry,
                css=str(data.get("css") or ""),
                id=release_id,
                api=int(data.get("api") or 0),
                built=str(data.get("built") or ""),
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
