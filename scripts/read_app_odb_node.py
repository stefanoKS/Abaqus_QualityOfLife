"""Read one door-profile node directly from an app-generated ODB.

Abaqus Python only. Prints labels, station, undeformed/deformed XY, pressure,
signed CNORMF components and the output-field inventory for the final frame.
"""

import argparse
import json
from collections import defaultdict
import math


def profile_stations(instance):
    points = {n.label: tuple(map(float, n.coordinates[:2])) for n in instance.nodes}
    adjacent = defaultdict(list)
    for element in instance.elements:
        if element.type != "R2D2":
            continue
        a, b = element.connectivity
        adjacent[a].append(b)
        adjacent[b].append(a)
    ends = [node for node, neighbours in adjacent.items() if len(neighbours) == 1]
    if len(ends) != 2 or any(len(values) > 2 for values in adjacent.values()):
        raise ValueError("Expected one open, unbranched door profile.")
    origin = min(ends, key=lambda node: (points[node][0], points[node][1], node))
    node, previous, distance = origin, None, 0.0
    stations = {}
    visited = set()
    while node not in visited:
        visited.add(node)
        stations[node] = distance
        further = [n for n in adjacent[node] if n != previous]
        if not further:
            break
        previous, node = node, further[0]
        distance += math.dist(points[previous], points[node])
    return points, stations, origin, distance


def samples(frame, instance, variable):
    names = [name for name in frame.fieldOutputs.keys() if name.split()[0] == variable]
    found = defaultdict(list)
    for name in names:
        for value in frame.fieldOutputs[name].getSubset(region=instance).values:
            if str(value.position) != "NODAL":
                continue
            data = (
                value.dataDouble
                if str(value.precision) == "DOUBLE_PRECISION"
                else value.data
            )
            found[value.nodeLabel].append(
                [float(item) for item in data] if hasattr(data, "__len__") else [float(data)]
            )
    return found, names


def main():
    from odbAccess import openOdb

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("odb")
    parser.add_argument("--step", default="Closing")
    parser.add_argument("--instance", default="PANEL-1")
    parser.add_argument("--node", type=int)
    args = parser.parse_args()
    odb = openOdb(path=args.odb, readOnly=True)
    try:
        step = odb.steps[args.step]
        frame = step.frames[-1]
        instance = odb.rootAssembly.instances[args.instance]
        points, stations, origin, length = profile_stations(instance)
        pressure, pressure_names = samples(frame, instance, "CPRESS")
        force, force_names = samples(frame, instance, "CNORMF")
        displacement, displacement_names = samples(frame, instance, "U")
        if args.node is None:
            node = max(
                (label for label, values in pressure.items() if values),
                key=lambda label: pressure[label][0][0],
            )
        else:
            node = args.node
        u = displacement[node][0] if node in displacement else None
        report = {
            "odb": args.odb,
            "step": args.step,
            "odb_step_name": step.name,
            "frame_id": frame.frameId,
            "frame_value": frame.frameValue,
            "total_time": step.totalTime,
            "frames": len(step.frames),
            "fields": sorted(frame.fieldOutputs.keys()),
            "pressure_fields": pressure_names,
            "force_fields": force_names,
            "displacement_fields": displacement_names,
            "profile_nodes": len(stations),
            "origin_node": origin,
            "length_mm": length,
            "node": node,
            "station_mm": stations[node],
            "undeformed_xy_mm": list(points[node]),
            "u_mm": u,
            "deformed_xy_mm": [points[node][0] + u[0], points[node][1] + u[1]] if u else None,
            "pressure_samples": pressure.get(node),
            "pressure_mpa": pressure[node][0][0] if node in pressure else None,
            "pressure_kpa": 1000.0 * pressure[node][0][0] if node in pressure else None,
            "cnormf_samples": force.get(node),
            "cnormf_n": force[node][0] if node in force else None,
            "positive_nodes": sum(
                1 for values in pressure.values() if values and values[0][0] > 0
            ),
        }
        print(json.dumps(report, ensure_ascii=True))
    finally:
        odb.close()


if __name__ == "__main__":
    main()
