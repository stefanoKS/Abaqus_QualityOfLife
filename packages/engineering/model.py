"""Engineering setup contract. CAD, render primitive and FE IDs are separate."""

from typing import Annotated, Literal
import math

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .spline import endpoint_points as spline_endpoints
from .roles import derive_mode
from . import motion as motion_policy

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


class Matrix(Model):
    """A material data table: rows of numbers, in source column order."""

    rows: list[list[float]] = Field(default_factory=list, max_length=2048)

    @field_validator("rows")
    @classmethod
    def check_shape(cls, rows):
        if rows:
            width = len(rows[0])
            if width == 0 or any(len(row) != width for row in rows):
                raise ValueError("Every row of a material table must have the same width.")
        return rows


class HyperfoamLaw(Model):
    """Abaqus ``*Hyperfoam`` definition, either fitted test data or direct.

    ``lateral`` records whether the source *supplied* lateral nominal strain. The
    supplied library stores zeros in that column while its
    ``lateralNominalStrain`` flag is OFF; those zeros are not measurements and are
    never emitted. ``poisson`` stays ``None`` when the source has no value.
    """

    n: Annotated[int, Field(ge=1, le=6)] = 1
    test_data: bool = True
    moduli: Literal["LONG_TERM", "INSTANTANEOUS"] = "LONG_TERM"
    lateral: bool = False
    poisson: float | None = None
    table: list[list[float]] = Field(default_factory=list, max_length=8)
    uniaxial: list[list[float]] = Field(default_factory=list, max_length=2048)

    @model_validator(mode="after")
    def check_table(self):
        if self.test_data:
            if len(self.uniaxial) < 3:
                raise ValueError("Hyperfoam test data needs at least three samples.")
            allowed = (3,) if self.lateral else (2, 3)
            if any(len(row) not in allowed for row in self.uniaxial):
                raise ValueError(
                    "Hyperfoam test data rows carry stress and strain, plus lateral "
                    "strain only when it was measured."
                )
            if self.lateral and any(len(row) != 3 for row in self.uniaxial):
                raise ValueError("Lateral strain is enabled, so every row needs three columns.")
        else:
            if not self.table:
                raise ValueError("Direct Hyperfoam coefficients are required.")
            if any(len(row) != 3 * self.n for row in self.table):
                raise ValueError(
                    f"Hyperfoam N={self.n} needs {3 * self.n} coefficients per row."
                )
        return self


class HyperelasticLaw(Model):
    """Abaqus ``*Hyperelastic`` definition with its source model and tables."""

    type: Literal["MARLOW", "YEOH", "OGDEN", "POLYNOMIAL", "NEO_HOOKE"]
    n: Annotated[int, Field(ge=1, le=6)] = 1
    test_data: bool = False
    moduli_time_scale: Literal["LONG_TERM", "INSTANTANEOUS"] = "LONG_TERM"
    lateral: bool = False
    table: list[list[float]] = Field(default_factory=list, max_length=8)
    uniaxial: list[list[float]] = Field(default_factory=list, max_length=2048)

    @model_validator(mode="after")
    def check_table(self):
        if self.test_data:
            if len(self.uniaxial) < 3:
                raise ValueError("Hyperelastic test data needs at least three samples.")
            if any(len(row) not in (2, 3) for row in self.uniaxial):
                raise ValueError("Hyperelastic test data rows carry stress and strain.")
        elif not self.table:
            raise ValueError("Direct hyperelastic coefficients are required.")
        return self


class ViscoelasticLaw(Model):
    """Abaqus ``*Viscoelastic`` Prony series (time domain, isotropic)."""

    domain: Literal["TIME", "FREQUENCY"] = "TIME"
    time: Literal["PRONY", "CREEP", "RELAXATION"] = "PRONY"
    table: list[list[float]] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def check_table(self):
        if self.time == "PRONY":
            if not self.table:
                raise ValueError("A Prony series needs at least one row.")
            if any(len(row) != 3 for row in self.table):
                raise ValueError("Prony rows carry g, k and the time constant tau.")
        return self


class PlasticLaw(Model):
    """Isotropic plastic hardening table (yield stress, plastic strain)."""

    hardening: Literal["ISOTROPIC", "KINEMATIC", "COMBINED", "JOHNSON_COOK"] = "ISOTROPIC"
    table: list[list[float]] = Field(default_factory=list, max_length=512)

    @model_validator(mode="after")
    def check_table(self):
        if not self.table:
            raise ValueError("A plastic law needs a hardening table.")
        if any(len(row) != 2 for row in self.table):
            raise ValueError("Plastic rows carry yield stress and plastic strain.")
        return self


