# ADR-0006 — Tool registry execution boundary

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** SynapseOS maintainers

## Context

Phase 6 must let future agents use a minimal set of repository-reading capabilities without
granting shell access or letting each adapter interpret security, timeout, and audit policy
differently. Tool output can contain source code, secrets, large logs, or hostile repository data,
so both execution and persistence need strict boundaries.

## Options considered

- Let the registry execute tools — reduces the number of objects, but mixes immutable capability
  discovery with mutable execution policy, persistence, cancellation, and resource lifecycle.
- Put authorization and auditing in every tool — keeps adapters self-contained, but duplicates
  security-critical logic and makes omission or inconsistent behavior likely.
- Keep an immutable registry and route every invocation through one executor — separates
  discovery from execution while enforcing one uniform deny-by-default lifecycle.

## Decision

Use a provider-neutral `Tool` contract and an immutable `ToolRegistry`. Compose exactly five
read-only tools explicitly: `read_file`, `list_files`, `search_text`, `git_status`, and `git_diff`.
The registry never imports or registers tools dynamically.

Require application callers to use `ToolExecutor`. It begins mandatory audit before lookup,
checks declaration and required permission membership, validates strict Pydantic input, performs
one bounded execution under a mandatory timeout, validates bounded JSON output, and finalizes a
sanitized audit record. It never retries. Cancellation is recorded and immediately propagated.

Keep filesystem and Git access in infrastructure adapters. Reject every symlink and any path that
is not canonically contained by the workspace. Git uses a fixed executable, fixed arguments, a
clean allowlisted environment, no shell, and bounded concurrent pipe reads.

Persist only allowlisted metrics and stable codes through a caller-owned SQLAlchemy session. Never
persist raw arguments, tool output, source content, diffs, subprocess streams, exception messages,
environment values, prompts, responses, or absolute host paths.

Phase 6 permission enforcement is intentionally limited to exact set membership. Policy
evaluation and approval decisions remain the responsibility of the Phase 7 Permission Engine.

## Consequences

- One central boundary consistently enforces declaration, permission membership, timeout,
  cancellation, output limits, safe errors, and audit lifecycle.
- Concrete tools remain small and testable, while the core package remains independent of
  SQLAlchemy and subprocess implementations.
- The caller retains transaction and resource ownership; a surrounding rollback removes the call
  and its event atomically.
- Symlinks are less convenient but remove a significant traversal and validation/open race class.
- Dynamic tools, write actions, shell, MCP, skills, retries, approval gates, and rich permission
  policy remain unavailable until their designated phases.

