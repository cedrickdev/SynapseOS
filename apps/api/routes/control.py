"""Authenticated bounded control routes for Engineering V1."""

from __future__ import annotations

import uuid
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from apps.api.dependencies.control import get_control_principal, get_control_queue
from core.control_api import (
    CancelWorkflowCommand,
    CloseProjectCommand,
    CommandReceipt,
    ControlPrincipal,
    HumanApprovalCommand,
    LaunchWorkflowCommand,
    ProjectIntakeCommand,
    ProjectIntakeResult,
    WorkflowLaunchResult,
    WorkflowStatus,
    WorkflowStatusQuery,
)
from core.control_api.errors import ControlError, ControlErrorCode
from infrastructure.control_api import SQLAlchemyControlService
from infrastructure.control_api.service import TransactionalQueue
from infrastructure.database.session import get_session

router = APIRouter(prefix="/control", tags=["control"])
SessionDependency = Annotated[Session, Depends(get_session)]
PrincipalDependency = Annotated[ControlPrincipal, Depends(get_control_principal)]
QueueDependency = Annotated[TransactionalQueue, Depends(get_control_queue)]


def _raise(error: ControlError) -> NoReturn:
    mapping = {
        ControlErrorCode.FORBIDDEN: (403, "Command denied."),
        ControlErrorCode.NOT_FOUND: (404, "Resource not found."),
        ControlErrorCode.CONFLICT: (409, "Command conflicts with authoritative state."),
        ControlErrorCode.QUEUE_FULL: (503, "Execution queue is at capacity."),
        ControlErrorCode.UNAVAILABLE: (503, "Control service unavailable."),
    }
    status_code, message = mapping[error.code]
    raise HTTPException(
        status_code=status_code,
        detail={"code": error.code.value, "message": message},
    ) from None


def _service(session: Session, queue: TransactionalQueue) -> SQLAlchemyControlService:
    return SQLAlchemyControlService(session, queue)


@router.post("/projects", response_model=ProjectIntakeResult, status_code=status.HTTP_201_CREATED)
def intake_project(
    command: ProjectIntakeCommand,
    response: Response,
    principal: PrincipalDependency,
    session: SessionDependency,
    queue: QueueDependency,
) -> ProjectIntakeResult:
    try:
        result = _service(session, queue).intake(principal, command)
        if result.replayed:
            response.status_code = status.HTTP_200_OK
        return result
    except ControlError as error:
        _raise(error)


@router.post("/projects/{project_id}/approve", response_model=CommandReceipt)
def approve_project(
    project_id: uuid.UUID,
    command: HumanApprovalCommand,
    principal: PrincipalDependency,
    session: SessionDependency,
    queue: QueueDependency,
) -> CommandReceipt:
    if command.project_id != project_id:
        _raise(ControlError(ControlErrorCode.CONFLICT))
    try:
        return _service(session, queue).approve(principal, command)
    except ControlError as error:
        _raise(error)


@router.post(
    "/projects/{project_id}/launch",
    response_model=WorkflowLaunchResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def launch_workflow(
    project_id: uuid.UUID,
    command: LaunchWorkflowCommand,
    response: Response,
    principal: PrincipalDependency,
    session: SessionDependency,
    queue: QueueDependency,
) -> WorkflowLaunchResult:
    if command.project_id != project_id:
        _raise(ControlError(ControlErrorCode.CONFLICT))
    try:
        result = _service(session, queue).launch(principal, command)
        if result.replayed:
            response.status_code = status.HTTP_200_OK
        return result
    except ControlError as error:
        _raise(error)


@router.post("/projects/{project_id}/cancel", response_model=CommandReceipt)
def cancel_workflow(
    project_id: uuid.UUID,
    command: CancelWorkflowCommand,
    principal: PrincipalDependency,
    session: SessionDependency,
    queue: QueueDependency,
) -> CommandReceipt:
    if command.project_id != project_id:
        _raise(ControlError(ControlErrorCode.CONFLICT))
    try:
        return _service(session, queue).cancel(principal, command)
    except ControlError as error:
        _raise(error)


@router.post("/projects/{project_id}/close", response_model=CommandReceipt)
def close_project(
    project_id: uuid.UUID,
    command: CloseProjectCommand,
    principal: PrincipalDependency,
    session: SessionDependency,
    queue: QueueDependency,
) -> CommandReceipt:
    if command.project_id != project_id:
        _raise(ControlError(ControlErrorCode.CONFLICT))
    try:
        return _service(session, queue).close(principal, command)
    except ControlError as error:
        _raise(error)
    except ValueError:
        _raise(ControlError(ControlErrorCode.CONFLICT))


@router.get("/projects/{project_id}/status", response_model=WorkflowStatus)
def workflow_status(
    project_id: uuid.UUID,
    principal: PrincipalDependency,
    session: SessionDependency,
    queue: QueueDependency,
) -> WorkflowStatus:
    try:
        return _service(session, queue).status(
            principal, WorkflowStatusQuery(project_id=project_id)
        )
    except ControlError as error:
        _raise(error)
