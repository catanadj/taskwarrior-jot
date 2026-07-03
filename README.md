# jot

`jot` keeps practical notes beside Taskwarrior tasks.

It is built to complement Taskwarrior-Nautical: task notes stay with one task,
chain notes stay with a recurring chain, and project notes hold wider context.

## Install

```bash
./install.sh
```

The installer copies `jot` to `~/.local/bin/jot` and stores data under your
Taskwarrior data directory:

- `TASKDATA`, if set
- `data.location` from `TASKRC` or `~/.taskrc`
- otherwise `~/.task`

For the optional time-expenditure hook:

```bash
./install.sh --with-timelog-hook
./install.sh --no-timelog-hook
```

If needed:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## First Run

```bash
jot
jot --help
jot tui
```

`jot` without arguments opens an interactive command browser when possible.
Commands accept minimum-unique prefixes, for example `jot proj-r finance`.

## Task Notes

```bash
jot 42
jot note 42
jot note-append 42 "Called vendor"
jot add-to task 42 --heading "Next steps" --text "Call again Monday"
jot task-cat 42
jot task-delete 42
```

`jot <task-ref>` opens the chain note when the task has a Nautical `chainID`;
otherwise it opens the task note.

## Chain Notes

```bash
jot chain 42
jot chain-append 42 "Skip holidays"
jot add-to chain 42 --heading "Operating notes" --text "Use fallback path"
jot chain-cat 42
```

Use these for recurring Nautical work where the useful context belongs to the
whole chain, not one occurrence.

## Project Notes

```bash
jot project Finances.Expense
jot project-append Finances.Expense "Waiting on policy update"
jot project-show Finances.Expense
jot project-report Finances.Expense
jot project-cat Finances.Expense
```

## Resources

```bash
jot attach task 42 ~/docs/invoice.pdf --label invoice
jot attach chain 42 https://example.com/runbook --label runbook
jot resources task 42
jot open-resource task 42 1
jot detach-resource task 42 1
```

Resources are stored in the note under `Resources` or `References`.

## Progress

Track any numeric progress. Jot does not impose a method.

```bash
jot progress task 42 set 120/350 --unit pages --status active
jot progress task 42 add 20
jot progress task 42 show

jot progress task 42 set 3/12 --track chest --unit sets
jot progress task 42 add 1 --track chest
jot progress chain 53,986e9d97,41 show
```

Progress state is stored in note frontmatter. Changes are logged under
`## Progress`.

## Time Expenditure

Jot can write task durations into notes under `## Time log`.

With the hook enabled:

```bash
task 42 start
task 42 stop
```

Without hooks, for example from Android Tasker/Termux:

```bash
jot timelog start 42
jot timelog stop 42
jot timelog pending
jot timelog stop --all
jot timelog cancel 42
```

If the task has `chainID`, time goes to the chain note. Otherwise it goes to the
task note.

## Search And Review

```bash
jot notes
jot notes --kind task
jot search vendor
jot recent --limit 10
jot list 42
jot show 42
jot export 42 --json
```

All commands support `--json`.

## TUI

```bash
jot tui
```

Main areas:

- `Browse`: tasks and projects
- `Notes`: all task, chain, and project notes
- `Latest Edits`: recent activity
- `Search`: note and event search

Useful keys:

- `q` quit
- `r` refresh
- `ctrl+p` command palette
- `m` context actions
- `Enter` open selection
- `e` edit note
- `a` add to task heading
- `c` add to chain heading
- `g` progress
- `f` attach resource
- `/` search

## Templates

Edit templates in:

```text
~/.task/jot/templates/
```

Files:

- `task-note.md`
- `chain-note.md`
- `project-note.md`

Common tokens:

- `{description}`
- `{project}`
- `{chain_id}`
- `{date}`
- `{time}`
- `{datetime}`

## Maintenance

```bash
jot paths
jot stats
jot doctor
jot rebuild-index
jot trash-list
jot trash-restore <id>
```

## Tests

```bash
python3 -m py_compile jot jot_core/*.py jot_tui/*.py tests/test_jot.py
python3 -m unittest discover -s tests -v
```

Tests use a fake `task` binary and temporary `HOME`.
