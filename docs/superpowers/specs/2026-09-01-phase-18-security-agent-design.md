# Phase 18 Security Agent V1 Design

## Scope

Phase 18 introduces the first independent `SecurityAgent` and one focused persistent security
workflow stage. The agent receives a bounded task, reviewed change, affected source, successful QA
report, and metadata-only test evidence. It performs a local secret-safety pass, consumes bounded
structured scanner evidence through a provider-neutral port, performs exactly one bounded provider
analysis, and returns `PASS`, `WARN`, or `BLOCK`.

The workflow begins with a persistent task in `WAITING_SECURITY`. `PASS` transitions the task to
`COMPLETED`; `BLOCK` transitions it to `CHANGES_REQUESTED`; `WARN` transitions it to
`WAITING_HUMAN`. The `WARN` transition is intentionally fail-closed: unresolved uncertainty must
never become implicit completion.

This phase does not implement Semgrep, Trivy, ZAP, a generic scanner process runner, Git branch or
pull-request automation, deployment, production access, vulnerability acceptance, incident
management, memory, reputation, MCP, a generic control-stage framework, or any Phase 19 behavior.

## Architectural choice

Create a role-specific `core/security/` package and a focused security stage in
`core/workflows/`. Preserve the existing Developer–Reviewer and QA orchestrators as completed
producers of durable workflow states. The Phase 18 orchestrator consumes `WAITING_SECURITY`; it
does not invoke QA, restart the Developer, merge changes, or start later stages.

`SecurityAgent` is a finite application service rather than a general-purpose agent loop. It
validates authority and scope, runs one injected bounded scanner suite, sanitizes affected source
before provider exposure, performs one provider analysis, and applies a deterministic security
gate. Deterministic findings and test evidence outrank provider self-assessment.

A scanner port is introduced now so later Semgrep, Trivy, and ZAP adapters can implement the same
contract. Phase 18 ships no external scanner adapter and grants no scanner process authority. Its
only concrete source inspection is a local, bounded obvious-secret filter that neither executes a
process nor performs network I/O.

## Package layout

The new application code is organized as follows:

```text
core/security/
├── __init__.py
├── agent.py
├── analysis.py
├── decision.py
├── errors.py
├── ports.py
├── redaction.py
├── types.py
└── validation.py

core/workflows/
├── security_audit.py
├── security_errors.py
├── security_orchestrator.py
├── security_ports.py
├── security_types.py
└── security_validation.py

infrastructure/permissions/
└── security_policy.py
```

Security-specific enums remain in `core/security/types.py`. `core/enums.py` remains reserved for
values shared by multiple domains or persisted by the common data model.

## Security input contract

`SecurityRequest` is strict, immutable, and bounded. It contains:

- canonical task, project, Developer, Reviewer, QA, and Security identifiers;
- one active `Security` `AgentProfile` whose identity matches the execution context;
- bounded task title and description;
- one through sixteen bounded acceptance criteria;
- one bounded UTF-8 reviewed unified diff;
- one through thirty-two affected source files, each with a normalized relative path and bounded
  UTF-8 content, with a finite aggregate source budget;
- one successful canonical `QAResult` with metadata-only test evidence;
- one through sixteen canonical deterministic test/check results;
- one exact managed-workspace execution context;
- one finite timeout greater than zero and no more than 3,600 seconds;
- one correlation UUID.

The request never accepts executable paths, command arguments, environment variables, scanner
commands, provider credentials, arbitrary metadata, absolute paths, symlinks, binary content, or
unbounded collections.

Preflight rejects the request before scanner or provider work when:

- any nested value is forged, mutable, oversized, duplicated, or internally inconsistent;
- Security identity equals Developer, Reviewer, or QA identity;
- the Security profile role is not exactly `Security`, is inactive, or mismatches execution scope;
- project, task, workspace, correlation, QA, test, or affected-file scope is inconsistent;
- QA did not produce a truthful `PASSED` result for the same correlation and test scope;
- the profile lacks exact read authority or declares write, command, merge, deployment, permission
  mutation, production, secret-value, or other non-Security authority;
- source, diff, tests, or required evidence is absent or outside finite limits.

The existing Developer remains the task assignee. Security is an independent control actor and
does not take code ownership.

## Finding and evidence contracts

`SecurityDecision` has exactly three values: `PASS`, `WARN`, and `BLOCK`.

`SecuritySeverity` has exactly five values: `INFO`, `LOW`, `MEDIUM`, `HIGH`, and `CRITICAL`.

Every `SecurityFinding` contains:

