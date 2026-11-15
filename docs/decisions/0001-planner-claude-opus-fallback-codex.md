# Top model plans, Codex is the fallback

Status: accepted

## Context

Multi-step requests need one model to choose the approach, split the work and set budgets. A weak plan wastes every later call.

## Decision

Claude Opus plans. If it is out of quota or failing, the top Codex model plans instead. Cheaper models only execute subtasks.

## Consequences

Plans are more consistent and fewer subtasks get thrown away. The cost is that planning always uses an expensive model, which is why trivial requests skip planning entirely.
