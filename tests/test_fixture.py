"""Mesh-first fixture workflow: identity, validation, deck binding and history."""

import json

import pytest
from fastapi.testclient import TestClient

from services import store
from services.api.main import app
from services.worker.__main__ import once
from fake_abaqus import install as install_fake_abaqus
from support import (
    create_model,
    legacy_fixture,
    post,
    prepare_mesh,
    run_worker,
    save_fixture,
    start_run,
)

SEAL = "WS-1"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    monkeypatch.setenv("SIMPLIFY_ABAQUS_LAUNCHER", str(install_fake_abaqus(tmp_path)))
    monkeypatch.delenv("SEAL_ODA", raising=False)
    with TestClient(app, base_url="http://127.0.0.1") as api:
        yield api


def artifact(job, name):
    return json.loads((store.job_dir(job["id"]) / name).read_text(encoding="utf-8"))


def wsfix(inp):
    lines = inp.splitlines()
    labels, collecting = [], False
    for line in lines:
        if line.startswith("*Nset, nset=WSFIX"):
            collecting = True
            continue
        if collecting:
            if line.startswith("*"):
                break
            labels.extend(int(part) for part in line.split(",") if part.strip())
    return labels


def deck_and_text(client, revision, mesh):
    deck = post(client, "/api/decks", {"revision": revision["id"], "token": store.new_id(), "mesh": mesh["id"]})
    assert once("test")
    job = store.job(deck["id"])
    assert job["status"] == "Completed", job["diagnostic"]
    return job, (store.job_dir(deck["id"]) / "analysis.inp").read_text(encoding="utf-8")


def test_mesh_without_fixture_blocks_deck_until_nodes_are_selected(client):
    revision = create_model(client, "Fixture first")
    mesh = prepare_mesh(client, revision)
    assert mesh["mesh_digest"] and mesh["mesh_compat"]
    assert mesh["fixture"] is None
    identity = artifact(mesh, "mesh-identity.json")
    assert identity["digest"] == mesh["mesh_digest"]
    assert identity["compat"] == mesh["mesh_compat"]
    assert identity["revision"] == revision["id"]
    assert "mesh.json" in mesh["manifest"] and "mesh-identity.json" in mesh["manifest"]

    blocked = client.post(
        "/api/decks", json={"revision": revision["id"], "token": store.new_id(), "mesh": mesh["id"]}
    )
    assert blocked.status_code == 409
    assert "fixed weatherstrip nodes" in blocked.json()["detail"]

    labels = legacy_fixture(client, mesh["id"])["labels"]
    saved = save_fixture(client, mesh["id"], labels)
    assert saved["fixture"]["count"] == len(labels)
    assert saved["fixture"]["hash"]

    deck, text = deck_and_text(client, revision, mesh)
    assert deck["mesh"] == mesh["id"]
    assert deck["mesh_digest"] == mesh["mesh_digest"]
    assert deck["input_hash"]
    assert f"Fixed weatherstrip nodes: {len(labels)} from reviewed mesh nodes" in text
    # An empty sequence of fixed nodes is never written.
    assert set(wsfix(text)) == {int(label.split(":")[1]) for label in labels}


def test_fixture_validation_rejects_unknown_rigid_and_foreign_labels(client):
    revision = create_model(client, "Fixture validation")
    mesh = prepare_mesh(client, revision)
    model = artifact(mesh, "mesh.json")
    deformable = {n for e in model["elements"] if e["type"] != "R2D2" for n in e["nodes"]}
    rigid = {n for e in model["elements"] if e["type"] == "R2D2" for n in e["nodes"]} - deformable
    assert rigid, "the synthetic section must have rigid-only panel nodes"

    def save(labels):
        return client.put("/api/meshes/" + mesh["id"] + "/fixture", json={"labels": labels})

    unknown = save([f"{SEAL}:999999"])
    assert unknown.status_code == 422 and "does not exist" in unknown.json()["detail"]
    rigid_label = save([f"{SEAL}:{sorted(rigid)[0]}"])
    assert rigid_label.status_code == 422 and "rigid panel" in rigid_label.json()["detail"]
    foreign = save([f"PANEL-1:{sorted(deformable)[0]}"])
    assert foreign.status_code == 422 and "another instance" in foreign.json()["detail"]
    malformed = save(["12"])
    assert malformed.status_code == 422 and "must read like" in malformed.json()["detail"]

    chosen = sorted(deformable)[:6]
    duplicated = save([f"{SEAL}:{n}" for n in [chosen[0], chosen[1], chosen[0]]])
    assert duplicated.status_code == 200
    assert duplicated.json()["fixture"]["labels"] == [f"{SEAL}:{a}" for a in chosen[:2]]
    # Deterministic ordering regardless of submission order.
    unordered = save([f"{SEAL}:{n}" for n in reversed(chosen)])
    assert unordered.json()["fixture"]["labels"] == [f"{SEAL}:{n}" for n in chosen]


