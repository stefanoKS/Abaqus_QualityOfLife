"""Gate C: faithful CAE material registration and deck support.

The supplied CAE library stays local; the private-library checks skip when it is
absent. Everything else uses a manufactured fixture for each law/combination so
CI runs without the library, a CAE license or a solver.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.engineering import abaqus_lib
from packages.engineering.model import Material, Project
from packages.engineering.geometry import synthetic
from services import material_library, store
from services.api.main import app
from support import (
    create_model,
    legacy_fixture,
    prepare_deck,
    prepare_mesh,
    save_fixture,
)

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = Path(r"I:\GithubProjects\AbaqusLibrary\HK_matlib.lib")
LIBRARY_SHA = "7ab001b64d3a35fe6d40bdc9c3feb253b74b4e2480e8615e34be635084dbbca6"

HYPERFOAM = {
    "E13": {"n": 1, "test": True, "rows": 130, "coupled": False},
    "SSS": {"n": 1, "test": True, "rows": 64, "coupled": False},
    "NISHIDA_FX-TPO70N": {"n": 1, "test": True, "rows": 114, "coupled": False},
    "NISHIDA_FX-TPO70B": {"n": 1, "test": True, "rows": 37, "coupled": False},
    "E27H": {"n": 1, "test": True, "rows": 155, "coupled": False},
    "E17": {"n": 1, "test": True, "rows": 201, "coupled": False},
    "EPTO_E110": {"n": 1, "test": False, "columns": 3, "coupled": False},
    "E-35-8_CALIBRATED": {"n": 3, "test": False, "columns": 9, "coupled": True, "prony": 5},
    "SSS_CALIBRATED": {"n": 3, "test": False, "columns": 9, "coupled": True, "prony": 5},
    "DKSPONGETASHA": {"n": 5, "test": False, "columns": 15, "coupled": True, "prony": 3},
    "DKSPONGEHK": {"n": 5, "test": False, "columns": 15, "coupled": True, "prony": 3},
}


def api_fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path / "data"))
    return TestClient(app, base_url="http://127.0.0.1")


def need_library():
    if not LIBRARY.is_file():
        pytest.skip("the local CAE library fixture is absent")
    return LIBRARY.read_bytes()


def fmt(value: float) -> str:
    return format(float(value), ".15g")


def blocks(lines):
    """Keyword blocks of an INP section, keyed by their lower-case keyword."""
    found: dict[str, list[str]] = {}
    current = None
    for line in lines:
        if line.startswith("*"):
            current = line
            found.setdefault(current, [])
        elif current:
            found[current].append(line)
    return found


def import_card(api, data, name, family="polymer", units="N-mm-s-tonne"):
    library = abaqus_lib.parse(data)
    key = next(card.key for card in library.cards if card.name == name)
    response = api.post(
        "/api/material-library/cae/import",
        data={
            "keys": json.dumps([key]),
            "families": json.dumps({key: family}),
            "units": units,
        },
        files={"file": ("HK_matlib.lib", data)},
    )
    assert response.is_success, response.text
    body = response.json()
    assert len(body["registered"]) == 1, body
    return material_library.get(body["registered"][0]["library_id"])


def assign(api, revision, face_id, detail, sole=False):
    setup = json.loads(json.dumps(revision["setup"]))
    prefix = "lib-" + detail["id"][:8]
    card = dict(detail["card"])
    card.update(
        {
            "id": f"{prefix}-v{detail['current_version']}",
            "name": detail["name"],
            "version": 1,
            "library_id": detail["id"],
            "library_version": detail["current_version"],
        }
    )
    if sole:
        # One material only: the emitted INP then has exactly this card.
        setup["materials"] = [card]
        for face in setup["faces"]:
            face["material"] = card["id"]
    else:
        setup["materials"] = [
            item
            for item in setup["materials"]
            if item["id"] != face_id and not item["id"].startswith(prefix)
        ] + [card]
        for face in setup["faces"]:
            if face["id"] == face_id:
                face["material"] = card["id"]
    saved = api.put(
        "/api/projects/" + revision["project"], json={"base": revision["id"], "setup": setup}
    )
    assert saved.is_success, saved.text
    return saved.json()


def prepare(api, revision):
    mesh = prepare_mesh(api, revision)
    labels = legacy_fixture(api, mesh["id"])["labels"]
    save_fixture(api, mesh["id"], labels)
    deck = prepare_deck(api, revision, mesh["id"])
    return mesh, deck


def inp_of(deck):
    return (store.job_dir(deck["id"]) / "analysis.inp").read_text(encoding="utf-8")


def test_all_27_records_register_and_are_classified(monkeypatch, tmp_path):
    data = need_library()
    library = abaqus_lib.parse(data)
    decisions = [abaqus_lib.assessment(card) for card in library.cards]
    assert all(item["registrable"] for item in decisions)
    assert sum(1 for item in decisions if item["available"]) == 19
    missing = {item["name"] for item in decisions if "density" in item["needs"]}
    assert missing == {
        "TP1303",
        "Material-1",
        "Santoprene",
        "test75",
        "EA1_75B",
        "TPE121_60W228",
        "Steel_ex",
    }
    thermal = next(item for item in decisions if item["name"] == "S50C")
    assert thermal["registrable"] and not thermal["available"]
    assert thermal["needs"] == ["structural_law"]
    assert (thermal["blocks"].get("thermal") or {}).get("conductivity")

    with api_fixture(monkeypatch, tmp_path) as api:
        preview = api.post(
            "/api/material-library/cae/preview", files={"file": ("HK_matlib.lib", data)}
        )
        assert preview.is_success, preview.text
        body = preview.json()
        assert body["sha256"] == LIBRARY_SHA
        assert body["registrable"] == 27
        assert body["available"] == 19
        # The old checkbox rule is gone: nothing well-formed is disabled.
        assert all(entry["assessment"]["registrable"] for entry in body["cards"])

        keys = json.dumps([card.key for card in library.cards])
        first = api.post(
            "/api/material-library/cae/import",
            data={
                "keys": keys,
                "families": json.dumps(
                    {
                        next(card.key for card in library.cards if card.name == "METAL"): "metal",
                        next(card.key for card in library.cards if card.name == "PA6"): "polymer",
                    }
                ),
                "units": "N-mm-s-tonne",
            },
            files={"file": ("HK_matlib.lib", data)},
        )
        assert first.is_success, first.text
        registered = first.json()["registered"]
        assert len(registered) == 27
        assert first.json()["skipped"] == []

        # Repeating the identical import registers nothing new.
        second = api.post(
            "/api/material-library/cae/import",
            data={"keys": keys, "families": "{}", "units": "N-mm-s-tonne"},
            files={"file": ("HK_matlib.lib", data)},
        ).json()
        assert all(item["existing"] for item in second["registered"])
        assert len(material_library.list_materials()) == 27

        # The registered cards carry their source record and full property data.
        foam = next(
            entry
            for entry in material_library.list_materials()
            if entry["name"] == "DKSPONGEHK"
        )
        detail = material_library.get(foam["id"])
        version = detail["versions"][0]
        assert version["source"]["sha256"] == LIBRARY_SHA
        assert version["source"]["record"]
        assert version["source"]["data"]["hyperfoam"]["n"] == 5
        assert version["card"]["model"] == "cae_law"
        assert len(version["card"]["hyperfoam"]["table"][0]) == 15
        assert len(version["card"]["viscoelastic"]["table"]) == 3
        assert version["source"]["available"] is True


def test_missing_density_and_thermal_only_block_prepare_then_complete(
    monkeypatch, tmp_path
):
    data = need_library()
    with api_fixture(monkeypatch, tmp_path) as api:
        revision = create_model(api, "Missing density", example=True)
        face = revision["setup"]["faces"][0]["id"]
        steel = import_card(api, data, "Steel_ex", family="metal")
        assert steel["card"]["density"] is None
        updated = assign(api, revision, face, steel)
        document = api.get(f"/api/revisions/{updated['id']}/readiness").json()
        codes = {finding["code"] for finding in document["findings"]}
        assert "material.missing_density" in codes
        assert document["can_prepare"] is False
        assert "Steel_ex" in next(
            finding
            for finding in document["findings"]
            if finding["code"] == "material.missing_density"
        )["params"]["materials"]

        # The engineer supplies the missing input in a new registered version; the
        # saved revision keeps its own snapshot and stays readable.
        completed = dict(steel["card"])
        completed["density"] = 7.85e-9
        completed["young"] = 206000.0
        completed["poisson"] = 0.3
        changed = api.put(
            "/api/materials/" + steel["id"],
            json={"card": completed, "note": "Density supplied"},
        )
        assert changed.is_success, changed.text
        assert changed.json()["current_version"] == steel["current_version"] + 1
        assert len(changed.json()["versions"]) == 2
        # The older revision is still pinned to version 1 with no density.
        assert api.get(f"/api/revisions/{updated['id']}").json()["setup"]["materials"][-1][
            "density"
        ] is None

        fresh = assign(api, updated, face, changed.json())
        document = api.get(f"/api/revisions/{fresh['id']}/readiness").json()
        codes = {finding["code"] for finding in document["findings"]}
        assert "material.missing_density" not in codes
        assert fresh["setup"]["materials"][-1]["library_version"] == 2
        # Prepare additionally needs a mesh; with one, the completed card runs.
        mesh = prepare_mesh(api, fresh)
        labels = legacy_fixture(api, mesh["id"])["labels"]
        save_fixture(api, mesh["id"], labels)
        document = api.get(f"/api/revisions/{fresh['id']}/readiness").json()
        assert document["can_prepare"] is True, [
            finding["code"] for finding in document["findings"]
        ]
        deck = prepare_deck(api, fresh, mesh["id"])
        text = inp_of(deck)
        assert "*Density\n7.85e-09" in text

        # Thermal-only S50C is registered, visible and actionable, not runnable.
        thermal = import_card(api, data, "S50C", family="metal")
        assert thermal["card"]["model"] == "cae_law"
        assert thermal["card"]["thermal"]["conductivity"]
        thermal_revision = assign(api, fresh, face, thermal)
        document = api.get(f"/api/revisions/{thermal_revision['id']}/readiness").json()
        codes = {finding["code"] for finding in document["findings"]}
        assert "material.no_structural_law" in codes
        assert document["can_prepare"] is False
        refused = api.post(
            "/api/decks",
            json={
                "revision": thermal_revision["id"],
                "token": store.new_id(),
                "mesh": mesh["id"],
            },
        )
        assert refused.status_code == 422 or refused.is_success
        if refused.is_success:
            # The worker refuses it too; the deck must never silently omit a law.
            from services.worker.__main__ import once

            once("test")
            job = store.job(refused.json()["id"])
            assert job["status"] == "Failed"
            assert "structural" in (job["diagnostic"] or "").lower()


@pytest.mark.parametrize("name", sorted(HYPERFOAM))
def test_each_hyperfoam_card_is_emitted_from_its_source(
    monkeypatch, tmp_path, name
):
    data = need_library()
    expected = HYPERFOAM[name]
    library = abaqus_lib.parse(data)
    card = next(card for card in library.cards if card.name == name)
    source = card.data["hyperfoam"]
    with api_fixture(monkeypatch, tmp_path) as api:
        detail = import_card(api, data, name)
        revision = create_model(api, "Foam " + name, example=True)
        face = revision["setup"]["faces"][0]["id"]
        saved = assign(api, revision, face, detail, sole=True)
        _, deck = prepare(api, saved)
        text = inp_of(deck)

    assert text.count("*Material, name=") == 1
    assert "*Density" in text
    if expected["test"]:
        header = next(
            line
            for line in text.splitlines()
            if line.startswith("*Hyperfoam, n=1, test data input")
        )
        assert header == "*Hyperfoam, n=1, test data input"
        assert "moduli=INSTANTANEOUS" not in header
        # The source flag is OFF, so its zero third column is storage, not data.
        assert source["uniaxialTestData"]["lateralNominalStrain"] == "OFF"
        rows = source["uniaxialTestData"]["table"]
        uniaxial = text.split("*Uniaxial Test Data\n", 1)[1].split("\n*", 1)[0]
        emitted = [row for row in uniaxial.splitlines() if row.strip()]
        assert len(emitted) == expected["rows"]
        assert emitted[0].split(", ") == [fmt(rows[0][0]), fmt(rows[0][1])]
        # Two active columns everywhere: the source's zero-filled third column is
        # never emitted as measured lateral strain.
        assert all(len(row.split(", ")) == 2 for row in emitted)
    else:
        table = source["table"]
        expected_columns = expected["columns"]
        assert len(table[0]) == expected_columns
        option = "" if source["moduli"] == "LONG_TERM" else ", moduli=INSTANTANEOUS"
        header = f"*Hyperfoam, n={expected['n']}{option}"
        assert header in text
        after = text.split(header + "\n", 1)[1]
        emitted = []
        for line in after.splitlines():
            if line.startswith("*"):
                break
            emitted.append(line)
        # Abaqus reads at most eight values per data line; the row is packed in
        # keyword order, never truncated or reordered.
        assert all(len(line.split(", ")) <= 8 for line in emitted)
        flattened = [item for line in emitted for item in line.split(", ")]
        assert flattened == [fmt(value) for value in table[0]]
        assert len(emitted) == (len(table[0]) + 7) // 8

    if expected["coupled"]:
        assert "*Viscoelastic, time=PRONY" in text
        prony = card.data["viscoelastic"]["table"]
        assert len(prony) == expected["prony"]
        after = text.split("*Viscoelastic, time=PRONY\n", 1)[1]
        emitted = [
            line
            for line in after.split("\n*", 1)[0].splitlines()
            if line.strip()
        ]
        assert len(emitted) == expected["prony"]
        assert emitted[0].split(", ") == [fmt(value) for value in prony[0]]
    else:
        assert "*Viscoelastic" not in text


def test_manufactured_fixture_covers_every_law_without_the_private_library(
    monkeypatch, tmp_path
):
    """CI-safe coverage: one manufactured card per combination the library has."""
    combinations = {
        "hyperfoam_test": {
            "hyperfoam": {
                "n": 1,
                "test_data": True,
                "moduli": "LONG_TERM",
                "uniaxial": [[float(i), i * 0.01] for i in range(1, 6)],
            }
        },
        "hyperfoam_direct": {
            "hyperfoam": {
                "n": 2,
                "test_data": False,
                "moduli": "INSTANTANEOUS",
                "table": [[1.0, 2.0, 0.1, 3.0, 4.0, 0.2]],
            }
        },
        "hyperfoam_prony": {
            "hyperfoam": {
                "n": 1,
                "test_data": False,
                "moduli": "INSTANTANEOUS",
                "table": [[1.0, 2.0, 0.1]],
            },
            "viscoelastic": {
                "time": "PRONY",
                "table": [[0.2, 0.0, 0.1], [0.1, 0.0, 1.0]],
            },
        },
        "hyperelastic_marlow": {
            "hyperelastic": {
                "type": "MARLOW",
                "test_data": True,
                "uniaxial": [[float(i), i * 0.01] for i in range(1, 6)],
            }
        },
        "hyperelastic_yeoh_mullins": {
            "hyperelastic": {
                "type": "YEOH",
                "test_data": False,
                "table": [[1.0, 2.0, 3.0, 4.0, 5.0, 6.0]],
            },
            "mullins": {"definition": "CONSTANTS", "table": [[1.0, 2.0, 3.0]]},
        },
        "elastic_plastic": {
            "young": 206000.0,
            "poisson": 0.3,
            "plastic": {"hardening": "ISOTROPIC", "table": [[300.0, 0.0], [400.0, 0.1]]},
        },
        "thermal_only": {"thermal": {"conductivity": [[0.05]], "specific_heat": [[4.5e8]]}},
    }
    with api_fixture(monkeypatch, tmp_path) as api:
        for index, (label, fields) in enumerate(combinations.items()):
            card = {
                "model": "cae_law",
                "color": "#46ad94",
                "density": 1e-9,
                "family": "polymer",
                **fields,
            }
            created = api.post(
                "/api/materials", json={"name": "Fixture " + label, "card": card}
            )
            assert created.is_success, (label, created.text)
        names = {entry["name"]: entry for entry in material_library.list_materials()}
        assert "Fixture thermal_only" in names
        revision = create_model(api, "Fixture sections", example=True)
        faces = revision["setup"]["faces"][:2]
        assignments = [
            ("Fixture hyperfoam_prony", faces[0]["id"], "polymer"),
            ("Fixture elastic_plastic", faces[1]["id"], "metal"),
        ]
        for card_name, face_id, family in assignments:
            entry = names[card_name]
            detail = material_library.get(entry["id"])
            assert detail["card"]["family"] == "polymer"
            detail["card"]["family"] = family
            revision = assign(api, revision, face_id, detail)
        mesh, deck = prepare(api, revision)
        assert mesh["status"] == "Completed"
        text = inp_of(deck)
        assert "*Hyperfoam, n=1, moduli=INSTANTANEOUS" in text
        assert "*Viscoelastic, time=PRONY" in text
        assert "*Plastic, hardening=ISOTROPIC" in text
        assert "*Elastic" in text
        # CAE 2024 rejects a DEFINITION parameter on the constants form; the
        # reference check pinned the accepted bare keyword.
        mullins = names["Fixture hyperelastic_yeoh_mullins"]
        detail = material_library.get(mullins["id"])
        assert detail["card"]["mullins"]["definition"] == "CONSTANTS"
        if "*Mullins Effect" in text:
            assert "*Mullins Effect, definition" not in text
        assert "*Element, type=CPS4R" in text
        assert "*Element, type=CPS4\n" in text


def test_legacy_material_table_migrates_to_nullable_density_and_properties(
    monkeypatch, tmp_path
):
    """An existing installation keeps every card through the one-time rebuild."""
    import sqlite3

    monkeypatch.setenv("SEAL_DATA", str(tmp_path / "legacy"))
    root = store.root()
    database = sqlite3.connect(root / "workbench.sqlite3")
    database.executescript(
        """
        CREATE TABLE material_library(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
          created REAL NOT NULL, updated REAL NOT NULL, current_version INTEGER NOT NULL);
        CREATE TABLE material_versions(
          library_id TEXT NOT NULL REFERENCES material_library(id),
          version INTEGER NOT NULL, model TEXT NOT NULL, color TEXT NOT NULL,
          density REAL NOT NULL, young REAL, poisson REAL, test_data TEXT NOT NULL,
          created REAL NOT NULL, note TEXT NOT NULL DEFAULT '',
          c10 REAL, d1 REAL, family TEXT NOT NULL DEFAULT 'polymer', source TEXT,
          PRIMARY KEY(library_id, version));
        INSERT INTO material_library VALUES ('lib-1','Legacy card',0,1.0,1.0,1);
        INSERT INTO material_versions VALUES
          ('lib-1',1,'linear_elastic','#46ad94',1.1e-9,5.0,0.49,'[]',1.0,'',NULL,NULL,'polymer',NULL);
        """
    )
    database.commit()
    database.close()
    store.initialize()
    with store.connection() as db:
        columns = {
            row["name"]: row for row in db.execute("PRAGMA table_info(material_versions)")
        }
        row = db.execute("SELECT * FROM material_versions").fetchone()
    assert columns["density"]["notnull"] == 0
    assert "properties" in columns
    assert row["density"] == pytest.approx(1.1e-9)
    detail = material_library.get("lib-1")
    assert detail["card"]["model"] == "linear_elastic"
    assert detail["card"]["density"] == pytest.approx(1.1e-9)
    assert detail["card"]["hyperfoam"] is None


def test_hyperfoam_packing_and_mullins_keyword_match_cae_2024():
    """Regression for the two writer defects the CAE reference check found.

    Abaqus reads at most eight Hyperfoam values per line, so an N=5 row (15
    values) must be emitted as two lines; CAE 2024 rejects a DEFINITION
    parameter on the Mullins constants form, so the bare keyword is used. Both
    are license-free: this is the writer only.
    """
    from integrations.abaqus import deck

    foam = {
        "id": "foam",
        "name": "Packed foam",
        "color": "#46ad94",
        "model": "cae_law",
        "density": 5.7e-10,
        "family": "polymer",
        "hyperfoam": {
            "n": 5,
            "test_data": False,
            "moduli": "INSTANTANEOUS",
            "table": [[float(index + 1) for index in range(15)]],
        },
        "hyperelastic": {
            "type": "YEOH",
            "n": 3,
            "test_data": False,
            "table": [[1.0, 2.0, 3.0, 4.0, 5.0, 6.0]],
        },
        "mullins": {"definition": "CONSTANTS", "table": [[1.0, 2.0, 3.0]]},
    }
    lines = deck.material_cards(Material.model_validate(foam), "MAT_1")
    header = lines.index("*Hyperfoam, n=5, moduli=INSTANTANEOUS")
    first, second = lines[header + 1], lines[header + 2]
    assert lines[header + 3].startswith("*")
    assert first.split(", ") == [fmt(index) for index in range(1, 9)]
    assert second.split(", ") == [fmt(index) for index in range(9, 16)]
    assert len(first.split(", ")) <= 8 and len(second.split(", ")) <= 8
    mullins = lines.index("*Mullins Effect")
    assert lines[mullins + 1] == "1, 2, 3"
    assert not any("definition=" in line for line in lines if line.startswith("*Mullins"))


def test_rejected_and_malformed_submissions_are_reported(monkeypatch, tmp_path):
    data = need_library()
    library = abaqus_lib.parse(data)
    metal_key = next(card.key for card in library.cards if card.name == "METAL")
    with api_fixture(monkeypatch, tmp_path) as api:
        # A malformed option is refused at the door, with the reason.
        bad = api.post(
            "/api/material-library/cae/import",
            data={"keys": "not json", "families": "{}"},
            files={"file": ("HK_matlib.lib", data)},
        )
        assert bad.status_code == 422
        # An undeclared family value is refused.
        wrong = api.post(
            "/api/material-library/cae/import",
            data={
                "keys": json.dumps([metal_key]),
                "families": json.dumps({metal_key: "ceramic"}),
            },
            files={"file": ("HK_matlib.lib", data)},
        )
        assert wrong.status_code == 422
        # An unsupported units basis is refused with a readable message.
        units = api.post(
            "/api/material-library/cae/import",
            data={"keys": json.dumps([metal_key]), "units": "mm-tonne-s"},
            files={"file": ("HK_matlib.lib", data)},
        )
        assert units.status_code == 422
        # A library record whose data cannot be parsed is not silently registered.
        not_a_library = api.post(
            "/api/material-library/cae/import",
            data={"keys": "[]"},
            files={"file": ("fake.lib", b'{"materials": []}')},
        )
        assert not_a_library.status_code == 422


def test_export_names_the_original_file_and_never_claims_an_edited_card(
    monkeypatch, tmp_path
):
    data = need_library()
    with api_fixture(monkeypatch, tmp_path) as api:
        detail = import_card(api, data, "METAL", family="metal")
        exported = api.post(
            "/api/material-library/cae/export",
            json={"folder": str(tmp_path), "material_ids": [detail["id"]]},
        )
        assert exported.is_success, exported.text
        result = exported.json()
        written = result["files"][0]
        assert written["mode"] == "original-file"
        assert written["path"].endswith("-original.lib")
        assert Path(written["path"]).read_bytes() == data
        assert [detail["id"]] == written["covers"]
