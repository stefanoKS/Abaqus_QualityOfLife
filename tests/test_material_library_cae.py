"""Gate 4: CAE material-library exchange, eligibility and element formulations.

The supplied CAE library stays local; these tests use it when present and skip
otherwise. Every DB write uses a disposable SEAL_DATA directory.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from packages.engineering import abaqus_lib
from packages.engineering.geometry import synthetic
from packages.engineering.identity import mesh_compat
from services import material_library, store
from services.api.main import app
from support import legacy_fixture, prepare_deck, prepare_mesh, save_fixture

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = Path(r"I:\GithubProjects\AbaqusLibrary\HK_matlib.lib")
LIBRARY_SHA = "7ab001b64d3a35fe6d40bdc9c3feb253b74b4e2480e8615e34be635084dbbca6"


def api_fixture(monkeypatch, tmp_path):
    monkeypatch.setenv("SEAL_DATA", str(tmp_path / "data"))
    return TestClient(app, base_url="http://127.0.0.1")


def need_library():
    if not LIBRARY.is_file():
        pytest.skip("the local CAE library fixture is absent")
    return LIBRARY.read_bytes()


def test_library_decodes_without_executing_and_preserves_japanese():
    data = need_library()
    library = abaqus_lib.parse(data)
    assert len(library.cards) == 27
    assert len(library.containers) == 1
    assert library.fingerprint == LIBRARY_SHA
    first = library.cards[0]
    assert first.metadata_json()["Data Source"] == "CAE からインポート"
    assert first.data["elastic"]["type"] == "ISOTROPIC"
    # Data is parsed as literal values, never executed.
    assert first.data["density"]["table"][0][0] == pytest.approx(1.13e-09)

    decisions = [abaqus_lib.assessment(card) for card in library.cards]
    # Registering is separate from running: every well-formed record registers.
    assert all(item["registrable"] for item in decisions)
    simplified = {
        item["name"] for item in decisions if item["model"] == "linear_elastic"
    }
    assert simplified == {"PA6", "METAL"}
    assert sum(1 for item in decisions if item["available"]) == 19
    assert sum(1 for item in decisions if "density" in item["needs"]) == 7
    assert sum(1 for item in decisions if "hyperfoam" in item["blocks"]) == 11
    # Nothing well-formed is dropped, and the run suitability is named precisely.
    assert not [item for item in decisions if item["reasons"]]
    assert next(item for item in decisions if item["name"] == "S50C")["needs"] == [
        "structural_law"
    ]


def test_export_is_byte_faithful_and_round_trips(tmp_path):
    data = need_library()
    library = abaqus_lib.parse(data)
    target = tmp_path / "exported.lib"
    result = abaqus_lib.write_export(library, target)
    assert target.read_bytes() == data
    assert result["sha256"] == LIBRARY_SHA
    assert result["bytes"] == len(data)
    assert len(abaqus_lib.parse(target.read_bytes()).cards) == 27
    # A JSON file renamed to .lib cannot pass the decoder.
    fake = tmp_path / "fake.lib"
    fake.write_text('{"materials": []}', encoding="utf-8")
    with pytest.raises(abaqus_lib.LibraryError):
        abaqus_lib.parse(fake.read_bytes())


def test_executable_pickle_opcodes_are_rejected():
    payload = b"cbuiltins\neval\n(S'1+1'\ntR."
    with pytest.raises(abaqus_lib.LibraryError):
        abaqus_lib.parse(payload)


def test_import_registers_eligible_cards_idempotently_and_reports_conflicts(
    monkeypatch, tmp_path
):
    data = need_library()
    library = abaqus_lib.parse(data)
    metal_key = next(card.key for card in library.cards if card.name == "METAL")
    pa6_key = next(card.key for card in library.cards if card.name == "PA6")
    with api_fixture(monkeypatch, tmp_path) as api:
        preview = api.post(
            "/api/material-library/cae/preview",
            files={"file": ("HK_matlib.lib", data)},
        )
        assert preview.is_success, preview.text
        body = preview.json()
        assert body["sha256"] == LIBRARY_SHA
        assert len(body["cards"]) == 27
        assert body["registrable"] == 27
        assert body["available"] == 19

        imported = api.post(
            "/api/material-library/cae/import",
            data={
                "keys": json.dumps([metal_key]),
                "family": "metal",
                "units": "N-mm-s-tonne",
            },
            files={"file": ("HK_matlib.lib", data)},
        )
        assert imported.is_success, imported.text
        registered = imported.json()["registered"]
        assert len(registered) == 1
        metal = material_library.get(registered[0]["library_id"])
        assert metal["card"]["model"] == "linear_elastic"
        assert metal["card"]["family"] == "metal"
        assert metal["card"]["young"] == pytest.approx(206000.0)
        assert metal["versions"][0]["source"]["sha256"] == LIBRARY_SHA
        assert metal["versions"][0]["source"]["category"] == ""

        # An identical reimport is idempotent: the same library entry, no version.
        repeat = api.post(
            "/api/material-library/cae/import",
            data={"keys": json.dumps([metal_key]), "family": "metal", "units": "N-mm-s-tonne"},
            files={"file": ("HK_matlib.lib", data)},
        ).json()
        assert repeat["registered"][0]["library_id"] == metal["id"]
        assert repeat["registered"][0]["existing"] is True
        assert len(material_library.get(metal["id"])["versions"]) == 1

        # A divergent same-name card is registered separately and named by content.
        divergent = api.post(
            "/api/material-library/cae/import",
            data={"keys": json.dumps([pa6_key]), "family": "polymer", "units": "N-mm-s-tonne"},
            files={"file": ("HK_matlib.lib", data)},
        ).json()
        pa6 = material_library.get(divergent["registered"][0]["library_id"])
        assert pa6["name"] == "PA6"
        # Re-importing the same record under the same name stays idempotent too.
        again = api.post(
            "/api/material-library/cae/import",
            data={"keys": json.dumps([pa6_key]), "family": "polymer", "units": "N-mm-s-tonne"},
            files={"file": ("HK_matlib.lib", data)},
        ).json()
        assert again["registered"][0]["existing"] is True

        # An ineligible-for-run card is still registered faithfully; it reports
        # what a new run would need instead of being silently dropped.
        foam_key = next(
            card.key for card in library.cards if "hyperfoam" in (card.data or {})
        )
        registered_foam = api.post(
            "/api/material-library/cae/import",
            data={"keys": json.dumps([foam_key]), "family": "polymer", "units": "N-mm-s-tonne"},
            files={"file": ("HK_matlib.lib", data)},
        ).json()
        assert len(registered_foam["registered"]) == 1
        assert registered_foam["skipped"] == []
        foam_detail = material_library.get(registered_foam["registered"][0]["library_id"])
        assert foam_detail["card"]["model"] == "cae_law"
        assert foam_detail["card"]["hyperfoam"]["test_data"] is True

        # The export writes a CAE-readable file and verifies it before publishing.
        exported = api.post(
            "/api/material-library/cae/export",
            json={"folder": str(tmp_path), "material_ids": [metal["id"]]},
        )
        assert exported.is_success, exported.text
        written = exported.json()["files"]
        assert len(written) == 1
        assert written[0]["path"].endswith(".lib")
        assert Path(written[0]["path"]).read_bytes() == data


def test_metal_and_polymer_regions_emit_explicit_element_types(monkeypatch, tmp_path):
    data = need_library()
    library = abaqus_lib.parse(data)
    metal_key = next(card.key for card in library.cards if card.name == "METAL")
    pa6_key = next(card.key for card in library.cards if card.name == "PA6")
    with api_fixture(monkeypatch, tmp_path) as api:
        metal = material_library.get(
            api.post(
                "/api/material-library/cae/import",
                data={"keys": json.dumps([metal_key]), "family": "metal", "units": "N-mm-s-tonne"},
                files={"file": ("HK_matlib.lib", data)},
            ).json()["registered"][0]["library_id"]
        )
        polymer = material_library.get(
            api.post(
                "/api/material-library/cae/import",
                data={"keys": json.dumps([pa6_key]), "family": "polymer", "units": "N-mm-s-tonne"},
                files={"file": ("HK_matlib.lib", data)},
            ).json()["registered"][0]["library_id"]
        )
        revision = api.post("/api/projects", json={"name": "Metal seal", "example": True}).json()
        setup = revision["setup"]
        assignments = {"foot": metal, "bulb": polymer}
        for face in setup["faces"]:
            detail = assignments.get(face["id"])
            if detail is None:
                continue
            card = dict(detail["card"])
            card.update(
                {
                    "id": "lib-" + detail["id"][:8],
                    "name": detail["name"],
                    "version": 1,
                    "library_id": detail["id"],
                    "library_version": detail["current_version"],
                }
            )
            setup["materials"] = [
                item for item in setup["materials"] if item["id"] != face["material"]
            ] + [card]
            face["material"] = card["id"]
        saved = api.put("/api/projects/" + revision["project"], json={"base": revision["id"], "setup": setup})
        assert saved.is_success, saved.text

        mesh = prepare_mesh(api, saved.json())
        artifact = json.loads((store.job_dir(mesh["id"]) / "mesh.json").read_text())
        assert artifact["counts"].get("CPS4", 0) > 0
        assert artifact["counts"].get("CPS4R", 0) > 0
        # Rigid R2D2 profiles stay native and are not counted as continuum quads.
        assert artifact["counts"].get("R2D2", 0) > 0
        quads = {element["type"] for element in artifact["elements"] if len(element["nodes"]) == 4}
        assert quads == {"CPS4", "CPS4R"}

        labels = legacy_fixture(api, mesh["id"])["labels"]
        save_fixture(api, mesh["id"], labels)
        deck = prepare_deck(api, saved.json(), mesh["id"])
        inp = (
            store.job_dir(deck["id"]) / "analysis.inp"
        ).read_text(encoding="utf-8")
        assert "*Element, type=CPS4\n" in inp
        assert "*Element, type=CPS4R\n" in inp
        # Two explicit region sections with their own materials.
        assert inp.count("*Solid Section") == 2
        assert "MAT_1" in inp and "MAT_2" in inp
        # A family change stales the mesh; a coefficient change does not.
        project = synthetic()
        before = mesh_compat(project)
        project.materials[1].young = 7.5
        assert mesh_compat(project) == before
        project.materials[1].family = "metal"
        assert mesh_compat(project) != before
