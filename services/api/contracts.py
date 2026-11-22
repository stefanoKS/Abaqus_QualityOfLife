from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from packages.engineering.model import Project


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


Name = Annotated[str, Field(min_length=1, max_length=100)]


class NewProject(Contract):
    name: Name
    dimension: Literal["2D", "3D"] = "2D"
    # Models live in a project group. Omitted (legacy clients) lands in the
    # default group instead of failing.
    group: UUID | None = None
    # An explicit opt-in to a public synthetic section. Creating a model
    # never seeds geometry by default: a new model starts empty.
    example: bool = False
    # Named example; ``two-panel`` adds a moving body below the seal and the
    # explicit 1.0 s / 1.3 s two-step durations.
    template: Literal["hollow", "two-panel"] = "hollow"


class NewGroup(Contract):
    name: Name


class MaterialCard(Contract):
    """A validated constitutive card independent of any model."""

    model: Literal["linear_elastic", "hyperfoam_test", "neo_hookean"]
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    density: float = Field(gt=0, le=1e9)
    young: float | None = Field(default=None, gt=0, le=1e9)
    poisson: float | None = Field(default=None, gt=-1, lt=0.5)
    # Compressible neo-Hookean: C10 in MPa, D1 in MPa^-1.
    c10: float | None = Field(default=None, gt=0, le=1e9)
    d1: float | None = Field(default=None, gt=0, le=1e9)
    test_data: list[tuple[float, float, float]] = Field(default_factory=list, max_length=1024)

    def checked(self, name="Library material"):
        from packages.engineering.model import Material

        return Material(
            id="library",
            name=name,
            version=1,
            **self.model_dump(),
        )


class LibraryCreate(Contract):
    name: Name
    card: MaterialCard
    note: str = Field(default="", max_length=200)


class LibraryUpdate(Contract):
    name: Name | None = None
    card: MaterialCard | None = None
    note: str = Field(default="", max_length=200)


class LibraryDuplicate(Contract):
    name: Name | None = None


class MaterialImportRequest(Contract):
    revision: UUID
    material_ids: list[str] = Field(default_factory=list, max_length=256)


class MaterialImportResult(Contract):
    material_id: str
    library_id: str
    version: int
    existing: bool


class LibraryVersion(Contract):
    version: int
    card: MaterialCard
    created: float
    note: str


class LibraryUsageRow(Contract):
    revision: str
    project: str
    number: int
    model_name: str
    material_id: str
    pinned_version: int | None = None


class LibrarySummary(Contract):
    id: str
    name: str
    archived: bool
    created: float
    updated: float
    current_version: int
    version_count: int
    usage_count: int
    card: MaterialCard


class LibraryDetail(LibrarySummary):
    versions: list[LibraryVersion]
    usage: list[LibraryUsageRow]


class NewProjectGroup(Contract):
    """One user action: create a project group and its first model together."""

    name: Name
    model_name: Name | None = None
    dimension: Literal["2D", "3D"] = "2D"
    example: bool = False
    # Request identity supplied once per user action. Repeating the request with
    # the same token returns the original group and model instead of creating
    # another pair after a lost response.
    token: UUID


class Group(Contract):
    id: str
    name: str
    created: float
    archived: bool = False


class Save(Contract):
    base: UUID
    setup: Project


class Revision(Contract):
    id: str
    project: str
    number: int
    created: float
    source_id: str | None
    group: str | None = None
    group_name: str | None = None
    mesh_compat: str | None = None
    archived: bool = False
    group_archived: bool = False
    setup: Project


class GroupCreated(Contract):
    group: Group
    model: Revision


class Summary(Contract):
    id: str
    revision: str
    number: int
    name: str
    dimension: str
    created: float
    group: str | None = None
    group_name: str | None = None
    revisions: int = 1
    archived: bool = False
    group_archived: bool = False


class DeleteConfirm(Contract):
    confirm: str = Field(default="", max_length=200)


class DeletionInfo(Contract):
    kind: Literal["model", "group"]
    id: str
    name: str
    archived: bool
    revisions: int = 0
    jobs: int = 0
    models: int = 0
    unarchived_models: int = 0
    active_jobs: list[str] = Field(default_factory=list)
    deletable: bool
    group: str | None = None
    group_name: str | None = None
    group_archived: bool = False


class DeletionResult(Contract):
    id: str
    name: str
    removed_jobs: int = 0
    removed_models: int = 0
    cleanup: Literal["done", "pending"] = "done"


class GroupSummary(Group):
    models: list[Summary]


class RevisionSummary(Contract):
    id: str
    project: str
    number: int
    created: float
    source_id: str | None = None
    name: str
    dimension: str


class DuplicateModel(Contract):
    name: Name | None = None


class Build(Contract):
    revision: UUID
    token: UUID


class Deck(Build):
    """Prepare the input deck from an already reviewed mesh."""

    mesh: UUID
    # Hash of the fixed-node set the engineer reviewed. A fixture changed by
    # another tab must conflict before the deck is enqueued; omitted by older
    # clients, which keeps their existing behaviour.
    fixture_hash: str | None = Field(default=None, max_length=64)


class Fixture(Contract):
    """Instance-qualified mesh node labels, e.g. ``WS-1:15``."""

    labels: list[str] = Field(default_factory=list, max_length=20000)
    # Optimistic concurrency: the hash of the fixture the editor loaded. The empty
    # string means "I believe no fixture is saved yet". ``None`` is a legacy
    # unconditional write.
    expected_hash: str | None = Field(default=None, max_length=64)


class FixtureInfo(Contract):
    labels: list[str]
    count: int
    hash: str


class Submit(Build):
    name: Name
    deck: UUID
    # New submissions are Abaqus-only. ``DEMO`` remains in the vocabulary so an
    # explicit legacy value can be rejected with an actionable message instead of
    # an opaque 422, and so historical rows keep their recorded mode.
    mode: Literal["DEMO", "ABAQUS"] = "ABAQUS"
    scenario: Literal["success", "failure", "slow", "extraction_failure"] = "success"
    cpus: int = Field(default=1, ge=1, le=32)


class Job(BaseModel):
    id: str
    revision: str
    project: str
    number: int
    project_name: str
    group: str | None = None
    group_name: str | None = None
    name: str
    dimension: str
    mode: str
    status: str
    solver: str
    extraction: str
    scenario: str
    phase: str
    created: float
    started: float | None
    ended: float | None
    heartbeat: float | None
    pid: int | None
    process_started: float | None
    step: str | None
    increment: int | None
    step_time: float | None
    exit_code: int | None
    extraction_exit: int | None
    cpus: int
    build: str | None
    mesh: str | None = None
    mesh_digest: str | None = None
    mesh_compat: str | None = None
    fixture_hash: str | None = None
    fixture: FixtureInfo | None = None
    fixture_labels: list[str] | None = None
    diagnostic: str
    manifest: list[str]
    input_hash: str | None