class MullinsLaw(Model):
    """Abaqus ``*Mullins Effect`` block, preserved with its base law."""

    definition: Literal["CONSTANTS", "TEST_DATA", "USER"] = "CONSTANTS"
    table: list[list[float]] = Field(default_factory=list, max_length=512)


class ThermalLaw(Model):
    """Thermal-only material data, kept for browsing and export."""

    conductivity: list[list[float]] = Field(default_factory=list, max_length=512)
    specific_heat: list[list[float]] = Field(default_factory=list, max_length=512)


class Material(Model):
    id: Id
    name: Name
    version: Annotated[int, Field(ge=1)] = 1
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    # ``neo_hookean`` is a compressible solid-rubber law: C10 in stress units
    # (MPa) and D1 in inverse stress units (MPa^-1). It is distinct from the
    # hyperfoam test-data law and from linear elasticity; no card is relabelled.
    # ``cae_law`` is a faithful registered CAE library record: its behaviour lives
    # in the typed blocks below and the simplified editor does not rewrite it.
    model: Literal["linear_elastic", "hyperfoam_test", "neo_hookean", "cae_law"]
    # Density is required to run, but a source record may legitimately omit it.
    # Registration keeps it empty so the missing input is visible, never guessed.
    density: Positive | None = None
    young: Positive | None = None
    poisson: Annotated[float, Field(gt=-1, lt=0.5)] | None = None
    c10: Positive | None = None
    d1: Positive | None = None
    test_data: list[tuple[float, float, float]] = Field(default_factory=list, max_length=1024)
    # Faithful CAE library laws. They are mutually compatible exactly as the
    # source defines them: a hyperfoam with a Prony series, a hyperelastic with
    # Mullins softening, an elastic-plastic metal, or thermal-only data.
    hyperfoam: HyperfoamLaw | None = None
    hyperelastic: HyperelasticLaw | None = None
    viscoelastic: ViscoelasticLaw | None = None
    plastic: PlasticLaw | None = None
    mullins: MullinsLaw | None = None
    thermal: ThermalLaw | None = None
    # Explicit engineering family. Reduced integration belongs to the element
    # formulation, not to the law: a weatherstrip polymer quad meshes as CPS4R and
    # a deformable metal quad as full-integration CPS4. A linear elastic law alone
    # cannot tell metal from polymer, so the engineer declares the family here.
    family: Literal["polymer", "metal"] = "polymer"
    # Optional pin to a global library version. The card values above remain the
    # immutable snapshot a saved revision and its deck actually use.
    library_id: Annotated[str, Field(max_length=80)] | None = None
    library_version: Annotated[int, Field(ge=1)] | None = None

    @property
    def structural_law(self) -> bool:
        """True when this card can define a continuum structural response."""
        return bool(
            self.model in ("linear_elastic", "hyperfoam_test", "neo_hookean")
            or (self.young is not None and self.poisson is not None)
            or self.hyperfoam
            or self.hyperelastic
            or self.plastic
        )

    @model_validator(mode="after")
    def check_card(self):
        # A metal region meshes as a full-integration quad, so it must carry a
        # structural law the element can use. A thermal-only registered record has
        # no structural behaviour at all and is never assigned to a region; the
        # family it was imported with is kept as declared metadata.
        if self.family == "metal" and self.structural_law and self.model not in (
            "linear_elastic",
            "cae_law",
        ):
            raise ValueError(
                "A metal family card uses a structural elastic/hyperelastic law in this "
                "phase; rubber test-data cards stay polymer."
            )
        if self.model == "linear_elastic" and (self.young is None or self.poisson is None):
            raise ValueError("Enter Young's modulus and Poisson's ratio for the elastic card.")
        if self.model == "linear_elastic" and self.density is None:
            raise ValueError("A linear elastic card needs a density.")
        if self.model == "hyperfoam_test" and len(self.test_data) < 3:
            raise ValueError("Supply at least three uniaxial test samples for hyperfoam.")
        if self.model == "neo_hookean" and (self.c10 is None or self.d1 is None):
            raise ValueError(
                "A compressible neo-Hookean card needs C10 (MPa) and D1 (MPa^-1)."
            )
        if self.model == "cae_law" and not (
            self.hyperfoam
            or self.hyperelastic
            or self.plastic
            or self.elastic_table
            or self.thermal
        ):
            raise ValueError("A registered CAE card needs at least one property block.")
        if (self.library_id is None) != (self.library_version is None):
            raise ValueError("A library pin needs both the material id and its version.")
        return self

    @property
    def elastic_table(self) -> bool:
        """True when the card carries isotropic elastic constants."""
        return self.model == "linear_elastic" or (
            self.young is not None and self.poisson is not None
        )


