# ADR 0002: Bitemporal features and events

- Status: accepted
- Date: 2026-08-20

## Context

Fundamental periods, event dates, publication dates, vendor ingestion, and revisions
are not the same time. A single timestamp makes leakage easy and difficult to audit.

## Decision

Features carry `observed_at` and `available_at`; events carry `event_at` and
`available_at`; universe rows carry effective intervals and `available_at`.
Snapshots filter knowledge time centrally.

## Consequences

Adapters require more work and data. In exchange, strategy code receives a clear
causal boundary and revisions remain inspectable.
