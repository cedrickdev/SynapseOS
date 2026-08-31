# Deterministic Testing

## Purpose

Produce repeatable evidence that a required behavior works and realistic regressions are caught.

## Workflow

1. State the production defect or mutation that the test must detect.
2. Derive expected results independently from the implementation.
3. Observe the focused test fail for the intended reason before production changes.
4. Implement the minimum behavior, rerun focused tests, then run neighboring regressions.
5. Record every failure, command outcome, unresolved risk, and environmental dependency.

## Safety and quality

- Use real components unless an external or expensive boundary requires a precise test double.
- Bound fixtures, output, time, concurrency, and generated data.
- Never hide flaky, failed, skipped, or unavailable checks.
- Stop and escalate when required infrastructure or authoritative evidence is unavailable.
- A passing test supports a claim only for the behavior it actually exercises.
