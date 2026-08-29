# Phase 16 Developer–Reviewer Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first bounded multi-agent SynapseOS workflow from a persistent `READY` task through Developer correction cycles and independent Reviewer approval to `WAITING_QA`.

**Architecture:** Add a focused `core/workflows` application package that composes the existing `DeveloperAgent`, `ReviewerAgent`, PostgreSQL `Task`, append-only `AuditEvent`, and `TaskStateMachine`. A narrow injected handoff builder supplies a fresh bounded diff after every Developer cycle; the orchestrator owns workflow sequencing and durable checkpoints but never owns injected resources.

**Tech Stack:** Python 3.12+, Pydantic v2 strict immutable models, asyncio timeouts, SQLAlchemy 2 synchronous sessions, PostgreSQL 16, Alembic, pytest, FakeLLMProvider, Ruff, and mypy strict.

**Spec:** `docs/superpowers/specs/2026-08-30-phase-16-developer-reviewer-workflow-design.md`

## Global Constraints

- Implement Phase 16 only; do not add QA, Security, merge, PR automation, event bus, scheduler, memory, reputation, deployment, or a generic workflow language.
- The only successful terminal state is `WAITING_QA`; cycle exhaustion and safe escalation end in `WAITING_HUMAN`.
- Developer and Reviewer identities must be distinct at both persistent UUID and profile-slug levels.
- All task status changes go through `TaskStateMachine`; direct status assignment remains forbidden.
- `max_review_cycles` is explicit and bounded from 1 through 10; workflow timeout is explicit, positive, and at most 3,600 seconds.
- There is no implicit retry, fallback, duplicated provider/tool call, or speculative parallel call.
- Cancellation propagates immediately; injected sessions, agents, providers, builders, tools, and clients are never closed.
- Prompts, responses, diffs, findings, command output, paths, arbitrary metadata, raw exceptions, and sensitive values are never persisted in workflow audit data.
- Tests use real PostgreSQL through Alembic; never call `metadata.create_all()`.
- Write tests first, observe the expected RED failure, implement the minimum GREEN behavior, refactor only while green, and commit each independently reviewable task.

---

### Task 1: Define immutable workflow contracts and safe errors

**Files:**
- Create: `core/workflows/__init__.py`
- Create: `core/workflows/errors.py`
- Create: `core/workflows/types.py`
- Test: `tests/workflows/__init__.py`
- Test: `tests/workflows/factories.py`
- Test: `tests/workflows/test_types.py`

**Interfaces:**
- Consumes: `DeveloperRequest`, `DeveloperResult`, `AgentProfile`, `AgentReport`, `ReviewerRequest`, `ReviewerResult`, `TaskStatus`, and UUID.
- Produces: `WorkflowOutcome`, `DeveloperReviewerWorkflowRequest`, `DeveloperReviewerWorkflowResult`, `WorkflowHandoffContext`, `WorkflowErrorCode`, and `WorkflowError`.

- [ ] **Step 1: Write strict contract tests**

  Add tests proving that a valid request contains persistent task/Developer/Reviewer UUIDs,
  `DeveloperRequest`, Reviewer profile, `max_review_cycles`, timeout, and correlation UUID. Assert
  frozen instances, `extra="forbid"`, strict cycle/timeout bounds, copied immutable collections,
  type-confused `model_copy()` rejection through public validation, and result cardinality:

  ```python
  request = DeveloperReviewerWorkflowRequest(
      task_id=task.id,
      developer_agent_id=developer.id,
      reviewer_agent_id=reviewer.id,
      developer_request=developer_request,
      reviewer_profile=reviewer_profile,
      max_review_cycles=2,
      timeout_seconds=30.0,
      correlation_id=developer_request.execution_context.correlation_id,
  )
  assert request.max_review_cycles == 2
  with pytest.raises(ValidationError):
      request.max_review_cycles = 3
  ```

  Test `DeveloperReviewerWorkflowResult` accepts only `WAITING_QA` with `APPROVED` and
  `WAITING_HUMAN` with `REVIEW_CYCLES_EXHAUSTED`, requires equal non-zero Developer/Reviewer cycle
  counts, and retains only final `AgentReport`/`ReviewerResult` plus scalar metadata.

