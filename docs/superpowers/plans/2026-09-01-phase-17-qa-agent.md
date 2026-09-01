# Phase 17 QA Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one bounded independent QA Agent and one audited QA workflow stage that executes
fixed test profiles, validates acceptance criteria, and advances `WAITING_QA` to
`WAITING_SECURITY`, `CHANGES_REQUESTED`, or fail-closed `WAITING_HUMAN`.

**Architecture:** Add a strict `core/qa/` application package that validates QA authority, executes
closed test profiles once through the existing `ToolExecutor`, performs one provider-neutral
analysis, and applies a deterministic gate. Add a separate `core/workflows/qa_*` stage that
validates persistent Developer/Reviewer/QA identities, claims a `WAITING_QA` task with an
append-only checkpoint, invokes QA once, and commits the existing `TaskStateMachine` transition.
The Phase 16 workflow remains unchanged.

**Tech Stack:** Python 3.12+, Pydantic v2, asyncio, existing `LLMProvider`, existing tool/permission/
command boundaries, SQLAlchemy 2, PostgreSQL, Alembic-managed test schema, pytest, Ruff, mypy strict.

**Spec:** `docs/superpowers/specs/2026-09-01-phase-17-qa-agent-design.md`

## Global Constraints

- Implement Phase 17 only; do not add Security Agent or Phase 18 behavior.
- Use English for source, comments, docstrings, documentation, branches, and commits.
- Follow RED-GREEN-REFACTOR: every production behavior must first have an observed failing test.
- Tests use real code; PostgreSQL integration tests use Alembic and never `metadata.create_all()`.
- Required test profiles are exactly `pytest`, `npm-test`, and `php-artisan-test`.
- QA runs required profiles sequentially and exactly once; provider analysis runs exactly once.
- No implicit retry, fallback, duplicate call, free-form shell, command arguments, or speculative
  concurrency.
- Every timeout, collection, string, diff, response, command output, result, and audit value is
  explicitly bounded.
- Cancellation propagates immediately and injected resources remain caller-owned.
- Prompts, provider responses, diffs, acceptance criteria, and raw command output are never
  persisted automatically.
- Deterministic test evidence always outranks Developer, Reviewer, and provider claims.
- Preserve Phase 16 public contracts and the existing task-state graph.

---

### Task 1: Strict QA contracts and safe errors

**Files:**
- Create: `core/qa/__init__.py`
- Create: `core/qa/types.py`
- Create: `core/qa/errors.py`
- Create: `tests/qa/__init__.py`
- Create: `tests/qa/factories.py`
- Create: `tests/qa/test_types.py`
- Create: `tests/qa/test_errors.py`

**Interfaces:**
- Consumes: `AgentProfile`, `CommandProfileId`, `CommandTerminalStatus`, `ReviewCheck`,
  `ReviewerResult`, and `ToolExecutionContext`.
- Produces: `QADecision`, `QACriterionStatus`, `QASeverity`, `QACriterionAssessment`, `QAFinding`,
  `QATestRecommendation`, `QATestExecution`, `QATestEvidence`, `QAAnalysis`, `QARequest`,
  `QAResult`, `QAErrorCode`, and `QAError`.

- [ ] **Step 1: Write failing immutable-contract tests**

Create tests that construct the wished-for public API and assert strict bounds, copied tuples,
unknown-field rejection, hidden input errors, nested revalidation, unique criteria/profile IDs,
normalized relative paths, distinct Developer/Reviewer/QA IDs, approved Reviewer input, exact
test-profile allowlist, criterion coverage, and truthful result shapes.

```python
def test_request_accepts_only_unique_phase_17_test_profiles() -> None:
    request = qa_request(
        required_test_profiles=(CommandProfileId.PYTEST, CommandProfileId.NPM_TEST)
    )
    assert request.required_test_profiles == (
        CommandProfileId.PYTEST,
        CommandProfileId.NPM_TEST,
    )
    with pytest.raises(ValidationError):
        qa_request(required_test_profiles=(CommandProfileId.RUFF,))


def test_failed_result_requires_actionable_findings() -> None:
    with pytest.raises(ValidationError):
        QAResult(
            decision=QADecision.FAILED,
            criteria=passed_criterion_assessments(),
            findings=(),
            recommendations=(),
            tests=(successful_test_evidence(),),
            rationale="Failure without evidence is forbidden.",
            confidence=0.9,
            correlation_id=CORRELATION_ID,
        )
```

