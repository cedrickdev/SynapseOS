"""TDD behavior and safety tests for the Phase 27 DomainDecomposer."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from core.architecture import (
    ADRDraft,
    ArchitectureAnalysis,
    ArchitectureOption,
    ArchitectureResult,
    build_architecture_result,
)
from core.domain_decomposition import (
    DomainDecomposer,
    DomainDecompositionError,
    DomainDecompositionErrorCode,
    DomainDecompositionRequest,
)
from core.intake import IntakeAnalysis, IntakeResult, build_intake_result
from core.llm import LLMModelMetadata, LLMProviderError, LLMRequest, LLMResponse, LLMRole
from infrastructure.llm import FakeLLMProvider


def _intake(summary: str = "Build a commerce platform.") -> IntakeResult:
    return build_intake_result(
        IntakeAnalysis(
            summary=summary,
            goals=("Deliver the client product.",),
            actors=("Customer", "Operator"),
            functional_requirements=("Users complete domain workflows.",),
            non_functional_requirements=("Domain boundaries remain auditable.",),
            constraints=("Remain provider-neutral.",),
            assumptions=("The architecture proposal is approved.",),
            risks=("Cross-domain coupling may grow.",),
            unanswered_questions=(),
            epics=("Domain delivery",),
            tasks=("Decompose business workstreams",),
        )
    )


def _architecture(
    *,
    blocked: bool = False,
    domains: tuple[str, ...] = ("Identity", "Catalog", "Orders"),
) -> ArchitectureResult:
    option = ArchitectureOption(
        id="modular-monolith",
        name="Modular monolith",
        stack=("Python", "PostgreSQL"),
        benefits=("Explicit boundaries",),
        drawbacks=("Requires boundary discipline",),
    )
    analysis = ArchitectureAnalysis(
        architecture="A modular architecture with domain boundaries.",
        options=(
            option,
            ArchitectureOption(
                id="service-oriented",
                name="Service-oriented",
                stack=("Go", "PostgreSQL"),
                benefits=("Independent scaling",),
                drawbacks=("Operational complexity",),
            ),
        ),
        selected_option_id=option.id,
        recommendation=option.id,
        recommendation_rationale="Current scale favors lower operational complexity.",
        confidence=0.84,
        risks=("Boundary erosion",),
        domains=domains,
        modules=tuple(domain.casefold().replace(" ", "-") for domain in domains),
        proposed_stack=option.stack,
        missing_information=(("Confirm regional ownership.",) if blocked else ()),
        adr_draft=ADRDraft(
            selected_option_id=option.id,
            title="Select the initial architecture",
            context="The project needs bounded delivery.",
            decision=option.id,
            alternatives=("Service-oriented",),
            consequences=("Lower initial complexity",),
        ),
    )
    return build_architecture_result(analysis)


def _request(*, blocked: bool = False, summary: str | None = None) -> DomainDecompositionRequest:
    selected_summary = summary or "Build a commerce platform."
    domains = (
        ("Data Ingestion", "Reporting")
        if "analytics" in selected_summary
        else (
            ("Messaging", "Notifications")
            if "communication" in selected_summary
            else ("Identity", "Catalog", "Orders")
        )
    )
    return DomainDecompositionRequest(
        project_id="project-1",
        intake=_intake(selected_summary),
        architecture=_architecture(blocked=blocked, domains=domains),
    )


def _response(workstreams: list[dict[str, object]] | None = None) -> LLMResponse:
    selected = workstreams or [
        {
            "id": "identity",
            "name": "Identity",
            "scope_kind": "DOMAIN",
            "purpose": "Own customer identity and access workflows.",
            "source_domains": ["Identity"],
            "responsibilities": ["Authentication", "Account lifecycle"],
            "required_capabilities": ["identity.design", "security.authentication"],
            "dependencies": [],
        },
        {
            "id": "catalog",
            "name": "Catalog",
            "scope_kind": "DOMAIN",
            "purpose": "Own product discovery and product information.",
            "source_domains": ["Catalog"],
            "responsibilities": ["Product data", "Product discovery"],
            "required_capabilities": ["catalog.modeling", "search.design"],
            "dependencies": [],
        },
        {
            "id": "orders",
            "name": "Orders",
            "scope_kind": "DOMAIN",
            "purpose": "Own purchase lifecycle workflows.",
            "source_domains": ["Orders"],
            "responsibilities": ["Checkout", "Order lifecycle"],
            "required_capabilities": ["orders.modeling", "transactions.design"],
            "dependencies": ["identity", "catalog"],
        },
    ]
    return LLMResponse(
        content=json.dumps(
            {
                "rationale": "Workstreams follow cohesive business capabilities.",
                "workstreams": selected,
            },
            separators=(",", ":"),
        ),
        model=LLMModelMetadata(provider="fake", model="domains-v1"),
    )


@pytest.mark.parametrize(
    ("summary", "workstreams", "expected_ids"),
    [
        ("Build a commerce platform.", None, ("identity", "catalog", "orders")),
        (
            "Build an analytics platform.",
            [
                {
                    "id": "data-ingestion",
                    "name": "Data Ingestion",
                    "scope_kind": "SERVICE",
                    "purpose": "Own reliable source ingestion.",
                    "source_domains": ["Data Ingestion"],
                    "responsibilities": ["Source connectors"],
                    "required_capabilities": ["data.ingestion"],
                    "dependencies": [],
                },
                {
                    "id": "reporting",
                    "name": "Reporting",
                    "scope_kind": "DOMAIN",
                    "purpose": "Own analytical reports.",
                    "source_domains": ["Reporting"],
                    "responsibilities": ["Report generation"],
                    "required_capabilities": ["analytics.reporting"],
                    "dependencies": ["data-ingestion"],
                },
            ],
            ("data-ingestion", "reporting"),
        ),
        (
            "Build a communication platform.",
            [
                {
                    "id": "messaging",
                    "name": "Messaging",
                    "scope_kind": "DOMAIN",
                    "purpose": "Own user conversations.",
                    "source_domains": ["Messaging"],
                    "responsibilities": ["Message lifecycle"],
                    "required_capabilities": ["messaging.design"],
                    "dependencies": [],
                },
                {
                    "id": "notifications",
                    "name": "Notifications",
                    "scope_kind": "SERVICE",
                    "purpose": "Own outbound delivery channels.",
                    "source_domains": ["Notifications"],
                    "responsibilities": ["Delivery routing"],
                    "required_capabilities": ["notifications.delivery"],
                    "dependencies": ["messaging"],
                },
            ],
            ("messaging", "notifications"),
        ),
    ],
)
def test_decomposer_builds_business_workstreams_for_multiple_specs(
    summary: str,
    workstreams: list[dict[str, object]] | None,
    expected_ids: tuple[str, ...],
) -> None:
    provider = FakeLLMProvider(responses=[_response(workstreams)])

    result = asyncio.run(
        DomainDecomposer(provider, max_tokens=768).decompose(_request(summary=summary))
    )

    assert tuple(item.id for item in result.workstreams) == expected_ids
    assert len(provider.requests) == 1
    provider_request = provider.requests[0]
    assert provider_request.max_tokens == 768
    assert provider_request.temperature == 0.0
    assert provider_request.messages[0].role is LLMRole.USER
    assert provider_request.system_prompt is not None
    assert "business domain or cohesive service" in provider_request.system_prompt
    assert "file, page, endpoint, or UI component" in provider_request.system_prompt


def test_dependencies_and_required_capabilities_are_preserved() -> None:
    result = asyncio.run(
        DomainDecomposer(FakeLLMProvider(responses=[_response()])).decompose(_request())
    )

    orders = result.workstreams[2]
    assert orders.dependencies == ("identity", "catalog")
    assert orders.required_capabilities == ("orders.modeling", "transactions.design")


def test_unresolved_architecture_is_rejected_before_provider_call() -> None:
    provider = FakeLLMProvider(responses=[_response()])

    with pytest.raises(DomainDecompositionError) as raised:
        asyncio.run(DomainDecomposer(provider).decompose(_request(blocked=True)))

    assert raised.value.code is DomainDecompositionErrorCode.ARCHITECTURE_BLOCKED
    assert provider.requests == ()


@pytest.mark.parametrize(
    "workstreams",
    [
        [
            {
                "id": "identity",
                "name": "Identity",
                "scope_kind": "DOMAIN",
                "purpose": "Own identity.",
                "source_domains": ["Identity"],
                "responsibilities": ["Accounts"],
                "required_capabilities": ["identity.design"],
                "dependencies": ["missing"],
            }
        ],
        [
            {
                "id": "identity",
                "name": "Identity",
                "scope_kind": "DOMAIN",
                "purpose": "Own identity.",
                "source_domains": ["Identity"],
                "responsibilities": ["Accounts"],
                "required_capabilities": ["identity.design"],
                "dependencies": ["orders"],
            },
            {
                "id": "orders",
                "name": "Orders",
                "scope_kind": "DOMAIN",
                "purpose": "Own orders.",
                "source_domains": ["Orders"],
                "responsibilities": ["Checkout"],
                "required_capabilities": ["orders.design"],
                "dependencies": ["identity"],
            },
        ],
    ],
)
def test_unknown_or_cyclic_dependencies_are_rejected(
    workstreams: list[dict[str, object]],
) -> None:
    provider = FakeLLMProvider(responses=[_response(workstreams)])

    with pytest.raises(DomainDecompositionError) as raised:
        asyncio.run(DomainDecomposer(provider).decompose(_request()))

    assert raised.value.code is DomainDecompositionErrorCode.INVALID_DECOMPOSITION
    assert len(provider.requests) == 1


def test_workstream_cannot_claim_an_unapproved_architecture_domain() -> None:
    content = json.loads(_response().content)
    content["workstreams"][0]["source_domains"] = ["Unapproved Domain"]
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=json.dumps(content),
                model=LLMModelMetadata(provider="fake", model="domains-v1"),
            )
        ]
    )

    with pytest.raises(DomainDecompositionError) as raised:
        asyncio.run(DomainDecomposer(provider).decompose(_request()))

    assert raised.value.code is DomainDecompositionErrorCode.INVALID_DECOMPOSITION


def test_every_approved_architecture_domain_must_be_covered() -> None:
    content = json.loads(_response().content)
    content["workstreams"] = content["workstreams"][:1]
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=json.dumps(content),
                model=LLMModelMetadata(provider="fake", model="domains-v1"),
            )
        ]
    )

    with pytest.raises(DomainDecompositionError) as raised:
        asyncio.run(DomainDecomposer(provider).decompose(_request()))

    assert raised.value.code is DomainDecompositionErrorCode.INVALID_DECOMPOSITION


@pytest.mark.parametrize("name", ["checkout.py", "Orders Page", "Payment Endpoint"])
def test_obvious_file_or_page_level_workstream_is_rejected(name: str) -> None:
    content = json.loads(_response().content)
    content["workstreams"][2]["name"] = name
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=json.dumps(content),
                model=LLMModelMetadata(provider="fake", model="domains-v1"),
            )
        ]
    )

    with pytest.raises(DomainDecompositionError) as raised:
        asyncio.run(DomainDecomposer(provider).decompose(_request()))

    assert raised.value.code is DomainDecompositionErrorCode.INVALID_DECOMPOSITION


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("purpose", "Own the checkout.py file."),
        ("responsibilities", ["Orders Page"]),
    ],
)
def test_file_or_page_granularity_is_rejected_in_semantic_fields(
    field: str,
    value: object,
) -> None:
    content = json.loads(_response().content)
    content["workstreams"][2][field] = value
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=json.dumps(content),
                model=LLMModelMetadata(provider="fake", model="domains-v1"),
            )
        ]
    )

    with pytest.raises(DomainDecompositionError) as raised:
        asyncio.run(DomainDecomposer(provider).decompose(_request()))

    assert raised.value.code is DomainDecompositionErrorCode.INVALID_DECOMPOSITION


def test_excessive_fragmentation_within_one_domain_is_rejected() -> None:
    content = json.loads(_response().content)
    content["workstreams"] = content["workstreams"][:2] + [
        {
            "id": f"orders-segment-{index}",
            "name": f"Orders Segment {index}",
            "scope_kind": "SERVICE",
            "purpose": "Own one cohesive portion of the order lifecycle.",
            "source_domains": ["Orders"],
            "responsibilities": [f"Order responsibility {index}"],
            "required_capabilities": [f"orders.segment-{index}"],
            "dependencies": [],
        }
        for index in range(5)
    ]
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=json.dumps(content),
                model=LLMModelMetadata(provider="fake", model="domains-v1"),
            )
        ]
    )

    with pytest.raises(DomainDecompositionError) as raised:
        asyncio.run(DomainDecomposer(provider).decompose(_request()))

    assert raised.value.code is DomainDecompositionErrorCode.INVALID_DECOMPOSITION


def test_workstream_id_must_be_deterministically_derived_from_name() -> None:
    content = json.loads(_response().content)
    content["workstreams"][2]["id"] = "random-orders-id"
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=json.dumps(content),
                model=LLMModelMetadata(provider="fake", model="domains-v1"),
            )
        ]
    )

    with pytest.raises(DomainDecompositionError) as raised:
        asyncio.run(DomainDecomposer(provider).decompose(_request()))

    assert raised.value.code is DomainDecompositionErrorCode.INVALID_DECOMPOSITION


def test_provider_failure_is_sanitized_without_retry() -> None:
    marker = "domain-provider-secret"
    provider = FakeLLMProvider(error=LLMProviderError(marker, provider="fake"))

    with pytest.raises(DomainDecompositionError) as raised:
        asyncio.run(DomainDecomposer(provider).decompose(_request()))

    assert raised.value.code is DomainDecompositionErrorCode.PROVIDER_FAILURE
    assert marker not in str(raised.value)
    assert len(provider.requests) == 1


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


def test_timeout_is_bounded_and_cancellation_propagates() -> None:
    with pytest.raises(DomainDecompositionError) as raised:
        asyncio.run(
            DomainDecomposer(_DelayingProvider(), timeout_seconds=0.001).decompose(_request())
        )
    assert raised.value.code is DomainDecompositionErrorCode.TIMEOUT

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(DomainDecomposer(_CancellingProvider()).decompose(_request()))


def test_secret_input_is_rejected_and_no_phase_28_api_is_exposed() -> None:
    provider = FakeLLMProvider(responses=[_response()])
    request = _request(summary='api_key="sk-live-domain-secret"')

    with pytest.raises(DomainDecompositionError) as raised:
        asyncio.run(DomainDecomposer(provider).decompose(request))

    assert raised.value.code is DomainDecompositionErrorCode.SENSITIVE_INPUT
    assert provider.requests == ()
    decomposer = DomainDecomposer(FakeLLMProvider())
    for name in ("create_team", "create_agent", "assign_agent", "match_agent", "persist"):
        assert not hasattr(decomposer, name)


def test_provider_payload_contains_only_canonical_phase_27_evidence() -> None:
    provider = FakeLLMProvider(responses=[_response()])
    request = _request()

    asyncio.run(DomainDecomposer(provider).decompose(request))

    payload = json.loads(
        provider.requests[0].messages[0].content.removeprefix("Domain decomposition evidence:\n")
    )
    assert payload == {
        "architecture": request.architecture.model_dump(mode="json"),
        "intake": request.intake.model_dump(mode="json"),
        "project_id": "project-1",
    }
    assert provider.requests[0].metadata == {}


@pytest.mark.parametrize(
    "content",
    [
        '{"rationale":"incomplete"}',
        json.dumps(
            {
                **json.loads(_response().content),
                "unexpected": "forbidden",
            }
        ),
        "x" * 131_073,
    ],
)
def test_malformed_or_oversized_output_is_rejected_without_retry(content: str) -> None:
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=content,
                model=LLMModelMetadata(provider="fake", model="domains-v1"),
            )
        ]
    )

    with pytest.raises(DomainDecompositionError) as raised:
        asyncio.run(DomainDecomposer(provider).decompose(_request()))

    assert raised.value.code is DomainDecompositionErrorCode.INVALID_DECOMPOSITION
    assert len(provider.requests) == 1


class _ExplodingMetadata(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError("provider-metadata-must-not-be-read")

    def __len__(self) -> int:
        return 1


def test_unused_provider_metadata_is_never_copied_or_retained() -> None:
    model = LLMModelMetadata(provider="fake", model="domains-v1").model_copy(
        update={"details": _ExplodingMetadata()}
    )
    provider = FakeLLMProvider(responses=[_response().model_copy(update={"model": model})])

    result = asyncio.run(DomainDecomposer(provider).decompose(_request()))

    assert tuple(workstream.id for workstream in result.workstreams) == (
        "identity",
        "catalog",
        "orders",
    )


def test_aggregate_request_size_is_rejected_before_provider_call() -> None:
    large_intake = build_intake_result(
        _intake().analysis.model_copy(update={"goals": tuple("😀" * 2_048 for _ in range(32))})
    )
    request = DomainDecompositionRequest(
        project_id="project-1",
        intake=large_intake,
        architecture=_architecture(),
    )
    provider = FakeLLMProvider(responses=[_response()])

    with pytest.raises(DomainDecompositionError) as raised:
        asyncio.run(DomainDecomposer(provider).decompose(request))

    assert raised.value.code is DomainDecompositionErrorCode.INVALID_INPUT
    assert provider.requests == ()


class _LateResponseProvider:
    propagates_cancellation = True

    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            return _response()
        raise AssertionError("provider unexpectedly completed")


class _UnsafeProvider(_LateResponseProvider):
    propagates_cancellation = False


def test_late_response_is_rejected_and_unsafe_provider_is_refused() -> None:
    with pytest.raises(DomainDecompositionError) as raised:
        asyncio.run(
            DomainDecomposer(_LateResponseProvider(), timeout_seconds=0.001).decompose(_request())
        )
    assert raised.value.code is DomainDecompositionErrorCode.TIMEOUT

    with pytest.raises(ValueError, match="cancellation-safe"):
        DomainDecomposer(_UnsafeProvider())


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
def test_invalid_execution_bounds_are_rejected(
    max_tokens: Any,
    timeout_seconds: Any,
) -> None:
    with pytest.raises(ValueError):
        DomainDecomposer(
            FakeLLMProvider(),
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
        )
