"""Engineering setup contract. CAD, render primitive and FE IDs are separate."""

from typing import Annotated, Literal
import math

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .spline import endpoint_points as spline_endpoints

Id = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")]
Name = Annotated[str, Field(min_length=1, max_length=160)]
Positive = Annotated[float, Field(gt=0, le=1e9)]
Coord = Annotated[float, Field(ge=-1e6, le=1e6)]
XYZ = tuple[Coord, Coord, Coord]
BoundedSize = Annotated[float, Field(ge=0.01, le=10000)]


class Model(BaseModel):
    model_config = ConfigDict(
        extra="forbid", allow_inf_nan=False, json_schema_serialization_defaults_required=True
    )


class Vertex(Model):
    id: Id
    xyz: XYZ


class SplineData(Model):
    """Canonical NURBS: the drawing's engineering curve, not a display chord.

    Either ``control_points`` (with ``knots``/``weights`` when rational) or
    ``fit_points`` is authoritative. ``tolerance`` is the maximum chord deviation
    allowed for display and meshing in project length units.
    """

    degree: Annotated[int, Field(ge=1, le=9)] = 3
    control_points: list[XYZ] = Field(default_factory=list, max_length=4096)
    fit_points: list[XYZ] = Field(default_factory=list, max_length=4096)
    knots: list[float] = Field(default_factory=list, max_length=8192)
    weights: list[float] = Field(default_factory=list, max_length=4096)
    tangents: list[XYZ] = Field(default_factory=list, max_length=2)
    closed: bool = False
    periodic: bool = False
    tolerance: BoundedSize = 0.02

    @model_validator(mode="after")
    def check_definition(self):
        if bool(self.control_points) == bool(self.fit_points):
            raise ValueError(
                "A spline needs exactly one of control points or fit points; import both from the drawing header."
            )
        poles = len(self.control_points)
        if self.control_points:
            if poles < self.degree + 1:
                raise ValueError(
                    f"Spline has {poles} control points; a degree {self.degree} spline needs at least {self.degree + 1}."
                )
            if self.knots and len(self.knots) != poles + self.degree + 1:
                raise ValueError(
                    "Spline knot vector length must equal control points + degree + 1."
                )
            if self.knots and any(b < a for a, b in zip(self.knots, self.knots[1:])):
                raise ValueError("Spline knots must be non-decreasing.")
            if self.weights and (
                len(self.weights) != poles or any(w <= 0 or not math.isfinite(w) for w in self.weights)
            ):
                raise ValueError("Spline weights must be one positive finite value per control point.")
        elif len(self.fit_points) < 2:
            raise ValueError("A fit-point spline needs at least two points.")
        if any(abs(p[2]) > 1e-8 for p in [*self.control_points, *self.fit_points]):
            raise ValueError("Spline points must be in the XY plane at Z = 0.")
        return self


class Edge(Model):
    id: Id
    name: Name
    component: Id
    start: Id
    end: Id
    kind: Literal["line", "arc", "spline"] = "line"
    center: XYZ | None = None
    sweep: Annotated[float, Field(gt=0, le=math.pi + 1e-8)] | None = None  # CCW radians
    spline: SplineData | None = None
    source_handle: str = Field(default="", max_length=96)
    layer: str = Field(default="", max_length=255)


class Face(Model):
    cavity: bool = False
    id: Id
    name: Name
    component: Id
    material: Id | None = None
    loops: list[list[str]] = Field(min_length=1, max_length=512)


class Solid(Model):
    id: Id
    section: Id
    component: Id


class Component(Model):
    id: Id
    # ``name`` is the authoritative drawing/import label. ``alias`` is an
    # optional user-facing display name; it is excluded from mesh identity, so a
    # rename never forces a remesh and never rewrites the source drawing.
    name: Name
    alias: str = Field(default="", max_length=160)
    role: Literal["seal", "moving_panel", "vehicle_body", "unassigned"]


class Material(Model):
    id: Id
    name: Name
    version: Annotated[int, Field(ge=1)] = 1
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    model: Literal["linear_elastic", "hyperfoam_test"]
    density: Positive
    young: Positive | None = None
    poisson: Annotated[float, Field(gt=-1, lt=0.5)] | None = None
    test_data: list[tuple[float, float, float]] = Field(default_factory=list, max_length=1024)
    # Optional pin to a global library version. The card values above remain the
    # immutable snapshot a saved revision and its deck actually use.
    library_id: Annotated[str, Field(max_length=80)] | None = None
    library_version: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def check_card(self):
        if self.model == "linear_elastic" and (self.young is None or self.poisson is None):
            raise ValueError("Enter Young's modulus and Poisson's ratio for the elastic card.")
        if self.model == "hyperfoam_test" and len(self.test_data) < 3:
            raise ValueError("Supply at least three uniaxial test samples for hyperfoam.")
        if (self.library_id is None) != (self.library_version is None):
            raise ValueError("A library pin needs both the material id and its version.")
        return self


