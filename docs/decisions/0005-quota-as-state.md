# Treat quota limits as state with a reset time

Status: accepted

## Context

Early versions retried an exhausted provider on every request, which failed slowly and sometimes cost money.

## Decision

When a provider reports a limit, the router stores its health and the earliest reset time and skips it until then. If every model in a chain is out, the task moves to a waiting state and resumes on its own after the reset (up to six hours).

## Consequences

Fewer failed calls and no silent stalls. Reset times are estimates, so a task may wait slightly longer than needed.