- [ ] **Step 2: Run the focused tests and observe RED**

Run:

```bash
.venv/bin/pytest tests/qa/test_types.py tests/qa/test_errors.py -q
```

Expected: collection fails because `core.qa` does not exist.

- [ ] **Step 3: Implement the minimal strict models and stable errors**

Use `ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True,
revalidate_instances="always")`. Define these exact public fields:

```python
class QADecision(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class QACriterionStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    UNVERIFIED = "UNVERIFIED"


class QASeverity(StrEnum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class QACriterionAssessment(_ImmutableQAModel):
    criterion_index: Annotated[int, Field(ge=1, le=16)]
    status: QACriterionStatus
    rationale: Text4096
    evidence_profiles: Annotated[tuple[CommandProfileId, ...], Field(max_length=3)]


class QAFinding(_ImmutableQAModel):
    category: Identifier
    severity: QASeverity
    reproduction_steps: Annotated[tuple[Text1024, ...], Field(min_length=1, max_length=8)]
    expected_behavior: Text4096
    actual_behavior: Text4096
    path: RelativePath | None = None


class QATestRecommendation(_ImmutableQAModel):
    title: Text255
    rationale: Text4096
    criterion_indices: Annotated[tuple[int, ...], Field(min_length=1, max_length=16)]


class QATestExecution(_ImmutableQAModel):
    profile_id: CommandProfileId
    status: CommandTerminalStatus
    exit_code: Annotated[int, Field(ge=-255, le=255)]
    stdout: Annotated[str, Field(max_length=32_768)]
    stderr: Annotated[str, Field(max_length=32_768)]
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]


class QATestEvidence(_ImmutableQAModel):
    profile_id: CommandProfileId
    status: CommandTerminalStatus
    exit_code: Annotated[int, Field(ge=-255, le=255)]
    truncated: bool
    duration_ms: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]


class QAAnalysis(_ImmutableQAModel):
    decision: QADecision
    criteria: Annotated[tuple[QACriterionAssessment, ...], Field(min_length=1, max_length=16)]
    findings: Annotated[tuple[QAFinding, ...], Field(max_length=64)]
    recommendations: Annotated[tuple[QATestRecommendation, ...], Field(max_length=32)]
    rationale: Text16384
    confidence: UnitScore


class QARequest(_ImmutableQAModel):
    task_id: UUID
    project_id: UUID
    developer_id: Identifier
    reviewer_id: Identifier
    qa_id: Identifier
    profile: AgentProfile
    task_title: Text255
    task_description: Text8192
    acceptance_criteria: Annotated[tuple[Text1024, ...], Field(min_length=1, max_length=16)]
    diff: Annotated[str, Field(min_length=1, max_length=16_384)]
    reviewer_result: ReviewerResult
    existing_checks: Annotated[tuple[ReviewCheck, ...], Field(min_length=1, max_length=16)]
    required_test_profiles: Annotated[
        tuple[CommandProfileId, ...], Field(min_length=1, max_length=3)
    ]
    execution_context: ToolExecutionContext
    timeout_seconds: Annotated[float, Field(gt=0.0, le=3600.0, allow_inf_nan=False)]
    correlation_id: UUID


class QAResult(_ImmutableQAModel):
    decision: QADecision
    criteria: Annotated[tuple[QACriterionAssessment, ...], Field(min_length=1, max_length=16)]
    findings: Annotated[tuple[QAFinding, ...], Field(max_length=64)]
    recommendations: Annotated[tuple[QATestRecommendation, ...], Field(max_length=32)]
    tests: Annotated[tuple[QATestEvidence, ...], Field(min_length=1, max_length=3)]
    rationale: Text16384
    confidence: UnitScore
    correlation_id: UUID
```

`QAErrorCode` must contain only stable categories: `INVALID_INPUT`, `INVALID_ROLE`,
`INACTIVE_AGENT`, `INVALID_PERMISSION`, `INVALID_TOOLS`, `INVALID_SCOPE`,
`TEST_EXECUTION_FAILURE`, `PROVIDER_FAILURE`, `INVALID_ANALYSIS`, `TIMEOUT`, and
`INTERNAL_FAILURE`. `QAError` stores only `code` and a constant safe message.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Task 1 command. Expected: all tests pass with no warnings.

