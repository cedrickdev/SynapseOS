# Task 4 Report: Planning, Decision, and Reporting Operations

## Scope

Implemented only the bounded Phase 5 `Agent.plan()`, `Agent.decide()`, and
`Agent.report()` operations, together with their focused workflow tests. The
shared private generation path was extracted only after the three individual
operation tests were green. No tools, skills, persistence, lifecycle ownership,
or orchestration behavior was added.

## RED/GREEN Evidence

### Plan

RED command:

```bash
.venv/bin/pytest tests/agents/test_agent_workflow.py::test_plan_returns_validated_plan_with_one_call -q
```

Observed result: failed with `AttributeError: 'Agent' object has no attribute
'plan'`.

GREEN command:

```bash
.venv/bin/pytest tests/agents/test_agent_workflow.py::test_plan_returns_validated_plan_with_one_call -q
```

Observed result: `1 passed`.

The test proves validated `Plan` return data, one provider request, explicit
`max_tokens`, one objective occurrence, validated observation JSON only in the
user message, and successful `PLAN` metadata history.

### Decide

RED command:

```bash
.venv/bin/pytest tests/agents/test_agent_workflow.py::test_decide_returns_validated_decision_with_one_call -q
```

Observed result: failed with `AttributeError: 'Agent' object has no attribute
'decide'`.

GREEN command:

```bash
.venv/bin/pytest tests/agents/test_agent_workflow.py::test_decide_returns_validated_decision_with_one_call -q
```

Observed result: `1 passed`.

The test proves validated `Decision` return data including finite bounded
confidence, one provider request, explicit `max_tokens`, only validated
observation and plan JSON in the user message, and successful `DECIDE` metadata
history.

### Report

RED command:

```bash
.venv/bin/pytest tests/agents/test_agent_workflow.py::test_report_returns_validated_report_with_one_call -q
```

Observed result: four parameterized failures, each with
`AttributeError: 'Agent' object has no attribute 'report'`.

GREEN command:

```bash
.venv/bin/pytest tests/agents/test_agent_workflow.py::test_report_returns_validated_report_with_one_call -q
```

Observed result: `4 passed`.

The test proves validated `AgentReport` return data for `SUCCEEDED`, `FAILED`,
`BLOCKED`, and `NEEDS_HUMAN`; one provider request; explicit `max_tokens`; only
validated observation, plan, and decision JSON in the user message; and
successful `REPORT` metadata history.

## Safety and Boundary Coverage

Command:

```bash
.venv/bin/pytest tests/agents/test_agent_workflow.py -q
```

Observed result: `19 passed`.

The focused suite additionally proves:

- malformed output raises the safe `AgentOutputValidationError`, retains no
  history, and does not expose the response marker;
- provider errors propagate as the same instance after one request, with no
  retry or history entry;
- `asyncio.CancelledError` propagates after one attempted request, with no
  history entry;
- blank and oversized objectives fail before the provider records a request;
- out-of-range decision confidence is rejected without history;
- maximum valid structured inputs keep serialized plan, decision, and report
  prompts within their derived bounded character limits.

## Final Verification

Commands and results:

```bash
.venv/bin/pytest tests/agents -q
# 128 passed

.venv/bin/ruff check core/agents tests/agents && .venv/bin/mypy core/agents tests/agents
# All checks passed!
# Success: no issues found in 11 source files

make test
# 414 passed in 1.51s
```

`git diff --check` was clean during self-review. The review confirmed that each
public operation has one explicit-token provider call, no retry, repair, or
fallback; provider errors and cancellation are not caught; only successful
decoded values append metadata-only history; and prompts never include prior
history or raw provider output.
