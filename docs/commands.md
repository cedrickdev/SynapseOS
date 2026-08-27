# Secure command profiles

Phase 11 adds one permissioned tool, `run_command_profile`, for bounded test, lint, build, and
read-only Git execution. It does not expose a shell. Callers provide only a `profile_id`; SynapseOS
owns the executable, arguments, working directory, environment, timeout, and output limits.

## Built-in profiles

| Profile | Purpose | Fixed arguments | Workspace evidence |
| --- | --- | --- | --- |
| `pytest` | test | current Python `-m pytest` | valid bounded `pyproject.toml` |
| `ruff` | lint | current Python `-m ruff check .` | valid bounded `pyproject.toml` |
| `mypy` | lint | current Python `-m mypy .` | valid bounded `pyproject.toml` |
| `npm-test` | test | trusted npm `test --ignore-scripts=false` | bounded `package.json` with `scripts.test` |
| `npm-build` | build | trusted npm `run build` | bounded `package.json` with `scripts.build` |
| `php-artisan-test` | test | trusted PHP `artisan test` | bounded `composer.json` and regular `artisan` |
| `git-status` | Git read | fixed porcelain status | direct `.git` marker |
| `git-diff` | Git read | fixed hardened worktree diff | direct `.git` marker |
| `git-diff-staged` | Git read | fixed hardened staged diff | direct `.git` marker |
| `git-log` | Git read | fixed format and maximum 50 records | direct `.git` marker |

Repository marker values never become arguments or environment values. Missing, malformed,
oversized, symlinked, or incompatible markers fail closed. Non-Python executables resolve only from
fixed application directories and must be canonical executable regular files.

## Authorization

The tool requires an active persisted `shell.execute` grant in the exact project scope. It is
`HIGH` risk and requires autonomy level 3. Existing cumulative permission rules may impose a
stronger decision. `DENY` and `ASK` stop before profile detection or process creation.

## Process boundary

- `asyncio.create_subprocess_exec` receives a fixed argument vector; no shell is involved.
- The working directory is the exact Phase 9 root derived from `project_id`.
- Standard input is closed and no PTY or background process is available.
- The child starts in a new process session with a fixed minimal environment.
- Parent credentials, proxies, Python/Node injection variables, and package-manager configuration
  are not inherited.
- Stdout and stderr are drained concurrently and retained independently up to finite limits.
- Timeout and cancellation terminate the process group, escalate when necessary, and reap it.
- Every invocation launches once. There is no retry, fallback, or duplicate call.

The environment intentionally includes only deterministic locale/CI values, a fixed executable
path, disabled Git prompts/configuration, disabled pagers/color, and Python isolation flags.

## Results and audit

The immediate bounded result contains:

- profile and category;
- exit code and truthful `SUCCEEDED`/`FAILED` terminal classification;
- bounded stdout and stderr;
- independent truncation flags and aggregate truncation;
- duration in milliseconds.

A non-zero exit code is a successful tool observation: the test, lint, or build failure remains
visible to the caller instead of being hidden. Policy, spawn, timeout, termination, and validation
failures use stable sanitized errors.

Existing PostgreSQL `ToolCall` and append-only `AuditEvent` records contain only tool identity,
scope, authorization result, stable error code, duration, output field/byte counts, and truncation.
They never contain stdout, stderr, argv, executable/cwd paths, marker contents, environment values,
OS errors, prompts, responses, or automatic command history.

## Configuration

| Variable | Default | Hard maximum |
| --- | ---: | ---: |
| `COMMAND_TIMEOUT_SECONDS` | 30 s | 30 s |
| `COMMAND_STDOUT_MAX_BYTES` | 256 KiB | 1 MiB |
| `COMMAND_STDERR_MAX_BYTES` | 128 KiB | 1 MiB |
| `COMMAND_MARKER_MAX_BYTES` | 256 KiB | 1 MiB |
| `COMMAND_READ_CHUNK_BYTES` | 64 KiB | 64 KiB |
| `COMMAND_TERMINATION_GRACE_SECONDS` | 1 s | 5 s |

All values must be finite and positive.

## Security boundary

This is an application-level command boundary, not a hostile-code sandbox. Test and build profiles
execute repository code with the worker's operating-system rights. Untrusted production workloads
must therefore run in a restricted container or stronger execution sandbox in a later phase.

Phase 11 adds no free-form command, argument override, shell operator, pipeline, redirection,
interactive terminal, background task, dependency installation, network enablement, Git mutation,
MCP capability, or Phase 12 behavior.
