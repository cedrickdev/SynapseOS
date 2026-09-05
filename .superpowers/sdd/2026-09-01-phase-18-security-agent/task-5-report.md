# Task 5 — deterministic Security veto and composition

Base: `65689d4`. Owned paths only; existing `.venv` preserved. No subagents.

## Requirements and evidence

Read task-5-brief.md first. Graph Verify context confirmed project
`synapseos-phase-18-security-agent`, generation `2026-09-04T20:57:30Z`.
Coverage reported no recorded gaps for the supplied QA/Security paths; analysis and
redaction metadata had changed, so current source was read directly. No exhaustive
caller or coverage claim is made.

## RED 1 — before any production edits

Command: `.venv/bin/pytest tests/security/test_decision.py tests/security/test_agent.py -q`

Exit: 1. Output: 49 failing tests (49 `F` progress markers, 100%).
The two public API assertions fail with `AssertionError: assert False` because
`build_security_result` and `SecurityAgent` are absent. Remaining tests fail with
`ModuleNotFoundError: No module named 'core.security.decision'` or
`ModuleNotFoundError: No module named 'core.security.agent'` during test execution.
The failures are the expected missing implementation, not collection errors.

Tests cover trust/severity decisions, completeness, provider proposals, reference
and location mismatches, source redaction, aggregation, one-shot composition,
validation order, scanner metadata leakage, failure classifications, deadlines,
cancellation, and caller-owned collaborator lifecycle.

The earlier attempted test edit was rejected by automatic approval review because
its usage quota was exhausted. No edit was applied; the user resumed from the clean
base. RED above was observed after that resumption.

## GREEN attempt 1 / RED 2 — stale QA handoff

The first implementation run of the same command passed 47 tests and failed 2.
Both failures were invalid fixtures: QA correctly forbids constructing a passed
result with failed or truncated tests. Corrected those fixtures to use deliberately
forged/stale handoffs (`model_copy`), retaining the brief's expected defensive WARN.

Command: `.venv/bin/pytest tests/security/test_decision.py -q -k 'failed-test or truncated-test' --tb=short`

Exit: 1. Output: `FF [100%]`, both failing at `build_security_result` with
`core.security.errors.SecurityError: Security input invalid.`

The gate must return a metadata-only WARN for a stale invalid handoff, without
using unvalidated evidence. The executing agent still rejects it before work.

## GREEN 2 and initial broad checks

Task 5 command: exit 0, 49 dots at 100% (all 49 passed).
Scoped Ruff import fix initially reported 17 remaining line-length errors; scoped
Ruff formatting then reported `5 files reformatted, 1 file left unchanged`.
`make lint && make typecheck`: exit 0, `All checks passed!` and
`Success: no issues found in 299 source files`.
`.venv/bin/pytest tests/security -o addopts='' -q`: exit 0,
`212 passed in 0.37s`.

## RED 3 — deadline and pending cancellation checkpoints

Command: `.venv/bin/pytest tests/security/test_agent.py -q -k scanner_cannot_continue --tb=short`

Exit: 1. Output: `FFF [100%]`. Late scanner return and swallowed timeout both
failed with `Failed: DID NOT RAISE SecurityError`. Pending cancellation failed
with `assert ['scanner', 'provider'] == ['scanner']`.

These actual boundary failures justify explicit checks of the global deadline
and pending cancellation between stages; a cooperative timeout alone cannot
stop downstream work when an injected scanner returns without yielding or
suppresses cancellation.

## GREEN 3 and final verification

The RED 3 command then exited 0 with `... [100%]` (all three regressions passed).
Additional characterization cases exercised wrong-type scanner reports, bare
credential echoes, constructor trust at the real agent boundary, and rejection
of mutable trust. These passed against the implementation without a production
change; they are supplemental coverage, not claimed as additional RED cycles.

Final commands and outputs:

```text
.venv/bin/pytest tests/security -o addopts='' -q
........................................................................ [ 32%]
........................................................................ [ 65%]
........................................................................ [ 98%]
....                                                                     [100%]
220 passed in 0.38s

make lint
.venv/bin/ruff check .
All checks passed!

make typecheck
.venv/bin/mypy .
Success: no issues found in 299 source files

.venv/bin/ruff format --check core/security/decision.py core/security/agent.py core/security/__init__.py tests/security/test_decision.py tests/security/test_agent.py tests/security/factories.py
6 files already formatted

git diff --check
(no output, exit 0)
```

All final commands exited 0. The Security suite includes 57 Task 5 tests and 163
existing tests. Intermediate checks found a test-only `SIM105` lint issue and a
misplaced `type: ignore` after formatting; both were corrected and all checks
rerun successfully. No failed check is omitted from this report.

## Delivered behavior

- Exported `SecurityAgent` and `build_security_result` with the specified signatures.
- Agent validates authority/scope and rejects obvious task-metadata secrets before
  scanner/provider work, sanitizes locally, calls the scanner once, strictly
  reconstructs its report, checks every scanner string before provider exposure,
  calls the existing analyzer once, and applies the deterministic gate.
