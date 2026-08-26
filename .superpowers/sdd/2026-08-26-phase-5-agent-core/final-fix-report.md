# Phase 5 Agent Core Final Fix Report

Date: 2026-08-26
Branch: `phase-5/agent-core`
Fix base: `f06b4f6c6019edffffec50a9e7532a193666106e`

## Summary

Fixed the final-review security wave for Phase 5 Agent Core:

- Revalidated every `AgentProfile` instance in `Agent.__init__`, including forged
  `model_copy(update=...)` profiles, before storing it.
- Added agent-level exception-boundary tests that recursively inspect exception public state,
  cause/context, traceback frames, local values, and local `repr()` output for unique markers.
- Scrubbed Phase 5 agent-frame locals before re-raising output-validation failures, provider
  failures, cancellation, forged structured inputs, invalid profiles, and prompt-cap failures.
- Preserved provider exception and `asyncio.CancelledError` identity, with no wrapping, retry, or
  duplicate call.
- Added an explicit 262,144-character generated user prompt ceiling before
  `LLMProvider.generate()`.
- Replaced the tautological history-replay marker assertion with a real observe-then-plan sequence.
- Documented the new prompt ceiling in `docs/agent-core.md` and ADR-0005.

## Files Changed

- `core/agents/agent.py`
- `tests/agents/test_agent_safety.py`
- `tests/agents/test_agent_workflow.py`
- `docs/agent-core.md`
- `docs/adr/0005-agent-runtime-boundary.md`
- `.superpowers/sdd/2026-08-26-phase-5-agent-core/final-fix-report.md`

## RED Evidence

Command:

```bash
.venv/bin/pytest tests/agents/test_agent_safety.py -q
```

Result before production edits: failed as expected, `9 failed, 1 passed`.

Representative failures:

- Output-validation failure traceback retained `profile-traceback-marker-2d89` through
  `core/agents/agent.py` frame local `self.__dict__['_profile'].__dict__['system_prompt']`.
- Provider-failure and cancellation tracebacks retained the profile marker through agent frames.
- Forged profiles were accepted instead of raising.
- Escape-heavy over-cap prompts reached the provider instead of failing before generation.

Command:

```bash
.venv/bin/pytest tests/agents/test_agent_workflow.py::test_plan_returns_validated_plan_with_one_call -q
```

Result after replacing the tautological replay assertion: `1 passed`. This was a test-quality fix:
the strengthened real observe-then-plan sequence confirmed the existing implementation already did
not replay the earlier subject or raw response metadata into the later request, so no production
change was made for that finding.

## GREEN Evidence

Command:

```bash
.venv/bin/pytest tests/agents/test_agent_safety.py -q
```

Result: `10 passed`.

Command:

```bash
.venv/bin/pytest tests/agents -q
```

Result: exit `0`, all agent tests passed through `[100%]`.

Command:

```bash
TEST_POSTGRES_PORT=55432 make test
```

Result: `430 passed in 1.53s`.

Command:

```bash
.venv/bin/ruff check .
```

Result: `All checks passed!`

Command:

```bash
.venv/bin/ruff format --check .
```

Result: `95 files already formatted`.

Command:

```bash
.venv/bin/mypy .
```

Result: `Success: no issues found in 73 source files`.

Command:

```bash
git diff --check
```

Result: exit `0`, no output.

## Security Self-Review

- Exception safety: tests traverse exception strings, `repr()`, `args`, public attributes,
  `__cause__`, `__context__`, every traceback frame local, and recursively reachable values through
  Pydantic models, `LLMRequest`, `LLMResponse`, provider doubles, `self`, mappings, and collections.
- Sensitive marker coverage: system prompt/profile, subject, objective, structured inputs, raw
  response content/metadata, generated request content, forged profile data, and oversized prompt
  content.
- Provider behavior: valid operations still make exactly one provider call; provider errors and
  cancellation propagate as the same exception instances; pre-provider validation and prompt-cap
  failures make zero provider calls.
- History behavior: history remains success-only metadata and does not retain prompts, subjects,
  objectives, raw responses, structured outputs, provider metadata details, or errors.
- Scope: no Phase 6+ tool execution, permissions engine, provider routing, lifecycle ownership,
  autonomous loop, checklist update, merge, push, or subagent dispatch was added.
- Decoder strictness: `core/agents/structured_output.py` was not weakened or relaxed.

## Concerns

- To satisfy the confidentiality requirement for provider failures and cancellations, the agent
  clears sensitive traceback chains while preserving the original exception object. This
  intentionally reduces traceback detail available to callers, but prevents prompts and profile
  data from remaining reachable through stack frames.