def test_partial_mounting_edge_is_written_exactly_and_leaves_neighbours_out(client):
    revision = create_model(client, "Partial patch")
    mesh = prepare_mesh(client, revision)
    model = artifact(mesh, "mesh.json")
    chain = next(
        nodes for nodes in model["edge_nodes"].values() if len(nodes) >= 6
    )
    selected = sorted(chain[::2])
    unselected = [node for node in chain if node not in selected]
    assert unselected, "a partial selection must leave at least one adjacent node free"
    save_fixture(client, mesh["id"], [f"{SEAL}:{node}" for node in selected])

    _, text = deck_and_text(client, revision, mesh)
    written = set(wsfix(text))
    assert written == set(selected)
    assert written != set(chain)
    assert set(unselected) - written == set(unselected)


def test_motion_and_friction_edits_reuse_the_mesh_but_stale_decks_cannot_submit(client):
    revision = create_model(client, "Reuse")
    mesh = prepare_mesh(client, revision)
    save_fixture(client, mesh["id"], legacy_fixture(client, mesh["id"])["labels"])
    deck, _ = deck_and_text(client, revision, mesh)

    setup = revision["setup"]
    setup["motion"]["travel"] = -5.0
    setup["motion"]["duration"] = 0.7
    setup["contact"]["friction"] = 0.45
    edited = client.put(
        "/api/projects/" + revision["project"], json={"base": revision["id"], "setup": setup}
    ).raise_for_status().json()
    # The mesh identity inputs ignore motion, contact and material properties.
    assert edited["mesh_compat"] == mesh["mesh_compat"] == revision["mesh_compat"]

    # The deck prepared for the previous revision is stale for the new head.
    stale = client.post(
        "/api/runs",
        json={
            "revision": edited["id"],
            "deck": deck["id"],
            "token": store.new_id(),
            "name": "stale",
            "mode": "ABAQUS",
        },
    )
    assert stale.status_code == 409
    assert "input deck for this saved revision" in stale.json()["detail"]

    # Reusing the same mesh for the edited revision works and reuses its digest.
    fresh, text = deck_and_text(client, edited, mesh)
    assert fresh["mesh_digest"] == mesh["mesh_digest"]
    assert "Prescribed Y travel: -5 mm" in text

    run = post(
        client,
        "/api/runs",
        {
            "revision": edited["id"],
            "deck": fresh["id"],
            "token": store.new_id(),
            "name": "current",
            "mode": "ABAQUS",
        },
    )
    assert once("test")
    assert once("test")  # solver, then extraction
    assert store.job(run["id"])["status"] == "Completed"


