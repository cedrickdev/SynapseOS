# Phase 14 Developer Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one bounded DeveloperAgent that uses the Phase 13 runtime and existing secure tools to inspect, change, and verify a managed repository.

**Architecture:** `DeveloperAgent` is a composition service, not a second loop. Focused modules validate the role boundary, compile eligible skill instructions, collect metadata-only tool evidence, and derive a truthful report after exactly one `AgentRuntime` run.

**Tech Stack:** Python 3.12, Pydantic v2, asyncio, pytest, existing SynapseOS runtime/skills/tools/permissions/workspaces/commands.

**Spec:** `docs/superpowers/specs/2026-08-28-phase-14-developer-agent-design.md`

## Global Constraints

- Implement Phase 14 only; do not add ReviewerAgent, multi-agent orchestration, MCP, memory, reputation, merge, deployment, or Phase 15 behavior.
- Use the existing `AgentRuntime`, `LLMLoopReasoner`, `ToolExecutor`, workspace tools, and fixed command profiles; do not duplicate those boundaries.
- Use strict RED-GREEN-REFACTOR TDD and run every new test once in RED before production code.
- Keep all source code, comments, tests, documentation, branches, and commits in English.
- Bound skill context to eight complete skills and 12 KiB UTF-8; never truncate instructions.
- Retain at most 128 metadata-only evidence records and never retain prompts, responses, file contents, patches, command output, absolute paths, environment values, or raw exceptions.
- Execute each model-selected tool call exactly once with no implicit retry.
- Preserve mandatory runtime/tool timeouts, cancellation, token/tool/iteration/failure limits, permission checks, and audit behavior.
- Test repository behavior through real adapters; use `FakeLLMProvider` only at the external model boundary.
- Do not use `metadata.create_all()`; database verification uses PostgreSQL migrated by Alembic.
- Never stage or modify `CLAUDE.local.md`.

---

### Task 1: Developer boundary contracts and validation

**Files:**
- Create: `core/developer/__init__.py`
- Create: `core/developer/errors.py`
- Create: `core/developer/types.py`
- Create: `core/developer/validation.py`
- Create: `tests/developer/__init__.py`
- Create: `tests/developer/factories.py`
- Create: `tests/developer/test_types.py`
- Create: `tests/developer/test_validation.py`

**Interfaces:**
- Consumes: `AgentProfile`, `AgentReport`, `RuntimeTask`, `RuntimeResult`, `ToolExecutionContext`, `CommandProfileId`.
- Produces: `DeveloperErrorCode`, `DeveloperError`, `DeveloperRequest`, `DeveloperCheckResult`, `DeveloperResult`, `validate_developer_request(request) -> ValidatedDeveloperRequest`.

- [ ] **Step 1: Write failing immutable-contract tests**

  Cover strict/frozen models, one-to-four required checks, bounded metadata collections, copied input collections, unique relative changed paths, and rejection of absolute/traversing paths.

- [ ] **Step 2: Run contract tests and verify RED**

  Run: `.venv/bin/pytest tests/developer/test_types.py -q`

  Expected: collection fails because `core.developer` does not exist.

- [ ] **Step 3: Implement minimal contracts and stable sanitized errors**

  Define strict Pydantic models. `DeveloperCheckResult` stores only profile ID, category, status, optional bounded exit code, and truncation. `DeveloperResult` stores the runtime result, existing `AgentReport`, selected/omitted IDs, changed relative paths, and checks.

- [ ] **Step 4: Run contract tests and verify GREEN**

  Run: `.venv/bin/pytest tests/developer/test_types.py -q`

- [ ] **Step 5: Write failing request-validation tests**

  Cover exact Developer role, active status, matching agent/task IDs, canonical permission identifiers, closed tool allowlist, mandatory read/write/command capabilities, declared-context equality, and rejection of Git/unknown required profiles before collaborator calls.

- [ ] **Step 6: Run validation tests and verify RED**

  Run: `.venv/bin/pytest tests/developer/test_validation.py -q`

  Expected: failures name missing validation behavior.

