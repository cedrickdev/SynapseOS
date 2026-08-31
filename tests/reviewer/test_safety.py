"""Lifecycle and confidentiality tests for Reviewer Agent composition."""

from __future__ import annotations

import asyncio
import json

import pytest

from core.llm import LLMModelMetadata, LLMRequest, LLMResponse
from core.reviewer import ReviewDecision, ReviewerAgent, ReviewerRequest
from infrastructure.llm import FakeLLMProvider
from tests.reviewer.factories import request_values


class CancellingClosableProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    async def generate(self, request: LLMRequest) -> LLMResponse:
        del request
        self.calls += 1
        raise asyncio.CancelledError

    async def close(self) -> None:
        self.closed = True


def test_agent_propagates_cancellation_and_never_closes_injected_provider() -> None:
    provider = CancellingClosableProvider()
    request = ReviewerRequest.model_validate(request_values())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(ReviewerAgent(provider).run(request))

    assert provider.calls == 1
    assert provider.closed is False


def test_agent_instance_retains_no_request_response_or_result_history() -> None:
    provider = CancellingClosableProvider()
    agent = ReviewerAgent(provider)

    assert set(vars(agent)) == {"_analyzer"}


def test_agent_redacts_request_echoes_from_a_successful_structured_result() -> None:
    """Prevent valid model text from retaining transient source evidence or its secret markers."""
    values = request_values()
    values.update(
        {
            "task_title": "Fix TASK_TITLE_SECRET_MARKER",
            "task_description": "Correct TASK_DESCRIPTION_SECRET_MARKER behavior.",
            "acceptance_criteria": ("Pass ACCEPTANCE_SECRET_MARKER verification.",),
            "diff": (
                "--- a/src/add.py\n+++ b/src/add.py\n@@ -1 +1 @@\n"
                "-return 0\n+return 'DIFF_SECRET_MARKER'\n"
            ),
        }
    )
    request = ReviewerRequest.model_validate(values)
    content = json.dumps(
        {
            "decision": "APPROVED",
            "findings": [
                {
                    "category": "correctness",
                    "severity": "LOW",
                    "rationale": request.acceptance_criteria[0],
                    "recommendation": request.task_description,
                },
                {
                    "category": "maintainability",
                    "severity": "LOW",
                    "rationale": request.task_title,
                    "recommendation": request.diff,
                },
                {
                    "category": "security",
                    "severity": "LOW",
                    "rationale": "The output contains TASK_TITLE_SECRET_MARKER.",
                    "recommendation": "Remove DIFF_SECRET_MARKER.",
                },
                {
                    "category": "testing",
                    "severity": "LOW",
                    "rationale": "A focused boundary case remains untested.",
                    "path": "src/add.py",
                    "line": 4,
                    "recommendation": "Add a focused regression test.",
                },
            ],
            "rationale": request.diff,
            "confidence": 0.9,
        }
    )
    provider = FakeLLMProvider(
        responses=[
            LLMResponse(
                content=content,
                model=LLMModelMetadata(provider="fake", model="reviewer-v1"),
            )
        ]
    )

    result = asyncio.run(ReviewerAgent(provider, max_tokens=512).run(request))

    assert result.decision is ReviewDecision.APPROVED
    assert result.rationale == "Reviewer rationale redacted because it echoed source evidence."
    assert result.findings[0].rationale == "Finding rationale redacted due to source evidence."
    assert result.findings[0].recommendation == (
        "Finding recommendation redacted due to source evidence."
    )
    assert result.findings[1].rationale == "Finding rationale redacted due to source evidence."
    assert result.findings[1].recommendation == (
        "Finding recommendation redacted due to source evidence."
    )
    assert result.findings[2].rationale == "Finding rationale redacted due to source evidence."
    assert result.findings[2].recommendation == (
        "Finding recommendation redacted due to source evidence."
    )
    assert result.findings[3].rationale == "A focused boundary case remains untested."
    assert result.findings[3].recommendation == "Add a focused regression test."
    assert result.findings[3].path == "src/add.py"
    serialized = result.model_dump_json()
    for source in (
        request.task_title,
        request.task_description,
        *request.acceptance_criteria,
        request.diff,
        "TASK_TITLE_SECRET_MARKER",
        "TASK_DESCRIPTION_SECRET_MARKER",
        "ACCEPTANCE_SECRET_MARKER",
        "DIFF_SECRET_MARKER",
    ):
        assert source not in serialized