- [ ] **Step 2: Run the focused tests and verify RED**

  Run: `.venv/bin/pytest tests/workflows/test_types.py -q`

  Expected: collection fails because `core.workflows` does not exist.

- [ ] **Step 3: Implement the minimum contracts**

  Define strict frozen Pydantic models with `extra="forbid"` and `hide_input_in_errors=True`.
  Define:

  ```python
  class WorkflowOutcome(StrEnum):
      APPROVED = "APPROVED"
      REVIEW_CYCLES_EXHAUSTED = "REVIEW_CYCLES_EXHAUSTED"

  class DeveloperReviewerWorkflowRequest(_ImmutableWorkflowModel):
      task_id: UUID
      developer_agent_id: UUID
      reviewer_agent_id: UUID
      developer_request: DeveloperRequest
      reviewer_profile: AgentProfile
      max_review_cycles: Annotated[int, Field(ge=1, le=10)]
      timeout_seconds: Annotated[float, Field(gt=0.0, le=3600.0, allow_inf_nan=False)]
      correlation_id: UUID
  ```

  Add a bounded immutable `WorkflowHandoffContext` containing canonical task/project UUID text,
  title, description, criteria, Developer/Reviewer slugs, Reviewer profile, and required profiles.
  Add a result model validator enforcing truthful outcome/status pairs and cycle counts.

  `WorkflowError` accepts only an enum code and maps it to an application-owned safe message. Codes
  cover invalid input/scope/state/role/agent, unsafe handoff, timeout, collaborator failure,
  persistence failure, and internal failure. Caller-provided messages are not accepted.

- [ ] **Step 4: Run focused tests and quality checks**

  Run:

  ```bash
  .venv/bin/pytest tests/workflows/test_types.py -q
  .venv/bin/ruff check core/workflows tests/workflows
  .venv/bin/mypy core/workflows tests/workflows
  ```

  Expected: all pass without warnings.

- [ ] **Step 5: Commit Task 1**

  ```bash
  git add core/workflows tests/workflows
  git commit -m "feat(workflow): define bounded orchestration contracts"
  ```

---

### Task 2: Add fail-closed persistent workflow preflight

**Files:**
- Create: `core/workflows/validation.py`
- Modify: `core/workflows/__init__.py`
- Modify: `tests/workflows/factories.py`
- Create: `tests/workflows/test_validation.py`

**Interfaces:**
- Consumes: `DeveloperReviewerWorkflowRequest`, SQLAlchemy `Session`, `Task`, `Agent`, existing Developer/Reviewer validation rules, and canonical workflow bounds.
- Produces: `ValidatedWorkflowScope` and `validate_workflow_request(session, request) -> ValidatedWorkflowScope`.

- [ ] **Step 1: Write PostgreSQL preflight tests**

  Build Project, READY Task, Developer Agent, and Reviewer Agent through the existing PostgreSQL
  fixture. Test a valid scope and parameterize rejection before collaborators for:

  - non-exact or type-confused request;
  - missing task or agent;
  - task not `READY`;
  - equal persistent UUIDs or equal profile slugs;
  - wrong roles and `OFFLINE`/`BLOCKED` status;
  - mismatched Developer slug, runtime task UUID, execution task/project/agent/correlation IDs;
  - Developer objective/criteria inconsistent with the persistent task;
  - absent, blank, non-string, duplicated, or over-bounds persistent criteria/title/description;
  - Reviewer profile inconsistent with persistent Reviewer slug/role/status.

  Assert task status, assignment, audit row count, Developer calls, Reviewer calls, and handoff calls
  remain unchanged after every rejected preflight.

