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
    # An explicit opt-in to the public demonstration section. Creating a model
    # never seeds geometry by default: a new model starts empty.
    example: bool = False


class NewGroup(Contract):
    name: Name


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
