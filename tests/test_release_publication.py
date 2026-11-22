"""Release publication must be complete, verified and recoverable.

A publisher that accepts an existing ``index.html`` as a release can point the
manifest at JavaScript and CSS that was never copied. These tests stage real
temporary trees, interrupt a publication and verify recovery, and prove that a
new release never alters the files of an older one.
"""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services import release

ROOT = Path(__file__).resolve().parents[1]
PUBLISHER = ROOT / "apps" / "web" / "scripts" / "publish-release.mjs"
NODE = shutil.which("node")


pytestmark = pytest.mark.skipif(NODE is None, reason="Node.js is not installed")


def make_tree(tmp_path, js="console.log('A')\n", css="body{color:black}\n"):
    web = tmp_path / "apps" / "web"
    dist = web / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (web / "scripts").mkdir(parents=True)
    shutil.copy2(PUBLISHER, web / "scripts" / "publish-release.mjs")
    (dist / "index.html").write_text(
        '<script type="module" crossorigin src="/assets/index-A.js"></script>'
        '<link rel="stylesheet" href="/assets/index-A.css">',
        encoding="utf-8",
    )
    (assets / "index-A.js").write_text(js, encoding="utf-8")
    (assets / "index-A.css").write_text(css, encoding="utf-8")
    (assets / "logo-A.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    services = tmp_path / "services" / "api"
    services.mkdir(parents=True)
    (services / "main.py").write_text("API_VERSION = 3\n", encoding="utf-8")
    return web, dist


def publish(web, dist):
    return subprocess.run(
        [NODE, str(web / "scripts" / "publish-release.mjs"), str(dist)],
        cwd=web,
        capture_output=True,
        text=True,
        timeout=120,
    )


def tree_digest(directory):
    files = sorted(p for p in directory.rglob("*") if p.is_file())
    return {
        str(p.relative_to(directory)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
    }


def test_publication_writes_a_verified_complete_manifest(tmp_path):
    web, dist = make_tree(tmp_path)
    result = publish(web, dist)
    assert result.returncode == 0, result.stderr
    manifest = json.loads((dist / "release.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == 2
    assert manifest["api"] == 3
    assert manifest["files"]
    directory = web / "releases" / manifest["id"]
    assert (directory / "index.html").is_file()
    for item in manifest["files"]:
        assert (directory / item["path"]).is_file(), item["path"]
    resolved = release.resolve(web)
    assert resolved.valid is True
    assert resolved.id == manifest["id"]
    assert resolved.files == len(manifest["files"])


def test_interrupted_publication_is_repaired_on_retry(tmp_path):
    web, dist = make_tree(tmp_path)
    first = publish(web, dist)
    assert first.returncode == 0, first.stderr
    manifest = json.loads((dist / "release.json").read_text(encoding="utf-8"))
    directory = web / "releases" / manifest["id"]
    # Simulate a copy interrupted after index.html: entry, styles and manifest gone.
    for path in directory.iterdir():
        if path.name != "index.html":
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
    assert [p.name for p in directory.iterdir()] == ["index.html"]

    retry = publish(web, dist)
    assert retry.returncode == 0, retry.stderr
    manifest = json.loads((dist / "release.json").read_text(encoding="utf-8"))
    directory = web / "releases" / manifest["id"]
    assert (directory / "manifest.json").is_file()
    assert (directory / "assets" / "index-A.js").is_file()
    assert (directory / "assets" / "index-A.css").is_file()
    resolved = release.resolve(web)
    assert resolved.valid is True


def test_missing_source_asset_fails_without_rewriting_the_manifest(tmp_path):
    web, dist = make_tree(tmp_path)
    assert publish(web, dist).returncode == 0
    before = (dist / "release.json").read_text(encoding="utf-8")
    (dist / "assets" / "index-A.js").unlink()

    result = publish(web, dist)
    assert result.returncode != 0
    assert "missing" in (result.stderr + result.stdout).lower()
    assert (dist / "release.json").read_text(encoding="utf-8") == before


def test_publishing_b_leaves_release_a_untouched(tmp_path):
    web, dist = make_tree(tmp_path, js="console.log('A')\n")
    assert publish(web, dist).returncode == 0
    first = json.loads((dist / "release.json").read_text(encoding="utf-8"))
    first_dir = web / "releases" / first["id"]
    first_files = tree_digest(first_dir)

    (dist / "assets" / "index-A.js").write_text("console.log('B')\n", encoding="utf-8")
    (dist / "assets" / "index-A.css").write_text("body{color:blue}\n", encoding="utf-8")
    assert publish(web, dist).returncode == 0
    second = json.loads((dist / "release.json").read_text(encoding="utf-8"))
    assert second["id"] != first["id"]
    assert tree_digest(first_dir) == first_files

    # A still verifies independently even though dist now points at B.
    still_valid, problem, count, _ = release._verify(first_dir, first)
    assert still_valid is True, problem
    assert count == len(first["files"])


def test_resolver_rejects_a_manifest_with_a_missing_file(tmp_path):
    web, dist = make_tree(tmp_path)
    assert publish(web, dist).returncode == 0
    manifest = json.loads((dist / "release.json").read_text(encoding="utf-8"))
    (web / "releases" / manifest["id"] / "assets" / "index-A.js").unlink()
    resolved = release.resolve(web)
    assert resolved.valid is False
    assert "missing" in resolved.broken.lower()
