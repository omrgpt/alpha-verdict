# ADR 0003: Deterministic agents before optional AI

- Status: accepted
- Date: 2026-08-20

## Context

Model-generated review can be persuasive without being reproducible and can leak
private evidence to external providers.

## Decision

Verdicts and finding codes come only from deterministic local agents. An optional
model may summarize merged audit JSON through a user-supplied callable after the
verdict exists.

## Consequences

The audit is reproducible and key-free. Natural-language output is less flexible by
default, but cannot silently alter ranks or conclusions.