- [ ] **Step 7: Implement fail-closed validation**

  Return a private immutable validated value containing canonical permissions and checks. Map all public validation failures to stable `DeveloperErrorCode` values with input-free messages.

- [ ] **Step 8: Run focused tests and quality checks**

  Run: `.venv/bin/pytest tests/developer/test_types.py tests/developer/test_validation.py -q`

  Run: `.venv/bin/ruff check core/developer tests/developer`

  Run: `.venv/bin/mypy core/developer tests/developer`

- [ ] **Step 9: Commit**

  Commit: `feat(developer): define secure role boundary`

### Task 2: Deterministic skill context policy

**Files:**
- Create: `core/developer/skills.py`
- Create: `tests/developer/test_skills.py`
- Modify: `core/developer/__init__.py`

**Interfaces:**
- Consumes: `ValidatedDeveloperRequest`, `SkillRegistry`, `SkillSelector`, `SkillSelectionRequest`.
- Produces: `DeveloperSkillContext(selected_ids, omitted_ids, prompt_fragment)` and `build_skill_context(...)`.

- [ ] **Step 1: Write failing eligibility and ordering tests**

  Use real `SkillRegistry` and `SkillSelector`. Prove undeclared, missing, permission-incompatible, tool-incompatible, and zero-score skills are excluded; selected skills follow selector order and are capped at eight.

- [ ] **Step 2: Run selection tests and verify RED**

  Run: `.venv/bin/pytest tests/developer/test_skills.py -q`

- [ ] **Step 3: Implement deterministic eligibility filtering**

  Select once with the request's domains, technologies, tags, objective, role, and canonical permissions. Intersect results with profile declarations and require recommended tools to be a subset of declared tools.

- [ ] **Step 4: Write failing byte-budget and secrecy tests**

  Prove complete instructions are included or omitted, never truncated; UTF-8 byte count is at most 12,288; final composed prompt is at most 16,384; stable IDs report omissions; exceptions never contain instructions.

- [ ] **Step 5: Run budget tests and verify RED**

  Run: `.venv/bin/pytest tests/developer/test_skills.py -q`

- [ ] **Step 6: Implement the subordinate skill compiler**

  Add a fixed security preamble and deterministic separators. Account for encoded bytes before appending each complete skill and fail closed if the base profile prompt plus compiled context exceeds the reasoner ceiling.

- [ ] **Step 7: Run focused tests and quality checks**

  Run: `.venv/bin/pytest tests/developer/test_skills.py -q`

  Run: `.venv/bin/ruff check core/developer tests/developer`

  Run: `.venv/bin/mypy core/developer tests/developer`

- [ ] **Step 8: Commit**

  Commit: `feat(developer): add bounded skill context`

### Task 3: Metadata-only evidence and deterministic reporting

**Files:**
- Create: `core/developer/evidence.py`
- Create: `core/developer/reporting.py`
- Create: `tests/developer/test_evidence.py`
- Create: `tests/developer/test_reporting.py`
- Modify: `core/developer/__init__.py`

**Interfaces:**
- Consumes: the runtime tool-executor protocol, `ToolResult`, `RuntimeResult`, required command profiles.
- Produces: `EvidenceCollectingToolExecutor.execute(...)`, immutable evidence snapshot, and `build_developer_result(...) -> DeveloperResult`.

- [ ] **Step 1: Write failing evidence-wrapper tests**

  Prove one delegation per call, a 128-record cap, first-observed unique successful changed paths, latest command result per profile, stable failed-tool codes, and no ownership/close behavior.

- [ ] **Step 2: Run evidence tests and verify RED**

  Run: `.venv/bin/pytest tests/developer/test_evidence.py -q`

- [ ] **Step 3: Implement metadata-only evidence collection**

  Revalidate relative write paths after successful tool results. Parse command output by an explicit allowlist and discard every unknown key, stdout/stderr, content, patch, absolute path, and raw error value.

- [ ] **Step 4: Write failing truthful-report tests**

  Use literal runtime/check fixtures to prove success requires all latest checks to succeed; missing checks are blocked; failed latest checks are failed; approval/permission outcomes need human; limits/timeouts/stagnation are blocked; audit/runtime failures are failed.