- [ ] **Step 2: Run validation tests and verify RED**

  Run: `.venv/bin/pytest tests/workflows/test_validation.py -q`

  Expected: import or assertion failure because workflow validation is absent.

- [ ] **Step 3: Implement strict canonical preflight**

  First reject `type(request) is not DeveloperReviewerWorkflowRequest`; then dump and strictly
  revalidate before reading nested fields. Load persistent records with the injected session and
  validate all cross-scope equality. Do not interpolate rejected values into errors.

  Return a frozen slots dataclass:

  ```python
  @dataclass(frozen=True, slots=True)
  class ValidatedWorkflowScope:
      request: DeveloperReviewerWorkflowRequest
      task: Task
      developer: Agent
      reviewer: Agent
      handoff_context: WorkflowHandoffContext
  ```

  Canonicalize persistent criteria to a unique tuple of nonblank strings and construct the bounded
  handoff context. Keep ORM objects internal; never place them in public Pydantic results.

- [ ] **Step 4: Run validation and regression tests**

  Run:

  ```bash
  .venv/bin/pytest tests/workflows/test_validation.py tests/developer/test_validation.py tests/reviewer/test_validation.py -q
  .venv/bin/ruff check core/workflows tests/workflows
  .venv/bin/mypy core/workflows tests/workflows
  ```

  Expected: all pass.

- [ ] **Step 5: Commit Task 2**

  ```bash
  git add core/workflows/validation.py core/workflows/__init__.py tests/workflows
  git commit -m "feat(workflow): validate persistent agent scope"
  ```

---

### Task 3: Define and enforce the fresh Reviewer handoff boundary

**Files:**
- Create: `core/workflows/ports.py`
- Create: `core/workflows/handoff.py`
- Modify: `core/workflows/__init__.py`
- Create: `tests/workflows/fakes.py`
- Create: `tests/workflows/test_handoff.py`

**Interfaces:**
- Consumes: `WorkflowHandoffContext`, latest `DeveloperResult`, one-based cycle, and existing Developer/Reviewer contracts.
- Produces: `DeveloperRunner`, `ReviewerRunner`, `ReviewerHandoffBuilder` protocols and `validate_reviewer_handoff(context, developer_result, request) -> ReviewerRequest`.

- [ ] **Step 1: Write handoff protocol and validation tests**

  Define deterministic recording fakes in tests. Test that one valid handoff preserves only:

  - canonical task/project and independent agent identifiers;
  - task title, description, criteria, and current bounded diff;
  - exact latest Developer report;
  - exact required check profiles;
  - lossless conversion of latest `DeveloperCheckResult` values into `ReviewCheck` values;
  - exact Reviewer profile from the validated persistent scope.

  Parameterize rejection of stale Developer report/checks, missing/extra/reordered check evidence,
  stale identifiers, wrong profile, write/command permissions or tools, malformed diff, and
  type-confused `ReviewerRequest`. Verify rejected values never appear in exception strings or repr.

- [ ] **Step 2: Run handoff tests and verify RED**

  Run: `.venv/bin/pytest tests/workflows/test_handoff.py -q`

  Expected: import failure because ports and handoff validation are absent.

- [ ] **Step 3: Implement structural ports and exact handoff revalidation**

  Define runtime-checkable protocols with exact asynchronous signatures:

  ```python
  class DeveloperRunner(Protocol):
      async def run(self, request: DeveloperRequest) -> DeveloperResult: ...

  class ReviewerRunner(Protocol):
      async def run(self, request: ReviewerRequest) -> ReviewerResult: ...

  class ReviewerHandoffBuilder(Protocol):
      async def build(
          self,
          context: WorkflowHandoffContext,
          developer_result: DeveloperResult,
          cycle: int,
      ) -> ReviewerRequest: ...
  ```

  Canonicalize both `DeveloperResult` and returned `ReviewerRequest` before equality checks. Convert
  Developer checks through explicit field copying; compare values, never object identity. Invoke
  existing `validate_reviewer_request` after workflow-specific checks.

