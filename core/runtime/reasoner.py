"""Strict one-shot language-model reasoning for bounded loops."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ValidationError

from core.agents import AgentOutputValidationError
from core.agents.structured_output import decode_structured_output
from core.llm import LLMMessage, LLMProvider, LLMProviderError, LLMRequest, LLMResponse, LLMRole
from core.runtime.errors import RuntimeError, RuntimeErrorCode
from core.runtime.types import (
    ReasonerOutput,
    RuntimeDecision,
    RuntimeHistoryEntry,
    RuntimeObservation,
    RuntimePlan,
    RuntimeReport,
    RuntimeTask,
    RuntimeTerminalReason,
    RuntimeTerminalStatus,
    RuntimeVerification,
)
from core.tools import ToolResult

_OBSERVE = (
    "Observe the task. Return exactly one JSON object with only: summary, facts, uncertainties."
)
_PLAN = (
    "Plan one bounded iteration. Return exactly one JSON object with only: objective, steps, "
    "success_criteria."
)
_DECIDE = (
    "Choose one action. Return exactly one JSON object with only: action, tool_name, arguments, "
    "rationale, confidence. action must be TOOL_CALL, COMPLETE, or ESCALATE."
)
_VERIFY = (
    "Verify the tool observation. Return exactly one JSON object with only: outcome, summary, "
    "progress_made. outcome must be CONTINUE, COMPLETE, or ESCALATE."
)
_REPORT = (
    "Report the terminal run. Return exactly one JSON object with only: summary, details, "
    "next_actions."
)


class LoopReasoner(Protocol):
    """Provider-neutral structured reasoning operations consumed by AgentRuntime."""

    async def observe(
        self,
        task: RuntimeTask,
        history: tuple[RuntimeHistoryEntry, ...],
    ) -> ReasonerOutput[RuntimeObservation]: ...

    async def plan(
        self,
        task: RuntimeTask,
        observation: RuntimeObservation,
        history: tuple[RuntimeHistoryEntry, ...],
    ) -> ReasonerOutput[RuntimePlan]: ...

    async def decide(
        self,
        task: RuntimeTask,
        observation: RuntimeObservation,
        plan: RuntimePlan,
        history: tuple[RuntimeHistoryEntry, ...],
    ) -> ReasonerOutput[RuntimeDecision]: ...

    async def verify(
        self,
        task: RuntimeTask,
        decision: RuntimeDecision,
        tool_result: ToolResult,
        history: tuple[RuntimeHistoryEntry, ...],
    ) -> ReasonerOutput[RuntimeVerification]: ...

    async def report(
        self,
        task: RuntimeTask,
        status: RuntimeTerminalStatus,
        reason: RuntimeTerminalReason,
        history: tuple[RuntimeHistoryEntry, ...],
    ) -> ReasonerOutput[RuntimeReport]: ...


class LLMLoopReasoner:
    """Decode one strict typed response per provider request without retries."""

    def __init__(self, provider: LLMProvider, *, system_prompt: str, max_step_tokens: int) -> None:
        if not system_prompt.strip() or len(system_prompt) > 16_384:
            raise ValueError("runtime system prompt is invalid")
        if not 1 <= max_step_tokens <= 131_072:
            raise ValueError("runtime step token limit is invalid")
        self._provider = provider
        self._system_prompt = system_prompt
        self._max_step_tokens = max_step_tokens

    async def observe(
        self,
        task: RuntimeTask,
        history: tuple[RuntimeHistoryEntry, ...],
    ) -> ReasonerOutput[RuntimeObservation]:
        return await self._generate(_OBSERVE, RuntimeObservation, task=task, history=history)

    async def plan(
        self,
        task: RuntimeTask,
        observation: RuntimeObservation,
        history: tuple[RuntimeHistoryEntry, ...],
    ) -> ReasonerOutput[RuntimePlan]:
        return await self._generate(
            _PLAN,
            RuntimePlan,
            task=task,
            observation=observation,
            history=history,
        )

    async def decide(
        self,
        task: RuntimeTask,
        observation: RuntimeObservation,
        plan: RuntimePlan,
        history: tuple[RuntimeHistoryEntry, ...],
    ) -> ReasonerOutput[RuntimeDecision]:
        return await self._generate(
            _DECIDE,
            RuntimeDecision,
            task=task,
            observation=observation,
            plan=plan,
            history=history,
        )

    async def verify(
        self,
        task: RuntimeTask,
        decision: RuntimeDecision,
        tool_result: ToolResult,
        history: tuple[RuntimeHistoryEntry, ...],
    ) -> ReasonerOutput[RuntimeVerification]:
        return await self._generate(
            _VERIFY,
            RuntimeVerification,
            task=task,
            decision=decision,
            tool_result=tool_result,
            history=history,
        )

    async def report(
        self,
        task: RuntimeTask,
        status: RuntimeTerminalStatus,
        reason: RuntimeTerminalReason,
        history: tuple[RuntimeHistoryEntry, ...],
    ) -> ReasonerOutput[RuntimeReport]:
        return await self._generate(
            _REPORT,
            RuntimeReport,
            task=task,
            status=status,
            reason=reason,
            history=history,
        )

    async def _generate[ValueT: BaseModel](
        self,
        instruction: str,
        model_type: type[ValueT],
        **values: object,
    ) -> ReasonerOutput[ValueT]:
        request = LLMRequest(
            system_prompt=self._system_prompt,
            messages=(
                LLMMessage(
                    role=LLMRole.USER,
                    content=f"{instruction}\nInput:\n{_safe_json(values)}",
                ),
            ),
            max_tokens=self._max_step_tokens,
        )
        try:
            response = await self._provider.generate(request)
        except LLMProviderError as error:
            error.__traceback__ = None
            del error
            raise RuntimeError(RuntimeErrorCode.LLM_FAILED, "Runtime reasoning failed.") from None
        try:
            value = decode_structured_output(response.content, model_type)
            tokens, available = _reported_usage(response)
            return ReasonerOutput(
                value=value,
                reported_tokens=tokens,
                usage_available=available,
            )
        except (AgentOutputValidationError, TypeError, ValueError, ValidationError) as error:
            error.__traceback__ = None
            del error, response
            raise RuntimeError(
                RuntimeErrorCode.LLM_OUTPUT_INVALID,
                "Runtime reasoning output is invalid.",
            ) from None


def _safe_json(values: dict[str, object]) -> str:
    serializable: dict[str, object] = {}
    for key, value in values.items():
        if isinstance(value, BaseModel):
            serializable[key] = value.model_dump(mode="json")
        elif isinstance(value, tuple) and all(isinstance(item, BaseModel) for item in value):
            serializable[key] = [item.model_dump(mode="json") for item in value]
        elif isinstance(value, StrEnum):
            serializable[key] = value.value
        else:
            serializable[key] = value
    return json.dumps(serializable, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _reported_usage(response: LLMResponse) -> tuple[int, bool]:
    usage = response.usage
    if usage is None:
        return 0, False
    if usage.total_tokens is not None:
        return usage.total_tokens, True
    components = (usage.prompt_tokens, usage.completion_tokens)
    reported = [item for item in components if item is not None]
    if not reported:
        return 0, False
    return sum(reported), True