- [ ] **Step 5: Run report tests and verify RED**

  Run: `.venv/bin/pytest tests/developer/test_reporting.py -q`

- [ ] **Step 6: Implement deterministic report mapping**

  Build bounded summaries from enums and counts only. Never reuse an LLM completion claim as verification and never hide failed/missing checks.

- [ ] **Step 7: Run focused tests and quality checks**

  Run: `.venv/bin/pytest tests/developer/test_evidence.py tests/developer/test_reporting.py -q`

  Run: `.venv/bin/ruff check core/developer tests/developer`

  Run: `.venv/bin/mypy core/developer tests/developer`

- [ ] **Step 8: Commit**

  Commit: `feat(developer): retain safe execution evidence`

### Task 4: DeveloperAgent composition

**Files:**
- Create: `core/developer/agent.py`
- Create: `tests/developer/test_agent.py`
- Modify: `core/developer/__init__.py`

**Interfaces:**
- Consumes: validated request, skill context, injected LLM provider, tool executor, runtime audit recorder, skill registry/selector, and `RuntimeLimits`.
- Produces: `DeveloperAgent.run(request: DeveloperRequest) -> DeveloperResult`.

- [ ] **Step 1: Write failing preflight and composition tests**

  Prove validation and skill compilation happen before provider/tool/audit work; one `LLMLoopReasoner` and one `AgentRuntime` run are used; runtime limits are passed unchanged; no collaborator is closed.

- [ ] **Step 2: Run composition tests and verify RED**

  Run: `.venv/bin/pytest tests/developer/test_agent.py -q`

- [ ] **Step 3: Implement minimal composition service**

  Validate, select/compile skills, create the evidence wrapper, compose the strict reasoner prompt, invoke one runtime run, and derive one deterministic result. Do not add retries, hidden tool calls, persistence, or cleanup of injected collaborators.

- [ ] **Step 4: Write failing propagation tests**

  Cover permission denial, approval escalation, invalid model output, token/tool/iteration/failure limits, timeout, stagnation, cancellation, and audit failure through the public DeveloperAgent boundary.

- [ ] **Step 5: Run propagation tests and verify RED**

  Run: `.venv/bin/pytest tests/developer/test_agent.py -q`

- [ ] **Step 6: Complete terminal mapping without intercepting cancellation**

  Preserve Phase 13 terminal results and immediate `CancelledError` propagation. Sanitize only Phase 14 validation/compilation failures.

- [ ] **Step 7: Run focused tests and quality checks**

  Run: `.venv/bin/pytest tests/developer/test_agent.py -q`

  Run: `.venv/bin/ruff check core/developer tests/developer`

  Run: `.venv/bin/mypy core/developer tests/developer`

- [ ] **Step 8: Commit**

  Commit: `feat(developer): compose bounded agent runtime`

### Task 5: Real-tool deterministic repository integration

**Files:**
- Create: `tests/developer/test_integration.py`
- Create: `tests/developer/test_safety.py`
- Modify: `tests/developer/factories.py`

**Interfaces:**
- Consumes: concrete `DeveloperAgent`, `FakeLLMProvider`, real `ToolExecutor`, real filesystem/write/Git/command tools, fixed `pytest` command profile, managed temporary repository.
- Produces: end-to-end evidence that Phase 14 satisfies the deterministic buggy-repository acceptance scenario.

- [ ] **Step 1: Write and run the failing simple-bug integration test**

  Fixture contains a tiny Python function with a wrong result and a real pytest test. Script complete structured provider outputs to inspect, patch once, run fixed pytest, verify, and complete. Assert the file changed, pytest passed, report succeeded, and provider/tool/command call counts contain no duplicates.

  Run: `.venv/bin/pytest tests/developer/test_integration.py::test_developer_fixes_and_verifies_bug -q`

- [ ] **Step 2: Make the smallest integration adjustments and verify GREEN**

  Adjust only production boundary behavior exposed by the real adapters; do not weaken adapters or replace them with mocks.

