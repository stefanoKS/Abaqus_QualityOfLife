"""Mesh-node fixture: eligible nodes, label validation and legacy edge resolution.

Labels are instance-qualified (``WS-1:15``) because FE labels are only unique
within an instance. Selection happens on actual mesh nodes, so a rectangle never
silently expands to a whole CAD edge.
"""

from hashlib import sha256
import json

SEAL_INSTANCE = "WS-1"
RIGID_ELEMENT = "R2D2"


def deformable_nodes(mesh):
    """Node labels used by at least one deformable element."""
    return {
        int(node)
        for element in mesh["elements"]
        if element["type"] != RIGID_ELEMENT
        for node in element["nodes"]
    }


def rigid_nodes(mesh):
    """Node labels used only by rigid elements (never eligible as a fixture)."""
    used = {int(node) for element in mesh["elements"] for node in element["nodes"]}
    return used - deformable_nodes(mesh)


def labels_hash(labels):
    canonical = json.dumps(sorted(labels), separators=(",", ":"), ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def parse(label):
    instance, _, number = str(label).partition(":")
    if not instance or not number.isdigit() or int(number) <= 0:
        raise ValueError(
            f"Fixed-node label '{label}' must read like {SEAL_INSTANCE}:12, "
            "with an instance name and a positive node number."
        )
    return instance, int(number)


def normalize(labels, mesh):
    """Validate, deduplicate and deterministically order the fixed-node labels.

    An empty selection is accepted here; prepare-deck validates that it is not
    empty, so the mesh stage can legitimately run before a fixture exists.
    """
    deformable = deformable_nodes(mesh)
    rigid = rigid_nodes(mesh)
    chosen = set()
    for label in labels:
        instance, number = parse(label)
        if instance != SEAL_INSTANCE:
            raise ValueError(
                f"Fixed-node label '{label}' refers to another instance. "
                f"Only {SEAL_INSTANCE} nodes can be fixed."
            )
        if number in rigid:
            raise ValueError(
                f"Node {label} belongs to the rigid panel and cannot be fixed."
            )
        if number not in deformable:
            raise ValueError(f"Node {label} does not exist in this mesh.")
        chosen.add(number)
    return [f"{SEAL_INSTANCE}:{number}" for number in sorted(chosen)]


def from_edges(mesh, edge_ids):
    """Resolve a legacy CAD-edge mounting selection to mesh-node labels."""
    available = mesh.get("edge_nodes") or {}
    nodes = set()
    missing = []
    for edge in edge_ids:
        chain = available.get(edge)
        if not chain:
            missing.append(edge)
        else:
            nodes.update(int(node) for node in chain)
    if missing:
        raise ValueError(
            "The stored mounting edges are not present in this mesh: "
            + ", ".join(missing)
            + ". Reselect the fixed nodes."
        )
    return [f"{SEAL_INSTANCE}:{number}" for number in sorted(nodes)]
