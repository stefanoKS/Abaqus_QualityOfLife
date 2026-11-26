"""Gate 5: only a frame with a supported finite measurement becomes playable."""

from types import SimpleNamespace
import json

from integrations.abaqus.extract_odb import extract


def _instance(name="PANEL-1"):
    nodes = [
        SimpleNamespace(label=label, coordinates=(float(label - 1), 0.0))
        for label in (1, 2, 3)
    ]
    elements = [SimpleNamespace(label=1, type="CPS3", connectivity=(1, 2, 3))]
    return SimpleNamespace(name=name, nodes=nodes, elements=elements)


def _u_field(instance, values):
    return SimpleNamespace(
        componentLabels=("U1", "U2"),
        type="VECTOR",
        values=[
            SimpleNamespace(
                instance=instance,
                position="NODAL",
                nodeLabel=label,
                precision="SINGLE_PRECISION",
                data=value,
                elementLabel=None,
                localCoordSystem=None,
            )
            for label, value in values
        ],
    )


def _frame(value, field_outputs, frame_id):
    return SimpleNamespace(
        frameValue=value,
        incrementNumber=frame_id,
        frameId=frame_id,
        fieldOutputs=field_outputs,
    )


def _metadata():
    return {
        "units": {"length": "mm", "force": "N", "time": "s"},
        "dimension": "2D",
        "placement": {},
        "sets": {},
        "thickness": 1.0,
        "reporting_width_mm": 1.0,
        "force_normalization": "total",
        "schema_version": 4,
        "requested": ["U", "S", "CPRESS", "CNORMF"],
        "closing": {"role": "door", "steps": [{"name": "Closing", "role": "door"}]},
        "steps": [{"name": "Closing", "role": "door"}],
        "body": None,
        "door_pressure": {"enabled": False},
        "assembly": {"door": None, "body": None},
        "fixture": {},
        "regions": {},
        "panel_reference": {"instance": "PANEL-1", "label": 1},
        "solver_outcome": "Succeeded",
    }


def _odb(frames):
    instance = _instance()
    step = SimpleNamespace(
        name="Closing",
        totalTime=0.0,
        frames=frames,
        historyRegions={},
    )
    return SimpleNamespace(
        rootAssembly=SimpleNamespace(instances={"PANEL-1": instance}),
        steps={"Closing": step},
    )


def _read(tmp_path):
    return json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))


def test_empty_tail_frame_is_dropped_and_previous_measurement_stays_last(tmp_path):
    instance = _instance()
    measured = _frame(0.6, {"U": _u_field(instance, [(1, (0.0, -0.6)), (2, (0.0, -0.6)), (3, (0.0, -0.6))])}, 12)
    header_only = _frame(0.9, {}, 13)
    extract(_odb([measured, header_only]), _metadata(), tmp_path)
    result = _read(tmp_path)
    assert len(result["frames"]) == 1
    assert result["frames"][0]["time"] == 0.6
    assert result["frames"][0]["native_frame_id"] == 12
    assert result["skipped_frames"][0]["native_frame_id"] == 13
    assert result["skipped_frames"][0]["frame_ordinal"] == 1
    assert "no supported finite field measurement" in result["skipped_frames"][0]["reason"]
    assert result["history_only"] is False


def test_measured_zero_is_a_usable_field_frame(tmp_path):
    instance = _instance()
    zero = _frame(0.0, {"U": _u_field(instance, [(1, (0.0, 0.0)), (2, (0.0, 0.0)), (3, (0.0, 0.0))])}, 1)
    extract(_odb([zero]), _metadata(), tmp_path)
    result = _read(tmp_path)
    assert len(result["frames"]) == 1
    assert result["initial_only"] is True
    frame = json.loads((tmp_path / result["frames"][0]["file"]).read_text(encoding="utf-8"))
    assert frame["displacements"]["PANEL-1"][0] == [1, 0.0, 0.0, 0.0]


def test_missing_channels_are_named_independently(tmp_path):
    instance = _instance()
    only_u = _frame(0.5, {"U": _u_field(instance, [(1, (0.0, 0.1)), (2, (0.0, 0.1)), (3, (0.0, 0.1))])}, 7)
    extract(_odb([only_u]), _metadata(), tmp_path)
    result = _read(tmp_path)
    assert len(result["frames"]) == 1
    assert set(result["unavailable"]) >= {"S", "CPRESS", "CNORMF"}
    frame = json.loads((tmp_path / result["frames"][0]["file"]).read_text(encoding="utf-8"))
    assert frame["unavailable"] == ["CNORMF", "CPRESS", "S"]
    assert frame["unavailable_reasons"] == {
        "CNORMF": "field_not_reported",
        "CPRESS": "field_not_reported",
        "S": "field_not_reported",
    }


def test_unreadable_optional_channel_keeps_the_readable_measurements(tmp_path):
    instance = _instance()
    good_u = _u_field(instance, [(1, (0.0, -0.2)), (2, (0.0, -0.2)), (3, (0.0, -0.2))])
    panel_instance = instance

    class BadValue:
        instance = panel_instance
        position = "NODAL"
        nodeLabel = 1
        precision = "SINGLE_PRECISION"
        elementLabel = None
        localCoordSystem = None

        @property
        def data(self):
            raise ValueError("corrupt CPRESS record")

    bad_pressure = SimpleNamespace(
        componentLabels=("CPRESS",),
        type="SCALAR",
        values=[BadValue()],
    )
    frame = _frame(0.4, {"U": good_u, "CPRESS": bad_pressure}, 9)
    extract(_odb([frame]), _metadata(), tmp_path)
    result = _read(tmp_path)
    assert len(result["frames"]) == 1
    payload = json.loads((tmp_path / result["frames"][0]["file"]).read_text(encoding="utf-8"))
    assert payload["displacements"]["PANEL-1"][0] == [1, 0.0, -0.2, 0.0]
    assert payload["unavailable"] == ["CNORMF", "CPRESS", "S"]
    assert payload["unavailable_reasons"]["CPRESS"].startswith("unreadable sample:")
    # A bad optional channel must not make the whole frame unreadable.
    assert result["skipped_frames"] == []


def test_nonfinite_only_field_is_not_a_usable_frame(tmp_path):
    instance = _instance()
    not_finite = SimpleNamespace(
        componentLabels=("U1", "U2"),
        type="VECTOR",
        values=[
            SimpleNamespace(
                instance=instance,
                position="NODAL",
                nodeLabel=1,
                precision="SINGLE_PRECISION",
                data=(float("nan"), 0.0),
                elementLabel=None,
                localCoordSystem=None,
            )
        ],
    )
    frame = _frame(0.7, {"U": not_finite}, 11)
    import pytest

    with pytest.raises(ValueError, match="no readable field frames or history"):
        extract(_odb([frame]), _metadata(), tmp_path)
