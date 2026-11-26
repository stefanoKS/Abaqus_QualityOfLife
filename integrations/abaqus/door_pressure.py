"""Door-panel contact-pressure profiles. Standard library only.

The module is imported by the production ODB extractor (which runs under Abaqus
Python) and by host-side tests, so it must never import application packages.
It owns three narrow pieces of the feature:

* the deterministic open-chain station axis along an R2D2 door profile;
* the one documented native-MPa -> display-kPa conversion;
* the duplicate/ambiguity rule for contact samples with one complete identity.

The Abaqus object model stays in ``extract_odb.py``; this module only sees plain
labels, coordinates and observations.
"""

from math import dist, hypot

NATIVE_PRESSURE_UNIT = "MPa"
DISPLAY_PRESSURE_UNIT = "kPa"
PRESSURE_TO_KPA = 1000.0
FORCE_UNIT = "N"


def profile_id(instance, origin_node):
    return "%s:%s" % (instance, origin_node)


def pressure_kpa(native_mpa):
    """The single conversion boundary: ODB CPRESS is MPa in N-mm units."""
    return None if native_mpa is None else float(native_mpa) * PRESSURE_TO_KPA


def magnitude(vector):
    if vector is None:
        return None
    return hypot(*[float(value) for value in vector])


def _points(nodes):
    points = {}
    for row in nodes:
        label = int(row[0])
        points[label] = (float(row[1]), float(row[2]))
    return points


def _r2d2(elements):
    return [
        element
        for element in elements
        if str(element.get("type", "")).upper() == "R2D2"
    ]


def _components(adjacent):
    seen = set()
    groups = []
    for start in sorted(adjacent):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        group = []
        while stack:
            node = stack.pop()
            group.append(node)
            for neighbour in adjacent[node]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        groups.append(sorted(group))
    return groups


def _unsupported(instance, alias, component, labels, reason, topology):
    origin = labels[0] if labels else None
    return {
        "id": profile_id(instance, origin) if origin is not None else instance + ":?",
        "instance": instance,
        "component": component,
        "alias": alias or instance,
        "origin_node": origin,
        "labels": list(labels),
        "stations_mm": [],
        "points_mm": [],
        "length_mm": 0.0,
        "topology": topology,
        "supported": False,
        "reason": reason,
        "orientation": "unavailable",
    }


def connected_profiles(instance, nodes, elements, alias=None, component=None):
    """Ordered profiles for one instance.

    Returns every connected R2D2 chain separately. Orientation follows the
    brief: an open chain starts at the endpoint with the lexicographically
    smallest ``(x, y, label)`` in assembled, undeformed XY, and each station is
    the sum of the preceding Euclidean segment lengths. A closed ring or a
    branch is reported as unsupported rather than traversed by guesswork.
    """
    points = _points(nodes)
    rigid = _r2d2(elements)
    if not rigid:
        return []
    adjacent = {}
    for element in rigid:
        connectivity = [int(value) for value in element["connectivity"]]
        if len(connectivity) != 2:
            continue
        a, b = connectivity
        if a == b:
            adjacent.setdefault(a, [])
            continue
        adjacent.setdefault(a, []).append(b)
        adjacent.setdefault(b, []).append(a)
    if not adjacent:
        return []
    missing = [label for label in adjacent if label not in points]
    if missing:
        return [
            _unsupported(
                instance,
                alias,
                component,
                sorted(adjacent),
                "missing_node_coordinates",
                "unavailable",
            )
        ]
    profiles = []
    for group in _components(adjacent):
        degrees = {label: len(adjacent[label]) for label in group}
        if any(value > 2 for value in degrees.values()):
            profiles.append(
                _unsupported(
                    instance,
                    alias,
                    component,
                    group,
                    "branched_profile",
                    "branched",
                )
            )
            continue
        ends = sorted((label for label in group if degrees[label] == 1), key=lambda n: points[n])
        if len(ends) != 2:
            profiles.append(
                _unsupported(
                    instance,
                    alias,
                    component,
                    group,
                    "closed_profile_unsupported",
                    "closed_ring",
                )
            )
            continue
        origin = min(ends, key=lambda label: (points[label][0], points[label][1], label))
        labels = []
        stations = []
        xy = []
        node = origin
        previous = None
        distance = 0.0
        visited = set()
        while node is not None and node not in visited:
            visited.add(node)
            labels.append(node)
            stations.append(distance)
            xy.append([points[node][0], points[node][1]])
            further = [neighbour for neighbour in adjacent[node] if neighbour != previous]
            if not further:
                break
            previous, node = node, further[0]
            distance += dist(points[previous], points[node])
        if len(visited) != len(group):
            profiles.append(
                _unsupported(
                    instance,
                    alias,
                    component,
                    group,
                    "disconnected_profile",
                    "disconnected",
                )
            )
            continue
        profiles.append(
            {
                "id": profile_id(instance, origin),
                "instance": instance,
                "component": component,
                "alias": alias or instance,
                "origin_node": origin,
                "labels": labels,
                "stations_mm": stations,
                "points_mm": xy,
                "length_mm": stations[-1] if stations else 0.0,
                "topology": "open_chain",
                "supported": True,
                "reason": None,
                "orientation": "lexicographic_min_endpoint",
            }
        )
    return profiles


