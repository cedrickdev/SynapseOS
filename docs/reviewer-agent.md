# Reviewer Agent

Phase 15 adds an independent, read-only `ReviewerAgent`. It evaluates one bounded set of Developer
evidence and returns `APPROVED` or `CHANGES_REQUESTED`. It does not modify the repository, execute
tools, change task state, merge code, or coordinate agents.

## Input boundary

`ReviewerRequest` is immutable and bounded. It contains stable project, task, Developer, and
Reviewer identifiers; task title and description; one through sixteen acceptance criteria; a
bounded unified diff; explicit required command-profile IDs; deterministic command results; the
Developer report; and an active Reviewer profile.

Preflight canonicalizes a detached copy before evaluating authority. It rejects self-review,
inactive or incorrect roles, inconsistent scope, unknown or write-capable tools, and any permission
outside `filesystem.read` and `git.read`. `filesystem.read` is mandatory. No provider call occurs
when preflight fails.

## One-shot analysis

`ReviewAnalyzer` performs exactly one provider-neutral `LLMProvider.generate()` call. The request
uses temperature `0`, an explicit `max_tokens` ceiling, a Reviewer-owned timeout, empty metadata,
and an exact JSON contract. Repository evidence is marked as untrusted data and cannot change the
Reviewer's authority.

Provider responses are bounded to 128 KiB before decoding. The strict result schema allows at most
64 findings with a closed severity enum, normalized relative paths, bounded rationale and
recommendations, and confidence from `0.0` through `1.0`. There is no retry, fallback provider, or
repair call. Cancellation propagates immediately. Provider and validation failures are detached
from raw exception chains and exposed only as stable sanitized errors.

## Deterministic approval gate

The provider proposes a review; application evidence decides whether approval is permitted.
`APPROVED` requires all of the following:

- Developer and Reviewer are distinct;
- the Developer report is `SUCCEEDED`;
- every explicitly required command profile has complete, canonical, non-truncated, passing
  evidence;
- no finding is `HIGH` or `CRITICAL`;
- the model proposed `APPROVED`;
- confidence is at least `0.70`.

Any failed condition produces `CHANGES_REQUESTED` and a stable deterministic blocker finding. The
gate may downgrade an approval but never upgrade a rejection. A full 64-finding model response
cannot hide the deterministic blocker.

## Review score

`calculate_review_score()` derives a deterministic `Decimal` value between `0.0` and `1.0` from
command evidence and fixed finding-severity penalties. The model cannot supply or override this
score. The result exposes the score for this review only; Phase 15 does not update reputation or
persist score history.

## Resource and confidentiality guarantees

- The Reviewer has no write, command, commit, merge, deployment, or permission-mutation API.
- The agent retains only its injected analyzer configuration, never request/result history.
- Injected providers are caller-owned and are never closed by the Reviewer.
- Raw provider responses, prompts, diffs, command output, and absolute paths are not persisted.
- Public errors contain no rejected content, provider diagnostic, or raw exception chain.
- Every collection, input string, response, generation, and network wait has a finite bound.

## Testing

The focused suite is deterministic and requires no live model:

```bash
.venv/bin/pytest tests/reviewer -q
```

`FakeLLMProvider` covers approval, requested changes, failed-test downgrade, one-call behavior, and
malformed output. Additional adversarial tests cover type-confusion attempts, self-review,
read-only authority, response limits, timeouts, cancellation, exception leakage, finding budgets,
and deterministic scoring.

## Deferred work

Phase 16 orchestration between Developer and Reviewer, correction cycles, task transitions, QA,
Security, merge gates, GitHub integration, persistence, reputation aggregation, and multi-agent
coordination remain unimplemented.