- Local redactor evidence is regenerated from the validated request and always
  trusted. Scanner confirmation requires an allowlisted suite, matching reference
  source IDs, and an in-scope location. An injected scanner cannot impersonate the
  reserved local redactor source. Provider findings always remain suspected.
- Confirmed trusted HIGH/CRITICAL findings force BLOCK. Otherwise findings,
  incomplete evidence, source mismatch, unknown references, uncertainty, non-PASS
  provider proposals, untrusted scanners, or confidence below 0.80 prevent PASS.
- Findings are bounded to 64 after prioritizing confirmed vetoes and severity;
  aggregation overflow is explicitly reported as uncertainty. Critical evidence
  survives a full local batch and full provider batch.
- Public rationale and finding strings filter exact source/line echoes, quoted
  source credential values, and the shared obvious-secret shapes. Unsafe scanner
  text is rejected as SCANNER_FAILURE before any provider call, rather than merely
  cleaned after analysis. Diff findings use `diff.patch`.
- Scanner exceptions, including their own TimeoutError, are SCANNER_FAILURE;
  elapsed overall deadlines are TIMEOUT. Provider failures retain the analyzer's
  PROVIDER_FAILURE classification. Pending cancellation stops downstream work.
  Error diagnostics/chains are discarded; no retries, history, or collaborator
  close calls are introduced.

## Concerns and boundaries

1. A valid PASSED QAResult cannot contain failed/truncated tests. Agent entry
   rejects such a forged handoff before scanning. The standalone gate returns a
   metadata-only WARN with incomplete `security-gate` summary for an invalid typed
   handoff; it does not attest to unvalidated scanner/source findings. Tests cover
   this defensive behavior without weakening existing QA/Security constructors.
2. The disclosure filter is deliberately bounded and conservative, not a complete
   secret detector. It uses the existing Task 3 patterns plus literal source
   echoes and quoted credential values. It may reject benign scanner text that
   happens to quote source. Encoded/transformed unknown secret formats remain
   outside the approved narrow detector's guarantees.
3. The asyncio deadline cannot preempt blocking synchronous scanner code while it
   is running. Explicit checkpoints prevent downstream work or successful return
   after it comes back late. This is not a hostile-code execution sandbox.
4. Input evidence cannot be made complete by provider confidence. Untrusted and
   mismatched scanner findings are retained as suspected; provider-only BLOCK is
   WARN. An empty allowlist still preserves local redactor vetoes but cannot pass
   a scanner suite as trusted.
5. Private exception-cleanup logic is reused from the existing Security analyzer;
   no Task 1–4 implementation files were modified.
6. PostgreSQL verification supplied by the controller (dedicated port 55433) is
   not claimed as a command executed by this worker. Task 5 tests need no database.
   No adapter, persistence, Task 6+, or Phase 19 work was added.

Only the assigned six Python paths and this report are included in the Task 5
commit. The pre-existing `.venv` and all other work are preserved.

## Fix round 1/5 — short source fragments

Reviewer base: `ad6b568`. The scanner disclosure check treated every nonblank
source line as a substring signature. A one-character source line (`a`) therefore
matched ordinary scanner metadata such as `authorization` and raised
`SCANNER_FAILURE` before the required provider call.

### RED — focused regression before production edits

Test: `tests/security/test_agent.py::test_short_source_line_does_not_reject_ordinary_scanner_metadata`

Command:
`.venv/bin/pytest tests/security/test_agent.py::test_short_source_line_does_not_reject_ordinary_scanner_metadata -q`

Exit: 1. Output: `F [100%]`; the test failed at `SecurityAgent.run` with
`core.security.errors.SecurityError: Security scanner failed.` This is the expected
failure: source line `a` collided with valid scanner explanation
`Authorization controls were reviewed.` and the provider was not reached.

### Minimal fix and GREEN

`core/security/decision.py` now preserves exact canonical whole-source echo
detection for fragments of every size, but allows substring matching only for a
trimmed fragment of at least eight characters with at least four distinct
characters. The independent `contains_obvious_secret` check remains first and
unchanged. `core/security/agent.py` continues to use the shared predicate and did
not require modification. The deferred private-import minor was not changed.

Focused GREEN command: the same focused pytest command exited 0 with `. [100%]`.

Final commands and exact outputs (all exit 0):

```text
.venv/bin/pytest tests/security -o addopts='' -q
........................................................................ [ 32%]
........................................................................ [ 65%]
........................................................................ [ 97%]
.....                                                                    [100%]
221 passed in 0.37s

make lint
.venv/bin/ruff check .
All checks passed!

make typecheck
.venv/bin/mypy .
Success: no issues found in 299 source files

.venv/bin/ruff format --check core/security/decision.py core/security/agent.py tests/security/test_agent.py
3 files already formatted

git diff --check
(no output)
```

The pre-existing untracked `.venv` was preserved. No files outside the assigned
fix-round write scope were modified.
