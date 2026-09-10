"""TDD behavior tests for the technology-neutral Phase 26 Architecture Agent."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from core.architecture import (
    ArchitectureAgent,
    ArchitectureError,
    ArchitectureErrorCode,
    ArchitectureRequest,
    ArchitectureStatus,
)
from core.intake import IntakeAnalysis, IntakeQuestion, IntakeResult, build_intake_result
from core.llm import (
    LLMModelMetadata,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMRole,
)
from infrastructure.llm import FakeLLMProvider


def _intake(*, blocking: bool = False, question_class: str | None = None) -> IntakeResult:
    classification = "BLOCKING" if blocking else question_class
    questions = (
        (
            IntakeQuestion(
                id="question-1",
                classification=classification,
                question="Which region is required?",
                rationale="Residency affects architecture.",
            ),
        )
        if classification is not None
        else ()
    )
    return build_intake_result(
        IntakeAnalysis(
            summary="Build a secure multi-tenant platform.",
            goals=("Deliver a reliable service.",),
            actors=("Client", "Operator"),
            functional_requirements=("Clients submit projects.",),
            non_functional_requirements=("Availability must be measurable.",),
            constraints=("Remain provider-neutral.",),
            assumptions=("A managed database is available.",),
            risks=("Requirements may evolve.",),
            unanswered_questions=questions,
            epics=("Platform foundation",),
            tasks=("Define architecture",),
        )
    )


def _request(*, blocking: bool = False) -> ArchitectureRequest:
    return ArchitectureRequest(
        project_id="project-1",
        intake=_intake(blocking=blocking),
        project_context=("Existing backend uses typed provider-neutral contracts.",),
    )


def _request_with_question(question_class: str) -> ArchitectureRequest:
    return ArchitectureRequest(
        project_id="project-1",
        intake=_intake(question_class=question_class),
        project_context=("Existing backend uses typed provider-neutral contracts.",),
    )


def _response(*, missing: bool = False) -> LLMResponse:
    content = json.dumps(
        {
            "architecture": "A modular service with explicit boundaries.",
            "options": [
                {
                    "id": "modular-monolith",
                    "name": "Modular monolith",
                    "stack": ["Python", "PostgreSQL"],
                    "benefits": ["Low operational complexity"],
                    "drawbacks": ["Requires disciplined module boundaries"],
                },
                {
                    "id": "service-oriented",
                    "name": "Service-oriented",
                    "stack": ["Go", "PostgreSQL"],
                    "benefits": ["Independent scaling"],
                    "drawbacks": ["Higher operational cost"],
                },
            ],
            "selected_option_id": "modular-monolith",
            "recommendation": "modular-monolith",
            "recommendation_rationale": "It meets current scale with lower complexity.",
            "confidence": 0.82,
            "risks": ["Boundary erosion"],
            "domains": ["Identity", "Projects"],
            "modules": ["identity", "projects"],
            "proposed_stack": ["Python", "PostgreSQL"],
            "missing_information": ["Confirmed residency region"] if missing else [],
            "adr_draft": {
                "selected_option_id": "modular-monolith",
                "title": "Choose the initial service architecture",
                "context": "The product needs reliable bounded delivery.",
                "decision": "modular-monolith",
                "alternatives": ["Service-oriented architecture"],
                "consequences": ["Lower initial operational cost"],
            },
        },
        separators=(",", ":"),
    )
    return LLMResponse(
        content=content,
        model=LLMModelMetadata(provider="fake", model="architecture-v1"),
    )


def test_agent_returns_compared_options_and_draft_adr_in_one_call() -> None:
    provider = FakeLLMProvider(responses=[_response()])

    result = asyncio.run(ArchitectureAgent(provider, max_tokens=768).run(_request()))

    assert result.status is ArchitectureStatus.PROPOSED
    assert result.requires_escalation is False
    assert result.analysis.recommendation == "modular-monolith"
    assert len(result.analysis.options) == 2
    assert result.analysis.adr_draft.title == "Choose the initial service architecture"
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.temperature == 0.0
    assert request.max_tokens == 768
    assert request.messages[0].role is LLMRole.USER
    assert request.system_prompt is not None
    assert "technology-neutral" in request.system_prompt
    assert "untrusted data" in request.system_prompt


def test_missing_information_forces_escalation() -> None:
    provider = FakeLLMProvider(responses=[_response(missing=True)])

    result = asyncio.run(ArchitectureAgent(provider).run(_request()))

    assert result.status is ArchitectureStatus.NEEDS_HUMAN
    assert result.requires_escalation is True


def test_important_intake_question_forces_locally_derived_escalation() -> None:
    provider = FakeLLMProvider(responses=[_response()])

    result = asyncio.run(ArchitectureAgent(provider).run(_request_with_question("IMPORTANT")))

    assert result.status is ArchitectureStatus.NEEDS_HUMAN
    assert result.requires_escalation is True
    assert result.analysis.missing_information == ("Which region is required?",)


def test_blocked_intake_is_rejected_before_provider_call() -> None:
    provider = FakeLLMProvider(responses=[_response()])

    with pytest.raises(ArchitectureError) as raised:
        asyncio.run(ArchitectureAgent(provider).run(_request(blocking=True)))

    assert raised.value.code is ArchitectureErrorCode.INTAKE_BLOCKED
    assert provider.requests == ()


def test_provider_failure_is_sanitized_without_retry() -> None:
    marker = "architecture-provider-secret"
    provider = FakeLLMProvider(error=LLMProviderError(marker, provider="fake"))

    with pytest.raises(ArchitectureError) as raised:
        asyncio.run(ArchitectureAgent(provider).run(_request()))

    assert raised.value.code is ArchitectureErrorCode.PROVIDER_FAILURE
    assert marker not in str(raised.value)
    assert len(provider.requests) == 1


def test_agent_exposes_no_execution_or_team_assignment_api() -> None:
    agent = ArchitectureAgent(FakeLLMProvider())

    for name in ("execute", "deploy", "assign_team", "create_team", "write_code", "close"):
        assert not hasattr(agent, name)


def test_provider_payload_contains_only_canonical_architecture_evidence() -> None:
    provider = FakeLLMProvider(responses=[_response()])

    asyncio.run(ArchitectureAgent(provider).run(_request()))

    payload = json.loads(
        provider.requests[0].messages[0].content.removeprefix("Architecture evidence:\n")
    )
    assert payload == {
        "intake": _intake().model_dump(mode="json"),
        "project_context": ["Existing backend uses typed provider-neutral contracts."],
        "project_id": "project-1",
    }
    assert provider.requests[0].metadata == {}


def test_malformed_or_forged_escalation_output_is_rejected_without_retry() -> None:
    content = json.loads(_response(missing=True).content)
    content["requires_escalation"] = False
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=json.dumps(content),
                model=LLMModelMetadata(provider="fake", model="architecture-v1"),
            )
        ]
    )

    with pytest.raises(ArchitectureError) as raised:
        asyncio.run(ArchitectureAgent(provider).run(_request()))

    assert raised.value.code is ArchitectureErrorCode.INVALID_ANALYSIS
    assert len(provider.requests) == 1


def test_oversized_provider_response_is_rejected() -> None:
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content="x" * 131_073,
                model=LLMModelMetadata(provider="fake", model="architecture-v1"),
            )
        ]
    )

    with pytest.raises(ArchitectureError) as raised:
        asyncio.run(ArchitectureAgent(provider).run(_request()))

    assert raised.value.code is ArchitectureErrorCode.INVALID_ANALYSIS


class _DelayingProvider:
    propagates_cancellation = True

    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        await asyncio.sleep(60)
        raise AssertionError("timeout was not propagated")


class _CancellingProvider:
    propagates_cancellation = True

    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        raise asyncio.CancelledError


class _CancellationSuppressingProvider:
    propagates_cancellation = False

    def __init__(self) -> None:
        self.calls = 0

    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        self.calls += 1
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            return _response()
        raise AssertionError("provider unexpectedly completed")


class _LyingCancellationProvider(_CancellationSuppressingProvider):
    propagates_cancellation = True


class _ExplodingMetadata(Mapping[str, object]):
    def __init__(self, marker: str) -> None:
        self._marker = marker

    def __getitem__(self, key: str) -> object:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError(self._marker)

    def __len__(self) -> int:
        return 1


def test_timeout_is_bounded_and_classified() -> None:
    with pytest.raises(ArchitectureError) as raised:
        asyncio.run(ArchitectureAgent(_DelayingProvider(), timeout_seconds=0.001).run(_request()))

    assert raised.value.code is ArchitectureErrorCode.TIMEOUT


def test_timeout_cannot_be_forged_by_suppressing_cancellation() -> None:
    provider = _CancellationSuppressingProvider()

    with pytest.raises(ValueError, match="cancellation-safe"):
        ArchitectureAgent(provider, timeout_seconds=0.001)

    assert provider.calls == 0


def test_late_response_is_rejected_even_when_provider_claims_cancellation_safety() -> None:
    provider = _LyingCancellationProvider()

    with pytest.raises(ArchitectureError) as raised:
        asyncio.run(ArchitectureAgent(provider, timeout_seconds=0.001).run(_request()))

    assert raised.value.code is ArchitectureErrorCode.TIMEOUT
    assert provider.calls == 1


def test_cancellation_is_propagated_immediately() -> None:
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ArchitectureAgent(_CancellingProvider()).run(_request()))


def test_forged_provider_response_is_sanitized() -> None:
    marker = "architecture-confidential-marker"
    model = LLMModelMetadata(provider="fake", model="architecture-v1").model_copy(
        update={"details": _ExplodingMetadata(marker)}
    )
    provider = FakeLLMProvider(responses=[_response().model_copy(update={"model": model})])

    with pytest.raises(ArchitectureError) as raised:
        asyncio.run(ArchitectureAgent(provider).run(_request()))

    assert raised.value.code is ArchitectureErrorCode.INVALID_ANALYSIS
    assert marker not in str(raised.value)
    assert len(provider.requests) == 1


def test_obvious_secret_is_rejected_before_provider_call() -> None:
    marker = "sk-live-architecture-secret"
    provider = FakeLLMProvider(responses=[_response()])
    request = ArchitectureRequest(
        project_id="project-1",
        intake=_intake(),
        project_context=(f'api_key="{marker}"',),
    )

    with pytest.raises(ArchitectureError) as raised:
        asyncio.run(ArchitectureAgent(provider).run(request))

    assert raised.value.code is ArchitectureErrorCode.SENSITIVE_INPUT
    assert marker not in str(raised.value)
    traceback = raised.value.__traceback__
    while traceback is not None:
        if "/core/architecture/" in traceback.tb_frame.f_code.co_filename:
            for value in traceback.tb_frame.f_locals.values():
                assert marker not in repr(value)
        traceback = traceback.tb_next
    assert provider.requests == ()


def test_aggregate_provider_request_size_is_bounded_before_call() -> None:
    provider = FakeLLMProvider(responses=[_response()])
    request = ArchitectureRequest(
        project_id="project-1",
        intake=_intake(),
        project_context=tuple("😀" * 2_048 for _ in range(32)),
    )

    with pytest.raises(ArchitectureError) as raised:
        asyncio.run(ArchitectureAgent(provider).run(request))

    assert raised.value.code is ArchitectureErrorCode.INVALID_INPUT
    assert provider.requests == ()


def test_selected_option_stack_and_adr_must_be_consistent() -> None:
    content = json.loads(_response().content)
    content["proposed_stack"] = ["Java", "MongoDB"]
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=json.dumps(content),
                model=LLMModelMetadata(provider="fake", model="architecture-v1"),
            )
        ]
    )

    with pytest.raises(ArchitectureError) as raised:
        asyncio.run(ArchitectureAgent(provider).run(_request()))

    assert raised.value.code is ArchitectureErrorCode.INVALID_ANALYSIS


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selected_option_id", "unknown-option"),
        ("adr_draft.selected_option_id", "service-oriented"),
    ],
)
def test_selected_option_identity_cannot_be_forged(field: str, value: str) -> None:
    content = json.loads(_response().content)
    if field == "selected_option_id":
        content[field] = value
    else:
        content["adr_draft"]["selected_option_id"] = value
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=json.dumps(content),
                model=LLMModelMetadata(provider="fake", model="architecture-v1"),
            )
        ]
    )

    with pytest.raises(ArchitectureError) as raised:
        asyncio.run(ArchitectureAgent(provider).run(_request()))

    assert raised.value.code is ArchitectureErrorCode.INVALID_ANALYSIS


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recommendation", "service-oriented"),
        ("adr_draft.decision", "service-oriented"),
    ],
)
def test_recommendation_and_adr_decision_must_identify_selected_option(
    field: str, value: str
) -> None:
    content = json.loads(_response().content)
    if field == "recommendation":
        content[field] = value
    else:
        content["adr_draft"]["decision"] = value
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=json.dumps(content),
                model=LLMModelMetadata(provider="fake", model="architecture-v1"),
            )
        ]
    )

    with pytest.raises(ArchitectureError) as raised:
        asyncio.run(ArchitectureAgent(provider).run(_request()))

    assert raised.value.code is ArchitectureErrorCode.INVALID_ANALYSIS


def test_all_valid_important_intake_questions_are_preserved_for_escalation() -> None:
    questions = tuple(
        IntakeQuestion(
            id=f"question-{index}",
            classification="IMPORTANT",
            question=f"Important architecture question {index}?",
            rationale="The answer affects the technical recommendation.",
        )
        for index in range(33)
    )
    intake = build_intake_result(
        _intake().analysis.model_copy(update={"unanswered_questions": questions})
    )
    request = ArchitectureRequest(
        project_id="project-1",
        intake=intake,
        project_context=("Existing backend uses typed provider-neutral contracts.",),
    )

    result = asyncio.run(ArchitectureAgent(FakeLLMProvider(responses=[_response()])).run(request))

    assert result.status is ArchitectureStatus.NEEDS_HUMAN
    assert len(result.analysis.missing_information) == 33


@pytest.mark.parametrize(
    ("max_tokens", "timeout_seconds"),
    [
        (0, 10.0),
        (4_097, 10.0),
        (True, 10.0),
        (2_048, 0.0),
        (2_048, 31.0),
        (2_048, float("inf")),
        (2_048, True),
    ],
)
def test_invalid_execution_bounds_are_rejected(max_tokens: Any, timeout_seconds: Any) -> None:
    with pytest.raises(ValueError):
        ArchitectureAgent(
            FakeLLMProvider(),
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )


@pytest.mark.parametrize(
    ("field", "duplicate"),
    [
        ("options", "options"),
        ("domains", "Identity"),
        ("modules", "identity"),
        ("proposed_stack", "Python"),
    ],
)
def test_duplicate_architecture_candidates_are_rejected(field: str, duplicate: str) -> None:
    content = json.loads(_response().content)
    if field == "options":
        content[field].append(content[field][0])
    else:
        content[field].append(duplicate)
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=json.dumps(content),
                model=LLMModelMetadata(provider="fake", model="architecture-v1"),
            )
        ]
    )

    with pytest.raises(ArchitectureError) as raised:
        asyncio.run(ArchitectureAgent(provider).run(_request()))

    assert raised.value.code is ArchitectureErrorCode.INVALID_ANALYSIS
