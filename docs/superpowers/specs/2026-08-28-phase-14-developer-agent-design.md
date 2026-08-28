# Phase 14 Developer Agent Design

## Scope

Phase 14 introduces one `DeveloperAgent` role that composes the completed Phase 13
`AgentRuntime`. It can understand one task, select relevant repository-owned skills, inspect one
managed workspace, modify code through existing transactional tools, execute existing fixed command
profiles, react to deterministic failures in later bounded iterations, and return a structured
developer result.

This phase does not add a second loop engine, a free-form shell, arbitrary command arguments,
permission mutation, branch merge, deployment, self-review, ReviewerAgent, multi-agent workflow,
MCP, memory, reputation, or Phase 15 behavior. Phase 12 remains deliberately unimplemented.

## Architectural choice

`DeveloperAgent` is a role-specific composition service in `core/developer/`; it is not a subclass
of `AgentRuntime` and does not duplicate its state machine. The service constructs a strict
`LLMLoopReasoner`, wraps the existing `ToolExecutor` with a metadata-only evidence collector, and
delegates exactly one run to `AgentRuntime`.

This is preferred over either a separate developer loop or direct access to workspace and command
adapters. One loop preserves Phase 13 budgets, cancellation, stagnation, and audit semantics. One
tool boundary preserves Phase 6–11 registry, permission, transaction, timeout, and output controls.

## Inputs

`DeveloperRequest` is strict, immutable, and bounded. It contains:

- a `RuntimeTask`;
- an `AgentProfile` whose role is `Developer`;
- the exact `ToolExecutionContext` for the managed workspace;
- declared domains, technologies, and tags used for deterministic skill selection;
- one through four required command profiles from the existing test/lint/build set.

The request is rejected before any LLM, tool, audit, or filesystem action when:

- task, profile, and execution identifiers are inconsistent;
- the profile is not an active Developer role;
- a declared tool is outside the closed Phase 14 developer tool set;
- required read, write, or command capabilities are absent;
- a required check is a Git profile or unknown profile;
- canonical profile permissions cannot be resolved.

The closed developer tool set is `read_file`, `list_files`, `search_literal`, `git_status`,
`git_diff`, `write_file`, `create_file`, `patch_file`, `delete_file`, and
`run_command_profile`. This allowlist grants no authority: every tool must also be registered,
declared in `ToolExecutionContext`, and authorized by the existing persisted permission engine.

## Skill selection and prompt boundary

`DeveloperAgent` calls the existing deterministic `SkillSelector` once. Eligibility requires all of
the following:

1. the skill ID is declared by `AgentProfile.skill_ids`;
2. the skill exists in the injected immutable `SkillRegistry`;
3. its required permissions are present in the canonical profile declaration;
4. the selector produces a positive domain, technology, tag, task, or role match;
5. its recommended tools are a subset of the developer's declared tool IDs.

At most eight skills are selected. Their complete validated instructions may be compiled into a
maximum 12 KiB UTF-8 context. Instructions are never truncated: a skill that cannot fit is omitted
and reported by stable ID. Ordering follows the deterministic selector. The final system prompt
must remain within the existing 16 KiB `LLMLoopReasoner` ceiling.

Skill instructions are explicitly subordinate to the Company Constitution, the Developer role,
the task, and the permission/tool boundaries. They are data, cannot grant permissions, cannot add
tools or command controls, and are never executed directly. Prompts and skill contents are not
persisted in runtime history, reports, audit events, or errors.

## Execution flow

```text
DeveloperRequest
  -> validate role, scope, permissions, tools, and required checks
  -> select eligible declared skills once
  -> compile bounded subordinate skill context
  -> LLMLoopReasoner
  -> AgentRuntime
       OBSERVE -> PLAN -> DECIDE
       -> ToolExecutor -> read/write/fixed command profile
       -> VERIFY -> next bounded iteration or terminal state
  -> deterministic evidence gate
  -> DeveloperResult + AgentReport
```

The LLM chooses only existing structured `RuntimeAction` values. A tool call is handed to the
wrapped `ToolExecutor` exactly once. The wrapper observes the returned immutable `ToolResult`; it
does not retry, mutate arguments, bypass permission evaluation, or close the executor.

