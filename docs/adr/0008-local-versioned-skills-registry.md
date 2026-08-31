# ADR-0008 — Local versioned Skills Registry

- **Status:** Accepted
- **Date:** 2026-08-26
- **Deciders:** SynapseOS owner and engineering agent

## Context

Agents need reusable craft guidance that can vary by mission and technology without hard-coding
framework-specific roles. The first registry must be inspectable, versioned, deterministic,
resource-bounded, provider-neutral, and unable to silently gain execution authority.

## Options considered

- Local versioned skill packages — reviewable with code, simple provenance, deterministic loading,
  and no synchronization service.
- PostgreSQL skill records — centrally queryable but duplicate version-control concerns and require
  premature mutation, synchronization, and administration APIs.
- Remote marketplace — flexible distribution but introduces trust, signatures, downloads, network
  lifecycle, and supply-chain policy beyond Phase 8.

## Decision

Use immutable local packages containing strict YAML metadata and bounded Markdown. Load one complete
caller-selected snapshot with no links, partial success, cache, retry, or remote source. Keep the
core registry and deterministic selector independent of filesystem/YAML infrastructure.

Permission metadata is an eligibility prerequisite, not authority. The Phase 7 database-backed
policy remains the only tool-execution authority. Agent skill declarations stay inert, and no skill
content is automatically injected into a model prompt in Phase 8.

## Consequences

- Skill changes are ordinary reviewed repository changes with explicit semantic versions.
- Invalid content fails the entire explicit load and emits only sanitized errors.
- V1 selection is predictable and explainable but intentionally less semantic than future routing.
- Remote distribution, signatures, persistence, hot reload, and runtime prompt integration require
  separate architecture and security decisions.