- [ ] **Step 5: Commit Task 1**

```bash
git add core/qa tests/qa
git commit -m "feat(qa): define bounded QA contracts"
```

---

### Task 2: Fail-closed QA authority and scope validation

**Files:**
- Create: `core/qa/validation.py`
- Create: `tests/qa/test_validation.py`
- Modify: `tests/qa/factories.py`
- Modify: `core/qa/__init__.py`

**Interfaces:**
- Consumes: `QARequest`, `AgentProfile`, `Permission`, `AgentStatus`, and
  `ToolExecutionContext`.
- Produces: `ValidatedQARequest`, `validate_qa_request(request: QARequest)`, and
  `validate_qa_profile_authority(profile: AgentProfile)`.

- [ ] **Step 1: Write failing preflight tests**

Cover valid authority and rejection before any collaborator call for wrong role, inactive profile,
self-QA, profile/context identity mismatch, task/project/correlation mismatch, incomplete permissions,
write permissions, write tools, arbitrary Git-write or command tools, missing
`run_command_profile`, non-approved Reviewer result, malformed/duplicated existing checks, and forged
Pydantic subclasses.

```python
def test_validation_rejects_write_authority() -> None:
    request = qa_request(
        profile=qa_profile(
            permission_ids=frozenset(
                {
                    "filesystem.read",
                    "filesystem.write",
                    "shell.execute",
                    "tests.execute",
                }
            )
        )
    )
    with pytest.raises(QAError) as raised:
        validate_qa_request(request)
    assert raised.value.code is QAErrorCode.INVALID_PERMISSION


def test_validation_requires_exact_context_scope() -> None:
    request = qa_request(execution_context=qa_execution_context(correlation_id=uuid4()))
    with pytest.raises(QAError) as raised:
        validate_qa_request(request)
    assert raised.value.code is QAErrorCode.INVALID_SCOPE
```

- [ ] **Step 2: Run validation tests and observe RED**

```bash
.venv/bin/pytest tests/qa/test_validation.py -q
```

Expected: import failure for `core.qa.validation`.

- [ ] **Step 3: Implement canonical preflight validation**

Define the closed authority sets:

```python
QA_TOOL_IDS = frozenset(
    {
        "read_file",
        "list_files",
        "search_text",
        "git_status",
        "git_diff",
        "run_command_profile",
    }
)
_REQUIRED_PERMISSIONS = frozenset(
    {Permission.FILESYSTEM_READ, Permission.SHELL_EXECUTE, Permission.TESTS_EXECUTE}
)
_ALLOWED_PERMISSIONS = _REQUIRED_PERMISSIONS | frozenset({Permission.GIT_READ})
_ACTIVE_STATUSES = frozenset({AgentStatus.ASSIGNED, AgentStatus.WORKING})
```

`ValidatedQARequest` is a frozen slotted dataclass with canonical `request` and permissions.
Strictly reconstruct nested models before checking them. Require `profile.role == "QA"`, profile ID
and tool declarations equal the execution context, all three role IDs distinct, exact UUID scope,
approved Reviewer result, canonical existing checks, and unique test profiles from the
Task 1 allowlist. Strip raw exceptions and raise only stable `QAError` values.

- [ ] **Step 4: Run Task 2 and Task 1 tests and verify GREEN**

```bash
.venv/bin/pytest tests/qa/test_types.py tests/qa/test_errors.py tests/qa/test_validation.py -q
```

- [ ] **Step 5: Commit Task 2**

```bash
git add core/qa tests/qa
git commit -m "feat(qa): enforce independent QA authority"
```

---

### Task 3: Permissioned exact-once test execution

**Files:**
- Create: `core/qa/ports.py`
- Create: `core/qa/testing.py`
- Create: `tests/qa/test_testing.py`
- Modify: `core/qa/__init__.py`
- Modify: `tests/qa/factories.py`

**Interfaces:**
- Consumes: `ValidatedQARequest`, `ToolExecutor.execute`, `ToolResult`, and
  `run_command_profile`.
