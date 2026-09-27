"""Transactional PostgreSQL control service for Engineering V1."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from core.closure import ClosurePreconditions, ProjectClosureRequest, ProjectClosureWorkflow
from core.control_api.errors import ControlError, ControlErrorCode
from core.control_api.policy import require_any_role
from core.control_api.types import (
    CancelWorkflowCommand,
    CloseProjectCommand,
    CommandReceipt,
    ControlPrincipal,
    ControlRole,
    HumanApprovalCommand,
    LaunchWorkflowCommand,
    ProjectIntakeCommand,
    ProjectIntakeResult,
    WorkflowLaunchResult,
    WorkflowStatus,
    WorkflowStatusQuery,
)
from core.enums import (
    AgentRunStatus as PersistedRunStatus,
)
from core.enums import (
    AuditActorType,
    AuditResult,
    ProjectStatus,
    TaskStatus,
)
from core.lessons import LessonsLearnedInput
from core.queue import AgentRunJob, QueueFullError
from core.queue import AgentRunStatus as QueueStatus
from core.tasks.state_machine import TaskStateMachine
from infrastructure.closure.sqlalchemy import SQLAlchemyProjectClosureStore
from infrastructure.database.models import (
    Agent,
    AgentRun,
    AuditEvent,
    ControlCommandReceipt,
    ControlProjectScope,
    ExecutionQueueJob,
    Project,
    Task,
)


class TransactionalQueue(Protocol):
    def enqueue_in_session(self, session: Session, job: AgentRunJob) -> bool: ...

    def cancel_in_session(self, session: Session, run_id: UUID) -> bool: ...


class PersistableCommand(Protocol):
    @property
    def command_id(self) -> UUID: ...

    @property
    def correlation_id(self) -> UUID: ...

    @property
    def idempotency_key(self) -> str: ...


class SQLAlchemyControlService:
    """Authorize and persist bounded human commands without synchronous agent work."""

    def __init__(self, session: Session, queue: TransactionalQueue) -> None:
        self._session = session
        self._queue = queue

    def intake(
        self, principal: ControlPrincipal, command: ProjectIntakeCommand
    ) -> ProjectIntakeResult:
        replay = self._replay(principal, command, "PROJECT_INTAKE", ProjectIntakeResult)
        if replay is not None:
            return replay
        self._authorize(
            principal,
            "PROJECT_INTAKE",
            command.correlation_id,
            ControlRole.OWNER,
            ControlRole.OPERATOR,
        )
        agent = self._session.get(Agent, command.assigned_agent_id)
        if agent is None or agent.role != "Developer":
            self._reject(principal, command.correlation_id, "PROJECT_INTAKE", "INVALID_SCOPE")
            raise ControlError(ControlErrorCode.CONFLICT)
        project = Project(
            name=command.name,
            description=command.specification,
            status=ProjectStatus.INTAKE,
        )
        task = Task(
            project=project,
            title=command.task_title,
            description=command.specification,
            assigned_agent=agent,
            status=TaskStatus.BACKLOG,
        )
        self._session.add_all([project, task])
        self._session.flush()
        result = ProjectIntakeResult(
            project_id=project.id,
            task_id=task.id,
            status=project.status.value,
        )
        self._session.add(
            ControlProjectScope(project_id=project.id, company_id=principal.company_id)
        )
        self._record_receipt(principal, command, "PROJECT_INTAKE", result.model_dump(mode="json"))
        self._accepted(principal, command.correlation_id, "PROJECT_INTAKE", project.id, task.id)
        self._session.commit()
        return result

    def approve(self, principal: ControlPrincipal, command: HumanApprovalCommand) -> CommandReceipt:
        replay = self._replay(principal, command, "HUMAN_APPROVAL", CommandReceipt)
        if replay is not None:
            return replay
        self._authorize(
            principal,
            "HUMAN_APPROVAL",
            command.correlation_id,
            ControlRole.OWNER,
            ControlRole.APPROVER,
        )
        project, task = self._locked_scope(
            principal,
            command.project_id,
            command.task_id,
            correlation_id=command.correlation_id,
            command_type="HUMAN_APPROVAL",
        )
        if project.status not in {
            ProjectStatus.INTAKE,
            ProjectStatus.DISCOVERY,
            ProjectStatus.PLANNING,
        } or task.status not in {TaskStatus.BACKLOG, TaskStatus.WAITING_HUMAN}:
            self._reject(
                principal, command.correlation_id, "HUMAN_APPROVAL", "INVALID_STATE", project.id
            )
            raise ControlError(ControlErrorCode.CONFLICT)
        TaskStateMachine(self._session).transition(
            task,
            TaskStatus.READY,
            actor_type=AuditActorType.HUMAN,
            actor_id=principal.actor_id,
            reason="Authorized human approval",
            metadata={"evidence_id": command.evidence_id},
            correlation_id=command.correlation_id,
        )
        project.status = ProjectStatus.APPROVED
        result = CommandReceipt(
            command_id=command.command_id,
            correlation_id=command.correlation_id,
            project_id=project.id,
            result="APPROVED",
        )
        self._record_receipt(
            principal, command, "HUMAN_APPROVAL", result.model_dump(mode="json"), task_id=task.id
        )
        self._session.add(
            AuditEvent(
                actor_type=AuditActorType.HUMAN,
                actor_id=principal.actor_id,
                project_id=project.id,
                task_id=task.id,
                event_type="CONTROL_HUMAN_APPROVED",
                action="approve_project",
                result=AuditResult.SUCCEEDED,
                data={"evidence_id": command.evidence_id},
                correlation_id=command.correlation_id,
            )
        )
        self._accepted(principal, command.correlation_id, "HUMAN_APPROVAL", project.id, task.id)
        self._session.commit()
        return result

    def launch(
        self, principal: ControlPrincipal, command: LaunchWorkflowCommand
    ) -> WorkflowLaunchResult:
        replay = self._replay(principal, command, "WORKFLOW_LAUNCH", WorkflowLaunchResult)
        if replay is not None:
            return replay
        self._authorize(
            principal,
            "WORKFLOW_LAUNCH",
            command.correlation_id,
            ControlRole.OWNER,
            ControlRole.OPERATOR,
        )
        project, task = self._locked_scope(
            principal,
            command.project_id,
            command.task_id,
            correlation_id=command.correlation_id,
            command_type="WORKFLOW_LAUNCH",
        )
        if (
            project.status is not ProjectStatus.APPROVED
            or task.status is not TaskStatus.READY
            or task.assigned_agent_id is None
        ):
            self._reject(
                principal, command.correlation_id, "WORKFLOW_LAUNCH", "INVALID_STATE", project.id
            )
            raise ControlError(ControlErrorCode.CONFLICT)
        TaskStateMachine(self._session).transition(
            task,
            TaskStatus.ASSIGNED,
            actor_type=AuditActorType.HUMAN,
            actor_id=principal.actor_id,
            reason="Authorized Engineering V1 launch",
            correlation_id=command.correlation_id,
        )
        project.status = ProjectStatus.IN_PROGRESS
        run = AgentRun(
            agent_id=task.assigned_agent_id,
            task_id=task.id,
            status=PersistedRunStatus.PENDING,
        )
        self._session.add(run)
        self._session.flush()
        job = AgentRunJob(
            run_id=run.id,
            task_id=task.id,
            idempotency_key=command.idempotency_key,
            max_attempts=1,
            timeout_seconds=command.timeout_seconds,
            heartbeat_timeout_seconds=min(command.timeout_seconds, 30.0),
        )
        try:
            if not self._queue.enqueue_in_session(self._session, job):
                raise ControlError(ControlErrorCode.CONFLICT)
        except QueueFullError:
            self._session.rollback()
            raise ControlError(ControlErrorCode.QUEUE_FULL) from None
        result = WorkflowLaunchResult(
            project_id=project.id,
            task_id=task.id,
            run_id=run.id,
            queue_status=QueueStatus.QUEUED.value,
        )
        self._record_receipt(
            principal,
            command,
            "WORKFLOW_LAUNCH",
            result.model_dump(mode="json"),
            task_id=task.id,
            run_id=run.id,
        )
        self._accepted(
            principal, command.correlation_id, "WORKFLOW_LAUNCH", project.id, task.id, run.id
        )
        self._session.commit()
        return result

    def cancel(self, principal: ControlPrincipal, command: CancelWorkflowCommand) -> CommandReceipt:
        replay = self._replay(principal, command, "WORKFLOW_CANCEL", CommandReceipt)
        if replay is not None:
            return replay
        self._authorize(
            principal,
            "WORKFLOW_CANCEL",
            command.correlation_id,
            ControlRole.OWNER,
            ControlRole.OPERATOR,
        )
        self._require_scope(
            principal,
            command.project_id,
            correlation_id=command.correlation_id,
            command_type="WORKFLOW_CANCEL",
        )
        run = self._session.get(AgentRun, command.run_id)
        task = self._session.get(Task, run.task_id) if run is not None else None
        if run is None or task is None or task.project_id != command.project_id:
            raise ControlError(ControlErrorCode.NOT_FOUND)
        if not self._queue.cancel_in_session(self._session, run.id):
            raise ControlError(ControlErrorCode.CONFLICT)
        if task.status not in {TaskStatus.COMPLETED, TaskStatus.CANCELLED}:
            TaskStateMachine(self._session).transition(
                task,
                TaskStatus.CANCELLED,
                actor_type=AuditActorType.HUMAN,
                actor_id=principal.actor_id,
                reason="Authorized workflow cancellation",
                correlation_id=command.correlation_id,
            )
        project = self._session.get(Project, command.project_id)
        if project is not None:
            project.status = ProjectStatus.CANCELLED
        result = CommandReceipt(
            command_id=command.command_id,
            correlation_id=command.correlation_id,
            project_id=command.project_id,
            result="CANCELLED",
        )
        self._record_receipt(
            principal,
            command,
            "WORKFLOW_CANCEL",
            result.model_dump(mode="json"),
            task_id=task.id,
            run_id=run.id,
        )
        self._accepted(
            principal,
            command.correlation_id,
            "WORKFLOW_CANCEL",
            command.project_id,
            task.id,
            run.id,
        )
        self._session.commit()
        return result

    def close(self, principal: ControlPrincipal, command: CloseProjectCommand) -> CommandReceipt:
        replay = self._replay(principal, command, "PROJECT_CLOSE", CommandReceipt)
        if replay is not None:
            return replay
        self._authorize(
            principal,
            "PROJECT_CLOSE",
            command.correlation_id,
            ControlRole.OWNER,
            ControlRole.APPROVER,
        )
        self._require_scope(
            principal,
            command.project_id,
            correlation_id=command.correlation_id,
            command_type="PROJECT_CLOSE",
        )
        project = self._session.get(Project, command.project_id)
        if project is None:
            raise ControlError(ControlErrorCode.NOT_FOUND)
        approved = self._has_event(project.id, "CONTROL_HUMAN_APPROVED")
        qa = self._latest_event(project.id, "QA_COMPLETED")
        security = self._latest_event(project.id, "SECURITY_COMPLETED")
        delivery_complete = not bool(
            self._session.scalar(
                select(Task.id)
                .where(
                    Task.project_id == project.id,
                    Task.status != TaskStatus.COMPLETED,
                )
                .limit(1)
            )
        )
        ProjectClosureWorkflow(SQLAlchemyProjectClosureStore(self._session)).run(
            ProjectClosureRequest(
                project_id=project.id,
                preconditions=ClosurePreconditions(
                    client_approved=approved,
                    delivery_complete=delivery_complete,
                    qa_approved=qa is not None and qa.data.get("decision") == "PASSED",
                    security_approved=security is not None
                    and security.data.get("decision") == "PASS",
                ),
                retrospective=f"Closure authorized by {command.evidence_id}.",
                lessons=LessonsLearnedInput(
                    project_id=str(project.id),
                    project_title=project.name,
                    evidence=(),
                ),
                correlation_id=command.correlation_id,
            )
        )
        result = CommandReceipt(
            command_id=command.command_id,
            correlation_id=command.correlation_id,
            project_id=project.id,
            result="ARCHIVED",
        )
        self._record_receipt(principal, command, "PROJECT_CLOSE", result.model_dump(mode="json"))
        self._accepted(principal, command.correlation_id, "PROJECT_CLOSE", project.id)
        self._session.commit()
        return result

    def status(self, principal: ControlPrincipal, query: WorkflowStatusQuery) -> WorkflowStatus:
        require_any_role(principal, *tuple(ControlRole))
        self._require_scope(principal, query.project_id)
        project = self._session.get(Project, query.project_id)
        if project is None:
            raise ControlError(ControlErrorCode.NOT_FOUND)
        task = self._session.scalar(
            select(Task)
            .where(Task.project_id == project.id)
            .order_by(Task.created_at.desc())
            .limit(1)
        )
        run = (
            None
            if task is None
            else self._session.scalar(
                select(AgentRun)
                .where(AgentRun.task_id == task.id)
                .order_by(AgentRun.created_at.desc())
                .limit(1)
            )
        )
        queue_status = (
            None
            if run is None
            else self._session.scalar(
                select(ExecutionQueueJob.status).where(ExecutionQueueJob.run_id == run.id)
            )
        )
        qa = self._latest_event(project.id, "QA_COMPLETED")
        security = self._latest_event(project.id, "SECURITY_COMPLETED")
        merge = self._session.scalar(
            select(AuditEvent)
            .where(
                AuditEvent.project_id == project.id,
                AuditEvent.event_type == "GIT_OPERATION_COMPLETED",
                AuditEvent.action == "validate_merge_requirements",
            )
            .order_by(AuditEvent.created_at.desc())
            .limit(1)
        )
        return WorkflowStatus(
            project_id=project.id,
            project_status=project.status.value,
            task_id=None if task is None else task.id,
            task_status=None if task is None else task.status.value,
            run_id=None if run is None else run.id,
            queue_status=None if queue_status is None else queue_status.value,
            assigned_agent_id=None if task is None else task.assigned_agent_id,
            qa_status=self._decision(qa),
            security_status=self._decision(security),
            human_approval=self._has_event(project.id, "CONTROL_HUMAN_APPROVED"),
            merge_gate_status=self._safe_data(merge, "merge_decision"),
            terminal=project.status
            in {ProjectStatus.COMPLETED, ProjectStatus.ARCHIVED, ProjectStatus.CANCELLED},
        )

    def _authorize(
        self,
        principal: ControlPrincipal,
        command_type: str,
        correlation_id: UUID,
        *roles: ControlRole,
    ) -> None:
        try:
            require_any_role(principal, *roles)
        except ControlError:
            self._reject(principal, correlation_id, command_type, "FORBIDDEN")
            raise

    def _locked_scope(
        self,
        principal: ControlPrincipal,
        project_id: UUID,
        task_id: UUID,
        *,
        correlation_id: UUID,
        command_type: str,
    ) -> tuple[Project, Task]:
        self._require_scope(
            principal,
            project_id,
            correlation_id=correlation_id,
            command_type=command_type,
        )
        project = self._session.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        task = self._session.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if project is None or task is None or task.project_id != project.id:
            raise ControlError(ControlErrorCode.NOT_FOUND)
        return project, task

    def _require_scope(
        self,
        principal: ControlPrincipal,
        project_id: UUID,
        *,
        correlation_id: UUID | None = None,
        command_type: str | None = None,
    ) -> None:
        company_id = self._session.scalar(
            select(ControlProjectScope.company_id).where(
                ControlProjectScope.project_id == project_id
            )
        )
        if company_id is None:
            if command_type is not None:
                self._reject(
                    principal,
                    correlation_id,
                    command_type,
                    "NOT_FOUND",
                )
            raise ControlError(ControlErrorCode.NOT_FOUND)
        if company_id != principal.company_id:
            if command_type is not None:
                self._reject(
                    principal,
                    correlation_id,
                    command_type,
                    "FORBIDDEN_SCOPE",
                    project_id,
                )
            raise ControlError(ControlErrorCode.FORBIDDEN)

    def _replay[ResultT: BaseModel](
        self,
        principal: ControlPrincipal,
        command: PersistableCommand,
        command_type: str,
        model: type[ResultT],
    ) -> ResultT | None:
        receipt = self._session.scalar(
            select(ControlCommandReceipt).where(
                ControlCommandReceipt.company_id == principal.company_id,
                ControlCommandReceipt.idempotency_key == command.idempotency_key,
            )
        )
        if receipt is None:
            return None
        if receipt.command_id != command.command_id or receipt.command_type != command_type:
            raise ControlError(ControlErrorCode.CONFLICT)
        return model.model_validate({**receipt.response_data, "replayed": True})

    def _record_receipt(
        self,
        principal: ControlPrincipal,
        command: PersistableCommand,
        command_type: str,
        response: dict[str, object],
        *,
        task_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> None:
        self._session.add(
            ControlCommandReceipt(
                command_id=command.command_id,
                correlation_id=command.correlation_id,
                idempotency_key=command.idempotency_key,
                command_type=command_type,
                company_id=principal.company_id,
                actor_id=principal.actor_id,
                project_id=response.get("project_id"),
                task_id=task_id,
                run_id=run_id,
                result=str(response.get("result", response.get("status", "ACCEPTED"))),
                response_data=response,
            )
        )

    def _accepted(
        self,
        principal: ControlPrincipal,
        correlation_id: UUID,
        command_type: str,
        project_id: UUID,
        task_id: UUID | None = None,
        run_id: UUID | None = None,
    ) -> None:
        self._session.add(
            AuditEvent(
                actor_type=AuditActorType.HUMAN,
                actor_id=principal.actor_id,
                project_id=project_id,
                task_id=task_id,
                agent_run_id=run_id,
                event_type="CONTROL_COMMAND_ACCEPTED",
                action="execute_control_command",
                result=AuditResult.SUCCEEDED,
                data={"command_type": command_type},
                correlation_id=correlation_id,
            )
        )

    def _reject(
        self,
        principal: ControlPrincipal,
        correlation_id: UUID | None,
        command_type: str,
        reason: str,
        project_id: UUID | None = None,
    ) -> None:
        self._session.add(
            AuditEvent(
                actor_type=AuditActorType.HUMAN,
                actor_id=principal.actor_id,
                project_id=project_id,
                event_type="CONTROL_COMMAND_REJECTED",
                action="reject_control_command",
                result=AuditResult.DENIED,
                data={"command_type": command_type, "reason": reason},
                correlation_id=correlation_id,
            )
        )
        self._session.commit()

    def _latest_event(self, project_id: UUID, event_type: str) -> AuditEvent | None:
        return self._session.scalar(
            select(AuditEvent)
            .where(AuditEvent.project_id == project_id, AuditEvent.event_type == event_type)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(1)
        )

    def _has_event(self, project_id: UUID, event_type: str) -> bool:
        return self._latest_event(project_id, event_type) is not None

    @staticmethod
    def _safe_data(event: AuditEvent | None, key: str) -> str | None:
        value = None if event is None else event.data.get(key)
        return value if isinstance(value, str) and len(value) <= 64 else None

    def _decision(self, event: AuditEvent | None) -> str | None:
        return self._safe_data(event, "decision")
