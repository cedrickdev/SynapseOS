"""Strict bounded contracts for human control of Engineering V1."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")]


def _uuid(value: object) -> object:
    return UUID(value) if isinstance(value, str) else value


StrictUUID = Annotated[UUID, BeforeValidator(_uuid)]


class ControlRole(StrEnum):
    OWNER = "OWNER"
    OPERATOR = "OPERATOR"
    APPROVER = "APPROVER"
    VIEWER = "VIEWER"


class _ControlModel(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ControlPrincipal(_ControlModel):
    actor_id: Identifier
    company_id: StrictUUID
    roles: Annotated[tuple[ControlRole, ...], Field(min_length=1, max_length=4)]

    @field_validator("roles", mode="before")
    @classmethod
    def copy_roles(cls, value: object) -> object:
        return tuple(value) if isinstance(value, (list, tuple)) else value

    @field_validator("roles")
    @classmethod
    def require_unique_roles(cls, value: tuple[ControlRole, ...]) -> tuple[ControlRole, ...]:
        if len(value) != len(set(value)):
            raise ValueError("control roles must be unique")
        return value


class _Command(_ControlModel):
    command_id: StrictUUID
    correlation_id: StrictUUID
    idempotency_key: Identifier


class ProjectIntakeCommand(_Command):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    specification: Annotated[str, Field(min_length=1, max_length=16_384)]
    task_title: Annotated[str, Field(min_length=1, max_length=500)]
    assigned_agent_id: StrictUUID

    @model_validator(mode="after")
    def strip_text(self) -> Self:
        if any(
            value != value.strip() for value in (self.name, self.specification, self.task_title)
        ):
            raise ValueError("control command text must be canonical")
        return self


class HumanApprovalCommand(_Command):
    project_id: StrictUUID
    task_id: StrictUUID
    evidence_id: Identifier


class LaunchWorkflowCommand(_Command):
    project_id: StrictUUID
    task_id: StrictUUID
    timeout_seconds: Annotated[float, Field(gt=0.0, le=3_600.0, allow_inf_nan=False)] = 900.0


class CancelWorkflowCommand(_Command):
    project_id: StrictUUID
    run_id: StrictUUID


class CloseProjectCommand(_Command):
    project_id: StrictUUID
    evidence_id: Identifier


class WorkflowStatusQuery(_ControlModel):
    project_id: StrictUUID


class ProjectIntakeResult(_ControlModel):
    project_id: StrictUUID
    task_id: StrictUUID
    status: str
    replayed: bool = False


class WorkflowLaunchResult(_ControlModel):
    project_id: StrictUUID
    task_id: StrictUUID
    run_id: StrictUUID
    queue_status: str
    replayed: bool = False


class CommandReceipt(_ControlModel):
    command_id: StrictUUID
    correlation_id: StrictUUID
    project_id: StrictUUID
    result: str
    replayed: bool = False


class WorkflowStatus(_ControlModel):
    project_id: StrictUUID
    project_status: str
    task_id: StrictUUID | None
    task_status: str | None
    run_id: StrictUUID | None
    queue_status: str | None
    assigned_agent_id: StrictUUID | None
    qa_status: str | None
    security_status: str | None
    human_approval: bool
    merge_gate_status: str | None
    terminal: bool
