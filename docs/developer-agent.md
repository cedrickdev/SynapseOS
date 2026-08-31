# Developer Agent

Phase 14 introduces the first bounded business role in SynapseOS. `DeveloperAgent` understands one
assigned task, selects relevant repository-owned skills, inspects one managed workspace, changes
files through existing transactional tools, runs fixed verification profiles, reacts to failures
inside the Phase 13 loop, and returns a deterministic report.

## Architecture

`DeveloperAgent` is a composition service in `core/developer/`. It does not subclass or duplicate
`AgentRuntime`:

```text
DeveloperRequest
  -> fail-closed role and scope validation
  -> deterministic bounded skill selection
  -> LLMLoopReasoner
  -> AgentRuntime
  -> ToolExecutor
  -> managed read/write/fixed-command adapters
  -> metadata-only evidence gate
  -> DeveloperResult + AgentReport
```

The role delegates exactly one run to `AgentRuntime`. Runtime iteration, timeout, token, tool-call,
failure, history, and stagnation limits therefore remain authoritative. One structured model
decision causes at most one tool call; there are no implicit retries.

## Request boundary

A request is rejected before any model, tool, audit, or filesystem work unless:

- the profile role is exactly `Developer` and its status is `ASSIGNED` or `WORKING`;
- profile, task, and execution-context identifiers agree;
- profile and execution-context tool declarations are identical;
- every permission identifier is canonical;
- filesystem read/write, shell execution, and test execution permissions are declared;
- at least one read tool, one write tool, and `run_command_profile` are declared;
- every declared tool belongs to the closed Developer allowlist;
- one through four unique required checks use test, lint, or build profiles rather than Git profiles.

The allowlist contains `read_file`, `list_files`, `search_text`, `git_status`, `git_diff`,
`write_file`, `create_file`, `patch_file`, `delete_file`, and `run_command_profile`. The allowlist
does not grant authority: tools must still be registered, declared for the run, and allowed by the
existing permission engine from active persisted grants. Test, lint, and build execution requires
both persisted `shell.execute` and `tests.execute` grants.

## Skill context

The existing deterministic `SkillSelector` ranks only skills declared by the agent. A selected
skill must exist in the injected immutable registry, have a positive match, fit the agent's
canonical permissions, and recommend only declared tools.

At most eight complete skills enter an ephemeral 12 KiB UTF-8 context. Instructions are never
truncated: a skill that does not fit is omitted by stable identifier. The complete system prompt
must remain within 16 KiB. Skill instructions are subordinate guidance and cannot grant
permissions, add tools, change command profiles, override the task, or bypass the Company
Constitution. Skill instructions and prompts are not persisted in results or audit metadata.

## Repository changes and verification

All repository access crosses the existing `ToolExecutor`. File mutations retain the Phase 10
transaction, audit, and compensation behavior. Tests, linting, and builds run only through the
Phase 11 fixed command profiles; the model cannot choose an executable, arguments, working
directory, environment, timeout, or output limits.

Command evidence is bound to the requested profile and validated for canonical profile/category,
exit-code/status, and returned-tool consistency before it can affect the report. The command runner
is an application-level safety boundary, not a hostile-code sandbox. Test and
build profiles execute code from the managed repository. Production use with untrusted source
still requires a stronger isolated execution backend in its designated future phase.

## Evidence and report truthfulness

The evidence wrapper delegates each call once and retains at most 128 records. It keeps only:

- the validated relative path of a successful write;
- command profile, category, exit code, terminal status, and truncation flag;
- tool name and stable error code for failed or denied calls.

It discards file content, patches, command stdout/stderr, prompts, responses, rationale, absolute
paths, environment values, and raw exceptions. Repeated command profiles retain a bounded sequence
so failures are not hidden; the latest result is authoritative for the final outcome.

The final `AgentReport` is application-generated, not model-generated:

- `SUCCEEDED`: runtime completed and every required latest check succeeded;
- `NEEDS_HUMAN`: permission, approval, or explicit agent escalation;
- `BLOCKED`: runtime limits, timeout, stagnation, or missing required checks;
- `FAILED`: runtime/audit failure or a failed latest required check.

A model completion claim never overrides missing or failed deterministic checks. The Developer
does not approve, merge, push, deploy, or review its own work.

## Cancellation and resource ownership

Cancellation propagates through `AgentRuntime` immediately after a sanitized cancellation audit.
`DeveloperAgent` never closes the injected model provider, tool executor, audit recorder, skill
registry, command runner, HTTP client, or database session.

## Verification

Run the focused Phase 14 tests:

```bash
.venv/bin/pytest tests/developer -q
```

The integration fixture uses `FakeLLMProvider` only for deterministic model output. It uses the
real `ToolExecutor`, permission engine, managed workspace filesystem, transactional patch tool,
fixed command policy, local process runner, and a real pytest subprocess. It covers both a direct
fix and a failed-test/corrective-iteration/success path.

Phase 15 `ReviewerAgent` and multi-agent coordination remain unimplemented.
