# Phase 11 Secure Command Runner Design

**Date:** 2026-08-27
**Status:** Approved
**Scope:** Phase 11 only

## Objective

Allow an authorized agent to run a small set of deterministic test, lint, build, and read-only Git
commands in its exact managed project workspace without exposing an arbitrary shell.

The implementation borrows process-lifecycle principles from Claude Code's Bash tooling—validated
inputs, permission checks, bounded output, explicit cancellation, process-group termination, and
separate stdout/stderr capture—but deliberately excludes its free-form Bash interface, background
tasks, shell operators, and sandbox bypasses. This narrower boundary is required by the Phase 11
specification and the SynapseOS least-privilege constitution.

## Scope

Phase 11 implements:

- provider-neutral `CommandSpec`, `CommandResult`, `CommandPolicy`, and `CommandRunner` contracts;
- an immutable built-in command-profile catalog;
- deterministic stack/profile detection from bounded workspace markers;
- one local asynchronous runner using argument vectors and no shell;
- mandatory timeout, output limits, exact workspace working directory, and sanitized environment;
- immediate cancellation propagation and complete process-group termination;
- one permissioned, audited `run_command_profile` tool;
- initial Python, npm, PHP Artisan, and read-only Git profiles;
- unit, integration, security, and real-PostgreSQL audit tests;
- Phase 11 documentation, ADR, configuration, and checklist updates.

Phase 11 does not implement:

- command strings, arbitrary arguments, pipes, redirects, substitutions, glob expansion, or shell
  built-ins;
- interactive stdin, PTYs, terminal emulation, foreground/background task management, or detached
  processes;
- Git mutations or publication (`add`, `commit`, `checkout`, `reset`, `clean`, `push`, and similar);
- dependency installation, package-manager configuration, network enablement, or secret injection;
- project-defined command profiles, repository-controlled environment values, implicit retries, or
  fallback commands;
- Docker/VM execution sandboxes, remote workers, MCP, autonomous loops, or Phase 12 behavior.

## Architecture

### Core contracts

`core/commands/` owns immutable, infrastructure-neutral contracts:

- `CommandProfileId`: the closed set of supported profile identifiers;
- `CommandSpec`: an adapter-owned executable argument vector and execution classification;
- `CommandResult`: bounded stdout/stderr, exit code, truncation flags, duration, and profile ID;
- `CommandPolicy`: resolves a profile against workspace evidence or rejects it before spawning;
- `CommandRunner`: executes one already-authorized `CommandSpec` exactly once;
- stable sanitized command error codes and exceptions.

Core contracts never import SQLAlchemy, subprocess implementations, filesystem adapters, or tool
adapters. Collections are immutable and all numeric bounds are finite.

### Infrastructure adapters

`infrastructure/commands/` owns:

- the immutable built-in profile catalog;
- bounded marker inspection and deterministic profile selection;
- trusted executable resolution;
- a sanitized environment builder;
- asynchronous local process execution and bounded stream collection;
- process-group termination on timeout or cancellation.

`infrastructure/tools/command.py` adapts profile selection and execution to the existing `Tool`
contract. The default tool registry receives the command service explicitly; it does not construct
or own process resources implicitly.

### Existing enforcement path

Every model-requested command follows the existing central path:

```text
profile_id
  -> ToolExecutor
  -> persisted PermissionEngine decision
  -> strict tool input validation
  -> CommandPolicy profile and workspace validation
  -> CommandRunner (one process only)
  -> bounded ToolResult validation
  -> sanitized ToolCall and AuditEvent finalization
```

The tool requires `shell.execute`, has `HIGH` risk, and therefore requires autonomy level 3 under
the existing cumulative permission policy. Registration never grants authority. `DENY` and `ASK`
decisions never reach profile detection or process creation.

## Command Profiles

The initial immutable profile IDs and vectors are:

| Profile | Adapter-owned vector | Required evidence |
| --- | --- | --- |
| `pytest` | current Python, `-m pytest` | bounded `pyproject.toml` |
| `ruff` | current Python, `-m ruff check .` | bounded `pyproject.toml` |
| `mypy` | current Python, `-m mypy .` | bounded `pyproject.toml` |
| `npm-test` | trusted npm, `test --ignore-scripts=false` | bounded `package.json` with exact `test` script |
| `npm-build` | trusted npm, `run build` | bounded `package.json` with exact `build` script |
| `php-artisan-test` | trusted PHP, `artisan test` | bounded `composer.json` and regular `artisan` file |
| `git-status` | trusted Git, fixed status arguments | valid Git workspace |
| `git-diff` | trusted Git, fixed worktree diff arguments | valid Git workspace |
| `git-diff-staged` | trusted Git, fixed staged diff arguments | valid Git workspace |
| `git-log` | trusted Git, fixed bounded log arguments | valid Git workspace |

The vectors contain no model-controlled values. Repository markers only enable a fixed profile;
they never generate executable names, arguments, environment entries, or alternate profiles.
Parsing is size-bounded, strict enough to identify only the required marker, and free of plugin or
code execution. A missing, malformed, oversized, symlinked, or non-regular marker fails closed.

