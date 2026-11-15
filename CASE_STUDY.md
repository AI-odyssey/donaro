# Case study: running a one-person consultancy on several AI models

## The problem

I work alone across nine areas: client policy work, academic research, content, development, writing, design, learning, finance and personal admin. By October 2026 I was using Claude, Codex, Gemini and a few others every day, each in its own app.

Three things kept going wrong.

1. **Quota stalls.** A long task would stop halfway because one provider hit its limit, and I would only notice hours later.
2. **Lost context.** Each app knew only its own conversation. I re-explained the same project to three models in a week.
3. **No overview.** I couldn't answer "what is running right now, and what is waiting for me?" without opening every app.

On top of that, the policy work involves confidential client material that must not reach every vendor.

## What I built first, and why it wasn't enough

The first version (early November) was a single chat page that forwarded everything to one model. It worked until the quota ran out. The second version added a fallback list, but it retried exhausted providers on every request and charged me for failed calls.

The very first logged call is a good picture of the early waste: I asked "what is 2 plus 2" and the call loaded 60,043 tokens of context, about USD 0.24, for a one-digit answer.

## Decisions that changed it

Each of these has a short record in `docs/decisions/`.

1. **A top model plans, others execute, a different vendor reviews.** Claude Opus plans and Codex is the fallback planner. The reviewer is a top-tier model, and from a different vendor than the writer whenever one is available.
2. **Track quota as state, not as errors.** When a provider says it is out, the router stores the reset time and skips it until then. If a whole chain is out, the task waits and resumes itself.
3. **Answer trivial things without a model.** Arithmetic and dates go to local code.
4. **Code changes only in throwaway worktrees.** Models propose patches; the server checks paths, runs tests, gets an independent review and only then merges.
5. **Never re-run a write after a crash.** On restart, write tasks are flagged for reconciliation instead of retried.
6. **Cap output per task** at 24,000 tokens so one runaway plan can't burn a day's budget.
7. **Confidential work stays on one vendor.** Client material runs only on Claude; if Claude is down, the task waits.

## A failure I want to show

On 14 November I saw sentences in my chat history that I had never typed. The cause was my own test harnesses: they called the live task API, and the server recorded every request as if I had sent it, so test text also leaked into the context of my next real request.

The fix was small once found. Requests now carry a `source` field (`chat` or `harness`). Harness requests skip chat history, follow-up context and notifications, and appear only on the board's test-task list. I moved 64 polluted entries out of the history and added a rule that any manual test must be marked as a harness request.

## After

| | Before (early Nov) | Now (16 Nov) |
|---|---|---|
| Entry points | one chat page | web, voice, iOS Shortcut, one API |
| Providers | one, then a blind fallback list | 11 models from 5 vendors with per-kind chains |
| Quota handling | retry and fail | skip until reset, wait and resume |
| Code changes | none | per-task worktree, tests, independent review, merge |
| Overview | open each app | one board: live tasks, local sessions, scheduled jobs, daily usage |
| Real tasks handled | | 82, of which 47 completed without my help |

What I still don't measure well: first-pass completion (done without me re-asking), cost per completed task, and how often I had to step in. These are the next metrics, and the work ontology in `docs/ontology.md` is meant to make them easy to compute.