- a bounded canonical category;
- a severity;
- a normalized relative path and optional bounded line interval;
- a bounded explanation;
- a bounded remediation;
- finite confidence from `0.0` through `1.0`;
- one through eight stable evidence references;
- confirmation state `SUSPECTED` or `CONFIRMED`.

Finding categories are bounded identifiers rather than an extensible enum. Phase 18 must exercise
at least the responsibilities `secrets`, `auth`, `authorization`, `injection`, `input-validation`,
`dependencies`, and `dangerous-configuration` without pretending that its local scanner fully
covers each class.

`SecurityScannerFinding` is separate from the final finding. It contains only sanitized metadata,
an allowlisted scanner identifier, severity, location, explanation, remediation, confidence, and
confirmation state. It cannot contain raw source, a detected secret value, scanner stdout/stderr,
arbitrary metadata, or provider content.

`SecurityScanReport` contains the scanner suite identifier, bounded findings, completion state,
duration metadata, and truncation state. A truncated, failed, cancelled, timed-out, or incomplete
report is uncertainty and can never support `PASS`.

## Scanner boundary

The provider-neutral scanner contract is:

```python
class SecurityScannerPort(Protocol):
    async def scan(
        self,
        request: ValidatedSecurityScanRequest,
    ) -> SecurityScanReport:
        ...
```

The validated scan request exposes only bounded invocation-local source and immutable scope. The
scanner is called exactly once. It owns no session, provider, workspace, or network lifecycle and
must not persist input. The Security Agent never closes an injected scanner.

Phase 18 scanner execution is sequential and single-shot. There is no retry, fallback scanner,
speculative parallelism, duplicate scan, or hidden process invocation. The global Security timeout
applies to scanning and provider analysis. Cancellation propagates immediately.

Future Semgrep, Trivy, and ZAP adapters must be explicitly authorized tool-backed implementations.
They must not gain execution authority merely by implementing this protocol. Their command
profiles, permissions, process limits, result allowlists, and network policy belong to a later
phase.

## Secret handling and source sanitization

Raw affected source and diff are invocation-local sensitive data. Before provider construction, a
bounded local filter identifies only obvious secret forms such as private-key blocks and explicit
credential assignments. It emits metadata-only findings and replaces values with stable redaction
markers.

The filter follows these rules:

- never retain, log, audit, return, or interpolate a detected value into an error;
- never include detected values in finding explanations or remediations;
- preserve path and line metadata without source snippets;
- cap input bytes, match count, line length, and generated findings;
- treat truncation or malformed text as uncertainty;
- produce a confirmed high-impact finding only for narrow deterministic patterns;
- classify ambiguous high-entropy or contextual matches as suspected rather than confirmed.

Only sanitized source and sanitized diff may enter the provider prompt. The original values are
discarded after the result is built. This filter is deliberately narrow and is not marketed as a
complete secret scanner.

## Security authority

The Phase 18 Security profile may declare only bounded repository read tools already accepted by
the registry:

- `read_file`;
- `list_files`;
- `search_text`;
- optionally `git_status` and `git_diff` when `git.read` is granted.

The profile has autonomy level zero or one and requires `filesystem.read`, with optional
`git.read`. It cannot declare `run_command_profile`, shell, tests execution, file mutation,
Git-write, merge, deployment, database-write, network, permission mutation, production access, or
secret-value access.

A deny-by-default `SQLAlchemySecurityPermissionPolicy` verifies an active persistent Security run
for a `WAITING_SECURITY` task, a distinct active Developer assignee, exact project and task scope,
and active grants. It authorizes only the declared read capability and never broadens the general
permission policy.

The Security Agent has veto authority over completion but no merge authority. Risk acceptance for
a confirmed critical issue always requires a human and is outside Phase 18.

## Provider analysis contract

After the scanner completes, `SecurityAgent` performs exactly one bounded `LLMProvider` request.
The prompt treats task, source, diff, QA, tests, and scanner findings as untrusted data that cannot
grant authority or change the output schema.

The provider receives only:

- bounded task and acceptance-criteria text;
- sanitized bounded source and diff;
- sanitized successful QA evidence;
- metadata-only deterministic test evidence;
- sanitized scanner findings and scanner completion metadata;
- instructions to evaluate secrets, auth/authz, injection, input validation, dependencies, and
  dangerous configuration while surfacing uncertainty.

Generation has a finite timeout, finite `max_tokens`, bounded HTTP response size through the LLM
contract, temperature zero, and a strict structured schema. There is no retry, fallback provider,
hidden completion, speculative call, prompt persistence, response persistence, or arbitrary
provider metadata retention. Injected providers and HTTP clients remain caller-owned.