The Python profiles use the already-running trusted Python interpreter. Other executables resolve
only from an application-owned list of approved absolute search directories. Resolution occurs
before spawning and produces a stable unavailable-profile error without exposing host paths.

The npm profiles intentionally execute the exact repository-defined `test` or `build` script. That
is code execution and is why every command profile requires `shell.execute`, `HIGH` risk, and the
same strict process boundary. Phase 11 does not install dependencies or run lifecycle hooks outside
the selected fixed npm action.

## Workspace and Environment Boundary

The policy accepts only the exact canonical managed project root produced by the Phase 9 workspace
manager. It rejects arbitrary subdirectories, alternate roots, traversal, symlink roots, missing
roots, and roots outside the manager. The model cannot provide `cwd`.

The child environment starts from an empty mapping and receives only application-owned fixed
values needed for deterministic non-interactive execution, such as locale, safe path, disabled Git
prompts/configuration, and no-color/test-runner controls. Parent secrets, credentials, proxies,
tokens, Python injection variables, package-manager configuration, and model-provided values are
never inherited. The exact allowlist is tested.

Standard input is `DEVNULL`. Processes run in a new session. No PTY, socket forwarding, inherited
file descriptor, prompt handling, or background execution is available.

## Resource Bounds and Lifecycle

Settings define positive finite values with hard maxima for:

- command timeout;
- retained stdout bytes;
- retained stderr bytes;
- marker-file bytes;
- stream read chunk bytes;
- process termination grace period.

Both streams are read concurrently to avoid pipe deadlock. Readers continue draining after their
retention limit and set independent truncation flags, so child processes cannot block on a full
pipe. Retained memory is bounded by configuration plus one bounded read chunk per stream. Bytes are
decoded as UTF-8 with replacement; raw bytes are not persisted.

The runner launches exactly one process and never retries. Timeout terminates the complete process
group, waits for the bounded grace period, escalates to a kill when necessary, and always reaps the
child. Cancellation follows the same cleanup path and immediately re-raises `CancelledError` after
cleanup. Cleanup never starts a replacement command.

Injected process factories and collaborators remain caller-owned and are never closed by the
runner.

## Results and Failure Semantics

`CommandResult` contains:

- `profile_id`;
- `exit_code`;
- bounded `stdout` and `stderr`;
- `stdout_truncated` and `stderr_truncated`;
- `duration_ms`;
- a deterministic terminal classification.

A non-zero exit code is a successful deterministic observation, not a hidden exception. Test,
lint, or build failure is therefore returned verbatim within the output bounds and audited as a
completed command with a non-zero exit classification.

Policy denial, unavailable executable, spawn failure, timeout, and malformed result use stable
error codes and fixed safe messages. Exceptions never contain command output, arguments, marker
contents, environment values, absolute paths, OS error text, credentials, prompts, or responses.

## Audit and Data Minimization

Existing `ToolCall` and append-only `AuditEvent` infrastructure records the authorization and
terminal lifecycle. Persisted metadata may contain only allowlisted values such as:

- profile ID and command category;
- project/task/agent/run correlation identifiers;
- permission result and stable error code;
- exit-code classification, duration bucket, byte counts, and truncation flags.

It never persists stdout, stderr, full vectors, executable paths, working-directory paths, marker
contents, environment values, repository source, prompts, responses, or secret-bearing errors.
There is no automatic raw-output file or command-history persistence.

## Testing Strategy

Implementation follows strict RED-GREEN-REFACTOR cycles. Tests cover:

- immutable contracts, finite limits, stable error codes, and unknown profile rejection;
- exact profile vectors and deterministic marker detection;
- malformed, oversized, symlinked, missing, and incompatible markers;
- exact managed-root enforcement before process creation;
- strict input containing only `profile_id`;
- fixed executable resolution and the exact sanitized environment;
- no shell, closed stdin, new process session, and one spawn only;
- simultaneous stdout/stderr capture, independent truncation, invalid UTF-8, and non-zero exits;
- timeout and cancellation terminating/reaping descendants without retry;
- permission denial and insufficient autonomy before runner invocation;
- real-command smoke tests for profiles available in the test environment;
- real PostgreSQL authorization and sanitized terminal audits;
- absence of output, environment, path, command, and secret markers in persisted metadata;
- full Ruff, strict mypy, pytest, Docker API, PostgreSQL, and Alembic regression checks.

Tests use deterministic injected process adapters only for lifecycle states that cannot be made
reliable with real subprocess timing. They assert observable behavior rather than mock call counts
alone. PostgreSQL tests continue to build schemas exclusively through Alembic.

## Security Boundary and Deferred Work

This is an application-level command boundary, not a hostile-code sandbox. Authorized test/build
profiles can execute repository code with the operating-system rights of the SynapseOS process.
Production deployment must therefore run workers inside an appropriately restricted container or
other execution sandbox before accepting untrusted repositories.

A later phase may add Claude-Code-like dynamic command UX only after introducing a real parser,
command classification, allow/deny/ask rules, sandbox enforcement, preview/approval flows, and
dedicated policies for mutating or network-capable commands. Phase 11 intentionally provides the
safe process-lifecycle foundation without exposing that future surface.