- Produces: `ToolExecutorPort`, `QATestRunner`, and `PermissionedQATestRunner`.

```python
@runtime_checkable
class ToolExecutorPort(Protocol):
    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
        context: ToolExecutionContext,
    ) -> ToolResult: ...


@runtime_checkable
class QATestRunner(Protocol):
    async def run(self, request: ValidatedQARequest) -> tuple[QATestExecution, ...]: ...
```

- [ ] **Step 1: Write failing runner tests**

Test deterministic order, exactly one tool call per profile, exact arguments, unchanged execution
context, canonical output conversion, functional nonzero exit retained as a failed test execution,
permission/tool failure normalized to `TEST_EXECUTION_FAILURE`, malformed output rejection,
cancellation propagation with no later profile, no retry, no executor close, and no retained runner
history.

```python
async def test_runner_executes_each_profile_once_in_request_order() -> None:
    executor = RecordingToolExecutor(successful_outputs())
    runner = PermissionedQATestRunner(executor)
    executions = await runner.run(validate_qa_request(qa_request()))
    assert [call.arguments for call in executor.calls] == [
        {"profile_id": "pytest"},
        {"profile_id": "npm-test"},
    ]
    assert tuple(item.profile_id for item in executions) == (
        CommandProfileId.PYTEST,
        CommandProfileId.NPM_TEST,
    )
```

- [ ] **Step 2: Run runner tests and observe RED**

```bash
.venv/bin/pytest tests/qa/test_testing.py -q
```

- [ ] **Step 3: Implement the exact-once runner**

Loop over the canonical tuple once. Call only:

```python
result = await executor.execute(
    "run_command_profile",
    {"profile_id": profile_id.value},
    request.request.execution_context,
)
```

Require `ToolResultStatus.SUCCEEDED`, an exact `run_command_profile` result shape, matching profile,
`CommandCategory.TEST`, truthful terminal status/exit code, strings no longer than 32,768
characters each, finite nonnegative duration, and boolean truncation flags. Convert nonzero command
exit to `QATestExecution(status=FAILED)`; convert tool denial, timeout, malformed output, or audit
failure to a sanitized `QAError(TEST_EXECUTION_FAILURE)`. Re-raise `CancelledError` immediately.

- [ ] **Step 4: Verify GREEN and run tool regressions**

```bash
.venv/bin/pytest tests/qa/test_testing.py tests/tools/test_command_tool.py \
  tests/database/test_command_tool_execution.py -q
```

- [ ] **Step 5: Commit Task 3**

```bash
git add core/qa tests/qa
git commit -m "feat(qa): run fixed test profiles exactly once"
```

---

### Task 4: One-shot bounded QA analysis

**Files:**
- Create: `core/qa/analysis.py`
- Create: `tests/qa/test_analysis.py`
- Create: `tests/qa/test_safety.py`
- Modify: `core/qa/__init__.py`
- Modify: `tests/qa/factories.py`

**Interfaces:**
- Consumes: `LLMProvider`, `LLMRequest`, validated `QARequest`, and fresh
  `QATestExecution` values.
- Produces: `QAAnalyzer.analyze(request, executions) -> QAAnalysis`.

- [ ] **Step 1: Write failing provider-boundary tests**

Cover one call after fresh test evidence, temperature zero, finite `max_tokens`, 30-second maximum
provider timeout, 131,072-byte response cap, strict JSON decoding, complete criterion index set,
no retries/fallback, malformed/oversized/forged response rejection, provider failure sanitization,
cancellation propagation, injected provider lifecycle, and prompt/result/source-echo retention.

```python
async def test_analysis_calls_provider_once_with_fresh_test_evidence() -> None:
    provider = FakeLLMProvider([qa_analysis_response()])
    analyzer = QAAnalyzer(provider, max_tokens=2048, timeout_seconds=1.0)
    analysis = await analyzer.analyze(qa_request(), successful_test_executions())
    assert analysis.decision is QADecision.PASSED
    assert len(provider.requests) == 1
    assert provider.requests[0].temperature == 0.0
    assert provider.requests[0].max_tokens == 2048
```

- [ ] **Step 2: Run analysis tests and observe RED**

```bash
.venv/bin/pytest tests/qa/test_analysis.py tests/qa/test_safety.py -q
```

