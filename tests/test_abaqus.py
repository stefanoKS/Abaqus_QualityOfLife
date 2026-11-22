"""License-free contracts; optional installed-runtime roundtrip uses only 'abaqus python'."""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from integrations.abaqus import launcher
from integrations.abaqus.deck import write_inp
from integrations.abaqus.extract_odb import _fields
from integrations.abaqus.interchange import DEMO_NOTICE, align_histories
from integrations.abaqus.results import write_demo, write_metadata
from packages.engineering import generate_mesh, synthetic


@pytest.fixture(scope="module")
def model_mesh():
    p = synthetic()
    return p, generate_mesh(p)


def test_deck_sections_history_mesh_and_motion(model_mesh):
    project, mesh = model_mesh
    deck = write_inp(project, mesh)
    assert "*Hyperfoam, N=1, test data input" in deck and "*Uniaxial Test Data" in deck
    assert "*Elastic" in deck and "*Rigid Body, ref node=PANEL_RP" in deck
    assert "*Contact Inclusions, all exterior" in deck and "*Dynamic\n" in deck
    assert "type=CPS4R" in deck and "type=R2D2" in deck and "CPE" not in deck
    assert "*Node Output, nset=PANEL_RP\nU1, U2, RF1, RF2" in deck
    assert "*Solid Section, elset=REGION_2" in deck
    assert f"PANEL_RP, 2, 2, {project.motion.travel}" in deck
    assert deck.count("*End Step") == 1


def test_deck_rejects_invalid_mount_and_degenerate_mesh(model_mesh):
    project, mesh = model_mesh
    project = project.model_copy(deep=True)
    project.selections[0].entities = []
    with pytest.raises(ValueError, match="mounting boundary"):
        write_inp(project, mesh)
    e = mesh["elements"][0]
    broken = dict(
        mesh, elements=[dict(e, nodes=[e["nodes"][0]] * len(e["nodes"])), *mesh["elements"][1:]]
    )
    with pytest.raises(ValueError, match="connectivity"):
        write_inp(project, broken)


def test_histories_align_in_time_and_normalize():
    rows = align_histories(
        {
            "U1": {0: 0, 1: 0, 3: 0},
            "U2": {0: 0, 1: -2, 3: -6},
            "RF1": {0.5: 0, 2: 0},
            "RF2": {0.5: 10, 2: 40},
        },
        {
            "force_normalization": "per_mm",
            "thickness": 2,
            "closing": {"direction": [0, -1]},
        },
        3,
        step="Closing",
    )
    assert [(r["time"], r["displacement"], r["force"]) for r in rows] == [
        (3.5, 1, -5),
        (4, 2, -10),
        (5, 4, -20),
    ]
    # Raw signed global components and the step identity stay available.
    assert (rows[0]["u2"], rows[0]["rf2"], rows[0]["rf1"], rows[0]["step"]) == (
        -1,
        10,
        0,
        "Closing",
    )
    assert not align_histories({"U2": {1: 0}}, {"force_normalization": "total"})
    # Closing travel is measured from this step's first sample, not from assembly.
    later = align_histories(
        {"U2": {0: -4, 1: -6}, "RF2": {0: 20, 1: 30}},
        {"force_normalization": "total", "thickness": 1, "closing": {"direction": [0, -1]}},
        start_time=2,
        step="Closing",
    )
    assert [(r["time"], r["displacement"]) for r in later] == [(2, 0), (3, 2)]
    assert later[1]["u2"] == -6 and later[1]["force"] == -30


def test_demo_reproducibility_and_labels(tmp_path, model_mesh):
    project, mesh = model_mesh
    write_demo(project, mesh, tmp_path)
    index = (tmp_path / "results.json").read_bytes()
    results = json.loads(index)
    last = json.loads((tmp_path / results["frames"][-1]["file"]).read_bytes())
    assert last["notice"] == DEMO_NOTICE == results["notice"]
    assert last["displacements"]["PANEL-1"][0][2] == project.motion.travel
    assert set(results["unavailable"]) >= {"LE", "S"}
    # Measured solver convention (docs/engineering-validation.md): the raw RF2 is
    # negative while the seal resists, so the projected closing force is positive.
    assert results["history"][-1]["rf2"] < 0
    assert results["history"][-1]["force"] > 0
    assert results["closing"]["direction"] == [0.0, -1.0]
    assert results["closing"]["steps"] == [{"name": "Closing", "role": "door"}]
    assert DEMO_NOTICE in (tmp_path / "history.csv").read_text(encoding="utf-8-sig")
    write_demo(project, mesh, tmp_path)
    assert (tmp_path / "results.json").read_bytes() == index


