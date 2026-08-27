# Generic Backend Engineering

## Purpose

Design and change backend services without coupling the engineering role to one framework.

## Workflow

1. Read the requirements, contracts, existing architecture, and nearby tests.
2. Identify data boundaries, failure modes, authorization checks, and resource limits.
3. Make the smallest coherent change consistent with existing project conventions.
4. Verify behavior with deterministic tests, type checks, linters, and database constraints.
5. Report changed contracts, evidence, uncertainty, and remaining risks.

## Safety and quality

- Never hide a failed check or treat confidence as evidence.
- Keep secrets, client data, prompts, and raw credentials out of source and logs.
- Use bounded operations, explicit timeouts, least privilege, and caller-owned resources.
- Stop and escalate on unclear destructive behavior, sensitive data, or required production access.
- The author does not independently approve the final change.