Tests are run only through `run_command_profile`. Phase 14 introduces no `TestRunner` duplicate:
the fixed Phase 11 command profile policy and runner are the V1 test runner required by the
roadmap. The model supplies only a closed `profile_id`; executable, arguments, cwd, environment,
timeout, and output limits remain application-owned.

## Evidence and result

The wrapper retains at most 128 successful metadata-only evidence records:

- successful write tool name and validated relative path;
- command profile ID, category, exit code, terminal status, and truncation flag;
- stable failed/denied tool name and error code.

It never retains file content, patches, command stdout/stderr, prompts, responses, rationale,
absolute workspace paths, environment values, provider errors, or database errors.

`DeveloperResult` contains:

- the bounded `RuntimeResult`;
- one existing `AgentReport`;
- selected and omitted skill IDs;
- unique changed relative paths in first-observed order;
- bounded `DeveloperCheckResult` values for observed command profiles.

The final `AgentReport` is deterministic and does not require another LLM call. Its outcome is:

- `SUCCEEDED` only when the runtime completed and every required check was observed at least once
  with a latest successful result;
- `NEEDS_HUMAN` for human approval or permission escalation;
- `BLOCKED` for loop limits, timeout, stagnation, or missing required check evidence;
- `FAILED` for runtime/audit failures or any latest required check failure.

An LLM completion claim cannot override deterministic command evidence. A failed required check is
never hidden. The report does not approve or merge the developer's work.

## Security and resource invariants

- All resource limits remain mandatory and originate in `RuntimeLimits` plus existing tool and
  command limits.
- One model decision causes at most one tool call; there are no implicit retries or duplicate
  calls.
- Cancellation propagates through `AgentRuntime`; no injected provider, executor, registry,
  session, or client is closed.
- Skill context, evidence, and result collections are bounded before work starts.
- Every action still receives permission evaluation and append-only tool/runtime audit.
- `git-status` and `git-diff` remain read-only profiles; merge, commit, push, checkout, reset, and
  deployment are unavailable.
- Required test/build profiles execute repository code and therefore retain the Phase 11 warning:
  this application boundary is not a hostile-code sandbox.

## Error handling

All public Phase 14 failures use stable `DeveloperErrorCode` values and sanitized messages.
Validation and skill compilation fail before external work. Runtime terminal states are returned,
not reinterpreted by an LLM. Tool and command failures remain deterministic observations. Audit
failure fails closed. Raw exceptions and rejected content are discarded before crossing the role
boundary.

## TDD and acceptance scenarios

Tests must observe RED before production implementation and cover:

1. immutable bounded request, evidence, check, and result contracts;
2. rejection of wrong role, inconsistent scope, undeclared/forbidden tools, and Git checks;
3. deterministic skill selection restricted by profile, permissions, tools, count, and byte budget;
4. no skill instruction, prompt, content, patch, stdout/stderr, or absolute path in retained result,
   evidence, audit metadata, or errors;
5. one complete run through concrete `LLMLoopReasoner(FakeLLMProvider)`, `AgentRuntime`, real
   `ToolExecutor`, real read/write/command adapters, and a small managed repository fixture;
6. a simple bug is inspected, patched once, tested through the fixed `pytest` profile, and reported
   successful with no duplicate provider/tool/command calls;
7. failed test followed by a bounded corrective iteration and later success;
8. completion without required checks is blocked;
9. failed latest required check is reported failed even if the LLM claims completion;
10. permission denial/approval escalation, timeout, token/tool/iteration/failure limits,
    stagnation, cancellation, and audit failure preserve Phase 13 behavior;
11. injected collaborators are never closed;
12. Phase 12 and Phase 15 remain absent.

PostgreSQL tests use the real Docker database migrated through Alembic. No `metadata.create_all()`
is permitted. Full acceptance requires pytest, Ruff, mypy strict, format check, Docker API build,
Alembic head, health check, and independent review.

## Documentation and checklist

Add `docs/developer-agent.md`, update `README.md` and `AGENTS.md`, and check only genuinely verified
Phase 14 boxes in `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`. Phase 12 and every Phase 15+ checkbox remain
unchanged.
