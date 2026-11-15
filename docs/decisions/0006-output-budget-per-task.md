# Cap output at 24,000 tokens per orchestrated task

Status: accepted

## Context

A runaway plan with many subtasks could spend a large share of a day's budget on one request.

## Decision

Each orchestrated task has a total output budget of 24,000 tokens, including planning and review, split across subtasks with a reserve.

## Consequences

Costs are bounded and visible. The number is fixed for now and should be tuned per kind of work once there is more data.
