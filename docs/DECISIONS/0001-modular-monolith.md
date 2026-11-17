# ADR 0001 — Modular monolith with explicit internal boundaries

* Status: accepted
* Date: 2026-11-17

## Context

The brief recommends a monorepo with `services/api`, `orchestrator`, `telephony`, `speech`, `risk-engine`. It also says a
modular monolith with clear service boundaries is acceptable for V1 and that correctness, testability and deployment
simplicity come first.

The real-time call path (audio → transcript → safety rules → state machine → reply → speech) is latency-sensitive and
stateful. Splitting it across network hops would add latency, partial-failure modes and operational surface without
product benefit at V1 scale.

## Decision

* One deployable Python service (`services/api`, importable package `sparta`).
* Internal packages mirror the recommended services and communicate **only through typed interfaces**:
  `sparta.risk`, `sparta.language`, `sparta.orchestrator`, `sparta.providers` (speech/LLM/VAD), `sparta.telephony`.
* Import direction is enforced by convention and a unit test: `risk` and `language` import nothing from `orchestrator`,
  `telephony`, `db` or `api`; `orchestrator` never imports `api`.
* `apps/web` and `apps/android` consume the HTTP/WebSocket contract only. The OpenAPI document is exported to
  `packages/contracts/openapi.json` and checked in CI for drift.
* The `/services/*` directories from the recommendation are not created as empty shells.

## Consequences

* Simplest possible local run and deployment (one container + Postgres + Redis).
* Any boundary can be extracted into its own service later because it already has an interface, tests and no upward
  imports.
* The package layout deviates from the literal recommended tree; this ADR documents the intentional change.
