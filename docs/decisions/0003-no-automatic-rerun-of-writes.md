# Never re-run a write task after a restart

Status: accepted

## Context

The server is a single process on a desktop and does restart. Re-running a task that had already written files or sent something could apply it twice.

## Decision

On startup, read-only tasks resume. Tasks that may have written are marked needs_reconciliation and shown to me instead of retried.

## Consequences

No double writes. A few tasks need a manual look after a crash.