class Selection(Model):
    id: Id
    name: Name
    entities: list[Id] = Field(default_factory=list, max_length=4096)


class Mounting(Model):
    selection: Id = "mount"


class Contact(Model):
    normal: Literal["hard"] = "hard"
    # ``all_exterior`` is the historical single-property contact domain. New
    # setups use independent named pairs so each interface can carry its own
    # Coulomb coefficient; the interior bonded partition seam stays outside the
    # exposed seal surface.
    scope: Literal["all_exterior", "named_pairs"] = "named_pairs"
    # Historical global coefficient. A version-3 revision keeps this exact value
    # (including zero and explicit non-defaults); new setups leave it ``None`` and
    # use the three independent pair coefficients below.
    friction: Annotated[float, Field(ge=0, le=5)] | None = None
    door_seal: Annotated[float, Field(ge=0, le=5)] = 0.7
    body_seal: Annotated[float, Field(ge=0, le=5)] = 0.7
    seal_self: Annotated[float, Field(ge=0, le=5)] = 0.7


class BodyMotion(Model):
    """Step-1 motion of the moving body in the two-panel template."""

    # Retained placement offset. New setups are drawn in place (zero); a legacy
    # offset is preserved on load/save/duplicate and shown read-only.
    offset: Coord = 0
    # New (version 4) form: a nonnegative stroke and an in-plane direction angle.
    # Global +X is 0 deg, +Y is 90 deg and positive is counterclockwise.
    angle: Annotated[float, Field(ge=-360, le=360)] = 90
    stroke: Annotated[float, Field(ge=0, le=10000)] = 0
    duration: Positive = 1.0
    # Legacy signed Y travel. Version-3 revisions keep it verbatim; version-4
    # revisions keep its Y component in sync for older readers but resolve the
    # prescribed motion from ``angle``/``stroke``.
    travel: Annotated[float, Field(ge=-10000, le=10000)] = 0

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_travel(cls, data):
        if isinstance(data, dict) and "travel" in data and "angle" not in data and "stroke" not in data:
            travel = data.get("travel")
            try:
                return {**data, "angle": -90.0 if float(travel) < 0 else 90.0, "stroke": abs(float(travel))}
            except (TypeError, ValueError):
                return data
        return data


class Motion(Model):
    # Retained placement offset (see BodyMotion.offset).
    offset: Coord = 0
    # New (version 4) prescribed motion: nonnegative stroke in mm and in-plane
    # direction angle in degrees. A zero stroke is a hold.
    angle: Annotated[float, Field(ge=-360, le=360)] = -90
    stroke: Annotated[float, Field(ge=0, le=10000)] = 10
    duration: Positive = 1.0
    # Legacy signed Y travel, preserved exactly for version-3 revisions.
    travel: Annotated[float, Field(ge=-10000, le=10000)] = -10.0
    # Legacy schema name; the direction is carried by ``angle`` on new setups.
    axis: Literal["Y"] = "Y"
    # Used only when analysis.mode == "body_then_door".
    body: BodyMotion = Field(default_factory=BodyMotion)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_travel(cls, data):
        """A client that only knows signed Y travel still migrates losslessly."""
        if isinstance(data, dict) and "travel" in data and "angle" not in data and "stroke" not in data:
            travel = data.get("travel")
            try:
                return {**data, "angle": -90.0 if float(travel) < 0 else 90.0, "stroke": abs(float(travel))}
            except (TypeError, ValueError):
                return data
        return data


class MeshSpec(Model):
    size: BoundedSize = 0.5
    local: dict[Id, BoundedSize] = Field(default_factory=dict, max_length=4096)
    recombine: bool = True