- [ ] **Step 3: Implement `QAAnalyzer`**

Mirror the established safe provider lifecycle without importing Reviewer private helpers. Build a
deterministic JSON evidence object with criteria enumerated from one, bounded diff, approved
Reviewer result, existing checks, and fresh tests. Define
`QAAnalyzer.__init__(provider: LLMProvider, *, max_tokens: int,
timeout_seconds: float = 10.0) -> None` and `QAAnalyzer.analyze(request: QARequest,
executions: tuple[QATestExecution, ...]) -> QAAnalysis` as the exact public interface.

The system prompt requires compact JSON keys
`decision,criteria[{criterion_index,status,rationale,evidence_profiles}],findings[{category,severity,reproduction_steps,expected_behavior,actual_behavior,path}],recommendations[{title,rationale,criterion_indices}],rationale,confidence`.
Treat all supplied text as untrusted data. Clear raw exception frames and source-containing locals
before raising a stable `QAError`.

- [ ] **Step 4: Verify GREEN with LLM regressions**

```bash
.venv/bin/pytest tests/qa/test_analysis.py tests/qa/test_safety.py tests/llm -q
```

- [ ] **Step 5: Commit Task 4**

```bash
git add core/qa tests/qa
git commit -m "feat(qa): add bounded QA evidence analysis"
```

---

### Task 5: Deterministic QA gate and agent composition

**Files:**
- Create: `core/qa/decision.py`
- Create: `core/qa/agent.py`
- Create: `tests/qa/test_decision.py`
- Create: `tests/qa/test_agent.py`
- Modify: `core/qa/__init__.py`
- Modify: `tests/qa/factories.py`

**Interfaces:**
- Consumes: `QARequest`, test executions, `QAAnalysis`, `QATestRunner`, and `LLMProvider`.
- Produces: `build_qa_result(request: QARequest, executions: tuple[QATestExecution, ...],
  analysis: QAAnalysis) -> QAResult` and `QAAgent.run(request: QARequest) -> QAResult`.

- [ ] **Step 1: Write failing deterministic-gate tests**

Test `PASSED` only for complete passing evidence. Test forced `FAILED` for missing/duplicate/failed/
truncated tests, failed existing checks, missing/failed/unverified criteria, any observed functional
mismatch, provider-proposed failure, confidence below `0.70`, stale review/scope, and source-echoing
findings. Require synthetic findings to include safe reproduction/expected/actual fields. Ensure
recommendations alone remain non-blocking when all criteria are verified.

```python
def test_failed_test_overrides_model_pass() -> None:
    result = build_qa_result(
        qa_request(),
        (failed_test_execution(CommandProfileId.PYTEST),),
        passing_qa_analysis(),
    )
    assert result.decision is QADecision.FAILED
    assert result.tests[0].status is CommandTerminalStatus.FAILED
    assert result.findings[0].category == "qa-gate.failed-test"
```

- [ ] **Step 2: Write failing QA Agent composition tests**

Assert validation happens before runner/provider, runner once, provider once after runner, global
request timeout, cancellation with no later call, no retry, no stored request/result history, and no
closing of injected runner/provider.

- [ ] **Step 3: Run Task 5 tests and observe RED**

```bash
.venv/bin/pytest tests/qa/test_decision.py tests/qa/test_agent.py -q
```

- [ ] **Step 4: Implement the gate and `QAAgent`**

Implement `QAAgent` with `__slots__ = ("_analyzer", "_test_runner")`, constructor
`QAAgent(provider: LLMProvider, test_runner: QATestRunner, *, max_tokens: int = 2048,
provider_timeout_seconds: float = 10.0)`, and asynchronous method
`run(request: QARequest) -> QAResult`.

Validate first, wrap the complete runner-plus-analysis path in `asyncio.timeout` using
`request.timeout_seconds`, and preserve the analyzer's smaller timeout. Redact exact or obvious
source echoes from rationale/findings/recommendations. Result tests contain metadata only and never
stdout or stderr. Re-raise cancellation; normalize timeout and unexpected errors without retaining
request or provider content.

- [ ] **Step 5: Verify GREEN and all QA tests**

```bash
.venv/bin/pytest tests/qa -q
```

