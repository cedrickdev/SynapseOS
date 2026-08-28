# Phase 15 Reviewer Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one bounded, read-only Reviewer Agent that independently evaluates Developer evidence and returns a deterministic structured approval decision.

**Architecture:** Add a focused `core/reviewer` package. One provider call produces strict qualitative analysis; a separate deterministic gate validates author independence, mandatory checks, Developer outcome, findings, and confidence before allowing approval. The Reviewer receives evidence as input and invokes no repository tool or agent loop.

**Tech Stack:** Python 3.12, Pydantic v2, provider-neutral `LLMProvider`, deterministic `FakeLLMProvider`, pytest, Ruff, mypy strict.

**Spec:** `docs/superpowers/specs/2026-08-28-phase-15-reviewer-agent-design.md`

## Global Constraints

- Implement Phase 15 only; do not add Phase 16 orchestration or task transitions.
- Reviewer and Developer IDs must differ before any provider call.
- The Reviewer is read-only and receives no write, command, commit, merge, deployment, or permission-mutation capability.
- One review performs exactly one bounded provider call, no retry, and zero tool calls.
- Mandatory failed or missing checks can never produce `APPROVED`.
- Deterministic evidence outranks Developer and LLM claims.
- No prompt, response, diff, file content, command output, absolute path, environment, secret, or raw exception is retained automatically.
- Cancellation propagates immediately and injected resources remain caller-owned.
- Every production behavior begins with an observed failing test.

---

### Task 1: Reviewer contracts and sanitized errors

**Files:**
- Create: `core/reviewer/__init__.py`
- Create: `core/reviewer/types.py`
- Create: `core/reviewer/errors.py`
- Create: `tests/reviewer/__init__.py`
- Create: `tests/reviewer/factories.py`
- Create: `tests/reviewer/test_types.py`

**Interfaces:**
- Produces: `ReviewDecision`, `FindingSeverity`, `ReviewCheck`, `ReviewFinding`, `ReviewAnalysis`, `ReviewerRequest`, `ReviewerResult`, `ReviewerError`, and `ReviewerErrorCode`.
- Consumes: `AgentProfile`, `AgentReport`, `CommandCategory`, `CommandProfileId`, and `CommandTerminalStatus`.

- [ ] **Step 1: Write failing immutable contract tests**

  Define fixtures for distinct `developer-01` and `reviewer-01` identities. Assert strict unknown-field rejection, immutable tuple copying, unique acceptance criteria/check profiles, normalized relative finding paths, finite confidence and score in `0.0..1.0`, at most 16 criteria/checks, at most 64 findings, and bounded text/diff fields.

- [ ] **Step 2: Run the focused test and confirm RED**

  Run: `.venv/bin/pytest tests/reviewer/test_types.py -q`

  Expected: collection fails because `core.reviewer` does not exist.

- [ ] **Step 3: Implement the minimal strict models and stable errors**

  Use frozen Pydantic models with `extra="forbid"` and `hide_input_in_errors=True`. Define decisions `APPROVED` and `CHANGES_REQUESTED`; severities `INFO`, `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`; bound retained rationales and recommendations; reject absolute/traversing paths. `ReviewCheck` must validate the canonical category and status/exit-code relationship exactly as `DeveloperCheckResult` does.

- [ ] **Step 4: Run focused tests and quality checks**

  Run: `.venv/bin/pytest tests/reviewer/test_types.py -q`

  Run: `.venv/bin/ruff check core/reviewer tests/reviewer`

  Run: `.venv/bin/mypy core/reviewer tests/reviewer`

- [ ] **Step 5: Commit**

  Commit: `feat(reviewer): define bounded review contracts`

### Task 2: Fail-closed Reviewer preflight

**Files:**
- Create: `core/reviewer/validation.py`
- Create: `tests/reviewer/test_validation.py`
- Modify: `core/reviewer/__init__.py`

**Interfaces:**
- Produces: `ValidatedReviewerRequest` and `validate_reviewer_request(request: ReviewerRequest) -> ValidatedReviewerRequest`.
- Consumes: Task 1 contracts and canonical `AgentStatus`/`Permission` enums.

- [ ] **Step 1: Write failing preflight tests**

  Assert rejection before collaborator invocation for self-review, wrong role, inactive Reviewer,
  profile/request identity mismatch, inconsistent task/project scope, missing criteria/diff/checks,
  write or command tools, unknown tools, write/shell/test permissions, and malformed canonical
  permission IDs. Assert acceptance only for active Reviewer profiles whose tools are a subset of
  `read_file`, `list_files`, `search_text`, `git_status`, and `git_diff`, and whose permissions are
  a subset of `filesystem.read` and `git.read` with `filesystem.read` required.

- [ ] **Step 2: Run the focused test and confirm RED**

  Run: `.venv/bin/pytest tests/reviewer/test_validation.py -q`

  Expected: import failure for `validate_reviewer_request`.

