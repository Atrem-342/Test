# Personal Operator Core

Personal Operator is a deterministic personal schedule manager intended to sit
behind a future conversational Hermes/Telegram adapter. This repository contains
only the backend/core MVP: no bot, LLM, web UI, or cloud services.

```text
Telegram (future)
        ↓
Hermes Agent (future: language + intent only)
        ↓
structured tools / API boundary
        ↓
Personal Operator Core (validation, time, state, statistics)
        ↓
SQLite (the source of truth)
```

## Principles and time strategy

SQLite owns templates, date snapshots, events, actual timestamps, state, audit
history, and the persistent reminder queue. The LLM must never calculate or retain
these facts. Weekly template times and future-event times are local wall-clock
values. When a `DayPlan` snapshot is first materialized they become timezone-aware
instants stored as ISO-8601 UTC timestamps. All runtime `datetime` arguments must
be timezone-aware. The database timezone is configured at creation and cannot be
silently changed, preventing existing snapshots from being reinterpreted.

A day plan is created transactionally once per date. It copies that weekday's
template blocks and that date's future events; subsequent template/event edits do
not rewrite the snapshot. Direct edits affect only snapshot blocks.

## Layout

```text
src/personal_operator/
  models.py  # enums, proposal DTO, statistics, workflow extension point
  db.py      # explicit SQLite schema and connection lifecycle
  core.py    # application/tool service and deterministic business rules
  demo.py    # clearly labelled placeholder schedule and end-to-end demo
tests/test_core.py
```

## Setup, database, demo, tests

Python 3.11+ is required. Runtime code uses only the standard library.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[test]'
python -m personal_operator.demo --db personal_operator_demo.db --timezone Europe/Berlin
pytest
```

Constructing `PersonalOperator(path, timezone)` creates/migrates the SQLite schema.
The demo then seeds a **DEMO/PLACEHOLDER** seven-day schedule, adds a future event,
materializes and prints a plan, completes one block, and prints SQLite-derived
statistics. Run it with a fresh path for a clean walkthrough.

## Core/tool boundary

`PersonalOperator` exposes reads (`get_today`, `get_day_plan`,
`get_current_block`, `get_next_block`, statistics) and validated commands
(`start_block`, `finish_block`, `add_event`, `add_block`, `cancel_block`,
`reschedule_block`, `suspend_day`). `ScheduleChangeProposal` is an intentionally
small DTO: adapters may interpret language into a proposal, ask for confirmation,
then call `apply_confirmed`. Read operations need no confirmation. This boundary
can later be wrapped by Hermes tools, MCP, or a local API without moving domain
logic into that adapter.

The persistent `scheduled_events` queue supports due-event reads and idempotent
success/failure transitions. A future minute worker can deliver reminders without
cron-per-reminder or duplicate execution. `audit_events` records domain changes;
its JSON payload is reserved for sparse event-specific context.

## Deliberate placeholders

* The bundled weekly schedule is generic demo data, not a user's real schedule.
* `REDUCED` and `RECOVERY` modes can be stored but have no invented transformation
  rules yet.
* `EndWorkflow`, optional block notes/continuation fields, and template
  `end_prompt` prepare category-specific checkpoints. No questions or extraction
  rules are implemented; any interim prompt must be
  `[END_OF_BLOCK_PROMPT_PLACEHOLDER]`.
* Reminder generation/delivery, retry policy, concurrent worker leases, moving a
  block across dates, and rich project/NEXT management are later extensions.
* Hermes remains a schedule interface, **not a universal assistant**. It must not
  debug code, teach subjects, give substantive project advice, or provide
  motivational coaching. A report such as “my tail test fails” should eventually
  be stored as a blocker/problem, not answered as a programming question.