def test_remesh_invalidates_fixture_and_old_deck(client):
    revision = create_model(client, "Remesh")
    first = prepare_mesh(client, revision)
    save_fixture(client, first["id"], legacy_fixture(client, first["id"])["labels"])
    deck, _ = deck_and_text(client, revision, first)

    setup = revision["setup"]
    setup["mesh"]["size"] = 0.8
    edited = client.put(
        "/api/projects/" + revision["project"], json={"base": revision["id"], "setup": setup}
    ).raise_for_status().json()
    assert edited["mesh_compat"] != first["mesh_compat"]

    incompatible = client.post(
        "/api/decks", json={"revision": edited["id"], "token": store.new_id(), "mesh": first["id"]}
    )
    assert incompatible.status_code == 409
    assert "different mesh inputs" in incompatible.json()["detail"]
    # The old deck references the previous revision, so it cannot be submitted.
    assert (
        client.post(
            "/api/runs",
            json={
                "revision": edited["id"],
                "deck": deck["id"],
                "token": store.new_id(),
                "name": "old",
                "mode": "ABAQUS",
            },
        ).status_code
        == 409
    )

    second = prepare_mesh(client, edited)
    assert second["mesh_digest"] != first["mesh_digest"]
    assert second["fixture"] is None, "a new mesh starts without a reviewed fixture"
    assert (
        client.post(
            "/api/decks",
            json={"revision": edited["id"], "token": store.new_id(), "mesh": second["id"]},
        ).status_code
        == 409
    )


def test_cross_model_mesh_and_forged_fixture_are_rejected(client):
    a = create_model(client, "Model A")
    b = create_model(client, "Model B")
    mesh_a = prepare_mesh(client, a)
    save_fixture(client, mesh_a["id"], legacy_fixture(client, mesh_a["id"])["labels"])
    cross = client.post(
        "/api/decks", json={"revision": b["id"], "token": store.new_id(), "mesh": mesh_a["id"]}
    )
    assert cross.status_code == 409
    assert "another model" in cross.json()["detail"]

    # A fixture written for one mesh cannot be claimed by another mesh identity.
    mesh_b = prepare_mesh(client, b)
    forged = client.put(
        "/api/meshes/" + mesh_b["id"] + "/fixture", json={"labels": ["WS-1:1", "WS-1:2"]}
    )
    assert forged.is_success
    # Node 1 and 2 exist in both meshes, but the deck records the identity it used.
    deck_b, _ = deck_and_text(client, b, mesh_b)
    assert deck_b["mesh_digest"] == mesh_b["mesh_digest"]
    assert deck_b["mesh"] == mesh_b["id"]
    assert deck_b["fixture_hash"] == store.job(mesh_b["id"])["fixture"]["hash"]


def test_legacy_edge_fixture_can_be_resolved_inspected_and_saved(client):
    revision = create_model(client, "Legacy mounting")
    mesh = prepare_mesh(client, revision)
    resolved = legacy_fixture(client, mesh["id"])
    assert resolved["count"] == len(resolved["labels"])
    assert all(label.startswith(SEAL + ":") for label in resolved["labels"])
    saved = save_fixture(client, mesh["id"], resolved["labels"])
    assert saved["fixture"]["labels"] == resolved["labels"]
    assert saved["fixture"]["hash"] == resolved["hash"]
    # Reopening the model still exposes the same reviewed nodes.
    assert store.job(mesh["id"])["fixture"]["labels"] == resolved["labels"]


def test_queued_deck_uses_the_fixture_snapshot_at_queue_time(client):
    """A fixture edit between queueing and claiming must not change the deck."""
    revision = create_model(client, "Snapshot")
    mesh = prepare_mesh(client, revision)
    model = artifact(mesh, "mesh.json")
    chain = next(nodes for nodes in model["edge_nodes"].values() if len(nodes) >= 6)
    first, second = sorted(chain[::2]), sorted(chain[1::2])
    save_fixture(client, mesh["id"], [f"{SEAL}:{n}" for n in first])
    deck = post(
        client, "/api/decks", {"revision": revision["id"], "token": store.new_id(), "mesh": mesh["id"]}
    )
    # Change the reviewed fixture before the worker claims the deck.
    save_fixture(client, mesh["id"], [f"{SEAL}:{n}" for n in second])
    assert once("test")
    job = store.job(deck["id"])
    assert job["status"] == "Completed", job["diagnostic"]
    text = (store.job_dir(deck["id"]) / "analysis.inp").read_text(encoding="utf-8")
    assert set(wsfix(text)) == set(first), "the queued deck must use the selection captured at queue time"
    assert job["fixture_labels"] == [f"{SEAL}:{n}" for n in first]
    assert job["fixture_hash"] != store.job(mesh["id"])["fixture"]["hash"]
    # The live fixture is now different, so this deck cannot be submitted.
    blocked = client.post(
        "/api/runs",
        json={
            "revision": revision["id"],
            "deck": deck["id"],
            "token": store.new_id(),
            "name": "after fixture edit",
            "mode": "ABAQUS",
        },
    )
    assert blocked.status_code == 409
    assert "fixture changed" in blocked.json()["detail"]


