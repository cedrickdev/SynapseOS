# Phase 15 final security fix report

- Date: 2026-08-29
- Branch: `phase-15/reviewer-agent`
- Commit: `fix(reviewer): close final security findings`

## Scope and approved references

This fix wave was limited to the four final reviewed Phase 15 findings. The implementation was
checked against:

- `docs/superpowers/specs/2026-08-28-phase-15-reviewer-agent-design.md`;
- `docs/superpowers/plans/2026-08-28-phase-15-reviewer-agent.md`;
- the current `core/reviewer/` implementation and `tests/reviewer/` suite.

No subagents were used. `CLAUDE.local.md`, the Phase 16 scope, documentation checklists, and the
Phase 15 progress ledger were not modified.

## Finding 1 — exported gate type confusion

Root cause: `build_reviewer_result()` trusted frozen model instances and used enum identity checks.
Pydantic `model_copy(update=...)` bypassed validation, so raw strings such as
`"CHANGES_REQUESTED"`, `"HIGH"`, and `"FAILED"` could evade those checks and permit approval.

RED evidence:

```text
.venv/bin/pytest tests/reviewer/test_decision.py::test_exported_gate_rejects_type_confused_models_without_approval -q
FFF
3 failed: raw-decision, raw-severity, raw-developer-outcome
```

GREEN evidence:

```text
.venv/bin/pytest tests/reviewer/test_decision.py::test_exported_gate_rejects_type_confused_models_without_approval -q
... [100%]

.venv/bin/pytest tests/reviewer/test_decision.py -q
.................. [100%]
```

Fix: the exported gate now requires exact request/analysis classes, dumps and strictly revalidates
both values into detached canonical models, and returns only stable `INVALID_INPUT` or
`INVALID_ANALYSIS` failures for malformed values. Identity-based gate checks run only on the
canonical values. Existing missing-check coverage now uses a valid request whose required profile
has no corresponding check; validation-bypassing inconsistent check metadata is tested as a
sanitized input failure.

## Finding 2 — successful output could echo source evidence

Root cause: valid `ReviewAnalysis` rationale and finding text were copied directly into
`ReviewerResult`, allowing complete task title, task description, acceptance criterion, diff, or
source-derived secret markers to survive a successful review.

RED evidence:

```text
.venv/bin/pytest tests/reviewer/test_safety.py::test_agent_redacts_request_echoes_from_a_successful_structured_result -q
F
1 failed: the complete diff remained in ReviewerResult.rationale
```

GREEN evidence:

```text
.venv/bin/pytest tests/reviewer/test_safety.py::test_agent_redacts_request_echoes_from_a_successful_structured_result -q
. [100%]

.venv/bin/pytest tests/reviewer/test_decision.py tests/reviewer/test_safety.py tests/reviewer/test_agent.py tests/reviewer/test_integration.py -q
........................... [100%]
```

Fix: result construction now derives a bounded source set from the detached canonical request,
including title, description, criteria, diff, and Developer report text. It case-insensitively
detects complete source fragments and source-derived marker-like tokens. Echoed overall rationale,
finding rationale, and recommendation are replaced with stable application-owned text. Unsafe
finding category/path data are also replaced or removed, while severity and safe actionable
finding fields remain intact.

## Finding 3 — provider exceptions and malformed responses escaped

Root cause: the analyzer normalized only timeout and declared `LLMProviderError` failures, and it
read `response.content` before revalidating the provider response. An ordinary `RuntimeError` or an
`LLMResponse.model_copy(update={"content": object()})` therefore escaped with raw boundary state.

RED evidence:

```text
.venv/bin/pytest \
  tests/reviewer/test_analysis.py::test_analysis_sanitizes_unexpected_provider_exception_without_raw_context \
  tests/reviewer/test_analysis.py::test_analysis_revalidates_type_confused_response_without_raw_context -q
FF
2 failed: RuntimeError escaped; malformed content raised AttributeError
```

GREEN evidence:

