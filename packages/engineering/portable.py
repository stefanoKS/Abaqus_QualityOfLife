"""Portable model and result containers.

``.aqmodel`` and ``.aqresult`` are versioned ZIP containers with a manifest that
names every member, its size and its SHA-256. Opening one validates the content
kind, the version, the required members, the member hashes, the expansion bound
and every path before extracting anything. A JSON or INP file renamed to one of
these extensions therefore cannot pass.

Nothing here depends on an absolute path or on the database: a model file carries
the canonical setup, its source provenance and the exact library snapshots it was
saved with; a result file carries the submitted setup, the result index, every
frame and the solver/extraction provenance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import os
import re
import tempfile
import zipfile

MODEL_KIND = "abaqus-qol-model"
RESULT_KIND = "abaqus-qol-result"
VERSION = 1
MAX_MEMBERS = 5000
MAX_EXPANSION = 4 * 1024 * 1024 * 1024
MAX_MEMBER = 2 * 1024 * 1024 * 1024
SAFE = re.compile(r"^[A-Za-z0-9._/-]+$")


class PortableError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _manifest(kind: str, members: dict[str, bytes], extra: dict) -> dict:
    return {
        "kind": kind,
        "version": VERSION,
        "created": datetime.now(timezone.utc).isoformat(),
        **extra,
        "members": [
            {
                "name": name,
                "bytes": len(payload),
                "sha256": digest(payload),
            }
            for name, payload in sorted(members.items())
        ],
    }


def write_container(path: Path, kind: str, members: dict[str, bytes], extra: dict) -> dict:
    """Publish a container atomically: stage, verify by re-reading, then replace."""
    if not members:
        raise PortableError("empty", "A container needs at least one member.")
    for name in members:
        if not SAFE.match(name) or ".." in name.split("/"):
            raise PortableError("unsafe-member", f"Unsafe member name {name!r}.")
    manifest = _manifest(kind, members, extra)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".partial", dir=str(path.parent)
    )
    # mkstemp returns an open descriptor; close it before writing on Windows.
    os.close(handle)
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
            for name, payload in sorted(members.items()):
                archive.writestr(name, payload)
        check = read_container(Path(temporary), kind)
        if check["manifest"]["members"] != manifest["members"]:
            raise PortableError("verify", "The staged container did not round-trip.")
        Path(temporary).replace(path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    return {
        "path": str(path),
        "kind": kind,
        "version": VERSION,
        "bytes": path.stat().st_size,
        "sha256": digest(path.read_bytes()),
        "members": len(members),
    }


def read_container(path: Path, expect: str | None = None) -> dict:
    path = Path(path)
    if not path.is_file():
        raise PortableError("missing", "The file is no longer available.")
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise PortableError("not-container", "The file is not a readable portable container.") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_MEMBERS:
            raise PortableError("too-many-members", "The container has too many members.")
        total = sum(info.file_size for info in infos)
        if total > MAX_EXPANSION:
            raise PortableError("too-large", "The container expands beyond the supported size.")
        for info in infos:
            name = info.filename
            if (
                not SAFE.match(name)
                or ".." in name.split("/")
                or name.startswith("/")
                or "\\" in name
            ):
                raise PortableError("unsafe-member", f"Unsafe member name {name!r}.")
            if info.file_size > MAX_MEMBER:
                raise PortableError("too-large", f"Member {name} is too large.")
        try:
            manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        except (KeyError, ValueError) as exc:
            raise PortableError("manifest", "The container manifest is missing or invalid.") from exc
        kind = manifest.get("kind")
        if expect and kind != expect:
            raise PortableError(
                "wrong-kind",
                f"This file is a {kind or 'unknown'} container, not a {expect} file.",
            )
        if kind not in (MODEL_KIND, RESULT_KIND):
            raise PortableError("wrong-kind", "The container kind is not supported.")
        if int(manifest.get("version") or 0) != VERSION:
            raise PortableError(
                "unsupported-version",
                f"Container version {manifest.get('version')} is not supported by this build.",
            )
        listed = {entry["name"]: entry for entry in manifest.get("members", [])}
        names = [info.filename for info in infos if info.filename != "manifest.json"]
        if set(names) != set(listed):
            raise PortableError("member-list", "The container members do not match its manifest.")
        members: dict[str, bytes] = {}
        for name in names:
            payload = archive.read(name)
            entry = listed[name]
            if len(payload) != int(entry["bytes"]) or digest(payload) != entry["sha256"]:
                raise PortableError("member-hash", f"Member {name} does not match its manifest.")
            members[name] = payload
    required = {"model.json"} if kind == MODEL_KIND else {"results.json", "setup.json"}
    if not required <= set(members):
        raise PortableError(
            "missing-member",
            "The container is missing " + ", ".join(sorted(required - set(members))) + ".",
        )
    return {"manifest": manifest, "members": members}


def model_container(setup: dict, source: dict, mesh: dict | None, fixture: dict | None) -> dict[str, bytes]:
    members = {
        "model.json": json.dumps(setup, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        "source.json": json.dumps(source, ensure_ascii=False, indent=1).encode("utf-8"),
    }
    if mesh is not None:
        members["mesh.json"] = json.dumps(mesh, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    if fixture is not None:
        members["fixture.json"] = json.dumps(
            fixture, ensure_ascii=False, indent=1
        ).encode("utf-8")
    return members


def result_container(
    setup: dict,
    index: dict,
    history: bytes,
    frames: dict[str, bytes],
    provenance: dict,
) -> dict[str, bytes]:
    members = {
        "setup.json": json.dumps(setup, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        "results.json": json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        "provenance.json": json.dumps(provenance, ensure_ascii=False, indent=1).encode("utf-8"),
    }
    if history:
        members["history.csv"] = history
    for name, payload in frames.items():
        members["frames/" + name] = payload
    return members
