"""Run the production ODB extractor against an external reference ODB.

Abaqus Python only: pass the original ODB, the six supplied upper profiles and
a disposable output directory. The metadata is the explicit external mapping
this slice supports (instances, steps, N-mm units); the profile axis itself is
derived from the ODB's own R2D2 connectivity by the same production module.
Nothing in the source ODB is modified.
"""

import argparse
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "integrations" / "abaqus"))

import extract_odb  # noqa: E402
import interchange  # noqa: E402
import door_pressure  # noqa: E402


def metadata(instances):
    return {
        "version": 1,
        "schema_version": 4,
        "units": "N-mm-s-tonne",
        "dimension": "2D",
        "thickness": 1.0,
        "thickness_mm": 1.0,
        "reporting_width_mm": 100.0,
        "reporting_width_basis": "default_100_mm",
        "force_basis": "total_width",
        "force_normalization": "total",
        "requested": ["U", "CPRESS", "CNORMF"],
        "contact": {
            "basis": "legacy",
            "door_seal": None,
            "body_seal": None,
            "seal_self": None,
            "legacy_scalar": 0.3,
        },
        "placement": {
            "initial_offset_y_mm": 0.0,
            "initial_vertical_mesh_clearance_mm": None,
            "prescribed_panel_travel_y_mm": -20.0,
            "door_side": "above",
            "door_direction": [0.0, -1.0],
            "door_angle_deg": -90.0,
            "door_stroke_mm": 20.0,
            "door_delta_mm": [0.0, -20.0],
        },
        "assembly": {"door": None, "body": None},
        "fixture": {"source": "external-reference", "count": None, "nodes": None},
        "closing": {
            "panel": "external",
            "panel_name": "Upper profile",
            "instance": instances[0],
            "reference_label": 1,
            "direction": [0.0, -1.0],
            "distance_mm": 20.0,
            "angle_deg": -90.0,
            "delta_mm": [0.0, -20.0],
            "steps": [{"name": "Step-2", "role": "door"}],
        },
        "steps": [
            {
                "name": "Step-1",
                "id": interchange.canonical_step("Step-1"),
                "role": "body",
                "instance": "PANEL_LOWER-1",
                "reference_label": 1,
                "direction": [0.0, 1.0],
                "distance_mm": 20.0,
                "angle_deg": 90.0,
                "delta_mm": [0.0, 20.0],
            },
            {
                "name": "Step-2",
                "id": interchange.canonical_step("Step-2"),
                "role": "door",
                "instance": instances[0],
                "reference_label": 1,
                "direction": [0.0, -1.0],
                "distance_mm": 20.0,
                "angle_deg": -90.0,
                "delta_mm": [0.0, -20.0],
            },
        ],
        "sets": {"edges": {}, "regions": {}, "mounting": {}},
        "panel_reference": {"instance": instances[0], "label": 1},
        "regions": {},
        "door_pressure": {
            "enabled": True,
            "instances": [
                {"instance": name, "component": "moving_panel", "alias": name}
                for name in instances
            ],
            "native_unit": "MPa",
            "display_unit": "kPa",
            "conversion": 1000.0,
            "force_unit": "N",
            "field_location": "NODAL",
            "contact_attribution": {
                "kind": "general_contact",
                "label": "general contact (upper profiles)",
                "basis": (
                    "The original ODB's General Contact domain also includes the "
                    "lower rigid panel and the seal; the door-side values are the "
                    "measured subset on the six upper profiles."
                ),
            },
            "request": {
                "pressure": "CPRESS",
                "force": "CFORCE",
                "nset": None,
                "global_stress_selected": False,
            },
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("odb")
    parser.add_argument("--output", required=True)
    parser.add_argument("--instance", action="append", required=True)
    args = parser.parse_args()

    from odbAccess import openOdb

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    data = metadata(args.instance)
    (output / "result-metadata.json").write_text(
        json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
    )
    odb = openOdb(path=args.odb, readOnly=True)
    try:
        extract_odb.extract(odb, data, output)
    finally:
        odb.close()
    index = json.loads((output / "results.json").read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "odb": str(args.odb),
                "frames": len(index["frames"]),
                "steps": [step["name"] for step in index.get("steps") or []],
                "profiles": [
                    {
                        "id": profile["id"],
                        "alias": profile["alias"],
                        "supported": profile["supported"],
                        "labels": len(profile.get("labels") or []),
                        "length_mm": profile.get("length_mm"),
                        "maximum_pressure_kpa": profile.get("maximum_pressure_kpa"),
                    }
                    for profile in index.get("door_pressure", {}).get("profiles") or []
                ],
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