```text
.venv/bin/pytest \
  tests/reviewer/test_analysis.py::test_analysis_sanitizes_unexpected_provider_exception_without_raw_context \
  tests/reviewer/test_analysis.py::test_analysis_revalidates_type_confused_response_without_raw_context \
  tests/reviewer/test_analysis.py::test_analysis_propagates_cancellation_after_one_attempt -q
... [100%]

.venv/bin/pytest tests/reviewer/test_analysis.py -q
...................... [100%]
```

Fix: `asyncio.CancelledError` remains explicitly propagated. Every ordinary provider-boundary
exception is detached, frame-cleared, and normalized to `PROVIDER_FAILURE`. A returned value must
be an exact `LLMResponse`; its dumped immutable mappings are copied into detached dictionaries and
the complete response is strictly revalidated before `content` is accessed. Malformed responses
produce only `INVALID_ANALYSIS`, with no raw cause, context, or secret-bearing traceback values.

## Finding 4 — Windows and UNC paths accepted

Root cause: `PurePosixPath` alone treats Windows drives and backslashes as ordinary relative path
text on POSIX hosts.

RED evidence:

```text
.venv/bin/pytest tests/reviewer/test_types.py::test_finding_rejects_windows_drive_unc_and_backslash_paths -q
FFF.F
4 failed: C:/, C:\\, backslash UNC, and relative backslash paths were accepted
```

GREEN evidence:

```text
.venv/bin/pytest \
  tests/reviewer/test_types.py::test_finding_rejects_windows_drive_unc_and_backslash_paths \
  tests/reviewer/test_types.py::test_finding_normalizes_a_relative_path -q
...... [100%]

.venv/bin/pytest tests/reviewer/test_types.py -q
.................................... [100%]
```

Fix: the relative-path validator now rejects every backslash, every `PureWindowsPath` drive, and
slash-form UNC prefixes in addition to the existing POSIX absolute/traversal/normalization checks.
Regression cases cover `C:/`, `C:\\`, `\\\\server\\share`, `//server/share`, and a relative
backslash path.

## Files changed

Production:

- `core/reviewer/decision.py` — strict exported-gate canonicalization and deterministic source
  echo redaction;
- `core/reviewer/analysis.py` — ordinary provider exception normalization and strict detached
  `LLMResponse` canonicalization;
- `core/reviewer/types.py` — portable relative-path validation.

Tests:

- `tests/reviewer/test_decision.py`;
- `tests/reviewer/test_safety.py`;
- `tests/reviewer/test_analysis.py`;
- `tests/reviewer/test_types.py`.

Delivery evidence:

- `.superpowers/sdd/2026-08-28-phase-15-reviewer-agent/final-fix-report.md`.

## Final verification

```text
make format
1 file reformatted, 282 files left unchanged

.venv/bin/pytest tests/reviewer -q
all Reviewer tests passed

make lint
All checks passed!

.venv/bin/ruff format --check .
283 files already formatted

make typecheck
Success: no issues found in 222 source files

make test
1045 passed in 39.02s

git diff --check
clean
```

The first sandboxed project-wide test attempt could not connect to local PostgreSQL and ended with
`938 passed, 107 errors`. Those errors were exclusively database setup failures caused by
`Operation not permitted` on local port `55432`. The same unmodified suite was immediately rerun
with local PostgreSQL access and completed with `1045 passed`.

## Concerns and limitations

- No open correctness or security concern remains for the four reviewed findings.
- Echo redaction is deliberately conservative and may replace otherwise useful text when it
  contains a complete canonical source fragment or an obvious source-derived marker token. Safe
  finding structure is retained to reduce that cost.
- The redactor prevents literal raw source echo and obvious marker echo; it is not a semantic
  paraphrase detector or a general-purpose secret scanner. That broader capability is outside
  Phase 15.
- The final commit hash is reported in the handoff because a commit cannot include its own hash in
  the report it contains. The single commit message is
  `fix(reviewer): close final security findings`.
- The pre-existing untracked `CLAUDE.local.md` remains untouched and will not be staged.