- [ ] **Step 4: Run handoff and agent regression tests**

  Run:

  ```bash
  .venv/bin/pytest tests/workflows/test_handoff.py tests/developer tests/reviewer -q
  .venv/bin/ruff check core/workflows tests/workflows
  .venv/bin/mypy core/workflows tests/workflows
  ```

  Expected: all pass with no hidden calls.

- [ ] **Step 5: Commit Task 3**

  ```bash
  git add core/workflows tests/workflows
  git commit -m "feat(workflow): enforce fresh review handoff"
  ```

---

### Task 4: Add bounded append-only workflow audit checkpoints

**Files:**
- Create: `core/workflows/audit.py`
- Modify: `core/workflows/errors.py`
- Modify: `core/workflows/__init__.py`
- Create: `tests/workflows/test_audit.py`

**Interfaces:**
- Consumes: `Session`, validated persistent scope, cycle, Reviewer decision/score/finding count, `TaskStateMachine`, and existing append-only `AuditEvent`.
- Produces: `WorkflowEventType`, `append_workflow_event(...)`, and checkpoint helpers that atomically commit a status transition plus bounded workflow events.

- [ ] **Step 1: Write real-PostgreSQL audit tests**

  Test each event type and assert exact allowlisted JSON data. Test shared correlation UUID,
  Developer/Reviewer actor attribution, project/task linkage, append-only behavior, chronological
  status events, and absence of source markers placed in task text, diff, findings, reports,
  exception strings, and workspace paths.

  Add transaction tests proving assignment plus `READY -> ASSIGNED` plus `WORKFLOW_STARTED` commit
  atomically, a transition failure rolls back its pending workflow event, and no helper closes the
  injected session.

- [ ] **Step 2: Run audit tests and verify RED**

  Run: `.venv/bin/pytest tests/workflows/test_audit.py -q`

  Expected: import failure because workflow audit helpers are absent.

- [ ] **Step 3: Implement the allowlisted audit/checkpoint layer**

  Define closed event values and explicit constructors. Never accept arbitrary metadata mappings.
  Use `AuditEvent` plus `TaskStateMachine`, add all rows/status mutations, and call `session.commit()`
  once per checkpoint. On SQLAlchemy failure call `session.rollback()` and raise only
  `WorkflowError(WorkflowErrorCode.PERSISTENCE_FAILURE)` from `None`.

  Assignment checkpoint sets `task.assigned_agent_id` before the audited READY transition. Later
  helpers accept only stable scalar values (`cycle`, `decision`, `review_score`, `finding_count`,
  `max_review_cycles`).

- [ ] **Step 4: Run audit and state-machine regression tests**

  Run:

  ```bash
  .venv/bin/pytest tests/workflows/test_audit.py tests/database/test_task_state_machine.py tests/database/test_append_only.py -q
  .venv/bin/ruff check core/workflows tests/workflows
  .venv/bin/mypy core/workflows tests/workflows
  ```

  Expected: all pass.

- [ ] **Step 5: Commit Task 4**

  ```bash
  git add core/workflows tests/workflows
  git commit -m "feat(workflow): add audited durable checkpoints"
  ```

---

### Task 5: Implement the bounded Developer–Reviewer correction loop

**Files:**
- Create: `core/workflows/orchestrator.py`
- Modify: `core/workflows/__init__.py`
- Modify: `tests/workflows/fakes.py`
- Create: `tests/workflows/test_orchestrator.py`
- Create: `tests/workflows/test_safety.py`

**Interfaces:**
- Consumes: validated request/scope, `DeveloperRunner`, `ReviewerRunner`, `ReviewerHandoffBuilder`, workflow audit/checkpoint helpers, and `asyncio.timeout`.
- Produces: `WorkflowOrchestrator.run(request) -> DeveloperReviewerWorkflowResult`.

