"""Mesh identity: the inputs that decide whether a stored mesh can be reused.

A mesh is reusable while everything that determines *its geometry and element
topology* is unchanged. Material properties, motion, contact, thickness and the
fixed-node fixture are deliberately excluded: editing them must reuse the mesh.
"""

from hashlib import sha256
import json

from .model import Project


def canonical(data):
    return json.dumps(
        data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )


def mesh_inputs(project: Project):
    """Return only the fields that change the produced mesh.

    Names, source handles, layers, material card values and the analysis setup are
    excluded on purpose, so renaming an edge or editing a material card does not
    force a remesh.
    """
    return {
        "dimension": project.dimension,
        "formulation": project.formulation,
        "plane": {
            "id": project.plane.id,
            "origin": list(project.plane.origin),
            "x_axis": list(project.plane.x_axis),
            "y_axis": list(project.plane.y_axis),
        },
        "vertices": [{"id": v.id, "xyz": list(v.xyz)} for v in project.vertices],
        "edges": [
            {
                "id": e.id,
                "start": e.start,
                "end": e.end,
                "kind": e.kind,
                "center": list(e.center) if e.center else None,
                "sweep": e.sweep,
                "spline": {
                    "degree": e.spline.degree,
                    "control_points": [list(p) for p in e.spline.control_points],
                    "fit_points": [list(p) for p in e.spline.fit_points],
                    "knots": list(e.spline.knots),
                    "weights": list(e.spline.weights),
                    "tangents": [list(p) for p in e.spline.tangents],
                    "closed": e.spline.closed,
                    "periodic": e.spline.periodic,
                    "tolerance": e.spline.tolerance,
                }
                if e.spline
                else None,
                "component": e.component,
            }
            for e in project.edges
        ],
        # A cavity is meshed only when a material fills it, so only the presence
        # of an assignment matters here, not which card it points at.
        "faces": [
            {
                "id": f.id,
                "cavity": f.cavity,
                "component": f.component,
                "loops": f.loops,
                "filled": f.material is not None,
            }
            for f in project.faces
        ],
        # FE inclusion depends on the analysis mode. The key is omitted for the
        # legacy door-only mode so every digest computed before this field
        # existed stays valid and historical meshes remain reusable.
        **(
            {"analysis_mode": project.analysis.mode}
            if project.analysis.mode != "door_only"
            else {}
        ),
        "components": [{"id": c.id, "role": c.role} for c in project.components],
        "mesh": {
            "size": project.mesh.size,
            "local": dict(sorted(project.mesh.local.items())),
            "recombine": project.mesh.recombine,
        },
    }


def mesh_compat(project: Project):
    """Digest of the mesh-determining inputs, independent of the analysis setup."""
    return sha256(canonical(mesh_inputs(project)).encode("utf-8")).hexdigest()
