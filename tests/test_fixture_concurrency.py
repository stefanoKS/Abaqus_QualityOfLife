"""Two synchronized fixture writers must not both overwrite a reviewed set.

The compare-and-set happens inside one SQLite write transaction, so the loser
gets 409 and the deck snapshots exactly the winner's nodes.
"""

import json
import re
import threading

import pytest
from fastapi.testclient import TestClient

from services import store
from services.api.main import app
from support import create_model, legacy_fixture, prepare_mesh, run_worker, save_fixture


def wsfix_nodes(inp):
    nodes = []
    inside = False
    for line in inp.splitlines():
        if line.lower().startswith("*nset") and "wsfix" in line.lower():
            inside = True
            continue
        if inside and line.startswith("*"):
            break
        if inside:
            nodes.extend(int(value) for value in re.findall(r"\d+", line))
    return sorted(nodes)


def test_synchronized_fixture_writers_only_one_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        revision = create_model(api, "Fixture race", example=True)
        mesh = prepare_mesh(api, revision)
        labels = legacy_fixture(api, mesh["id"])["labels"]
        first = save_fixture(api, mesh["id"], labels)
        base = first["fixture"]["hash"]
        assert base

        half = max(1, len(labels) // 2)
        choices = [labels[:half], labels[half:]]
        assert choices[0] != choices[1]

        barrier = threading.Barrier(2)
        results = []

        def writer(selection):
            barrier.wait(timeout=30)
            response = api.put(
                f"/api/meshes/{mesh['id']}/fixture",
                json={"labels": selection, "expected_hash": base},
            )
            results.append((response.status_code, selection, response))

        threads = [threading.Thread(target=writer, args=(choice,)) for choice in choices]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)

        codes = sorted(code for code, _, _ in results)
        assert codes == [200, 409], [(code, response.text) for code, _, response in results]
        winner = next(selection for code, selection, _ in results if code == 200)
        stored = store.fixture(mesh["id"])
        assert stored["labels"] == winner
        assert stored["hash"]

        # The winning selection is the one a deck snapshots, and its INP WSFIX
        # contains exactly the winning nodes.
        deck = api.post(
            "/api/decks",
            json={
                "revision": revision["id"],
                "token": store.new_id(),
                "mesh": mesh["id"],
                "fixture_hash": stored["hash"],
            },
        )
        assert deck.status_code == 200, deck.text
        run_worker()
        job = store.job(deck.json()["id"])
        assert job["status"] == "Completed", job["diagnostic"]
        inp = (store.job_dir(job["id"]) / "analysis.inp").read_text(encoding="utf-8")
        assert wsfix_nodes(inp) == sorted(int(label.split(":")[1]) for label in winner)

        # The losing reviewed hash can no longer prepare a deck.
        before = len(api.get("/api/decks").json())
        stale = api.post(
            "/api/decks",
            json={
                "revision": revision["id"],
                "token": store.new_id(),
                "mesh": mesh["id"],
                "fixture_hash": base,
            },
        )
        assert stale.status_code == 409
        assert len(api.get("/api/decks").json()) == before

        # A stale unconditional overwrite is still possible only through the
        # documented legacy path; the modern UI always sends expected_hash.
        current = store.fixture(mesh["id"])
        assert current["labels"] == winner
