"""Bounded one-call runtime operations for one agent profile."""

from __future__ import annotations

import json
from collections import deque
from datetime import UTC, datetime

from pydantic import BaseModel, ValidationError

from core.agents.structured_output import decode_structured_output
from core.agents.types import (
    AgentHistoryEntry,
    AgentOperation,
    AgentProfile,
    AgentReport,
    Decision,
    Observation,
    Plan,
)
from core.llm import LLMMessage, LLMProvider, LLMRequest, LLMResponse, LLMRole

_MAX_SUBJECT_LENGTH = 32_768
_MAX_OBJECTIVE_LENGTH = 8_192
_MAX_USER_PROMPT_LENGTH = 262_144
_MAX_HISTORY_LABEL_LENGTH = 255
_UNKNOWN_HISTORY_LABEL = "unknown"
_OBSERVATION_INSTRUCTION = (
    "Observe the following subject. Return exactly one JSON object with only these fields: "
    "summary, facts, uncertainties, risks.\nSubject:\n"
)
_PLAN_INSTRUCTION = (
    "Create a plan for the supplied objective and observation. Return exactly one JSON object "
    "with only these fields: objective, steps, success_criteria, risks.\nObjective:\n"
)
_DECISION_INSTRUCTION = (
    "Make a decision using the supplied observation and plan. Return exactly one JSON object "
    "with only these fields: choice, rationale, confidence, requires_human_approval, evidence."
)
_REPORT_INSTRUCTION = (
    "Report the supplied observation, plan, and decision. Return exactly one JSON object with "
    "only these fields: summary, outcome, details, next_actions."
)


def _normalize_history_label(value: str) -> str:
    """Produce a bounded, non-blank label that is safe to retain in history."""
    normalized = value.strip()[:_MAX_HISTORY_LABEL_LENGTH]
    return normalized or _UNKNOWN_HISTORY_LABEL


def _revalidate_structured_input[ModelT: BaseModel](
    value: ModelT,
    model_type: type[ModelT],
) -> ModelT:
    """Return one strict model reconstruction without exposing invalid input values."""
    type_name = model_type.__name__
    value_data: object = None
    failed = False
    try:
        if type(value) is not model_type:
            raise ValueError
        value_data = value.__dict__
        return model_type.model_validate(value_data, strict=True, extra="forbid")
    except (AttributeError, TypeError, ValueError, ValidationError) as raw_error:
        failed = True
        del raw_error

    if failed:
        value_data = None
        del value
        del value_data
        raise ValueError(f"{type_name} input is invalid")

    raise AssertionError("unreachable structured input validation state")