- [ ] **Step 6: Commit Task 5**

```bash
git add core/qa tests/qa
git commit -m "feat(qa): compose deterministic QA Agent"
```

---

### Task 6: Persistent QA workflow contracts and preflight

**Files:**
- Create: `core/workflows/qa_types.py`
- Create: `core/workflows/qa_errors.py`
- Create: `core/workflows/qa_ports.py`
- Create: `core/workflows/qa_validation.py`
- Create: `tests/workflows/test_qa_types.py`
- Create: `tests/workflows/test_qa_validation.py`
- Create: `tests/workflows/qa_factories.py`
- Modify: `core/workflows/__init__.py`

**Interfaces:**
- Consumes: persistent `Task` and `Agent`, `QARequest`, `QAResult`, and `validate_qa_request`.
- Produces: `QAWorkflowOutcome`, `QAWorkflowRequest`, `QAWorkflowResult`, `QAWorkflowErrorCode`,
  `QAWorkflowError`, `QARunner`, `ValidatedQAWorkflowScope`, and
  `validate_qa_workflow_request`.

```python
class QAWorkflowRequest(_ImmutableQAWorkflowModel):
    task_id: UUID
    developer_agent_id: UUID
    reviewer_agent_id: UUID
    qa_agent_id: UUID
    qa_request: QARequest
    correlation_id: UUID


class QAWorkflowResult(_ImmutableQAWorkflowModel):
    task_status: TaskStatus
    outcome: QAWorkflowOutcome
    qa_result: QAResult
    correlation_id: UUID


class QARunner(Protocol):
    async def run(self, request: QARequest) -> QAResult: ...
```

- [ ] **Step 1: Write failing workflow contract tests**

Cover strict immutable nested revalidation, distinct UUIDs, exact correlation, truthful
`PASSED/WAITING_SECURITY` and `FAILED/CHANGES_REQUESTED` pairs, and result sanitization.

- [ ] **Step 2: Write failing real-PostgreSQL preflight tests**

Use existing Alembic-backed fixtures. Cover missing task/agents, non-`WAITING_QA` task, wrong role,
inactive agent, non-independent identities, task assignment not equal to Developer, slug/profile
mismatch, project/task/correlation/workspace mismatch, and valid canonical scope. Assert every
failure changes no state and invokes no runner.

```python
def test_qa_preflight_requires_waiting_qa_and_existing_assignment(db_session: Session) -> None:
    request = persisted_qa_workflow_request(db_session, task_status=TaskStatus.WAITING_REVIEW)
    with pytest.raises(QAWorkflowError) as raised:
        validate_qa_workflow_request(db_session, request)
    assert raised.value.code is QAWorkflowErrorCode.INVALID_STATE
```

- [ ] **Step 3: Run Task 6 tests and observe RED**

```bash
.venv/bin/pytest tests/workflows/test_qa_types.py \
  tests/workflows/test_qa_validation.py -q
```

- [ ] **Step 4: Implement types, errors, port, and preflight**

Strictly canonicalize the request and nested QA request. Load task plus all three agents; require
`Developer`, `Reviewer`, and `QA` roles, active statuses, three distinct UUIDs/slugs, preserved
Developer assignment, exact task/project/context/correlation scope, and valid QA authority. Return
a frozen slotted `ValidatedQAWorkflowScope`. Roll back and sanitize SQLAlchemy failures; never
commit, call QA, or close the session during preflight.

- [ ] **Step 5: Verify GREEN**

Run Task 6 tests and the existing Phase 16 workflow tests.

```bash
.venv/bin/pytest tests/workflows/test_qa_types.py \
  tests/workflows/test_qa_validation.py tests/workflows/test_validation.py -q
```

- [ ] **Step 6: Commit Task 6**

```bash
git add core/workflows tests/workflows
git commit -m "feat(workflow): validate persistent QA scope"
```

---

### Task 7: Audited QA workflow orchestration

**Files:**
- Create: `core/workflows/qa_audit.py`
- Create: `core/workflows/qa_orchestrator.py`
- Create: `tests/workflows/test_qa_audit.py`
- Create: `tests/workflows/test_qa_orchestrator.py`
- Create: `tests/workflows/test_qa_safety.py`
- Modify: `core/workflows/__init__.py`
- Modify: `tests/workflows/qa_factories.py`