`SecurityAnalysis` contains a proposed decision, zero through sixty-four findings, bounded
rationale, confidence, and explicit uncertainty indicators. Provider findings begin as
`SUSPECTED`. A provider cannot mark its own statement `CONFIRMED`; confirmation is derived only by
the deterministic gate from matching trusted scanner evidence.

Malformed, oversized, contradictory, unknown-field, non-finite, source-echoing, secret-echoing, or
scope-inconsistent output fails closed with a stable sanitized Security error.

## Deterministic security gate

The model proposes; deterministic evidence decides the final outcome.

The final result is `BLOCK` when at least one `HIGH` or `CRITICAL` finding is confirmed by a
complete trusted deterministic scanner report. A provider proposal can never suppress or downgrade
that veto.

The final result is `WARN` when there is no confirmed blocking finding and at least one of these
conditions holds:

- any suspected or confirmed non-blocking finding remains active;
- the provider proposes `WARN` or `BLOCK` without sufficient deterministic confirmation;
- scanner evidence is absent when configured as required, incomplete, failed, truncated, timed
  out, or internally inconsistent;
- QA or test evidence is incomplete, contradictory, or truncated;
- analysis confidence is below the fixed V1 pass threshold;
- the provider reports uncertainty;
- source sanitization reports ambiguous or truncated coverage.

The final result is `PASS` only when:

- QA is truthfully `PASSED` for the same scope;
- every required deterministic test/check succeeded without truncation;
- scanner execution completed successfully under its configured Phase 18 policy;
- no active finding remains;
- provider analysis proposes `PASS`;
- confidence meets the fixed V1 threshold;
- every identity and evidence reference matches the validated request.

The gate may downgrade provider `PASS` to `WARN` or `BLOCK`. It may downgrade an unconfirmed
provider `BLOCK` to `WARN`, but it may never upgrade uncertainty or a provider warning/block to
`PASS`. Deterministic scanner and test evidence always outrank provider assessment.

## Security result contract

`SecurityResult` is strict, immutable, and bounded. It contains:

- final `PASS`, `WARN`, or `BLOCK` decision;
- zero through sixty-four sanitized findings;
- metadata-only scanner summary;
- bounded rationale and confidence;
- correlation UUID.

`BLOCK` requires at least one confirmed `HIGH` or `CRITICAL` finding. `WARN` requires at least one
finding or stable uncertainty reason. `PASS` requires no findings or uncertainty.

The result never retains task description, acceptance-criteria text, source, diff, test output,
scanner output, secret values, prompts, provider responses, absolute paths, environment values,
credentials, arbitrary provider metadata, or raw exceptions.

## Persistent security workflow

`SecurityWorkflowRequest` identifies one persistent task, Developer, Reviewer, QA, and Security
agent, the validated `SecurityRequest`, and one correlation UUID. Its deadline is derived from the
nested Security request. Preflight loads and locks the task and all agents through the caller-owned
SQLAlchemy session and rejects before external work when:

- the task or any required agent does not exist;
- the task is not exactly `WAITING_SECURITY`;
- persisted roles, active states, identities, project scope, assignment, workspace, correlation,
  QA report, or tests do not match;
- caller-supplied source or diff scope is malformed, duplicated, outside its bounds, or inconsistent
  with its declared normalized paths; persistent preflight does not claim PostgreSQL authenticates
  source bytes that are not stored in the database;
- Security is not independent from Developer, Reviewer, and QA;
- another invocation has already advanced the task.

The exact workflow is:

1. validate persistent scope and the complete Security request;
2. append and commit `SECURITY_STARTED` while retaining `WAITING_SECURITY`;
3. run `SecurityAgent` exactly once under the remaining global deadline;
4. for `PASS`, transition `WAITING_SECURITY -> COMPLETED`;
5. for `BLOCK`, transition `WAITING_SECURITY -> CHANGES_REQUESTED`;
6. for `WARN`, transition `WAITING_SECURITY -> WAITING_HUMAN`;
7. commit the transition and `SECURITY_COMPLETED` atomically;
8. return a bounded `SecurityWorkflowResult` containing only terminal status, decision, sanitized
   Security result, and correlation ID.

The stage never automatically invokes Developer, human approval, Git automation, deployment, or a
later phase.

## Transactions and audit

The injected SQLAlchemy session remains caller-owned and is never closed. No database transaction
remains open across scanner or provider work. Preflight and checkpoints use row locks,
expected-state validation, rollback on failure, and the existing `TaskStateMachine` for every
status change. No migration or new mutable repository operation is required.