class Selection(Model):
    id: Id
    name: Name
    entities: list[Id] = Field(default_factory=list, max_length=4096)


class Mounting(Model):
    selection: Id = "mount"


class Contact(Model):
    normal: Literal["hard"] = "hard"
    scope: Literal["all_exterior"] = "all_exterior"
    friction: Annotated[float, Field(ge=0, le=5)] = 0.3


class BodyMotion(Model):
    """Step-1 motion of the moving body in the two-panel template."""

    offset: Coord = 0
    # Signed Y travel. Seating normally moves down (negative), but the schema
    # does not assume the door and body share a sign.
    travel: Annotated[float, Field(ge=-10000, le=10000)] = 0
    duration: Positive = 1.0


class Motion(Model):
    axis: Literal["Y"] = "Y"
    travel: Annotated[float, Field(ge=-10000, lt=0)] = -5.5
    offset: Coord = 0
    duration: Positive = 1.3
    # Used only when analysis.mode == "body_then_door".
    body: BodyMotion = Field(default_factory=BodyMotion)


class MeshSpec(Model):
    size: BoundedSize = 1.0
    local: dict[Id, BoundedSize] = Field(default_factory=dict, max_length=4096)
    recombine: bool = True


class Analysis(Model):
    # Legacy door-only is the default so every historical revision keeps its
    # exact meaning. Two-panel seating must be chosen explicitly.
    mode: Literal["door_only", "body_then_door"] = "door_only"
    template: Literal["implicit_dynamic_closing"] = "implicit_dynamic_closing"
    thickness: Positive = 1
    force_normalization: Literal["total", "per_mm"] = "total"
    outputs: list[Literal["U", "RF", "S", "LE", "CSTRESS"]] = Field(
        default_factory=lambda: ["U", "RF", "S", "LE", "CSTRESS"], max_length=5
    )


class Extrusion(Model):
    length: Positive = 18
    subdivisions: Annotated[int, Field(ge=1, le=100)] = 4


class Plane(Model):
    id: Literal["section_xy"] = "section_xy"
    origin: tuple[Literal[0], Literal[0], Literal[0]] = (0, 0, 0)
    x_axis: tuple[Literal[1], Literal[0], Literal[0]] = (1, 0, 0)
    y_axis: tuple[Literal[0], Literal[1], Literal[0]] = (0, 1, 0)


class Source(Model):
    # ``empty`` is an explicit state, not a blank drawing: the model exists,
    # keeps its name, dimension and settings, and has no geometry at all.
    kind: Literal["empty", "synthetic", "dxf", "dwg"]
    filename: str = Field(default="", max_length=255)
    digest: str = Field(default="", max_length=64)
    drawing_units: str = Field(default="millimetres", max_length=128)