class Agent:
    """Execute bounded provider calls for one immutable agent profile."""

    def __init__(
        self,
        profile: AgentProfile,
        provider: LLMProvider,
        *,
        max_history: int = 100,
        max_tokens: int = 2048,
    ) -> None:
        """Create an agent without assuming ownership of its injected provider."""
        validated_profile: AgentProfile | None = None
        profile_data: object = None
        try:
            profile_invalid = False
            try:
                if type(profile) is not AgentProfile:
                    raise ValueError
                profile_data = profile.__dict__
                validated_profile = AgentProfile.model_validate(
                    profile_data,
                    strict=True,
                    extra="forbid",
                )
            except (AttributeError, TypeError, ValueError, ValidationError) as raw_error:
                profile_invalid = True
                del raw_error
            if profile_invalid:
                profile_data = None
                validated_profile = None
                raise ValueError("agent profile is invalid")
            if max_history < 1:
                raise ValueError("max_history must be at least 1")
            if not 1 <= max_tokens <= 131_072:
                raise ValueError("max_tokens must be between 1 and 131072")
            assert validated_profile is not None
            self._profile = validated_profile
            self._provider = provider
            self._history: deque[AgentHistoryEntry] = deque(maxlen=max_history)
            self._max_tokens = max_tokens
        except BaseException as error:
            error.__traceback__ = None
            profile_data = None
            validated_profile = None
            del profile
            del provider
            del profile_data
            del validated_profile
            del error
            raise

    @property
    def history(self) -> tuple[AgentHistoryEntry, ...]:
        """Return an immutable snapshot of safe completed-operation metadata."""
        return tuple(self._history)

    async def observe(self, subject: str) -> Observation:
        """Return one validated observation of a bounded, non-blank subject."""
        try:
            if not subject.strip():
                raise ValueError("subject must not be blank")
            if len(subject) > _MAX_SUBJECT_LENGTH:
                raise ValueError("subject must not exceed 32768 characters")

            return await self._generate_structured(
                content=f"{_OBSERVATION_INSTRUCTION}{subject}",
                model_type=Observation,
                operation=AgentOperation.OBSERVE,
            )
        except BaseException:
            del subject
            del self
            raise

    async def plan(self, observation: Observation, objective: str) -> Plan:
        """Return one validated plan for a supplied observation and objective."""
        validated_observation: Observation | None = None
        try:
            if not objective.strip():
                raise ValueError("objective must not be blank")
            if len(objective) > _MAX_OBJECTIVE_LENGTH:
                raise ValueError("objective must not exceed 8192 characters")
            validated_observation = _revalidate_structured_input(observation, Observation)

            return await self._generate_structured(
                content=(
                    f"{_PLAN_INSTRUCTION}{objective}\nObservation:\n"
                    f"{json.dumps(validated_observation.model_dump(mode='json'))}"
                ),
                model_type=Plan,
                operation=AgentOperation.PLAN,
            )
        except BaseException:
            validated_observation = None
            del observation
            del objective
            del validated_observation
            del self
            raise

    async def decide(self, observation: Observation, plan: Plan) -> Decision:
        """Return one validated decision for supplied immutable values."""
        validated_observation: Observation | None = None
        validated_plan: Plan | None = None
        try:
            validated_observation = _revalidate_structured_input(observation, Observation)
            validated_plan = _revalidate_structured_input(plan, Plan)
            return await self._generate_structured(
                content=(
                    f"{_DECISION_INSTRUCTION}\nObservation:\n"
                    f"{json.dumps(validated_observation.model_dump(mode='json'))}\nPlan:\n"
                    f"{json.dumps(validated_plan.model_dump(mode='json'))}\nDecision:\n"
                ),
                model_type=Decision,
                operation=AgentOperation.DECIDE,
            )
        except BaseException:
            validated_observation = None
            validated_plan = None
            del observation
            del plan
            del validated_observation
            del validated_plan
            del self
            raise

    async def report(
        self,
        observation: Observation,
        plan: Plan,
        decision: Decision,
    ) -> AgentReport:
        """Return one validated report for supplied immutable values."""
        validated_observation: Observation | None = None
        validated_plan: Plan | None = None
        validated_decision: Decision | None = None
        try:
            validated_observation = _revalidate_structured_input(observation, Observation)
            validated_plan = _revalidate_structured_input(plan, Plan)
            validated_decision = _revalidate_structured_input(decision, Decision)
            return await self._generate_structured(
                content=(
                    f"{_REPORT_INSTRUCTION}\nObservation:\n"
                    f"{json.dumps(validated_observation.model_dump(mode='json'))}\nPlan:\n"
                    f"{json.dumps(validated_plan.model_dump(mode='json'))}\nDecision:\n"
                    f"{json.dumps(validated_decision.model_dump(mode='json'))}\nReport:\n"
                ),
                model_type=AgentReport,
                operation=AgentOperation.REPORT,
            )
        except BaseException:
            validated_observation = None
            validated_plan = None
            validated_decision = None
            del observation
            del plan
            del decision
            del validated_observation
            del validated_plan
            del validated_decision
            del self
            raise

    async def _generate_structured[ModelT: BaseModel](
        self,
        *,
        content: str,
        model_type: type[ModelT],
        operation: AgentOperation,
    ) -> ModelT:
        """Generate, decode, and record exactly one successful typed response."""
        request: LLMRequest | None = None
        response: LLMResponse | None = None
        result: ModelT | None = None
        try:
            if len(content) > _MAX_USER_PROMPT_LENGTH:
                raise ValueError("agent user prompt exceeds 262144 characters")
            request = LLMRequest(
                system_prompt=self._profile.system_prompt,
                messages=(LLMMessage(role=LLMRole.USER, content=content),),
                max_tokens=self._max_tokens,
            )
            response = await self._provider.generate(request)
            result = decode_structured_output(response.content, model_type)
            self._record_success(operation, response)
            return result
        except BaseException as error:
            error.__traceback__ = None
            request = None
            response = None
            result = None
            del content
            del request
            del response
            del result
            del self
            del error
            raise

    def _record_success(self, operation: AgentOperation, response: LLMResponse) -> None:
        """Append safe metadata only after structured output has validated."""
        self._history.append(
            AgentHistoryEntry(
                operation=operation,
                completed_at=datetime.now(UTC),
                provider=_normalize_history_label(response.model.provider),
                model=_normalize_history_label(response.model.model),
                usage=response.usage,
            )
        )