**Interfaces:**
- Consumes: `ValidatedQAWorkflowScope`, `QARunner`, `TaskStateMachine`, and append-only
  `AuditEvent`.
- Produces: `QAWorkflowOrchestrator.run(request) -> QAWorkflowResult` plus committed checkpoint
  helpers.

- [ ] **Step 1: Write failing checkpoint and audit tests**

Cover row-locked `QA_STARTED`, duplicate/stale start rejection, existing `TOOL_EXECUTION` authority,
atomic `QA_COMPLETED` plus task transition, allowlisted audit data, one correlation ID, rollback,
and no prompt/diff/criteria/output/path/finding/error content in persisted data.

- [ ] **Step 2: Write failing orchestration tests**

Cover exactly one QA call, `PASSED -> WAITING_SECURITY`, `FAILED -> CHANGES_REQUESTED`, no automatic
Developer/Security call, global deadline from `qa_request.timeout_seconds`, command/provider/
malformed-result failure to `WAITING_HUMAN`, cancellation with no later checkpoint, stale concurrent
human transition winning, database failure with no retry, and caller-owned session/runner.

```python
async def test_passed_qa_advances_only_to_waiting_security(db_session: Session) -> None:
    request = persisted_qa_workflow_request(db_session)
    runner = RecordingQARunner(passed_qa_result(request.qa_request))
    result = await QAWorkflowOrchestrator(db_session, runner).run(request)
    assert result.task_status is TaskStatus.WAITING_SECURITY
    assert result.outcome is QAWorkflowOutcome.PASSED
    assert runner.calls == [request.qa_request]
```

- [ ] **Step 3: Run Task 7 tests and observe RED**

```bash
.venv/bin/pytest tests/workflows/test_qa_audit.py \
  tests/workflows/test_qa_orchestrator.py tests/workflows/test_qa_safety.py -q
```

- [ ] **Step 4: Implement durable checkpoints**

Define `QAEventType` with `QA_STARTED`, `QA_COMPLETED`, and `QA_ESCALATED`. Under a task row lock,
`commit_qa_started_checkpoint` requires `WAITING_QA`, verifies no unmatched prior `QA_STARTED`,
appends only QA agent/correlation scalar scope, and commits. Completion reacquires the row lock,
verifies expected state, uses `TaskStateMachine.transition`, stages the bounded QA event, and commits
atomically. Use existing `TOOL_EXECUTION` events for command audit rather than duplicating command
output or command-event rows.

- [ ] **Step 5: Implement the orchestrator**

Implement `QAWorkflowOrchestrator` with `__slots__ = ("_qa", "_session")`, constructor
`QAWorkflowOrchestrator(session: Session, qa: QARunner)`, and asynchronous method
`run(request: QAWorkflowRequest) -> QAWorkflowResult`.

Validate before start, derive one monotonic deadline from the nested timeout, commit `QA_STARTED`,
invoke QA once, strictly reconstruct `QAResult`, and commit exactly one permitted transition.
Cancellation clears sensitive locals and re-raises immediately. Operational failures use a bounded
recovery deadline to attempt `WAITING_HUMAN` only when the row remains at the expected state; they
never become functional `FAILED` results.

- [ ] **Step 6: Verify GREEN with Phase 16 regressions**

```bash
.venv/bin/pytest tests/workflows -q
```

- [ ] **Step 7: Commit Task 7**

```bash
git add core/workflows tests/workflows
git commit -m "feat(workflow): orchestrate audited QA gate"
```

---

### Task 8: Concrete PostgreSQL and secure-command integration

**Files:**
- Create: `tests/qa/test_integration.py`
- Create: `tests/qa/integration_fixtures.py`
- Create: `tests/workflows/test_qa_integration.py`
- Create: `tests/database/test_qa_permission_policy.py`
- Create: `tests/tools/test_qa_command_tool.py`
- Create: `infrastructure/permissions/qa_policy.py`
- Modify: `infrastructure/permissions/__init__.py`
- Modify: `infrastructure/tools/command.py`
- Modify: `infrastructure/tools/__init__.py`

