"""Read an open R2D2 profile directly from an N-mm Abaqus ODB for acceptance.

Run with Abaqus Python. This independent reference reader prints JSON and
opens the ODB read-only. See docs/door-panel-pressure-handoff.md for examples.
"""

import argparse
import json
import math
from collections import defaultdict


def stations(instance):
    points = {n.label: tuple(map(float, n.coordinates[:2])) for n in instance.nodes}
    adjacent = defaultdict(list)
    for element in instance.elements:
        if element.type != "R2D2":
            raise ValueError("Choose an instance containing only R2D2 profile elements.")
        a, b = element.connectivity
        adjacent[a].append(b)
        adjacent[b].append(a)
    ends = [n for n, neighbors in adjacent.items() if len(neighbors) == 1]
    if len(ends) != 2 or any(len(v) > 2 for v in adjacent.values()):
        raise ValueError("This reference reader requires one open, unbranched profile.")
    node = min(ends, key=lambda n: (*points[n], n))
    previous, distance = None, 0.0
    visited = set()
    while node not in visited:
        visited.add(node)
        yield node, distance, points[node]
        further = [n for n in adjacent[node] if n != previous]
        if not further:
            break
        previous, node = node, further[0]
        distance += math.dist(points[previous], points[node])
    if len(visited) != len(adjacent):
        raise ValueError("Disconnected profile. Supply an individual connected chain.")


def nodal_field(frame, variable, instance):
    names = [name for name in frame.fieldOutputs.keys() if name.split()[0] == variable]
    if len(names) > 1:
        raise ValueError("Ambiguous %s fields: %s" % (variable, names))
    if not names:
        return None, {}
    name = names[0]
    samples = {}
    for value in frame.fieldOutputs[name].getSubset(region=instance).values:
        if str(value.position) != "NODAL" or value.nodeLabel in samples:
            raise ValueError("Expected one NODAL sample per instance and label for " + name)
        data = value.dataDouble if str(value.precision) == "DOUBLE_PRECISION" else value.data
        samples[value.nodeLabel] = data
    return name, samples


def profile(frame, instance, include_samples):
    pressure_name, pressure = nodal_field(frame, "CPRESS", instance)
    force_name, forces = nodal_field(frame, "CNORMF", instance)
    _, displacement = nodal_field(frame, "U", instance)
    rows = []
    for node, station, xy in stations(instance):
        u = displacement.get(node)
        rows.append({
            "node": node,
            "s_mm": station,
            "xy_deformed_mm": [xy[i] + float(u[i]) for i in range(2)] if u is not None else None,
            "pressure_kPa": 1000.0 * float(pressure[node]) if node in pressure else None,
            "cnormf_N": list(map(float, forces[node])) if node in forces else None,
        })
    valid = [r for r in rows if r["pressure_kPa"] is not None]
    result = {
        "pressure_field": pressure_name, "force_field": force_name,
        "node_count": len(rows), "pressure_samples": len(valid),
        "force_samples": sum(r["cnormf_N"] is not None for r in rows),
        "positive_pressure_nodes": sum(r["pressure_kPa"] > 0 for r in valid),
        "origin_node": rows[0]["node"], "length_mm": rows[-1]["s_mm"],
        "peak": max(valid, key=lambda r: r["pressure_kPa"], default=None),
    }
    if include_samples:
        result["samples"] = rows
    return result


def main():
    from odbAccess import openOdb

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("odb")
    parser.add_argument("--step", required=True)
    parser.add_argument("--instance", action="append", required=True)
    parser.add_argument("--frame", type=int, default=-1, help="Frame index in the named step")
    parser.add_argument("--samples", action="store_true", help="Include every station in the JSON")
    args = parser.parse_args()
    odb = openOdb(path=args.odb, readOnly=True)
    try:
        frame = odb.steps[args.step].frames[args.frame]
        report = {
            "odb_version": str(odb.jobData.version), "step": args.step,
            "frame_id": frame.frameId, "time_s": frame.frameValue,
            "profiles": {name: profile(frame, odb.rootAssembly.instances[name], args.samples)
                         for name in args.instance},
        }
        print(json.dumps(report, ensure_ascii=True, allow_nan=False))
    finally:
        odb.close()


if __name__ == "__main__":
    main()