- [ ] **Step 3: Implement minimal canonical validation**

  Return a frozen dataclass containing the request and canonical permission set. Raise only stable,
  sanitized `ReviewerError` messages; never interpolate rejected IDs, paths, diff, criteria, or
  profile content.

- [ ] **Step 4: Run focused tests and quality checks**

  Run: `.venv/bin/pytest tests/reviewer/test_validation.py tests/reviewer/test_types.py -q`

  Run: `.venv/bin/ruff check core/reviewer tests/reviewer`

  Run: `.venv/bin/mypy core/reviewer tests/reviewer`

- [ ] **Step 5: Commit**

  Commit: `feat(reviewer): enforce independent read-only scope`

### Task 3: One-shot structured review analysis

**Files:**
- Create: `core/reviewer/analysis.py`
- Create: `tests/reviewer/test_analysis.py`
- Modify: `core/reviewer/__init__.py`

**Interfaces:**
- Produces: `ReviewAnalyzer(provider: LLMProvider, *, max_tokens: int)` and `analyze(request: ReviewerRequest) -> ReviewAnalysis`.
- Consumes: `LLMRequest`, `LLMMessage`, strict `decode_structured_output`, Task 1 models, and validated requests from Task 2.

- [ ] **Step 1: Write failing one-shot analysis tests**

  With `FakeLLMProvider`, assert one request, explicit `max_tokens`, one system prompt, one user
  message containing the bounded evidence, strict JSON decoding, no metadata containing evidence,
  and no second request. Add malformed JSON, extra-field, excessive-findings, absolute-path,
  provider-error, and cancellation cases. Assert cancellation is propagated and all other failures
  become sanitized `ReviewerError` values without response content.

- [ ] **Step 2: Run the focused test and confirm RED**

  Run: `.venv/bin/pytest tests/reviewer/test_analysis.py -q`

  Expected: import failure for `ReviewAnalyzer`.

- [ ] **Step 3: Implement one bounded provider call**

  Build one provider-neutral request with temperature `0.0`, explicit max tokens no greater than
  `4096`, and no sensitive metadata. Serialize only validated fields with deterministic compact
  JSON. Decode directly to `ReviewAnalysis`, discard raw response immediately, normalize known
  provider/validation failures, and do not catch `asyncio.CancelledError`.

- [ ] **Step 4: Run focused tests and quality checks**

  Run: `.venv/bin/pytest tests/reviewer/test_analysis.py tests/reviewer/test_validation.py -q`

  Run: `.venv/bin/ruff check core/reviewer tests/reviewer`

  Run: `.venv/bin/mypy core/reviewer tests/reviewer`

- [ ] **Step 5: Commit**

  Commit: `feat(reviewer): add one-shot review analysis`

### Task 4: Deterministic decision gate and score

**Files:**
- Create: `core/reviewer/decision.py`
- Create: `core/reviewer/scoring.py`
- Create: `tests/reviewer/test_decision.py`
- Create: `tests/reviewer/test_scoring.py`
- Modify: `core/reviewer/__init__.py`

**Interfaces:**
- Produces: `build_reviewer_result(request: ReviewerRequest, analysis: ReviewAnalysis) -> ReviewerResult` and `calculate_review_score(checks: tuple[ReviewCheck, ...], findings: tuple[ReviewFinding, ...]) -> Decimal`.
- Consumes: Task 1 models and `AgentReportOutcome`.

- [ ] **Step 1: Write failing gate tests**

  Assert `APPROVED` only with successful Developer report, all required checks present and passing,
  no high/critical finding, model approval, and confidence at least `0.70`. Separately prove that
  missing, failed, truncated/inconsistent checks, unsuccessful Developer
  reports, high/critical findings, low confidence, and model-requested changes all yield
  `CHANGES_REQUESTED`. Assert the gate never upgrades a proposed rejection.

- [ ] **Step 2: Write failing deterministic score tests**

  Assert identical inputs produce identical `Decimal` scores; all-pass/no-finding yields `1.0`;
  failed checks and increasing severity reduce the score monotonically; values remain in
  `0.0..1.0`; the model cannot supply or override the score.

- [ ] **Step 3: Run focused tests and confirm RED**

  Run: `.venv/bin/pytest tests/reviewer/test_decision.py tests/reviewer/test_scoring.py -q`

  Expected: imports fail for decision and scoring functions.

- [ ] **Step 4: Implement the minimal deterministic gate and score**

  Index checks by profile, evaluate every required profile, append stable synthetic findings for
  deterministic blockers, cap findings at 64, and preserve model findings in order. Compute the
  score from fixed `Decimal` weights for check completion and severities, quantized consistently;
  never call a provider from either function.

- [ ] **Step 5: Run focused tests and quality checks**

  Run: `.venv/bin/pytest tests/reviewer/test_decision.py tests/reviewer/test_scoring.py -q`

  Run: `.venv/bin/ruff check core/reviewer tests/reviewer`

  Run: `.venv/bin/mypy core/reviewer tests/reviewer`

- [ ] **Step 6: Commit**

  Commit: `feat(reviewer): enforce deterministic review gate`

