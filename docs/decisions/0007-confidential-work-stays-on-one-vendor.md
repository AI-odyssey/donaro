# Confidential client work never leaves Claude

Status: accepted

## Context

Client material in the policy work is confidential. Sending it to every vendor in a fallback chain, to a speech service or to a public repository is not acceptable.

## Decision

A task is confidential if its department is the policy department or if the request, attachments or context contain policy signal words or a client term from private files. Confidential tasks run only on Claude and wait if Claude is unavailable. If the private term files cannot be read, every task is treated as confidential. The public export refuses to finish if any client term, key, account name or similar appears.

## Consequences

Some confidential tasks wait longer during Claude outages. In exchange, client data stays with one vendor and out of version control.