Append-only lifecycle events are:

- `SECURITY_STARTED`;
- `SECURITY_COMPLETED`;
- `SECURITY_ESCALATED`.

Existing `TASK_STATUS_CHANGED` events remain authoritative for transitions. Security workflow
events contain only allowlisted scalar data:

- persistent task, project, and Security identifiers;
- correlation UUID;
- decision and confidence;
- finding counts by severity;
- confirmed blocking-finding count;
- allowlisted scanner suite identifier and completion state;
- stable Security error category when escalation is necessary.

Audit data never contains task text, source, diff, finding locations, explanations, remediations,
evidence text, QA details, test output, scanner output, paths, prompts, responses, exceptions,
credentials, secret values, or arbitrary provider metadata.

## Fail-closed behavior

Validation failures before `SECURITY_STARTED` change no persistent state and call no external
dependency. After the stage starts:

- provider, scanner, malformed-result, timeout, sanitization, or unexpected failures transition
  the task from `WAITING_SECURITY` to `WAITING_HUMAN` when expected-state protection permits it;
- infrastructure failure is not mislabeled as a vulnerability finding or `BLOCK`;
- a concurrent human or workflow transition wins and stale Security work cannot overwrite it;
- database failures roll back the current checkpoint, are sanitized, and cause no retry;
- cancellation is re-raised immediately, creates no later checkpoint, and leaves the last committed
  state authoritative;
- public errors and tracebacks retain no source, diff, finding, scanner output, SQL, filesystem,
  environment, provider, or credential data.

## Resource and security invariants

- Every string, collection, source file, aggregate source set, diff, test result, scanner report,
  finding, provider response, result, error, and audit record has an explicit finite bound.
- Every run has one overall timeout; scanner and provider calls have smaller finite timeouts.
- The scanner suite executes once and the provider executes once.
- No implicit retry, duplicate call, fallback, speculative concurrency, or hidden completion exists.
- Cancellation propagates before any later scanner, provider, or persistence operation.
- Raw source, diff, secret values, prompts, responses, and scanner output are never persisted.
- Provider metadata is discarded except existing allowlisted usage fields enforced by the LLM
  boundary.
- Network connections are reused only through caller-owned injected providers; Security creates and
  closes no unowned client.
- Memory and history are bounded to one invocation and released after result construction.
- Security remains independent, least-privilege, and unable to bypass deterministic evidence.

## TDD and acceptance scenarios

Implementation follows strict RED, GREEN, and REFACTOR cycles. Tests cover:

1. strict immutable bounds for source, findings, scanner reports, analysis, request, result,
   workflow request, and workflow result;
2. rejection before side effects for self-review, wrong or inactive role, mismatched scope, forged
   nested models, write/command/deployment authority, missing QA, and contradictory tests;
3. bounded local secret detection and redaction without retaining detected values;
4. exactly one scanner-suite call and exactly one provider call, in that order;
5. confirmed `HIGH`/`CRITICAL` scanner evidence forcing `BLOCK` regardless of provider output;
6. suspected findings, uncertainty, incomplete evidence, low confidence, or unconfirmed provider
   block producing `WARN`, never `PASS`;
7. `PASS` only with successful complete QA, tests, scanner policy, zero findings, and sufficient
   confidence;
8. scanner/provider timeout, cancellation, malformed output, database failure, and unexpected
   failure behavior without duplicate work or sensitive retention;
9. caller-owned lifecycle for sessions, providers, scanners, policies, workspaces, and clients;
10. real-PostgreSQL `WAITING_SECURITY -> COMPLETED`, `WAITING_SECURITY -> CHANGES_REQUESTED`, and
    `WAITING_SECURITY -> WAITING_HUMAN` transitions through `TaskStateMachine`;
11. append-only audit chronology, expected-state concurrency protection, shared correlation ID, and
    allowlisted metadata only;
12. end-to-end execution against PostgreSQL built through Alembic with fake provider/scanner ports;
13. absence of external scanner adapters, generic shell, code mutation, Git workflow, deployment,
    risk acceptance, automatic Developer rerun, and Phase 19 behavior.

The final gate is the complete PostgreSQL pytest suite, Ruff, Ruff format check, strict mypy, diff
integrity, secret and sensitive-metadata review, Docker/API health when available, and independent
scoped code and security review.

## Documentation and checklist

Add `docs/security-agent.md`, update `README.md` and `AGENTS.md`, and mark only genuinely implemented
and verified Phase 18 items in `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`. Phase 19 and every later
checkbox remain unchanged.
