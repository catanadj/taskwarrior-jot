# jot

`jot` is a note-first companion for Taskwarrior and Taskwarrior-Nautical.

Taskwarrior is good at telling you what needs doing. Jot is for the context
around the work: what happened, what you learned, what file mattered, how far
you got, and how long it took.

## Install

```bash
./install.sh
```

This installs `jot` to `~/.local/bin/jot` and stores notes under your
Taskwarrior data directory. The installer follows `TASKDATA`, then
`data.location` from `TASKRC` or `~/.taskrc`, then falls back to `~/.task`.
Python 3.11 or newer is required.

For time expenditure notes, let the installer enable the hook when asked, or
use:

```bash
./install.sh --with-timelog-hook
```

## A Normal Day With Jot

You start with a Taskwarrior task:

```bash
task add project:Finances.Expense "Fix billing discrepancy"
```

Taskwarrior now knows the task exists. Jot gives it a place to accumulate
working memory:

```bash
jot 42
```

If the task is a Nautical recurring task, `jot 42` opens the chain note. If it
is not part of a chain, it opens the task note. You do not need to decide every
time.

You make a quick note without opening the editor:

```bash
jot note-append 42 "Vendor says invoice was regenerated on Friday"
```

Then you add a concrete next step under the right heading:

```bash
jot add-to task 42 --heading "Next steps" --text "Call vendor Monday"
```

You attach the relevant file:

```bash
jot attach task 42 ~/invoices/vendor.pdf --label vendor-invoice
```

Later, you need the file again:

```bash
jot resources task 42
jot open-resource task 42 1
```

The task is no longer just a line in Taskwarrior. It has a small notebook beside
it.

## When The Work Repeats

Some notes belong to one occurrence. Other notes belong to the whole recurring
chain.

```bash
jot chain 42
jot chain-append 42 "Skip public holidays"
jot add-to chain 42 --heading "Operating notes" --text "Use the fallback path"
```

This is the main way Jot complements Taskwarrior-Nautical: one note can stay
with the concrete task, and another can stay with the recurrence itself.

## When The Context Is Bigger Than One Task

Projects also get notes:

```bash
jot project Finances.Expense
jot project-append Finances.Expense "Waiting on reimbursement policy update"
jot project-report Finances.Expense
```

Use project notes for standards, policies, risks, links, or anything you keep
rediscovering across related tasks.

## Tracking Progress

Jot can track any numeric progress without forcing a method.

Reading a book:

```bash
jot progress task 42 set 120/350 --unit pages --status active
jot progress task 42 add 20
jot progress task 42 show
```

Tracking several things on the same task:

```bash
jot progress task 42 set 3/12 --track chest --unit sets
jot progress task 42 set 4/12 --track legs --unit sets
jot progress task 42 add 1 --track chest
jot progress task 42 show
```

Progress state lives in the note. Changes are logged under `## Progress`.

## Tracking Time Spent

Jot can write time expenditure into notes under `## Time log`.

With the hook enabled:

```bash
task 42 start
task 42 stop
```

If hooks cannot run, for example from Android Tasker/Termux, let Jot manage the
session:

```bash
jot timelog start 42
jot timelog stop 42
```

If you forgot what is running:

```bash
jot timelog pending
```

If several sessions need to be closed:

```bash
jot timelog stop --all
```

Time goes to the chain note when `chainID` exists. Otherwise it goes to the
task note.

To see where time went:

```bash
jot timelog report today
jot timelog report week
jot timelog report week --project reading --details
jot timelog report --since 2026-07-01 --until 2026-07-07
jot timelog report month --csv > time.csv
```

Reports group time by day, project, chain, and task. `--details` shows the
individual intervals and their keys. Intervals crossing midnight or report
boundaries are counted only where they overlap.

Forgot to start the timer, or entered the wrong time?

```bash
jot timelog add 42 --from 2026-07-14T09:00 --to 2026-07-14T10:30
jot timelog amend a1b2c3d4 --to 2026-07-14T10:45
jot timelog delete a1b2c3d4 --yes
jot timelog trash
jot timelog restore '#1'
```

Amended and deleted entries are archived under `.jot_trash/timelog/`. Deleted
entries remain restorable by key or by the `#ID` shown in `timelog trash`.

## Finding Things Again

```bash
jot search vendor
jot notes
jot notes --kind task
jot recent --limit 10
jot show 42
jot export 42 --json
```

All commands support `--json`.

## The TUI

The CLI has no third-party Python dependencies. The TUI additionally requires
the `textual` package; the installer reports whether it is available.

```bash
jot tui
```

Use the TUI when you want to browse instead of remember commands.
The Time tab provides period totals, day/project/task rollups, and the
individual intervals behind them. Add or amend intervals directly, archive
mistakes, restore them from trash, or open an interval to jump to its task.

Main areas:

- `Browse`: tasks and projects
- `Notes`: all notes
- `Latest Edits`: recent activity
- `Search`: note and event search

Useful keys:

- `Enter`: open selection
- `e`: edit note
- `a`: add to task heading
- `c`: add to chain heading
- `g`: progress
- `f`: attach resource
- `m`: context actions
- `/`: search
- `q`: quit

## Command Cheatsheet

```bash
jot
jot --help
jot tui

jot note 42
jot chain 42
jot project Finances.Expense

jot note-append 42 "text"
jot chain-append 42 "text"
jot project-append Finances.Expense "text"

jot add-to task 42 --heading "Next steps" --text "Call Monday"
jot headings task 42
jot section task 42 "Next steps"

jot attach task 42 ~/file.pdf --label file
jot resources task 42
jot open-resource task 42 1

jot progress task 42 set 1/10 --unit pages
jot progress task 42 add 1
jot progress task 42 show

jot timelog start 42
jot timelog stop 42
jot timelog pending
jot timelog trash

jot paths
jot stats
jot doctor
jot migrate --dry-run
jot rebuild-index
```

Jot notes carry a small schema version so upgrades remain predictable. Inspect
an upgrade with `jot migrate --dry-run`, then run `jot migrate`; changed notes
are copied under `.jot_backups/` before their metadata is updated. `jot doctor
--repair` also removes stale fallback locks, applies safe migrations, and
rebuilds the derived index.

## Templates

Jot creates notes from templates in:

```text
~/.task/jot/templates/
```

Files:

- `task-note.md`
- `chain-note.md`
- `project-note.md`

Useful tokens:

- `{description}`
- `{project}`
- `{chain_id}`
- `{date}`
- `{time}`
- `{datetime}`

## Tests

```bash
python3 -m py_compile jot jot_core/*.py jot_tui/*.py tests/test_jot.py
python3 -m unittest discover -s tests -v
```

Tests use a fake `task` binary and temporary `HOME`.
