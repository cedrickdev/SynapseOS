"""Bounded runtime construction and observation for one agent profile."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

from core.agents.structured_output import decode_structured_output
from core.agents.types import AgentHistoryEntry, AgentOperation, AgentProfile, Observation
from core.llm import LLMMessage, LLMProvider, LLMRequest, LLMRole

_MAX_SUBJECT_LENGTH = 32_768
_OBSERVATION_INSTRUCTION = (
    "Observe the following subject. Return exactly one JSON object with only these fields: "
    "summary, facts, uncertainties, risks.\nSubject:\n"
)


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
        if max_history < 1:
            raise ValueError("max_history must be at least 1")
        if not 1 <= max_tokens <= 131_072:
            raise ValueError("max_tokens must be between 1 and 131072")
        self._profile = profile
        self._provider = provider
        self._history: deque[AgentHistoryEntry] = deque(maxlen=max_history)
        self._max_tokens = max_tokens

    @property
    def history(self) -> tuple[AgentHistoryEntry, ...]:
        """Return an immutable snapshot of safe completed-operation metadata."""
        return tuple(self._history)

    async def observe(self, subject: str) -> Observation:
        """Return one validated observation of a bounded, non-blank subject."""
        if not subject.strip():
            raise ValueError("subject must not be blank")
        if len(subject) > _MAX_SUBJECT_LENGTH:
            raise ValueError("subject must not exceed 32768 characters")

        request = LLMRequest(
            system_prompt=self._profile.system_prompt,
            messages=(
                LLMMessage(
                    role=LLMRole.USER,
                    content=f"{_OBSERVATION_INSTRUCTION}{subject}",
                ),
            ),
            max_tokens=self._max_tokens,
        )
        response = await self._provider.generate(request)
        observation = decode_structured_output(response.content, Observation)
        self._history.append(
            AgentHistoryEntry(
                operation=AgentOperation.OBSERVE,
                completed_at=datetime.now(UTC),
                provider=response.model.provider,
                model=response.model.model,
                usage=response.usage,
            )
        )
        return observation