- [ ] **Step 1: Write one-cycle approval RED test**

  Use recording Developer, handoff, and Reviewer fakes. Start with a persistent READY task. Assert
  exact status sequence, Developer assignment, one call to each collaborator, final `WAITING_QA`,
  truthful counts, final bounded reports, expected audit sequence, no QA/Security calls, and no
  collaborator closure.

- [ ] **Step 2: Run the approval test and verify RED**

  Run: `.venv/bin/pytest tests/workflows/test_orchestrator.py -q -k one_cycle`

  Expected: import failure because `WorkflowOrchestrator` is absent.

- [ ] **Step 3: Implement minimum one-cycle orchestration**

  Constructor:

  ```python
  class WorkflowOrchestrator:
      def __init__(
          self,
          session: Session,
          developer: DeveloperRunner,
          reviewer: ReviewerRunner,
          handoff_builder: ReviewerHandoffBuilder,
      ) -> None: ...

      async def run(
          self,
          request: DeveloperReviewerWorkflowRequest,
      ) -> DeveloperReviewerWorkflowResult: ...
  ```

  Validate before calls, enter one overall `asyncio.timeout`, commit assignment and IN_PROGRESS,
  call Developer, checkpoint WAITING_REVIEW, build/revalidate handoff, call Reviewer, then checkpoint
  WAITING_QA only for final `APPROVED`.

- [ ] **Step 4: Write correction and exhaustion RED tests**

  Add tests for one rejection then approval and repeated rejection at limits 1 and 3. Assert fresh
  handoff cycle numbers and diff markers, exact call counts, no retained earlier results, transition
  chronology, and exhaustion at `WAITING_HUMAN` without an extra Developer/Reviewer call.

- [ ] **Step 5: Run correction tests and verify RED**

  Run: `.venv/bin/pytest tests/workflows/test_orchestrator.py -q -k 'correction or exhausted'`

  Expected: assertions fail because the minimum implementation has no correction loop.

- [ ] **Step 6: Implement the explicit bounded correction loop**

  Iterate `range(1, max_review_cycles + 1)`. Never use recursion. A requested change commits
  `CHANGES_REQUESTED`; continue through an audited `IN_PROGRESS` transition only when another cycle
  remains. Otherwise commit `WAITING_HUMAN` plus exhaustion audit and return the exhausted result.

- [ ] **Step 7: Write failure, timeout, cancellation, and sanitization RED tests**

  Test Developer error, handoff error, Reviewer error, unexpected exception with secret marker,
  global timeout, and cancellation during each collaborator. Assert:

  - ordinary failures become stable `WorkflowError` values and durable `WAITING_HUMAN` when legal;
  - raw exception context, traceback frames, source markers, and absolute paths are absent;
  - timeout causes no retry or extra call;
  - `CancelledError` is re-raised and causes no subsequent transition, audit, model, tool, or handoff
    call;
  - injected collaborators/session remain open;
  - orchestrator instance retains only injected collaborators/session, not requests or results.

- [ ] **Step 8: Run safety tests and verify RED**

  Run: `.venv/bin/pytest tests/workflows/test_safety.py -q`

  Expected: failure until safe normalization and cancellation behavior exist.

- [ ] **Step 9: Implement fail-closed normalization without retries**

  Catch `asyncio.CancelledError` separately and re-raise. Convert timeout and ordinary exceptions to
  application-owned codes, clear raw traceback frames/references, perform one legal safe escalation
  checkpoint, then raise from `None`. Never catch `BaseException`; never invoke a collaborator from
  error handling.

- [ ] **Step 10: Run focused orchestration and full regression tests**

  Run:

  ```bash
  .venv/bin/pytest tests/workflows -q
  .venv/bin/pytest tests/tasks tests/database/test_task_state_machine.py tests/developer tests/reviewer -q
  .venv/bin/ruff check core/workflows tests/workflows
  .venv/bin/mypy core/workflows tests/workflows
  ```

  Expected: all pass.

