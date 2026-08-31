"""Phase 14 Developer role composed over the bounded AgentRuntime."""

from __future__ import annotations

from core.developer.evidence import EvidenceCollectingToolExecutor
from core.developer.reporting import build_agent_report
from core.developer.skills import build_skill_context
from core.developer.types import DeveloperRequest, DeveloperResult
from core.developer.validation import validate_developer_request
from core.llm import LLMProvider
from core.runtime import (
    AgentRuntime,
    LLMLoopReasoner,
    RuntimeAuditRecorder,
    RuntimeLimits,
    RuntimeToolExecutor,
)
from core.skills import SkillRegistry


class DeveloperAgent:
    """Execute one scoped Developer task without owning injected resources."""

    def __init__(
        self,
        provider: LLMProvider,
        tool_executor: RuntimeToolExecutor,
        audit_recorder: RuntimeAuditRecorder,
        skill_registry: SkillRegistry,
        limits: RuntimeLimits,
    ) -> None:
        self._provider = provider
        self._tool_executor = tool_executor
        self._audit_recorder = audit_recorder
        self._skill_registry = skill_registry
        self._limits = limits

    async def run(self, request: DeveloperRequest) -> DeveloperResult:
        """Validate, execute one bounded runtime, and report deterministic evidence."""
        validated = validate_developer_request(request)
        skills = build_skill_context(validated, self._skill_registry)
        evidence_executor = EvidenceCollectingToolExecutor(self._tool_executor)
        reasoner = LLMLoopReasoner(
            self._provider,
            system_prompt=request.profile.system_prompt + skills.prompt_fragment,
            max_step_tokens=self._limits.max_step_tokens,
        )
        runtime = AgentRuntime(
            reasoner,
            evidence_executor,
            self._audit_recorder,
            self._limits,
        )
        runtime_result = await runtime.run(request.task, request.execution_context)
        evidence = evidence_executor.snapshot()
        checks = evidence.check_results()
        report = build_agent_report(
            runtime_result,
            request.required_check_profiles,
            checks,
        )
        return DeveloperResult(
            runtime=runtime_result,
            report=report,
            selected_skill_ids=skills.selected_ids,
            omitted_skill_ids=skills.omitted_ids,
            changed_paths=evidence.changed_paths,
            checks=checks,
        )