- [ ] **Step 3: Write and run the failing correction-loop integration test**

  Script an initial wrong patch, failed fixed pytest result, a corrective patch, and a successful rerun. Assert latest evidence wins and the first failure remains observable through bounded history/metadata.

- [ ] **Step 4: Make the correction loop pass**

  Preserve exactly-once calls and bounded history while allowing the existing runtime to continue after deterministic failure.

- [ ] **Step 5: Add adversarial safety scenarios**

  Prove completion without checks is blocked, failed checks beat LLM completion, undeclared/forbidden tools never execute, prompts/skill text/patches/output/secrets are absent from results and audit metadata, and cancellation leaves collaborators open.

- [ ] **Step 6: Run all Phase 14 tests and mutation-check assertions**

  Run: `.venv/bin/pytest tests/developer -q`

  Mentally mutate each authorization, count, byte limit, latest-check branch, and exactly-once delegation; ensure at least one named test fails for each mutation.

- [ ] **Step 7: Commit**

  Commit: `test(developer): verify real repository workflow`

### Task 6: Documentation and Phase 14 checklist

**Files:**
- Create: `docs/developer-agent.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`

**Interfaces:**
- Consumes: verified implementation behavior and commands.
- Produces: operator/developer documentation and truthful Phase 14 completion state.

- [ ] **Step 1: Document the implemented boundary**

  Explain composition, closed tools, skills as subordinate context, fixed check profiles, deterministic evidence/reporting, limits, cancellation, audit, injected resource ownership, security limitations, and an English usage example.

- [ ] **Step 2: Update repository summaries**

  Add Phase 14 architecture and test commands to README/AGENTS without claiming ReviewerAgent, multi-agent workflow, hostile-code sandboxing, or Phase 15 support.

- [ ] **Step 3: Update only genuinely complete Phase 14 checkboxes**

  Leave Phase 12 and Phase 15+ unchanged. Do not check any item lacking an implementation test and full verification evidence.

- [ ] **Step 4: Run documentation-adjacent quality checks**

  Run: `.venv/bin/ruff format --check .`

  Run: `.venv/bin/ruff check .`

  Run: `.venv/bin/mypy .`

- [ ] **Step 5: Commit**

  Commit: `docs(developer): document Phase 14 safeguards`

### Task 7: Full verification, independent review, and delivery

**Files:**
- Modify only files required to fix verified Phase 14 defects.

**Interfaces:**
- Consumes: complete Phase 14 branch.
- Produces: fresh local/Docker evidence, review resolution, pushed branch, and a stacked pull request.

- [ ] **Step 1: Run the complete local gate from a clean process**

  Run: `.venv/bin/pytest -q`

  Run: `.venv/bin/ruff check .`

  Run: `.venv/bin/ruff format --check .`

  Run: `.venv/bin/mypy .`

- [ ] **Step 2: Verify real PostgreSQL and Docker acceptance**

  Build/start the Compose stack, wait for PostgreSQL and API health, run Alembic to head, run the PostgreSQL-backed suite, call `/health`, and stop the stack without deleting user data.

- [ ] **Step 3: Request independent code and security review**

  Review the complete branch against the Phase 14 spec, focusing on duplicate calls, permission bypass, prompt/output retention, path disclosure, cancellation, unbounded collections, resource ownership, and accidental Phase 15 scope.

- [ ] **Step 4: Resolve findings with RED-GREEN cycles**

  Reproduce each valid defect with a failing test before changing production code, rerun focused and full gates, and commit conventional fixes. Reject unsupported feedback with concrete evidence.

- [ ] **Step 5: Verify scope and worktree cleanliness**

  Confirm Phase 12 and Phase 15 remain untouched, no forbidden capability exists, no secret is staged, and `CLAUDE.local.md` remains untracked/unmodified.

- [ ] **Step 6: Push and open the stacked pull request**

  Push `phase-14/developer-agent`, open a PR against `phase-13/loop-engineering-v1`, and include scope, safeguards, tests, Docker/PostgreSQL evidence, decisions, known limitations, and explicit Phase 15 exclusion.