class Analysis(Model):
    # Legacy door-only is the default so every historical revision keeps its
    # exact meaning. Version-4 setups derive this from the assigned roles.
    mode: Literal["door_only", "body_then_door"] = "door_only"
    template: Literal["implicit_dynamic_closing"] = "implicit_dynamic_closing"
    # Solver plane-stress thickness. It is fed to *Solid Section and the surface
    # interaction data and is never the reporting width.
    thickness: Positive = 1
    # Reporting width W for displayed total force: (RF . d) * W / thickness.
    # New setups default to a represented 100 mm section while still solving a
    # 1 mm plane-stress section with no extruded mesh.
    reporting_width: Annotated[float, Field(gt=0, le=1e6)] = 100
    # ``legacy_thickness`` means an old revision whose force basis was its own
    # solver thickness. Ambiguous old evidence keeps "basis unavailable".
    reporting_width_basis: Literal["default_100_mm", "legacy_thickness"] = "default_100_mm"
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
    # How the drawing's declared unit header was interpreted. Empty on
    # revisions that predate the recorded policy.
    unit_basis: str = Field(default="", max_length=40)
    # The original declaration, the one numeric factor applied to world
    # geometry and where that decision came from. ``unit_factor`` is mm per
    # drawing unit; geometry stored in the project is already mm.
    unit_declaration: str = Field(default="", max_length=64)
    unit_factor: Annotated[float, Field(gt=0, le=1e15)] = 1.0
    unit_provenance: str = Field(default="", max_length=160)


class Project(Model):
    # Version 4 adds role-derived steps, independent contact coefficients, an
    # oblique prescribed motion and the represented reporting width. Versions
    # 1-3 keep their stored meaning and are never silently rescaled.
    schema_version: int = 4
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

    @model_validator(mode="before")
    @classmethod
    def legacy_defaults(cls, data):
        """Preserve historical effective defaults when saved fields are absent."""
        if not isinstance(data, dict):
            return data
        try:
            version = int(data.get("schema_version", 1))
        except (TypeError, ValueError):
            return data
        if version >= 4:
            return data
        changed = dict(data)
        changed.setdefault("schema_version", 1)
        mesh = changed.get("mesh")
        if version < 2 and mesh is None:
            mesh = {}
        if version < 2 and isinstance(mesh, dict) and "size" not in mesh:
            changed["mesh"] = {**mesh, "size": 1.0}
        motion = changed.get("motion")
        if motion is None:
            motion = {}
        if isinstance(motion, dict):
            motion = dict(motion)
            motion.setdefault("travel", -5.5)
            if version < 2 and "duration" not in motion:
                motion["duration"] = 1.3
            body = motion.get("body")
            if version < 2 and isinstance(body, dict) and "duration" not in body:
                motion["body"] = {**body, "duration": 1.0}
            changed["motion"] = motion
        # Version 3 and older carry one global contact coefficient and a force
        # basis equal to the solver thickness. Both are preserved verbatim.
        contact = changed.get("contact")
        contact = dict(contact) if isinstance(contact, dict) else {}
        # Version 3 and older always carried one global coefficient over the
        # all-exterior domain, whatever a newer payload shape contains.
        contact["scope"] = "all_exterior"
        if contact.get("friction") is None:
            contact["friction"] = 0.3
        changed["contact"] = contact
        analysis = changed.get("analysis")
        analysis = dict(analysis) if isinstance(analysis, dict) else {}
        thickness = analysis.get("thickness", 1)
        analysis["reporting_width"] = thickness
        analysis["reporting_width_basis"] = "legacy_thickness"
        changed["analysis"] = analysis
        return changed

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
        if self.schema_version >= 4 and self.components:
            # The step sequence is derived from the assigned roles. An
            # incomplete or duplicated assignment stays door-only and becomes a
            # readiness finding instead of a partially built analysis.
            self.analysis.mode = derive_mode(self.components, self.edges, self.faces)
            # Keep the legacy Y component readable for older consumers while the
            # prescribed motion itself resolves from angle/stroke.
            door = motion_policy.resolve(self.motion, self.schema_version)
            body = motion_policy.resolve(self.motion.body, self.schema_version, body=True)
            self.motion.travel = round(door["delta"][1], 9)
            self.motion.body.travel = round(body["delta"][1], 9)
        if self.analysis.mode == "body_then_door":
            if self.schema_version < 4:
                roles = [c.role for c in self.components]
                if roles.count("moving_panel") != 1 or roles.count("vehicle_body") != 1:
                    raise ValueError(
                        "Body-then-door analysis needs exactly one door panel and one body panel."
                    )
                if not any(not face.cavity for face in self.faces):
                    raise ValueError("Body-then-door analysis needs at least one seal region.")
            body = self.motion.body
            # Zero stroke/travel is a valid hold; only a non-positive duration is invalid.
            if body.duration <= 0:
                raise ValueError("Body seating duration must be positive.")
            if self.motion.duration <= 0:
                raise ValueError("Door closing duration must be positive.")
        return self