class Project(Model):
    schema_version: Literal[1] = 1
    name: Name
    dimension: Literal["2D", "3D"] = "2D"
    formulation: Literal["plane_stress", "extrusion_preview"] = "plane_stress"
    units: Literal["N-mm-s-tonne"] = "N-mm-s-tonne"
    plane: Plane = Field(default_factory=Plane)
    # Counts are enforced by the model validator so an explicitly empty model can
    # exist while a drawing-backed model stays as strict as before.
    vertices: list[Vertex] = Field(default_factory=list, max_length=8192)
    edges: list[Edge] = Field(default_factory=list, max_length=4096)
    faces: list[Face] = Field(default_factory=list, max_length=512)
    components: list[Component] = Field(default_factory=list, max_length=512)
    materials: list[Material] = Field(default_factory=list, max_length=256)
    selections: list[Selection] = Field(default_factory=list, max_length=128)
    mounting: Mounting = Field(default_factory=Mounting)
    contact: Contact = Field(default_factory=Contact)
    motion: Motion = Field(default_factory=Motion)
    mesh: MeshSpec = Field(default_factory=MeshSpec)
    extrusion: Extrusion = Field(default_factory=Extrusion)
    analysis: Analysis = Field(default_factory=Analysis)
    source: Source

    @property
    def is_empty(self):
        """True only for an explicit model that has not imported a drawing yet."""
        return self.source.kind == "empty"

    @property
    def material_regions(self):
        return [face for face in self.faces if not face.cavity or face.material is not None]

    @property
    def solids(self):
        return (
            [
                Solid(id=f"solid-{f.id}", section=f.id, component=f.component)
                for f in self.material_regions
            ]
            if self.dimension == "3D"
            else []
        )

    @model_validator(mode="after")
    def topology(self):
        if (self.dimension == "2D") != (self.formulation == "plane_stress"):
            raise ValueError("Choose plane stress for 2D or extrusion preview for 3D.")
        if self.source.kind == "empty":
            if self.vertices or self.edges or self.faces or self.components or self.materials or self.selections:
                raise ValueError(
                    "An empty model must not carry geometry, regions, selections or material "
                    "cards. Import a drawing first."
                )
            return self
        if len(self.vertices) < 2 or not self.edges or not self.components:
            raise ValueError(
                "A drawing-backed model needs at least two vertices, one section edge and "
                "one component."
            )
        groups = [
            self.vertices,
            self.edges,
            self.faces,
            self.components,
            self.selections,
            self.materials,
        ]
        ids = [obj.id for group in groups for obj in group]
        if len(ids) != len(set(ids)):
            raise ValueError("Geometry, component, selection and material IDs must be unique.")
        vertices = {v.id: v.xyz for v in self.vertices}
        edges = {e.id: e for e in self.edges}
        components = {c.id for c in self.components}
        materials = {m.id for m in self.materials}
        for e in self.edges:
            if e.component not in components or e.start not in vertices or e.end not in vertices:
                raise ValueError(f"{e.name}: unresolved vertex or component.")
            a, b = vertices[e.start], vertices[e.end]
            closed_spline = e.kind == "spline" and e.spline is not None and e.spline.closed
            if abs(a[2]) > 1e-8 or abs(b[2]) > 1e-8 or (
                math.dist(a, b) < 1e-7 and not closed_spline
            ):
                raise ValueError(f"{e.name}: section edges must be nonzero and in the XY plane.")
            if e.kind == "arc":
                if e.center is None or e.sweep is None or abs(e.center[2]) > 1e-8:
                    raise ValueError(f"{e.name}: missing planar circular arc definition.")
                r = math.dist(a, e.center)
                theta = math.atan2(a[1] - e.center[1], a[0] - e.center[0]) + e.sweep
                reconstructed = (
                    e.center[0] + r * math.cos(theta),
                    e.center[1] + r * math.sin(theta),
                    0,
                )
                if math.dist(b, reconstructed) > max(1e-7, 1e-9 * r):
                    raise ValueError(f"{e.name}: arc endpoints and sweep disagree.")
            if e.kind == "spline":
                if e.spline is None:
                    raise ValueError(f"{e.name}: missing spline definition.")
                first, last = spline_endpoints(e.spline)
                tolerance = max(1e-7, 1e-6 * max(1.0, math.dist(a, b)))
                if math.dist(a, first) > tolerance or math.dist(b, last) > tolerance:
                    raise ValueError(
                        f"{e.name}: spline endpoints disagree with its vertices. Re-import the curve."
                    )
        for f in self.faces:
            if f.component not in components or f.material and f.material not in materials:
                raise ValueError(f"{f.name}: unresolved component or material.")
            for loop in f.loops:
                if not loop or len(loop) > 4096:
                    raise ValueError(f"{f.name}: invalid boundary size.")
                sequence = []
                for token in loop:
                    edge = edges.get(token.removeprefix("-"))
                    if not edge:
                        raise ValueError(f"{f.name}: missing boundary {token}.")
                    sequence.append(
                        (edge.end, edge.start) if token.startswith("-") else (edge.start, edge.end)
                    )
                if any(a[1] != b[0] for a, b in zip(sequence, sequence[1:] + sequence[:1])):
                    raise ValueError(f"{f.name}: invalid or open boundary.")
        cad = set(vertices) | set(edges) | {f.id for f in self.faces}
        if any(set(s.entities) - cad for s in self.selections) or set(self.mesh.local) - set(edges):
            raise ValueError("Geometry changed. Rebuild selections and local mesh controls.")
        if self.mounting.selection not in {s.id for s in self.selections}:
            raise ValueError("Mounting selection no longer exists.")
        if self.analysis.mode == "body_then_door":
            roles = [c.role for c in self.components]
            if roles.count("moving_panel") != 1 or roles.count("vehicle_body") != 1:
                raise ValueError(
                    "Body-then-door analysis needs exactly one moving door and one moving body."
                )
            if not any(not face.cavity for face in self.faces):
                raise ValueError("Body-then-door analysis needs at least one seal region.")
            body = self.motion.body
            if body.travel == 0:
                raise ValueError("Set a non-zero body travel for body-then-door analysis.")
            if body.duration <= 0:
                raise ValueError("Body seating duration must be positive.")
            if self.motion.duration <= 0:
                raise ValueError("Door closing duration must be positive.")
        return self