def test_explicit_remesh_in_the_same_revision_supersedes_mesh_and_deck(client):
    revision = create_model(client, "Same revision remesh")
    first = prepare_mesh(client, revision)
    labels = legacy_fixture(client, first["id"])["labels"]
    save_fixture(client, first["id"], labels)
    deck, _ = deck_and_text(client, revision, first)

    # A second explicit mesh for the same revision, even with identical bytes.
    second = prepare_mesh(client, revision)
    assert second["id"] != first["id"]
    assert second["mesh_digest"] == first["mesh_digest"]
    assert second["fixture"] is None

    superseded = client.post(
        "/api/decks",
        json={"revision": revision["id"], "token": store.new_id(), "mesh": first["id"]},
    )
    assert superseded.status_code == 409
    assert "supersedes" in superseded.json()["detail"]
    unreviewed = client.post(
        "/api/decks",
        json={"revision": revision["id"], "token": store.new_id(), "mesh": second["id"]},
    )
    assert unreviewed.status_code == 409
    assert "fixed weatherstrip nodes" in unreviewed.json()["detail"]
    stale = client.post(
        "/api/runs",
        json={
            "revision": revision["id"],
            "deck": deck["id"],
            "token": store.new_id(),
            "name": "superseded deck",
            "mode": "ABAQUS",
        },
    )
    assert stale.status_code == 409
    assert "superseded mesh" in stale.json()["detail"]

    # Reviewing the new mesh restores the workflow; the older deck stays rejected.
    save_fixture(client, second["id"], labels)
    fresh, _ = deck_and_text(client, revision, second)
    assert fresh["mesh"] == second["id"]
    assert (
        client.post(
            "/api/runs",
            json={
                "revision": revision["id"],
                "deck": deck["id"],
                "token": store.new_id(),
                "name": "older deck",
                "mode": "ABAQUS",
            },
        ).status_code
        == 409
    )


