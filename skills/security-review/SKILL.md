# Independent Security Review

## Purpose

Identify credible security risks independently and block critical unresolved findings.

## Workflow

1. Establish assets, trust boundaries, actors, entry points, permissions, and sensitive data flows.
2. Inspect changed code, dependencies, configuration, tests, and failure paths using least privilege.
3. Classify findings by exploitability, impact, evidence, affected resource, and remediation.
4. Verify remediations with deterministic tests or scanners and recheck bypass paths.
5. Report findings without secrets, distinguish evidence from inference, and record residual risk.

## Safety and quality

- Never place credentials, exploit payload secrets, client data, or unsafe raw content in reports.
- Never approve the review author's own critical change without independent evidence.
- Bound scans and reads; do not execute untrusted code or access production by default.
- Stop and escalate critical findings, authorization ambiguity, destructive tests, or sensitive data.
- A known critical vulnerability blocks release until remediated or explicitly governed.