def test_demo_csv_keeps_signed_rf2_and_separates_the_projected_total(tmp_path, model_mesh):
    import csv

    project, mesh = model_mesh
    project = project.model_copy(deep=True)
    project.analysis.thickness = 2.0
    project.analysis.force_normalization = "per_mm"
    write_demo(project, mesh, tmp_path)
    with (tmp_path / "history.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    last = rows[-1]
    raw = float(last["panel_RF2_N"])
    # The logged defect: this column used to receive the projected total.
    assert raw < 0
    assert float(last["panel_total_RF2_N"]) == pytest.approx(raw)
    assert float(last["closing_total_force_N"]) == pytest.approx(-raw)
    projected = last["closing_force_N/mm"]
    assert float(projected) == pytest.approx(-raw / 2.0)


def test_raw_integration_point_with_precision_and_position():
    value = SimpleNamespace(
        instance=SimpleNamespace(name="WS-1"),
        position="INTEGRATION_POINT",
        integrationPoint=3,
        sectionPoint=None,
        precision="DOUBLE_PRECISION",
        elementLabel=42,
        dataDouble=(1.0, 2.0),
        localCoordSystemDouble=None,
    )
    field = SimpleNamespace(type="TENSOR_2D_PLANAR", componentLabels=("S11", "S22"), values=[value])
    u, raw, seen = _fields(SimpleNamespace(fieldOutputs={"S": field}), {"S", "LE"}, "2D")
    assert not u and seen == {"S"}
    assert raw["S"]["values"][0] == dict(
        instance="WS-1", position="INTEGRATION_POINT", element=42, integration_point=3, data=[1, 2]
    )


def test_solver_evidence_and_license_diagnostics(tmp_path):
    (tmp_path / "analysis.odb").write_bytes(b"early file")
    assert not launcher.solver_evidence(tmp_path, 0)[0]
    (tmp_path / "analysis.sta").write_text(
        "1 2 1 0 3 3 0.1 0.075 0.025\nTHE ANALYSIS HAS COMPLETED SUCCESSFULLY\n"
    )
    assert launcher.progress(tmp_path) == dict(
        step=1, increment=2, step_time=0.075, phase="Running"
    )
    assert launcher.solver_evidence(tmp_path, 0)[0]
    assert not launcher.solver_evidence(tmp_path, 9)[0]
    (tmp_path / "solver.log").write_text("License checkout failed")
    assert "license" in launcher.solver_evidence(tmp_path, 0)[1].lower()
    (tmp_path / "analysis.sta").unlink()
    (tmp_path / "solver.log").write_text("Waiting for a license.")
    assert launcher.progress(tmp_path)["phase"] == "Waiting for license"


def test_missing_launcher_and_cpu_validation(tmp_path, monkeypatch):
    monkeypatch.delenv(launcher.ENV_LAUNCHER, raising=False)
    monkeypatch.delenv(launcher.ENV_LAUNCHER_ALIAS, raising=False)
    # Discovery would find the installation on this host; test the missing case.
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    monkeypatch.setattr(launcher, "DISCOVERY_DIRS", ())
    with pytest.raises(ValueError, match="No Abaqus launcher found"):
        launcher.configured_launcher()
    with pytest.raises(ValueError, match="CPU"):
        launcher.start_solver(None, tmp_path, "1 & echo foo", None)
    with pytest.raises(ValueError, match="existing absolute"):
        launcher._launcher("abq2024.bat")


@pytest.mark.skipif(os.name != "nt", reason="Windows batch argument contract")
def test_windows_batch_launcher_spaces_and_fixed_arguments(tmp_path):
    launch = tmp_path / "fixture launcher.cmd"
    launch.write_text("@echo off\r\necho %* > received.txt\r\nexit /b 0\r\n")
    (tmp_path / "analysis.inp").touch()
    with (tmp_path / "solver.log").open("wb") as log:
        assert launcher.start_solver(launch, tmp_path, 2, log).wait(timeout=15) == 0
    assert (
        tmp_path / "received.txt"
    ).read_text().strip() == "job=analysis input=analysis.inp cpus=2 interactive"


ODB_FIXTURE = """
from odbAccess import Odb, HistoryPoint
from abaqusConstants import *
from inpParser import InputFile

keywords = InputFile('analysis.inp').parse(usePyArray=True)
assert 'DYNAMIC' in [k.name.upper().lstrip('*') for k in keywords]
odb = Odb(name='analysis', analysisTitle='Extractor fixture', description='Manufactured data', path='analysis.odb')
part = odb.Part(name='PANEL', embeddedSpace=TWO_D_PLANAR, type=DEFORMABLE_BODY)
part.addNodes(nodeData=((1,0.,0.),(2,1.,0.),(3,0.,1.)),nodeSetName='NALL')
part.addElements(elementData=((1,1,2,3),),type='CPS3',elementSetName='TEST')
panel = odb.rootAssembly.Instance(name='PANEL-1', object=part)
seal = odb.rootAssembly.Instance(name='WS-1', object=part)
step = odb.Step(name='Closing', description='Generated', domain=TIME, timePeriod=1.)
h = step.HistoryRegion(name='Node PANEL-1.1', description='Panel RP', point=HistoryPoint(node=panel.nodes[0]))
h.HistoryOutput(name='U2', description='Y travel', type=SCALAR).addData(frameValue=(0.,1.), value=(0.,-2.))
h.HistoryOutput(name='RF2', description='Reaction', type=SCALAR).addData(frameValue=(0.,0.5,1.), value=(0.,-5.,-10.))
for t in (0., 1.):
    frame = step.Frame(incrementNumber=int(t), frameValue=t, description='Fixture')
    u = frame.FieldOutput(name='U',description='Displacement',type=VECTOR, componentLabels=('U1','U2'))
    for instance, dy in ((panel,-2.), (seal,-1.)):
        u.addData(position=NODAL,instance=instance,labels=(1,2,3),data=((0.,dy*t),)*3)
    stress = frame.FieldOutput(name='S',description='Stress',type=TENSOR_2D_PLANAR)
    stress.addData(position=INTEGRATION_POINT,instance=seal,labels=(1,),data=((1.,2.,0.,0.),))
odb.save()
odb.close()
"""


@pytest.mark.skipif(
    not os.environ.get("SIMPLIFY_ABAQUS_TEST_LAUNCHER"),
    reason="opt-in installed Abaqus Python ODB fixture, no solve",
)
def test_installed_runtime_roundtrip(tmp_path, model_mesh):
    path = Path(os.environ["SIMPLIFY_ABAQUS_TEST_LAUNCHER"])
    project, mesh = model_mesh
    (tmp_path / "analysis.inp").write_text(write_inp(project, mesh), encoding="ascii")
    (tmp_path / "fixture.py").write_text(ODB_FIXTURE, encoding="ascii")
    with (tmp_path / "fixture.log").open("wb") as log:
        code = launcher._start(path, ["python", "fixture.py"], tmp_path, log).wait(timeout=100)
    assert code == 0, (tmp_path / "fixture.log").read_text(errors="replace")
    odb = tmp_path / "analysis.odb"
    before = hashlib.sha256(odb.read_bytes()).hexdigest()
    write_metadata(project, mesh, tmp_path)
    meta_path = tmp_path / "result-metadata.json"
    metadata = json.loads(meta_path.read_bytes())
    metadata["panel_reference"]["label"] = 1
    metadata["regions"] = {"WS-1": {"1": "bulb"}, "PANEL-1": {"1": "panel"}}
    meta_path.write_text(json.dumps(metadata))
    with (tmp_path / "extraction.log").open("wb") as log:
        code = launcher.start_extraction(path, tmp_path, log).wait(timeout=100)
    assert code == 0, (tmp_path / "extraction.log").read_text(errors="replace")
    assert hashlib.sha256(odb.read_bytes()).hexdigest() == before
    results = json.loads((tmp_path / "results.json").read_bytes())
    assert results["mode"] == "ABAQUS"
    assert results["history"][1]["displacement"] == 1
    assert results["history"][1]["u2"] == -2
    assert set(results["unavailable"]) >= {"CPRESS", "LE"}
    frame = json.loads((tmp_path / results["frames"][-1]["file"]).read_bytes())
    assert frame["displacements"]["PANEL-1"][0] == [1, 0, -2, 0]
    assert frame["displacements"]["WS-1"][0] == [1, 0, -1, 0]
    assert frame["fields"]["S"]["values"][0]["integration_point"] == 1