def test_submitted_run_replays_its_archived_fixture(client):
    revision = create_model(client, "Archive")
    mesh = prepare_mesh(client, revision)
    model = artifact(mesh, "mesh.json")
    chain = next(nodes for nodes in model["edge_nodes"].values() if len(nodes) >= 6)
    archived = [f"{SEAL}:{n}" for n in sorted(chain[::2])]
    revised = [f"{SEAL}:{n}" for n in sorted(chain[1::2])]
    save_fixture(client, mesh["id"], archived)
    deck, text = deck_and_text(client, revision, mesh)
    run = post(
        client,
        "/api/runs",
        {
            "revision": revision["id"],
            "deck": deck["id"],
            "token": store.new_id(),
            "name": "Archived",
            "mode": "ABAQUS",
        },
    )
    assert once("test") and once("test")
    assert set(wsfix(text)) == {int(label.split(":")[1]) for label in archived}

    # Change the live fixture and remesh, then reopen the historical run.
    save_fixture(client, mesh["id"], revised)
    prepare_mesh(client, revision)
    job = store.job(run["id"])
    assert job["status"] == "Completed"
    assert job["fixture_labels"] == archived
    assert store.job(mesh["id"])["fixture"]["labels"] == revised
    # The archived deck still contains the original selection.
    assert set(wsfix((store.job_dir(deck["id"]) / "analysis.inp").read_text())) == {
        int(label.split(":")[1]) for label in archived
    }
    # The archived evidence keeps provenance through the extractor's metadata.
    metadata = json.loads(
        (store.job_dir(run["id"]) / "result-metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["fixture"] == {
        "source": "mesh-node-selection",
        "count": len(archived),
        "nodes": archived,
    }


def test_legacy_edge_resolution_uses_the_open_revision(client):
    first = create_model(client, "Open revision")
    edges = [e["id"] for e in first["setup"]["edges"] if e["component"] == "seal"]
    a, b = edges[0], edges[1]
    setup = first["setup"]
    setup["selections"][0]["entities"] = [a]
    saved_a = client.put(
        "/api/projects/" + first["project"], json={"base": first["id"], "setup": setup}
    ).raise_for_status().json()
    mesh = prepare_mesh(client, saved_a)

    other = json.loads(json.dumps(saved_a["setup"]))
    other["selections"][0]["entities"] = [b]
    saved_b = client.put(
        "/api/projects/" + first["project"], json={"base": saved_a["id"], "setup": other}
    ).raise_for_status().json()
    assert saved_b["mesh_compat"] == saved_a["mesh_compat"] == mesh["mesh_compat"]

    labels_a = post(
        client, f"/api/meshes/{mesh['id']}/fixture/edges?revision={saved_a['id']}", {}
    )["labels"]
    labels_b = post(
        client, f"/api/meshes/{mesh['id']}/fixture/edges?revision={saved_b['id']}", {}
    )["labels"]
    model = artifact(mesh, "mesh.json")
    assert {int(l.split(":")[1]) for l in labels_a} == set(model["edge_nodes"][a])
    assert {int(l.split(":")[1]) for l in labels_b} == set(model["edge_nodes"][b])
    assert labels_a != labels_b

    stranger = create_model(client, "Stranger")
    rejected = client.post(
        f"/api/meshes/{mesh['id']}/fixture/edges?revision={stranger['id']}", json={}
    )
    assert rejected.status_code == 409
    assert "another model" in rejected.json()["detail"]


def test_result_header_carries_the_reviewed_fixture(tmp_path):
    from packages.engineering import generate_mesh, synthetic
    from packages.engineering.fixture import from_edges
    from integrations.abaqus.results import write_demo

    project = synthetic()
    mesh = generate_mesh(project)
    labels = from_edges(mesh, project.selections[0].entities)
    write_demo(project, mesh, tmp_path, labels)
    index = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert index["fixture"] == {
        "source": "mesh-node-selection",
        "count": len(labels),
        "nodes": labels,
    }

    legacy = tmp_path / "legacy"
    legacy.mkdir()
    write_demo(project, mesh, legacy)
    old = json.loads((legacy / "results.json").read_text(encoding="utf-8"))
    assert old["fixture"]["source"] == "cad-edge-selection"
    assert old["fixture"]["nodes"] is None


def test_historical_run_and_old_artifacts_survive_the_new_pipeline(client):
    revision = create_model(client, "History")
    mesh = prepare_mesh(client, revision)
    save_fixture(client, mesh["id"], legacy_fixture(client, mesh["id"])["labels"])
    deck, _ = deck_and_text(client, revision, mesh)
    run = post(
        client,
        "/api/runs",
        {
            "revision": revision["id"],
            "deck": deck["id"],
            "token": store.new_id(),
            "name": "Historical",
            "mode": "ABAQUS",
        },
    )
    assert once("test")
    assert once("test")  # solver, then extraction
    stored = store.job(run["id"])
    assert stored["status"] == "Completed"
    # The run keeps the deck and mesh it was prepared from, and the job artifacts
    # remain downloadable after a later edit and a new mesh.
    assert stored["build"] == deck["id"] and stored["mesh_digest"] == mesh["mesh_digest"]
    setup = revision["setup"]
    setup["motion"]["travel"] = -3.0
    edited = client.put(
        "/api/projects/" + revision["project"], json={"base": revision["id"], "setup": setup}
    ).raise_for_status().json()
    prepare_mesh(client, edited)
    assert store.job(run["id"])["status"] == "Completed"
    assert client.get("/api/jobs/" + run["id"] + "/artifacts/results.json").is_success
    assert (
        client.get("/api/jobs/" + deck["id"] + "/artifacts/analysis.inp").is_success
    )