**Interfaces:**
- Consumes: concrete `QAAgent`, `PermissionedQATestRunner`, `ToolExecutor`,
  secure command policy/runner, PostgreSQL permission/audit repositories, `FakeLLMProvider`, and
  `QAWorkflowOrchestrator`.
- Produces: `SQLAlchemyQAPermissionPolicy` and `RunQATestProfileTool`, retaining the existing tool
  name while restricting its schema to Phase 17 test profiles.
- Produces: acceptance evidence for the complete Phase 17 data path.

- [ ] **Step 1: Write failing concrete integration tests**

Provision a managed temporary repository, persisted QA agent and exact active grants, real command
policy/runner/tool executor, and Alembic-built PostgreSQL schema. Run a small real pytest profile.
Assert one process, one permission decision, one `TOOL_EXECUTION`, one provider request, metadata-
only `QAResult`, and the final task transition. Add failed-test and denied-permission paths.

- [ ] **Step 2: Run integration tests and observe RED**

```bash
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/qa/test_integration.py \
  tests/workflows/test_qa_integration.py -q
```

- [ ] **Step 3: Add only the minimal composition/factory fixes required by integration**

Do not add an API endpoint, background worker, dependency container, migration, browser runner,
Security runner, or free-form command path. Wire existing concrete objects directly in tests. The
general Phase 7 policy cannot authorize a non-assigned autonomy-0/1 QA agent without weakening its
global invariant, so add one separate deny-by-default QA policy requiring the exact role, state,
run, Developer assignment, risk, tool, and persisted grants. Pair it with a test-only command input
schema so the delegation cannot authorize lint, build, or Git profiles.

- [ ] **Step 4: Verify focused and full suites**

```bash
TEST_POSTGRES_PORT=55432 .venv/bin/pytest tests/qa tests/workflows -q
make check
.venv/bin/ruff format --check .
```

- [ ] **Step 5: Commit Task 8**

```bash
git add core tests
git commit -m "test(qa): verify concrete QA workflow"
```

---

### Task 9: Documentation, checklist, and final acceptance

**Files:**
- Create: `docs/qa-agent.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`
- Modify: `docs/superpowers/plans/2026-09-01-phase-17-qa-agent.md`

**Interfaces:**
- Consumes: verified Phase 17 behavior and final command evidence.
- Produces: truthful operating documentation and only genuinely completed Phase 17 checkboxes.

- [ ] **Step 1: Document exact Phase 17 behavior**

Document the request/result contracts, exact test profile catalog, permission requirements,
provider and timeout bounds, deterministic gate, state transitions, audit behavior, failure modes,
resource ownership, example composition, and explicit exclusions. Update repository status in
`README.md` and `AGENTS.md` without claiming Phase 18.

- [ ] **Step 2: Run complete verification before checking boxes**

```bash
make check
.venv/bin/ruff format --check .
git diff --check origin/main...HEAD
```

Also run the focused real-PostgreSQL integration command from Task 8, inspect the diff for secrets,
absolute paths, raw outputs, provider payloads, accidental Phase 18 code, and AI co-author trailers,
and verify Docker/API health only if those commands are actually executed successfully.

- [ ] **Step 3: Update only Phase 17 checkboxes**

Check these five responsibility boxes only when the implementation and tests prove them:

- analyze acceptance criteria;
- verify existing tests;
- propose missing tests;
- execute the test suite;
- pass or fail the QA gate.

Do not alter Phase 18 or later checkboxes. Record any unavailable Docker evidence as unverified
rather than checking or claiming it.

- [ ] **Step 4: Re-run final verification after documentation changes**

```bash
make check
.venv/bin/ruff format --check .
git diff --check origin/main...HEAD
```

- [ ] **Step 5: Commit the verified documentation**

```bash
git add README.md AGENTS.md SYNAPSEOS_DEVELOPMENT_CHECKLIST.md docs/qa-agent.md \
  docs/superpowers/plans/2026-09-01-phase-17-qa-agent.md
git commit -m "docs(qa): complete Phase 17 delivery"
```

- [ ] **Step 6: Finish the branch**

Run an independent scoped code and security review, fix every accepted finding through a failing
regression test, repeat the full acceptance gate, push `phase-17/qa-agent`, and open a pull request
targeting `main`. The PR description must include exact test counts and explicitly state that Phase
18 is not implemented.
