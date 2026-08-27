# Generic Frontend Engineering

## Purpose

Implement understandable and accessible interfaces while preserving the product's established
design language.

## Workflow

1. Read user journeys, acceptance criteria, components, tokens, and accessibility requirements.
2. Identify loading, empty, error, permission, responsive, and keyboard states before changing UI.
3. Reuse established components and keep state ownership explicit and local where practical.
4. Verify behavior using deterministic tests, accessibility checks, type checks, and linting.
5. Report supported states, evidence, uncertainty, and known limitations.

## Safety and quality

- Never expose secrets or sensitive server data in browser code, errors, or telemetry.
- Bound rendered collections and network-driven content; preserve cancellation and timeouts.
- Never conceal failed checks or substitute model confidence for observable evidence.
- Stop and escalate ambiguous destructive actions, authentication changes, or privacy risks.
- Require independent review before acceptance.
