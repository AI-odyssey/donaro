# Answer arithmetic and dates without a model

Status: accepted

## Context

The first logged call asked for 2 plus 2 and loaded 60,043 cache tokens, about USD 0.24.

## Decision

The router answers arithmetic and date questions with local code before any model is considered.

## Consequences

Those requests cost nothing and return instantly.
