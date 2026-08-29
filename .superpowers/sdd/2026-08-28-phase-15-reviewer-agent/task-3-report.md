# Phase 15 Task 3 — One-shot structured review analysis

## Scope delivered

- Added `ReviewAnalyzer`, a provider-neutral, one-shot analysis boundary.
- Added focused behavioral coverage for valid structured analysis, canonical preflight input,
  malformed/adversarial output, provider failure, cancellation, and token bounds.
- Exported `ReviewAnalyzer` from `core.reviewer`.

No Reviewer Agent composition, decision gate, scoring, runtime/tool execution, task transitions,
Phase 16 behavior, or `CLAUDE.local.md` changes were included.

## RED evidence

Before production code existed, the new focused test command was run:

```text
.venv/bin/pytest tests/reviewer/test_analysis.py -q
```

It failed at collection with the expected missing public interface:

```text
ImportError: cannot import name 'ReviewAnalyzer' from 'core.reviewer'
```

## GREEN evidence

After the minimal implementation:

```text
.venv/bin/pytest tests/reviewer/test_analysis.py tests/reviewer/test_validation.py -q
35 passed
```

The complete Reviewer suite then passed:

```text
.venv/bin/pytest tests/reviewer -q
66 passed
```

## Quality evidence

```text
.venv/bin/ruff check core/reviewer tests/reviewer
All checks passed!

.venv/bin/ruff format --check core/reviewer tests/reviewer
10 files already formatted

.venv/bin/mypy core/reviewer tests/reviewer
Success: no issues found in 10 source files

git diff --check
exit 0
```

The repository-wide `make check` lint and typing stages passed. Its first test invocation was blocked
from the sandbox's local PostgreSQL connection. With local database access permitted, the first full
test run reached 996 passing tests and one unrelated timing failure in
`tests/tools/test_git_tools.py::test_git_process_is_killed_when_execution_is_cancelled`. A clean
repeat of the full suite passed:

```text
make test
997 passed in 8.63s
```

## Self-review

- `analyze()` calls Task 2 preflight first and prompt construction reads only
  `ValidatedReviewerRequest.request`, never the original mutable request.
- The implementation has one `LLMProvider.generate()` call, no retry loop, no fallback provider,
  and no runtime or tool-executor dependency.
- The request has one system prompt and one user message, `temperature=0.0`, an explicit
  constructor-bounded token ceiling of `1..4096`, and empty metadata.
- User evidence is deterministic compact JSON from canonical task evidence only; Reviewer IDs,
  profile/system prompt, and authority metadata are not included.
- `decode_structured_output()` enforces a strict JSON object and the strict `ReviewAnalysis` model;
  malformed JSON, unknown fields, oversized findings, and unsafe paths are normalized to
  `ReviewerError(INVALID_ANALYSIS)` without response content.
- `LLMProviderError` becomes `ReviewerError(PROVIDER_FAILURE)` without raw provider diagnostics.
  `asyncio.CancelledError` is not caught and propagates unchanged.
- The raw `LLMResponse` local is deleted after decoding or structured-output failure; it is not
  stored on the analyzer or returned.

## Concerns

None. Provider request timeouts are not a field in the existing provider-neutral `LLMRequest`
contract, so this bounded Task 3 implementation did not introduce a new provider capability.

## Fix round 1 — provider-boundary hardening

### Root cause

The initial one-shot boundary raised `ReviewerError` inside active `except` blocks. Python therefore
attached the raw provider or output-validation exception as `__context__`; the exception traceback
also retained local request, prompt, and response references. The original boundary also had no
Reviewer-owned provider deadline, no byte limit before decoding, and an underspecified response
contract.

### RED evidence

New tests were added before production changes for:

- raw provider and structured-output markers in `ReviewerError.__context__`, `__cause__`, public
  representations, and traceback frame locals;
- the exact compact output contract and closed decision/severity enums;
- a 131,073-byte response rejected before invoking the decoder;
- Reviewer-owned timeout normalization and bounded timeout constructor validation.

The initial focused RED run was:

```text
.venv/bin/pytest tests/reviewer/test_analysis.py tests/agents/test_structured_output.py -q
10 failed, 31 passed
```

The failures demonstrated the missing JSON contract, raw `LLMProviderError` and
`AgentOutputValidationError` in `ReviewerError.__context__`, absent timeout constructor argument,
and oversized content reaching the decoder.

An exploratory shared-decoder change was rejected after it broke strict JSON-array-to-immutable-
tuple behavior. It was fully reverted. The Reviewer performs one decoder invocation after the byte
check and does not pre-parse the response; the established shared strict decoder remains unchanged.

### GREEN evidence

The final focused runs succeeded:

```text
.venv/bin/pytest tests/reviewer/test_analysis.py -q
....................                                                     [100%]

.venv/bin/pytest tests/reviewer/test_analysis.py tests/reviewer/test_validation.py \
  tests/reviewer/test_types.py -q
........................................................................ [ 96%]
...                                                                      [100%]
```

Collection confirms 75 focused tests: 20 analysis, 24 validation, and 31 type-contract tests.

### Quality evidence

```text
.venv/bin/ruff check core/reviewer tests/reviewer
All checks passed!

.venv/bin/ruff format --check core/reviewer tests/reviewer
10 files already formatted

.venv/bin/mypy core/reviewer tests/reviewer
Success: no issues found in 10 source files

git diff --check
exit 0
```

### Fix-round self-review

- Public `analyze()` receives only a detached success value or sanitized error from the internal
  operation, deletes request and analyzer references before raising, and raises outside every
  exception context.
- Raw provider, timeout, and structured-output exceptions have their tracebacks, causes, contexts,
  and retained traceback frames cleared before deletion. Tests inspect `str`, `repr`, exception
  links, and each resulting traceback-local representation for a secret marker.
- Generation is wrapped once in `asyncio.timeout`; `timeout_seconds` is finite, strictly positive,
  and at most 30 seconds. External `asyncio.CancelledError` is explicitly re-raised without
  normalization. There is no retry or fallback path.
- Response content is encoded once as UTF-8 and rejected above the finite 131,072-byte Reviewer
  ceiling before the single strict decode entry point.
- The system prompt specifies the exact response keys, finding keys, closed decision and severity
  enums, and rejection of extra keys/prose.

### Concerns

None for this round. The response ceiling is intentionally a Reviewer-local resource limit;
provider timeout remains caller-owned by `ReviewAnalyzer` and is not added to the shared provider
contract.

### Repository-wide verification

The final `make check` Ruff and mypy stages passed. Its first test attempt had one unrelated
Git-process startup timing failure (`1 failed, 1005 passed` in
`tests/tools/test_git_tools.py::test_git_process_is_killed_when_execution_is_cancelled`). No
unrelated code was changed. A clean repeat succeeded:

```text
make test
1006 passed in 8.70s
```
