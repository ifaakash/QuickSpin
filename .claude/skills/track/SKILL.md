---
name: track
description: Read and update the QuickSpin backlog in Vikunja (self-hosted on the Pi 5). Use when asked what to work on, what today's tasks are, to log progress on an item, to close one, or to file a new story. This is the source of truth for the backlog — not TODO.md or current.md.
---

# QuickSpin backlog (Vikunja)

Source of truth for project work. Instance: `http://100.76.6.76:3456` (Pi 5,
tailnet-only — unreachable if Tailscale is down). Project `2` = QuickSpin.

Always go through `scripts/track.sh`. **Never call the API with a literal
token** — every command is recorded in the session transcript, so a token on a
command line is a token leaked permanently. The script reads it from
`~/.config/quickspin/vikunja.env` (mode 600).

## Commands

| Command | Use |
|---|---|
| `scripts/track.sh today` | what to work on now — open and due today or overdue |
| `scripts/track.sh backlog` | all open items, priority-ordered |
| `scripts/track.sh show <id>` | full description of ONE item |
| `scripts/track.sh add "<title>" --desc-file F [--prio 0-5] [--due YYYY-MM-DD]` | file a story |
| `scripts/track.sh due <id> today\|YYYY-MM-DD\|clear` | pull into / out of today |
| `scripts/track.sh prio <id> <0-5>` | reprioritise (5 = DO NOW) |
| `scripts/track.sh note <id> "<text>"` | log progress as a comment |
| `scripts/track.sh done <id>` | close |

## Context discipline — the reason this wrapper exists

`today` and `backlog` return `#id [P4] title due-date` only. **Never fetch full
task bodies to answer "what should I work on"** — that is what made the
markdown files expensive. Read `show <id>` only for the item actually being
picked up.

When writing a story body, write it to a file and pass `--desc-file`. Passing a
long description inline puts it in context twice (composing, then transcript).

## Two API traps, both already hit

1. **`POST /tasks/{id}` is a full-document REPLACE, not a patch.** Any field
   omitted is reset to its zero value. Sending `{"due_date":...}` alone wiped
   the description and priority off four tasks. The script's `patch()` helper
   does read-merge-write; use it for any new mutating subcommand.
2. **Descriptions are HTML, not markdown** — the editor is rich text. Markdown
   sent as-is renders as literal asterisks. Write `<p>`/`<b>`/`<code>` in
   `--desc-file` bodies. Reads go through `html2txt`.

Filter syntax is the expression form (`filter=done = false && due_date <
now/d+1d`) — Vikunja before 0.24 used `filter_by`/`filter_comparator` triples,
so older examples found online will not work on 2.6.0.
