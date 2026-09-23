"""Tests for bounded AI Manager multi-agent coordination graphs."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from core.autonomy import (
    CommunicationPolicyEvaluator,
    CommunicationPolicyGrant,
    CommunicationPolicyRequest,
    CommunicationPolicyResult,
)
from core.genome import CollaborationChannel, CollaborationDataClass
from core.manager import (
    CoordinationGraphDisposition,
    CoordinationGraphReason,
    ManagerCoordinationGraphPlanner,
    ManagerCoordinationGraphRequest,
)


def _allowed_result(
    *,
    project_id: UUID,
    task_id: UUID,
    sender_id: UUID,
    recipient_id: UUID | None,
    channel: CollaborationChannel,
    now: datetime,
) -> CommunicationPolicyResult:
    delegation_id = uuid4()
    request = CommunicationPolicyRequest(
        communication_id=uuid4(),
        project_id=project_id,
        task_id=task_id,
        sender_agent_id=sender_id,
        recipient_agent_id=recipient_id,
        purpose="review:handoff",
        channel=channel,
        data_classification=CollaborationDataClass.INTERNAL,
        delegation_id=delegation_id,
        required_scope="communication:review",
        requested_at=now,
    )
    grant = CommunicationPolicyGrant(
        policy_id=uuid4(),
        policy_version="communication-policy-v1",
        project_id=project_id,
        task_id=task_id,
        sender_agent_id=sender_id,
        recipient_agent_id=recipient_id,
        allowed_purposes=(request.purpose,),
        allowed_channels=(channel,),
        allowed_data_classes=(request.data_classification,),
        delegation_id=delegation_id,
        allowed_scopes=(request.required_scope,),
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=5),
        evidence_reference=f"audit://communication-policy/{request.communication_id}",
    )
    return CommunicationPolicyEvaluator().evaluate(request, grant=grant)


def test_policy_denied_edge_cannot_enter_a_coordination_graph() -> None:
    now = datetime.now(UTC)
    project_id, task_id = uuid4(), uuid4()
    policy_result = CommunicationPolicyEvaluator().evaluate(
        CommunicationPolicyRequest(
            communication_id=uuid4(),
            project_id=project_id,
            task_id=task_id,
            sender_agent_id=uuid4(),
            recipient_agent_id=uuid4(),
            purpose="review:handoff",
            channel=CollaborationChannel.INTERNAL_EVENT,
            data_classification=CollaborationDataClass.INTERNAL,
            delegation_id=uuid4(),
            required_scope="communication:review",
            requested_at=now,
        ),
        grant=None,
    )

    result = ManagerCoordinationGraphPlanner().plan(
        ManagerCoordinationGraphRequest(
            project_id=project_id,
            task_id=task_id,
            graph_version=1,
            policy_results=(policy_result,),
            proposed_at=now,
        )
    )

    assert result.disposition is CoordinationGraphDisposition.REJECT
    assert result.reasons == (CoordinationGraphReason.POLICY_DENIED,)
    assert result.draft is None
    assert result.may_authorize_communication is False
    assert result.may_send_messages is False


def test_admitted_edges_produce_a_stable_metadata_only_graph_draft() -> None:
    now = datetime.now(UTC)
    project_id, task_id = uuid4(), uuid4()
    agent_a, agent_b = uuid4(), uuid4()
    internal = _allowed_result(
        project_id=project_id,
        task_id=task_id,
        sender_id=agent_a,
        recipient_id=agent_b,
        channel=CollaborationChannel.INTERNAL_EVENT,
        now=now,
    )
    external = _allowed_result(
        project_id=project_id,
        task_id=task_id,
        sender_id=agent_b,
        recipient_id=None,
        channel=CollaborationChannel.EXTERNAL,
        now=now,
    )

    result = ManagerCoordinationGraphPlanner().plan(
        ManagerCoordinationGraphRequest(
            project_id=project_id,
            task_id=task_id,
            graph_version=1,
            policy_results=(internal, external),
            proposed_at=now,
        )
    )

    assert result.disposition is CoordinationGraphDisposition.PROPOSE
    assert result.reasons == ()
    assert result.draft is not None
    assert result.draft.agent_ids == tuple(sorted((agent_a, agent_b), key=str))
    assert tuple(edge.communication_id for edge in result.draft.edges) == (
        internal.request.communication_id,
        external.request.communication_id,
    )
    assert result.draft.external_edge_count == 1
    assert result.requires_permission_check is True
    assert result.may_persist_graph is False


def test_self_communication_is_rejected_even_when_policy_admitted_it() -> None:
    now = datetime.now(UTC)
    project_id, task_id, agent_id = uuid4(), uuid4(), uuid4()
    admitted = _allowed_result(
        project_id=project_id,
        task_id=task_id,
        sender_id=agent_id,
        recipient_id=agent_id,
        channel=CollaborationChannel.INTERNAL_EVENT,
        now=now,
    )

    result = ManagerCoordinationGraphPlanner().plan(
        ManagerCoordinationGraphRequest(
            project_id=project_id,
            task_id=task_id,
            graph_version=1,
            policy_results=(admitted,),
            proposed_at=now,
        )
    )

    assert result.disposition is CoordinationGraphDisposition.REJECT
    assert result.reasons == (CoordinationGraphReason.SELF_COMMUNICATION,)
    assert result.draft is None
