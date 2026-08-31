# ADR-0011 — Secure command profiles

- **Status:** Accepted
- **Date:** 2026-08-27
- **Deciders:** SynapseOS maintainers

## Context

Agents need deterministic tests, linters, builds, and Git inspection, but a free-form shell gives
model output direct access to command parsing, process creation, host resources, and possible
credentials. Repository test/build scripts are themselves executable code and require an explicit
high-risk boundary even when the outer vector is fixed.

Claude Code demonstrates useful lifecycle patterns: schema validation, permission gates, separate
stream capture, bounded output, cancellation, and process-group cleanup. Its flexible Bash strings,
operators, background tasks, and bypass controls exceed the Phase 11 specification and current
SynapseOS sandbox guarantees.

## Decision

Expose one `run_command_profile` tool backed by an immutable built-in catalog. The model selects
only a closed profile ID. SynapseOS resolves bounded workspace evidence, a trusted executable,
fixed arguments, exact managed cwd, fixed environment, and finite limits before launching one
no-shell subprocess.

Require persisted `shell.execute`, `HIGH` risk, autonomy level 3, central ToolExecutor validation,
and sanitized PostgreSQL audit. Keep non-zero exits as visible deterministic results. Terminate and
reap the full process group on timeout or cancellation, without retry.

## Consequences

- The initial command surface is small, reviewable, testable, and provider-neutral.
- Test/build profiles can still execute repository code; application policy is not an OS sandbox.
- The profile catalog must be extended in code and reviewed rather than configured by a repository.
- Dynamic Claude-Code-like command UX is deferred until SynapseOS has parsing, classification,
  allow/deny/ask rules, sandbox enforcement, previews, and human approval flows.
- Shell strings, background tasks, Git mutations, network enablement, and Phase 12 remain excluded.
