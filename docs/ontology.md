# Work ontology (draft, 16 Nov 2026)

Status: proposal, waiting for approval of the object list. Not implemented yet.

The task store today only models the system itself: departments and which model is assigned to each. It does not model the work. This draft names the nouns of the work so the board and the agents can operate on the same objects.

## Objects

Phase 1 (data already exists):

| Object | What it is | Key properties | Relations | Actions (who) |
|---|---|---|---|---|
| Engagement | one work folder, which is also one row in the Notion work log | folder path (key), title, department, status, category, client alias | belongs to a department; has tasks, deliverables, decisions, deadlines | create (AI), change status (AI or me), sync with Notion (automatic), archive (my approval) |
| Task | one piece of work done by an AI, whatever the source: a Donaro task, a Claude Code or Codex session, a scheduled run | source, title, status, current step, assigned model, start/end, tokens, test flag, confidential flag | belongs to an engagement; has model calls; creates deliverables; raises decisions; parent/child | submit (me or AI), cancel and retry (me), move department (me) |
| Deliverable | a file a task produced | path, kind, producing task, review result, external or internal | made by a task; belongs to an engagement; reviewed | pass/return (QC agent), send to phone (AI), send externally (my approval only) |
| Decision | something only I can decide | question, recommendation, alternatives, status, due date | raised by a task or engagement; unblocks tasks | raise (AI), approve or reject (me only) |
| Deadline | a dated commitment | date, kind, days left | belongs to an engagement | add (AI), warn when overdue (code) |
| Department / assignment | existing objects | department, executor and reviewer assignment | engagements and tasks belong to one | change assignment (me) |

Phase 2 (with the legislative data feed): model call, review, client (alias only), issue (bill or policy), automation (scheduled job or always-on helper).

Client names never appear in code or in this repository. Clients are alias keys; the alias-to-name map stays in a private local file.

## Where the board data goes

| Collected today | Object |
|---|---|
| Donaro task | Task (source: donaro), linked to an engagement by its workspace path |
| Claude Code session | Task (source: claude_code), linked by working directory; title is the session's sidebar title |
| Claude Code subagent | child Task |
| Codex session | Task (source: codex) |
| Scheduled job | Automation, one Task per run |
| Telegram bot, voice assistant | Automation (always-on) |
| Daily tokens, Jev calls | aggregates over model calls |
| Task waiting for input | Decision (pending) |
| Result files | Deliverable |