### Task 5: Reviewer Agent composition and safety integration

**Files:**
- Create: `core/reviewer/agent.py`
- Create: `tests/reviewer/test_agent.py`
- Create: `tests/reviewer/test_safety.py`
- Create: `tests/reviewer/test_integration.py`
- Modify: `core/reviewer/__init__.py`

**Interfaces:**
- Produces: `ReviewerAgent(provider: LLMProvider, *, max_tokens: int = 2048)` and `run(request: ReviewerRequest) -> ReviewerResult`.
- Consumes: Tasks 2–4 validation, analyzer, and deterministic decision gate.

- [ ] **Step 1: Write failing composition tests**

  Assert call order `validate -> analyze once -> deterministic gate`, no provider invocation on
  preflight failure, and exactly one provider request on success. Prove the class has no tool
  executor, write API, retry, close, merge, approval mutation, or workflow dependency.

- [ ] **Step 2: Write failing security and lifecycle tests**

  Feed secrets, absolute paths, prompt-injection text, oversized provider output, malformed error
  messages, and contradictory approval evidence. Assert results/errors contain none of the source
  content; cancellation propagates; and a provider exposing `close()` is never closed.

- [ ] **Step 3: Write failing FakeLLMProvider integration scenarios**

  Cover a fully passing review that returns `APPROVED`, a quality finding that returns
  `CHANGES_REQUESTED`, and an LLM approval over a failed required test that is deterministically
  downgraded. Assert one request per scenario and stable score/findings.

- [ ] **Step 4: Run focused tests and confirm RED**

  Run: `.venv/bin/pytest tests/reviewer/test_agent.py tests/reviewer/test_safety.py tests/reviewer/test_integration.py -q`

  Expected: import failure for `ReviewerAgent`.

- [ ] **Step 5: Implement minimal composition**

  Store only the injected provider and immutable token ceiling. Validate synchronously, perform one
  awaited analysis, derive the result synchronously, and return it. Do not retain requests,
  responses, evidence, or result history on the agent instance.

- [ ] **Step 6: Run the complete Reviewer suite and quality checks**

  Run: `.venv/bin/pytest tests/reviewer -q`

  Run: `.venv/bin/ruff check core/reviewer tests/reviewer`

  Run: `.venv/bin/ruff format --check core/reviewer tests/reviewer`

  Run: `.venv/bin/mypy core/reviewer tests/reviewer`

- [ ] **Step 7: Commit**

  Commit: `feat(reviewer): compose bounded Reviewer Agent`

### Task 6: Documentation, complete verification, and delivery

**Files:**
- Create: `docs/reviewer-agent.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`
- Modify only Phase 15 code/tests when fixing verified defects.

**Interfaces:**
- Consumes: complete verified Phase 15 implementation.
- Produces: user/developer documentation, truthful Phase 15 checklist state, full verification evidence, and a stacked pull request.

- [ ] **Step 1: Document the exact implemented boundary**

  Document inputs, one-shot analysis, deterministic gate, scoring, read-only authority, security
  limits, cancellation/resource ownership, FakeLLMProvider usage, and explicit Phase 16 exclusion.
  Update README status/roadmap and AGENTS commands without claiming unimplemented behavior.

- [ ] **Step 2: Update only genuinely complete Phase 15 checkboxes**

  Change only Phase 15 boxes with direct implementation and test evidence. Leave Phase 12, Phase
  16, QA, Security, workflow, frontend, and Context Intelligence boxes unchanged.

- [ ] **Step 3: Run the complete local gate**

  Run: `.venv/bin/pytest -q`

  Run: `.venv/bin/ruff check .`

  Run: `.venv/bin/ruff format --check .`

  Run: `.venv/bin/mypy .`

- [ ] **Step 4: Verify Docker and PostgreSQL acceptance**

  Build and start the Compose API/database stack, confirm both services are healthy, run Alembic to
  head, execute PostgreSQL-backed tests, and call `/health`. Do not delete user volumes.

- [ ] **Step 5: Request independent code and security review**

  Review the complete branch for self-review bypass, write authority, duplicate provider calls,
  missing-test approval, unbounded data, prompt/diff leakage, absolute paths, cancellation,
  injected-resource closure, and accidental Phase 16 behavior.

- [ ] **Step 6: Resolve valid findings with fresh RED-GREEN cycles**

  Add one failing regression test for each accepted finding before production changes. Rerun the
  focused suite and all gates after fixes.

- [ ] **Step 7: Verify scope and cleanliness**

  Run `git diff --check`, confirm Phase 16+ checkboxes are untouched, scan staged content for
  secrets, and leave untracked `CLAUDE.local.md` unmodified and unstaged.

- [ ] **Step 8: Commit, push, and open the stacked PR**

  Use conventional commits, push `phase-15/reviewer-agent`, and open a PR against
  `phase-14/developer-agent`. Include scope, decisions, safeguards, tests, Docker/PostgreSQL
  evidence, known limitations, and explicit Phase 16 exclusion.
