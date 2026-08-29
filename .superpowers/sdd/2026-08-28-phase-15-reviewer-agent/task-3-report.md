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
