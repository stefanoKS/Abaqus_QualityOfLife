"""Global material library: immutable versions, pins, usage, archive and import.

A model revision owns an immutable material snapshot. Library edits create new
versions and never rewrite a saved revision or a historical run.
"""

import pytest
from fastapi.testclient import TestClient

from fake_abaqus import install as install_fake_abaqus
from services.api.main import app
from services import store
from support import create_model, prepared, run_worker, start_run


def card_of(material):
    return {
        "model": material["model"],
        "color": material["color"],
        "density": material["density"],
        "young": material["young"],
        "poisson": material["poisson"],
        "test_data": material["test_data"],
    }


def create_library(api, name="Library EPDM"):
    return api.post(
        "/api/materials",
        json={
            "name": name,
            "card": {
                "model": "linear_elastic",
                "color": "#336655",
                "density": 1.1e-9,
                "young": 5.0,
                "poisson": 0.49,
                "test_data": [],
            },
        },
    )


def test_versions_are_immutable_and_name_edits_do_not_version(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        created = create_library(api)
        assert created.status_code == 201, created.text
        material = created.json()
        assert material["current_version"] == 1
        assert material["version_count"] == 1

        rename = api.put(f"/api/materials/{material['id']}", json={"name": "Renamed EPDM"})
        assert rename.status_code == 200
        assert rename.json()["name"] == "Renamed EPDM"
        assert rename.json()["version_count"] == 1

        v1 = material["card"]
        changed = dict(v1, young=8.5)
        updated = api.put(f"/api/materials/{material['id']}", json={"card": changed})
        assert updated.status_code == 200, updated.text
        detail = updated.json()
        assert detail["current_version"] == 2
        assert detail["version_count"] == 2
        assert detail["versions"][0]["version"] == 1
        assert detail["versions"][0]["card"]["young"] == 5.0
        assert detail["versions"][1]["card"]["young"] == 8.5

        # Re-saving identical values must not create a third version.
        again = api.put(f"/api/materials/{material['id']}", json={"card": changed})
        assert again.json()["version_count"] == 2


def test_invalid_library_card_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        bad = api.post(
            "/api/materials",
            json={
                "name": "Bad foam",
                "card": {
                    "model": "hyperfoam_test",
                    "color": "#112233",
                    "density": 1e-9,
                    "test_data": [[0.1, 0.01, -0.005]],
                },
            },
        )
        assert bad.status_code == 422


def test_model_revision_pins_a_version_and_usage(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        revision = create_model(api, "Pinned model", example=True)
        imported = api.post(
            "/api/materials/import", json={"revision": revision["id"]}
        ).json()
        assert len(imported) == 2

        setup = revision["setup"]
        for item in imported:
            material = next(m for m in setup["materials"] if m["id"] == item["material_id"])
            material["library_id"] = item["library_id"]
            material["library_version"] = item["version"]
        saved = api.put(
            f"/api/projects/{revision['project']}",
            json={"base": revision["id"], "setup": setup},
        ).json()

        library_id = imported[0]["library_id"]
        usage = api.get(f"/api/materials/{library_id}").json()["usage"]
        assert [row["revision"] for row in usage] == [saved["id"]]
        assert usage[0]["pinned_version"] == 1

        # A library edit creates v2 but leaves the saved model snapshot alone.
        detail = api.get(f"/api/materials/{library_id}").json()
        changed = dict(detail["card"], young=9.5)
        api.put(f"/api/materials/{library_id}", json={"card": changed})
        still = api.get(f"/api/revisions/{saved['id']}").json()
        pinned = next(m for m in still["setup"]["materials"] if m["library_id"] == library_id)
        assert pinned["young"] != 9.5
        assert pinned["library_version"] == 1

        # Explicit adoption creates a new revision with the new pin.
        adopted = still["setup"]
        target = next(m for m in adopted["materials"] if m["library_id"] == library_id)
        target.update(changed)
        target["library_version"] = 2
        newer = api.put(
            f"/api/projects/{saved['project']}",
            json={"base": saved["id"], "setup": adopted},
        ).json()
        adopted_card = next(m for m in newer["setup"]["materials"] if m["library_id"] == library_id)
        assert adopted_card["young"] == 9.5
        assert adopted_card["library_version"] == 2
        # Material-only changes reuse geometry and mesh identity.
        assert newer["mesh_compat"] == saved["mesh_compat"]

        # The deck written from the adopted revision carries the new value.
        _, deck, _ = prepared(api, newer)
        inp = (api.get(f"/api/jobs/{deck['id']}/artifacts/analysis.inp")).text
        assert "9.5" in inp


def test_two_models_share_one_library_material(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        first = create_model(api, "Model A", example=True)
        imported = api.post("/api/materials/import", json={"revision": first["id"]}).json()
        library = api.get(f"/api/materials/{imported[0]['library_id']}").json()
        first_setup = first["setup"]
        for item in imported:
            material = next(
                m for m in first_setup["materials"] if m["id"] == item["material_id"]
            )
            material["library_id"] = item["library_id"]
            material["library_version"] = item["version"]
        saved_first = api.put(
            f"/api/projects/{first['project']}",
            json={"base": first["id"], "setup": first_setup},
        )
        assert saved_first.status_code == 200, saved_first.text

        second = create_model(api, "Model B", example=True)
        setup = second["setup"]
        target = next(
            m
            for m in setup["materials"]
            if m["model"] == library["card"]["model"]
        )
        target.update(library["card"])
        target["library_id"] = library["id"]
        target["library_version"] = library["current_version"]
        saved = api.put(
            f"/api/projects/{second['project']}",
            json={"base": second["id"], "setup": setup},
        )
        assert saved.status_code == 200, saved.text
        detail = api.get(f"/api/materials/{library['id']}").json()
        assert detail["usage_count"] == 2
        assert len({row["project"] for row in detail["usage"]}) == 2


def test_historical_run_survives_library_edit_and_archive(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    monkeypatch.setenv("SIMPLIFY_ABAQUS_LAUNCHER", str(install_fake_abaqus(tmp_path)))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        revision = create_model(api, "Historical run", example=True)
        imported = api.post(
            "/api/materials/import", json={"revision": revision["id"]}
        ).json()
        setup = revision["setup"]
        base = next(m for m in setup["materials"] if m["id"] == "base_rubber")
        item = next(row for row in imported if row["material_id"] == "base_rubber")
        base["library_id"] = item["library_id"]
        base["library_version"] = item["version"]
        saved = api.put(
            f"/api/projects/{revision['project']}",
            json={"base": revision["id"], "setup": setup},
        ).json()
        _, deck, _ = prepared(api, saved)
        run = start_run(api, saved, deck)
        # One claim runs the solver, the next runs extraction.
        run_worker()
        run_worker()
        completed = store.job(run["id"])
        assert completed["status"] == "Completed", completed["diagnostic"]
        directory = store.job_dir(run["id"])
        before = {
            name: store.digest(directory / name)
            for name in ("analysis.inp", "history.csv", "results.json")
            if (directory / name).is_file()
        }
        assert "analysis.inp" in before
        snapshot_before = api.get(f"/api/revisions/{saved['id']}").json()["setup"]

        # Edit and archive the library material after the run completed.
        detail = api.get(f"/api/materials/{item['library_id']}").json()
        api.put(
            f"/api/materials/{item['library_id']}",
            json={"card": dict(detail["card"], young=12.5)},
        )
        api.post(f"/api/materials/{item['library_id']}/archive")

        # The saved revision, the run and its artifacts are untouched.
        assert api.get(f"/api/revisions/{saved['id']}").json()["setup"] == snapshot_before
        assert api.get(f"/api/jobs/{run['id']}").json()["status"] == "Completed"
        for name, digest in before.items():
            assert store.digest(directory / name) == digest


def test_duplicate_archive_and_restore(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        material = create_library(api).json()
        copy = api.post(
            f"/api/materials/{material['id']}/duplicate", json={"name": "Copy EPDM"}
        )
        assert copy.status_code == 201
        assert copy.json()["id"] != material["id"]
        assert copy.json()["card"] == material["card"]

        archived = api.post(f"/api/materials/{material['id']}/archive")
        assert archived.json()["archived"] is True
        listed = api.get("/api/materials").json()
        assert material["id"] not in {row["id"] for row in listed}
        assert material["id"] in {
            row["id"] for row in api.get("/api/materials?include_archived=true").json()
        }
        refused = api.put(f"/api/materials/{material['id']}", json={"name": "Nope"})
        assert refused.status_code == 409
        restored = api.post(f"/api/materials/{material['id']}/restore")
        assert restored.json()["archived"] is False
        assert api.put(f"/api/materials/{material['id']}", json={"name": "Back"}).status_code == 200


def test_import_never_merges_distinct_cards_by_name(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        a = create_model(api, "Import A", example=True)
        b = create_model(api, "Import B", example=True)
        first = api.post("/api/materials/import", json={"revision": a["id"]}).json()
        second = api.post("/api/materials/import", json={"revision": b["id"]}).json()
        # Same names and identical example values, but separate library entries.
        assert len({row["library_id"] for row in first}) == 2
        assert len({row["library_id"] for row in second}) == 2
        assert {row["library_id"] for row in first}.isdisjoint(
            {row["library_id"] for row in second}
        )

        # Re-importing after the saved revision pins the library is idempotent.
        setup = a["setup"]
        for row in first:
            material = next(m for m in setup["materials"] if m["id"] == row["material_id"])
            material["library_id"] = row["library_id"]
            material["library_version"] = row["version"]
        api.put(f"/api/projects/{a['project']}", json={"base": a["id"], "setup": setup})
        head = next(
            entry
            for entry in api.get("/api/projects").json()
            if entry["id"] == a["project"]
        )
        again = api.post("/api/materials/import", json={"revision": head["revision"]}).json()
        assert all(row["existing"] for row in again)


def test_neo_hookean_library_card_round_trips_and_versions(monkeypatch, tmp_path):
    """A compressible neo-Hookean card keeps C10/D1, units and version history.

    Existing linear-elastic cards are never relabelled as a rubber law.
    """
    monkeypatch.setenv("SEAL_DATA", str(tmp_path))
    with TestClient(app, base_url="http://127.0.0.1") as api:
        created = api.post(
            "/api/materials",
            json={
                "name": "Synthetic neo-Hookean",
                "card": {
                    "model": "neo_hookean",
                    "color": "#2f9e8f",
                    "density": 1.1e-9,
                    "c10": 0.5,
                    "d1": 0.01,
                    "test_data": [],
                },
            },
        )
        assert created.status_code == 201, created.text
        material = created.json()
        assert material["card"]["model"] == "neo_hookean"
        assert material["card"]["c10"] == 0.5
        assert material["card"]["d1"] == 0.01
        assert material["card"]["young"] is None

        detail = api.get(f"/api/materials/{material['id']}").json()
        changed = dict(detail["card"], c10=0.75)
        updated = api.put(f"/api/materials/{material['id']}", json={"card": changed})
        assert updated.status_code == 200, updated.text
        versions = updated.json()["versions"]
        assert versions[0]["card"]["c10"] == 0.5
        assert versions[1]["card"]["c10"] == 0.75
        assert versions[1]["card"]["d1"] == 0.01

        # A card created as linear elastic stays linear elastic.
        linear = create_library(api, "Linear remains linear").json()
        assert linear["card"]["model"] == "linear_elastic"
        assert linear["card"]["c10"] is None