- [ ] **Step 11: Commit Task 5**

  ```bash
  git add core/workflows tests/workflows
  git commit -m "feat(workflow): orchestrate bounded review cycles"
  ```

---

### Task 6: Add real-provider-contract end-to-end tests and documentation

**Files:**
- Create: `tests/workflows/test_integration.py`
- Create: `docs/developer-reviewer-workflow.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`

**Interfaces:**
- Consumes: concrete `DeveloperAgent`, concrete `ReviewerAgent`, deterministic
  `FakeLLMProvider`, real PostgreSQL schema from Alembic, recording tool/audit fakes, and the public
  `core.workflows` API.
- Produces: documented and verified Phase 16 behavior with only completed Phase 16 boxes checked.

- [ ] **Step 1: Write end-to-end RED tests with concrete agents**

  Build deterministic provider scripts for:

  - Developer succeeds and Reviewer approves in one cycle;
  - first Reviewer requests changes, second Developer cycle produces fresh evidence, and second
    Reviewer approves;
  - all Reviewer cycles request changes and exhaust the limit.

  Use real PostgreSQL records and schema, concrete bounded agents, real task transitions/audit, and
  a deterministic handoff builder that supplies a different bounded diff per cycle. Assert exact
  provider-call counts, terminal states, audit chronology, result bounds, and no Phase 17 behavior.

- [ ] **Step 2: Run integration tests and verify RED**

  Run: `.venv/bin/pytest tests/workflows/test_integration.py -q`

  Expected: fail on any missing composition behavior discovered by the concrete contracts.

- [ ] **Step 3: Make only focused integration corrections**

  Correct mismatches in workflow composition without weakening Developer, Reviewer, task-state,
  audit, timeout, or security contracts. Do not add QA/Security placeholders or abstractions.

- [ ] **Step 4: Document the completed Phase 16 boundary**

  Document exact flow, configuration, handoff contents, checkpoint/audit behavior, timeout and
  cancellation semantics, resource ownership, safe failures, usage example, and explicit Phase 17
  exclusions in `docs/developer-reviewer-workflow.md`.

  Update README status/roadmap and AGENTS architecture/commands. Change only the seven Phase 16
  checklist boxes after corresponding tests pass. Leave Phase 17 and later boxes untouched.

- [ ] **Step 5: Run the fresh final verification gate**

  Run:

  ```bash
  .venv/bin/pytest -q
  .venv/bin/pytest --collect-only -q
  .venv/bin/ruff check .
  .venv/bin/ruff format --check .
  .venv/bin/mypy .
  git diff --check
  docker compose build api
  docker compose up -d api
  docker compose ps
  docker compose exec -T api alembic current
  curl --fail --silent http://localhost:8000/health
  ```

  Expected: full suite passes, clean Ruff/format/mypy output, Docker services healthy, Alembic at
  head, and health JSON `{"status":"ok"}`.

- [ ] **Step 6: Perform final scope and security review**

  Compare the branch against `phase-15/reviewer-agent`. Verify only Phase 16 checklist changes,
  no prompt/diff/output persistence, no hidden retry, no unbounded collection or loop, no injected
  resource closure, no direct task status mutation, no raw exception leakage, no Phase 17 code, and
  no staged `CLAUDE.local.md`.

- [ ] **Step 7: Commit Task 6**

  ```bash
  git add core/workflows tests/workflows docs/developer-reviewer-workflow.md README.md AGENTS.md SYNAPSEOS_DEVELOPMENT_CHECKLIST.md
  git commit -m "docs(workflow): complete Phase 16 delivery"
  ```

- [ ] **Step 8: Push and open the stacked pull request**

  Push `phase-16/developer-reviewer-workflow` and open a pull request with base
  `phase-15/reviewer-agent`. Include test count, static checks, Docker/PostgreSQL/Alembic/API
  evidence, security-review outcome, Phase 16 scope, and explicit Phase 17 exclusion.