def profile_definitions(instances, wanted):
    """Profiles for the configured door instances.

    ``instances`` is the extractor's plain instance list (``name``, ``nodes``,
    ``elements``). ``wanted`` names the door instances and their aliases; an
    instance that is absent or carries no R2D2 chain produces an explicit
    unavailable profile instead of silently disappearing.
    """
    by_name = {row["name"]: row for row in instances}
    profiles = []
    for entry in wanted:
        name = entry["instance"]
        instance = by_name.get(name)
        if instance is None:
            profiles.append(
                _unsupported(
                    name,
                    entry.get("alias"),
                    entry.get("component"),
                    [],
                    "instance_missing",
                    "unavailable",
                )
            )
            continue
        found = connected_profiles(
            name,
            instance.get("nodes") or [],
            instance.get("elements") or [],
            alias=entry.get("alias"),
            component=entry.get("component"),
        )
        if not found:
            profiles.append(
                _unsupported(
                    name,
                    entry.get("alias"),
                    entry.get("component"),
                    [],
                    "profile_missing",
                    "unavailable",
                )
            )
        profiles.extend(found)
    return profiles


def _same(one, other):
    if isinstance(one, (list, tuple)) or isinstance(other, (list, tuple)):
        if not isinstance(one, (list, tuple)) or not isinstance(other, (list, tuple)):
            return False
        return len(one) == len(other) and all(
            float(a) == float(b) for a, b in zip(one, other)
        )
    return float(one) == float(other)


def coalesce(observations):
    """One value per complete identity, or an explicit ambiguity.

    Repeated observations are folded only when every stored value is exactly
    identical. Conflicting values are never summed, averaged or maximised: the
    node is left missing and the reason names the ambiguity. ``observations``
    is a list of scalars or component lists (one per stored sample).
    """
    if not observations:
        return None, None
    first = observations[0]
    if all(_same(first, other) for other in observations[1:]):
        if isinstance(first, (list, tuple)):
            return [float(value) for value in first], None
        return float(first), None
    return None, "conflicting_contact_observations"


def align_profile(profile, pressure, force, displacement):
    """Frame arrays for one profile, in station order.

    ``pressure`` and ``force`` map a node label to the list of observations
    stored for that node under the selected contact domain. A label that was
    never observed stays ``None``; a measured zero stays ``0.0``.
    """
    labels = profile.get("labels") or []
    pressure_mpa = []
    pressure_display = []
    cnormf = []
    force_magnitude = []
    ambiguous = []
    missing_pressure = []
    missing_force = []
    for label in labels:
        value, reason = coalesce(pressure.get(label, []))
        if reason:
            ambiguous.append([label, "pressure", reason])
        pressure_mpa.append(value)
        pressure_display.append(pressure_kpa(value))
        if value is None and label not in pressure:
            missing_pressure.append(label)
        vector, reason = coalesce(force.get(label, []))
        if reason:
            ambiguous.append([label, "force", reason])
        if vector is None and label not in force:
            missing_force.append(label)
        cnormf.append(vector)
        force_magnitude.append(magnitude(vector))
    availability = {}
    if missing_pressure:
        availability["pressure"] = "pressure_sample_missing"
    if missing_force:
        availability["force"] = "force_sample_missing"
    if not displacement:
        availability["displacement"] = "displacement_field_missing"
    return {
        "instance": profile.get("instance"),
        "labels": list(labels),
        "pressure_mpa": pressure_mpa,
        "pressure_kpa": pressure_display,
        "cnormf_n": cnormf,
        "force_magnitude_n": force_magnitude,
        "ambiguous": ambiguous,
        "availability": availability,
    }
