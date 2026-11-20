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


class Save(Contract):
    base: UUID
    setup: Project


class Revision(Contract):
    id: str
    project: str
    number: int
    created: float
    source_id: str | None
    setup: Project


class Summary(Contract):
    id: str
    revision: str
    number: int
    name: str
    dimension: str
    created: float


class Build(Contract):
    revision: UUID
    token: UUID


class Submit(Build):
    name: Name
    build: UUID
    mode: Literal["DEMO", "ABAQUS"] = "DEMO"
    scenario: Literal["success", "failure", "slow", "extraction_failure"] = "success"
    cpus: int = Field(default=1, ge=1, le=32)


class Job(BaseModel):
    id: str
    revision: str
    project: str
    number: int
    project_name: str
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
    diagnostic: str
    manifest: list[str]
    input_hash: str | None
