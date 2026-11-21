"""Shared workflow helpers for the mesh-first pipeline (not a test module)."""

from services import store


def post(api, path, data):
    res = api.post(path, json=data)
    assert res.is_success, res.text
    return res.json()


def run_worker(owner="test"):
    from services.worker.__main__ import once

    assert once(owner)


def prepare_mesh(api, revision, owner="test"):
    mesh = post(api, "/api/meshes", {"revision": revision["id"], "token": store.new_id()})
    run_worker(owner)
    job = store.job(mesh["id"])
    assert job["status"] == "Completed", job["diagnostic"]
    return job


def save_fixture(api, mesh_id, labels):
    res = api.put("/api/meshes/" + str(mesh_id) + "/fixture", json={"labels": labels})
    assert res.is_success, res.text
    return res.json()


def legacy_fixture(api, mesh_id):
    """Resolve the stored CAD-edge mounting selection to nodes of this mesh."""
    return post(api, "/api/meshes/" + str(mesh_id) + "/fixture/edges", {})


def prepare_deck(api, revision, mesh_id, owner="test"):
    deck = post(
        api, "/api/decks", {"revision": revision["id"], "token": store.new_id(), "mesh": mesh_id}
    )
    run_worker(owner)
    job = store.job(deck["id"])
    assert job["status"] == "Completed", job["diagnostic"]
    return job


def prepared(api, revision=None, owner="test"):
    """Create (if needed) a model with a completed mesh, fixture and deck."""
    if revision is None:
        revision = post(api, "/api/projects", {"name": "Section"})
    mesh = prepare_mesh(api, revision, owner)
    labels = legacy_fixture(api, mesh["id"])["labels"]
    save_fixture(api, mesh["id"], labels)
    deck = prepare_deck(api, revision, mesh["id"], owner)
    return revision, deck, mesh
