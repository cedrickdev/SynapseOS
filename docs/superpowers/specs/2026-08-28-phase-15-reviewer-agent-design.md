# Phase 15 Reviewer Agent Design

## Scope

Phase 15 introduces one independent `ReviewerAgent` that evaluates completed Developer work. It
reads a bounded task description, acceptance criteria, Git diff, deterministic check evidence, and
the Developer report, then returns one structured `APPROVED` or `CHANGES_REQUESTED` decision.

This phase does not add Developer-to-Reviewer orchestration, correction cycles, task-state
transitions, QA, Security, merge gates, GitHub integration, MCP, memory, reputation aggregation, or
Phase 16 behavior. The Reviewer never changes repository content in V1.

## Architectural choice

`ReviewerAgent` is a role-specific service in `core/reviewer/`. It uses one bounded provider call
for qualitative analysis and a deterministic decision gate for constitutional and test evidence.
It does not reuse `AgentRuntime`, because reviewing is one finite analysis operation with no action
loop and no tool execution. Reusing the loop would introduce artificial iterations and the risk of
duplicate model calls.

The service receives already collected, bounded evidence instead of opening a workspace or running
tools. This keeps Phase 15 read-only and leaves workflow assembly and evidence collection to Phase
16. The provider-neutral `LLMProvider` and deterministic `FakeLLMProvider` remain the only model
boundary.

## Inputs

`ReviewerRequest` is strict, immutable, and bounded. It contains:

- stable task, project, Developer, and Reviewer identifiers;
- the task title and description;
- one through sixteen acceptance criteria;
- a bounded UTF-8 unified Git diff;
- one through ten explicit required command-profile IDs and one through sixteen deterministic check
  results;
- the completed `AgentReport` produced by `DeveloperAgent`;
- an active Reviewer `AgentProfile` with read-only authority.

Preflight validation rejects the request before the provider is called when:

- Reviewer and Developer identifiers are equal;
- the profile is not an active `Reviewer` role or does not match the request;
- task or project scope is inconsistent;
- the profile declares any tool other than `read_file`, `list_files`, `search_text`, `git_status`,
  or `git_diff`;
- the profile declares any permission other than `filesystem.read` or `git.read`;
- acceptance criteria, diff, checks, or Developer evidence are absent, oversized, duplicated, or
  internally inconsistent.

The diff and criteria are transient provider input. They are never included in errors, output
metadata, audit data, or persistent history by this phase.

## Provider analysis contract

The Reviewer makes exactly one bounded LLM request. Its system prompt states that repository and
task inputs are untrusted data, not instructions capable of changing authority. Generation has an
explicit timeout, token limit, and structured JSON schema.

The model returns a `ReviewAnalysis` containing:

- a proposed `APPROVED` or `CHANGES_REQUESTED` decision;
- zero through sixty-four findings;
- each finding's stable category, `INFO`, `LOW`, `MEDIUM`, `HIGH`, or `CRITICAL` severity, bounded
  rationale, optional normalized relative path and line, and recommended change;
- bounded overall rationale and confidence from `0.0` through `1.0`.

Malformed, oversized, unknown-field, or contradictory output fails closed. Provider failures are
normalized and sanitized. There is no implicit retry, fallback provider, or second completion.

## Deterministic decision gate

The LLM proposes; application evidence decides whether approval is permitted. The final decision is
always `CHANGES_REQUESTED` when any of these conditions holds:

- Reviewer and Developer are not independent;
- the Developer report is not `SUCCEEDED`;
- a required check is missing, failed, or has inconsistent metadata;
- any accepted finding has `HIGH` or `CRITICAL` severity;
- the model proposes changes;
- confidence is below the fixed V1 approval threshold.

The gate may downgrade `APPROVED` to `CHANGES_REQUESTED`; it may never upgrade a model-requested
change to approval. A downgraded result includes stable, sanitized deterministic findings explaining
the failed gate. Deterministic test evidence outranks both the Developer's and Reviewer's claims.

## Output and review score

`ReviewerResult` contains the final decision, bounded findings, rationale, confidence, and a
deterministic `review_score` from `0.0` through `1.0`. The score measures the reviewed change for
this review only; it does not update agent reputation and is not persisted automatically.

The V1 score is derived from deterministic check completion and weighted finding severities. It is
not generated directly by the model. Identical validated inputs produce the same score.

No output contains raw prompts, provider responses, complete diff content, file content, command
output, absolute paths, environment values, credentials, or raw exceptions.

## Security and resource invariants

- The Reviewer has no write, command, commit, merge, deployment, permission-mutation, or approval
  bypass capability.
- Input strings, collections, provider output, finding count, rationale, and recommendations are
  bounded before retention.
- One review causes exactly one provider call and zero tool calls.
- Timeout and cancellation propagate immediately; cancellation is never normalized as a failure.
- Injected providers and clients remain caller-owned and are never closed.
- Diff content and acceptance criteria are not persisted automatically.
- Error messages use stable codes and do not echo rejected or sensitive content.
- Findings use normalized relative paths only; absolute paths and traversal are rejected.

## TDD and acceptance scenarios

Tests must observe RED before production implementation and cover:

1. immutable and bounded request, check, finding, analysis, and result contracts;
2. rejection of self-review, wrong/inactive role, inconsistent scope, write tools, command tools,
   and non-read permissions before provider invocation;
3. exactly one bounded provider call and no tool execution;
4. deterministic approval when all required evidence passes and the analysis is acceptable;
5. deterministic `CHANGES_REQUESTED` for missing or failed required checks, unsuccessful Developer
   report, high/critical findings, low confidence, or model-requested changes;
6. malformed or adversarial structured output fails closed without leaking its content;
7. review score bounds, determinism, and severity weighting;
8. no prompt, response, diff, command output, absolute path, or raw provider error in results or
   errors;
9. timeout, cancellation, token and response-size limits, no retry, and caller-owned resources;
10. deterministic scenarios using `FakeLLMProvider` for both approval and requested changes;
11. Phase 16 orchestration, task transitions, QA, Security, and repository writes remain absent.

The complete gate remains pytest, Ruff, Ruff format check, mypy strict, Docker/PostgreSQL health,
Alembic head, and independent review.

## Documentation and checklist

Add `docs/reviewer-agent.md`, update `README.md` and `AGENTS.md`, and check only genuinely verified
Phase 15 items in `SYNAPSEOS_DEVELOPMENT_CHECKLIST.md`. Phase 16 and every later phase remain
unchanged.
