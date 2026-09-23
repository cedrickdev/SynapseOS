"""Tests for fail-closed Governor communication-policy enforcement."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from core.autonomy import (
    CommunicationPolicyDisposition,
    CommunicationPolicyEvaluator,
    CommunicationPolicyGrant,
    CommunicationPolicyReason,
    CommunicationPolicyRequest,
)
from core.genome import CollaborationChannel, CollaborationDataClass
from core.security import SecurityDecision


def _valid_policy_pair() -> tuple[CommunicationPolicyGrant, CommunicationPolicyRequest]:
    now = datetime.now(UTC)
    project_id, task_id, sender_id, recipient_id = uuid4(), uuid4(), uuid4(), uuid4()
    delegation_id = uuid4()
    return (
        CommunicationPolicyGrant(
            policy_id=uuid4(),
            policy_version="communication-policy-v1",
            project_id=project_id,
            task_id=task_id,
            sender_agent_id=sender_id,
            recipient_agent_id=recipient_id,
            allowed_purposes=("review:handoff",),
            allowed_channels=(CollaborationChannel.INTERNAL_EVENT,),
            allowed_data_classes=(CollaborationDataClass.INTERNAL,),
            delegation_id=delegation_id,
            allowed_scopes=("communication:review",),
            valid_from=now - timedelta(minutes=1),
            expires_at=now + timedelta(minutes=5),
            evidence_reference="audit://communication-policy/grant-2",
        ),
        CommunicationPolicyRequest(
            communication_id=uuid4(),
            project_id=project_id,
            task_id=task_id,
            sender_agent_id=sender_id,
            recipient_agent_id=recipient_id,
            purpose="review:handoff",
            channel=CollaborationChannel.INTERNAL_EVENT,
            data_classification=CollaborationDataClass.INTERNAL,
            delegation_id=delegation_id,
            required_scope="communication:review",
            requested_at=now,
        ),
    )


def test_external_channel_cannot_send_a_data_class_omitted_from_policy() -> None:
    now = datetime.now(UTC)
    project_id, task_id, sender_id, delegation_id = uuid4(), uuid4(), uuid4(), uuid4()
    policy = CommunicationPolicyGrant(
        policy_id=uuid4(),
        policy_version="communication-policy-v1",
        project_id=project_id,
        task_id=task_id,
        sender_agent_id=sender_id,
        recipient_agent_id=None,
        allowed_purposes=("customer:update",),
        allowed_channels=(CollaborationChannel.EXTERNAL,),
        allowed_data_classes=(CollaborationDataClass.PUBLIC,),
        delegation_id=delegation_id,
        allowed_scopes=("communication:customer",),
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=5),
        evidence_reference="audit://communication-policy/grant-1",
    )
    request = CommunicationPolicyRequest(
        communication_id=uuid4(),
        project_id=project_id,
        task_id=task_id,
        sender_agent_id=sender_id,
        recipient_agent_id=None,
        purpose="customer:update",
        channel=CollaborationChannel.EXTERNAL,
        data_classification=CollaborationDataClass.CONFIDENTIAL,
        delegation_id=delegation_id,
        required_scope="communication:customer",
        requested_at=now,
    )

    result = CommunicationPolicyEvaluator().evaluate(request, grant=policy)

    assert result.disposition is CommunicationPolicyDisposition.DENY
    assert result.reasons == (CommunicationPolicyReason.DATA_CLASS_NOT_AUTHORIZED,)
    assert result.requires_permission_check is True
    assert result.may_authorize_communication is False
    assert result.may_execute is False


def test_matching_policy_only_proceeds_to_authoritative_permission_check() -> None:
    policy, request = _valid_policy_pair()

    result = CommunicationPolicyEvaluator().evaluate(request, grant=policy)

    assert result.disposition is CommunicationPolicyDisposition.PROCEED_TO_PERMISSION_CHECK
    assert result.reasons == ()
    assert result.requires_permission_check is True
    assert result.may_authorize_communication is False
    assert result.may_mutate_permissions is False


def test_missing_policy_is_denied_by_default() -> None:
    _, request = _valid_policy_pair()

    result = CommunicationPolicyEvaluator().evaluate(request, grant=None)

    assert result.disposition is CommunicationPolicyDisposition.DENY
    assert result.reasons == (CommunicationPolicyReason.NO_ACTIVE_POLICY,)


def test_security_veto_blocks_an_otherwise_matching_policy() -> None:
    policy, request = _valid_policy_pair()

    result = CommunicationPolicyEvaluator().evaluate(
        request,
        grant=policy,
        security_decision=SecurityDecision.BLOCK,
    )

    assert result.disposition is CommunicationPolicyDisposition.DENY
    assert result.reasons == (CommunicationPolicyReason.SECURITY_VETO,)


def test_policy_is_bound_to_delegation_and_scope() -> None:
    policy, request = _valid_policy_pair()
    mismatched = request.model_copy(
        update={
            "delegation_id": uuid4(),
            "required_scope": "communication:production",
        }
    )

    result = CommunicationPolicyEvaluator().evaluate(mismatched, grant=policy)

    assert result.disposition is CommunicationPolicyDisposition.DENY
    assert result.reasons == (
        CommunicationPolicyReason.DELEGATION_NOT_AUTHORIZED,
        CommunicationPolicyReason.SCOPE_NOT_AUTHORIZED,
    )
