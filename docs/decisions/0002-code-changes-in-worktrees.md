# Code changes only in per-task git worktrees

Status: accepted

## Context

Letting a model edit the live checkout directly risks half-applied changes, edits outside the intended files, and secrets being touched.

## Decision

Each code task gets its own branch and worktree from a snapshot of the source (including uncommitted changes). The model returns file patches; the server checks allowed paths and surrounding context, runs the checks, gets an independent review and checks for conflicts before merging. Deletes, out-of-scope edits and failing checks are never merged automatically. Models get no shell on the main checkout.

## Consequences

Code changes are reversible and reviewable. Merges are slower and some valid changes (like file deletion) need a human step.
