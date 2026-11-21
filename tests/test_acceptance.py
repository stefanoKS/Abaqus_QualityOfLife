"""The acceptance harness must fail loudly, so its checks are unit-tested.

Each case here corresponds to a real release-blocking condition: a fixture that
does not match the deck, a stroke that never reaches contact, a solver that did
not finish, and a CSV that disagrees with the extracted ODB.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("acceptance_dwg", ROOT / "scripts" / "acceptance_dwg.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


def history(rf2, u2, force=None):
    return [
        {"time": 0.0, "u2": 0.0, "rf2": 0.0, "force": 0.0, "displacement": 0.0},
        {
            "time": 1.3,
            "u2": u2,
            "rf2": rf2,
            "force": -rf2 if force is None else force,
            "displacement": abs(u2),
        },
    ]


def test_wsfix_must_match_exactly():
    assert acceptance.wsfix_matches([1, 2, 3], ["1", "2", "3"])
    assert not acceptance.wsfix_matches([1, 2], ["1", "2", "3"])
    assert not acceptance.wsfix_matches([1, 2, 4], ["1", "2", "3"])


def test_prescribed_travel_must_be_attained():
    ok, travel = acceptance.travel_attained(history(-0.02, -6.5), -6.5)
    assert ok and abs(travel - 6.5) < 1e-9
    ok, travel = acceptance.travel_attained(history(-0.02, -5.7), -6.5)
    assert not ok
    ok, _ = acceptance.travel_attained([], -6.5)
    assert not ok


def test_contact_must_be_detected():
    assert acceptance.first_contact(history(-0.018, -6.5))["rf2"] == -0.018
    assert acceptance.first_contact(history(0.0, -6.5)) is None
    assert acceptance.first_contact([]) is None


def test_csv_must_agree_with_the_extracted_history():
    rows = [{"panel_U2_mm": "-6.5", "panel_RF2_N": "-0.018122"}]
    assert acceptance.csv_agrees(rows, history(-0.018122, -6.5))
    assert not acceptance.csv_agrees(rows, history(-0.018122, -6.4))
    assert not acceptance.csv_agrees([], history(-0.018122, -6.5))


def test_fixed_nodes_must_be_present_and_immobile():
    frames = [{"displacements": {"WS-1": [[1, 0.0, 0.0, 0.0], [2, 0.0, 0.0, 0.0]]}}]
    assert acceptance.frame_fixed_error(frames, {1, 2}) == 0.0
    assert acceptance.frame_fixed_error(frames, {1, 3}) is None
    moved = [{"displacements": {"WS-1": [[1, 0.0, 0.5, 0.0], [2, 0.0, 0.0, 0.0]]}}]
    assert acceptance.frame_fixed_error(moved, {1, 2}) == 0.5
