# jot

`jot` is a note-first companion for Taskwarrior and Taskwarrior-Nautical.
It helps you keep the context around a task in one place: what happened, what
changed, what still matters, and what belongs to the wider project or recurring
chain.

Use `jot` when Taskwarrior alone is not enough and you want:

- task notes that stay with the task
- chain notes for recurring Nautical work
- project notes for shared project context
- quick timestamped updates without opening the full editor every time
- a TUI that makes browsing and updating notes faster than typing commands

## Install

From the repo root:

```bash
./install.sh
```

That installs `jot` into:

- `~/.local/bin/jot`
- `~/.local/lib/jot/`

If `~/.local/bin` is not on your `PATH`, add:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

The installer places `jot` data under your Taskwarrior data directory:

- `TASKDATA` when set
- otherwise `data.location` from `TASKRC` or `~/.taskrc`
- otherwise `~/.task`

Set `JOT_HOME` if you want to override only the `jot` data directory.

## Start Here

If you just want to see what `jot` can do:

```bash
jot
```

In an interactive terminal, this opens a searchable command browser. Moving
through the list shows what each command does, its syntax, a concrete example,
and its arguments without executing it. When output is redirected or Textual
is unavailable, `jot` prints the standard help instead.

Commands accept minimum-unique prefixes. For example,
`jot proj-r Finances.Expense` runs `jot project-report Finances.Expense`;
`jot prog ch 53 sh` runs `jot progress chain 53 show`. This also applies to
choice arguments such as `task`, `chain`, and `project`. Ambiguous prefixes are
rejected with the matching choices listed.

If you want the full help:

```bash
jot --help
```

If you want the visual interface:

```bash
jot tui
```

## What `jot` Is Good At

### For a single task

Keep the task’s context in one place:

```bash
jot 42
jot note 42
jot note-append 42 Followed up with the vendor
jot add-to task 42 --heading "Next steps" --text "Call vendor Monday"
jot attach task 42 ~/invoices/vendor.pdf --label vendor-invoice
jot resources task 42
jot headings task 42
jot section task 42 "Next steps"
jot task-cat 42
```

When a note is changed in your editor, Jot prints a unified diff of the saved
changes to `stderr`. This keeps `--json` output parseable while still showing
what changed after the editor closes.

### For recurring Nautical work

Keep a note for the whole recurrence chain:

```bash
jot chain 42
jot chain-append 42 Skip holidays
jot add-to chain 42 --heading "Operating notes" --text "Use the fallback path"
jot attach chain 42 https://example.com/runbook --label runbook
jot headings chain 42
jot chain-cat 42
```

### For project-wide context

Keep shared notes for a project namespace:

```bash
jot project Finances.Expense
jot project-append Finances.Expense Waiting on reimbursement policy update
jot add-to project Finances.Expense --heading "Risks" --text "Vendor delay"
jot attach project Finances.Expense ~/docs/reimbursement-policy.pdf
jot section project Finances.Expense Risks
jot project-report Finances.Expense
jot project-show Finances.Expense
```

### For quick updates

Capture short events and keep them visible in Taskwarrior:

```bash
jot add --type status 42 waiting on vendor
jot list 42
jot show 42
jot search vendor
```

### For measurable progress

Track any numeric current/target measurement without imposing a methodology:

```bash
jot progress task 42 set 120/350 --unit pages --status active
jot progress task 42 add 20
jot progress task 42 subtract 5
jot progress task 42 status paused
jot progress task 42 show

jot progress chain 42 set 3/12 --unit sessions
jot progress project Renovation set 2.5/8 --unit rooms
```

One note can hold multiple named tracks:

```bash
jot progress task 42 set 3/12 --track chest --unit sets
jot progress task 42 set 4/12 --track legs --unit sets
jot progress task 42 add 1 --track chest
jot progress task 42 show
jot progress chain 53,986e9d97,41 show
```

Track names, units, and statuses are free-form. Omitting `--track` uses the
backward-compatible `default` track when it exists. Adjustment commands infer
the track when a note has only one named track; multiple named tracks require
`--track`. Current state is stored in note frontmatter,
while every change is appended under `## Progress`. Percentages are calculated
for display. `progress show` renders each track as a terminal-aware visual
progress bar with a consistent red-to-green completion scale, trend summary,
and recent history tail. Use `--history 0` to hide recent entries or
`--history 10` to show a longer tail. It accepts
comma-separated references to compare several task, chain, or project notes at
once. Progress updates use file locking and atomic replacement so concurrent
commands cannot overwrite each other. Jot never changes Taskwarrior task status
automatically.

## TUI

`jot tui` is the fastest way to browse and update notes.
Task, project, and latest-edit workspaces include a `Progress` tab with the
current measurement, calculated percentage, status, and a compact progress bar.
Task and project browser rows also show compact progress summaries, so tracked
work is visible without opening its workspace.
The progress dialog lists tracks already stored for each available note scope,
infers a sole track, and provides an explicit `New track...` option for `set`.

Main shortcuts:

- `q` quit
- `r` refresh data
- `u` refresh the current workspace
- `ctrl+p` open the command palette
- `/` focus search
- `Enter` open the selected row
- `e` open the active note in the editor
- `d` move the active note to trash
- `f` attach a file or URL resource to the active note
- `o` open a resource from the active note
- `x` detach a resource from the active note
- `g` set or adjust progress for the current task, chain, or project
- `a` add a timestamped entry under a task heading
- `c` add a timestamped entry under a chain heading
- `p` open the project workspace

The TUI has three main areas:

- `Browse` for tasks and projects
- `Latest Edits` for recent activity
- `Search` for finding notes and logged events

## Common Commands

Task notes:

```bash
jot note <task-ref>
jot note-append <task-ref> [text...]
jot task-cat <task-ref>
jot task-delete <task-ref>
jot trash-list
jot trash-restore <id>
```

Chain notes:

```bash
jot chain <task-ref>
jot chain-append <task-ref> [text...]
jot chain-cat <task-ref>
jot chain-delete <task-ref>
```

Project notes:

```bash
jot project <project-name>
jot project-append <project-name> [text...]
jot project-show <project-name>
jot project-report <project-name>
jot project-cat <project-name>
jot project-delete <project-name>
```

Browsing and reporting:

```bash
jot project-list
jot report recent --limit 10
jot stats
jot paths
jot rebuild-index
jot search --kind project-note vendor
```

Reference and event capture:

```bash
jot add [--type TYPE] <task-ref> [text...]
jot add-to {task|chain|project} <ref> --heading <title> [--text "..."]
jot attach {task|chain|project} <ref> <path-or-url> [--label LABEL]
jot resources {task|chain|project} <ref>
jot open-resource {task|chain|project} <ref> <id>
jot detach-resource {task|chain|project} <ref> <id>
jot headings {task|chain|project} <ref>
jot section {task|chain|project} <ref> <heading>
jot list <task-ref>
jot show <task-ref>
jot export <task-ref>
```

Progress tracking:

```bash
jot progress {task|chain|project} <ref> set <current>/<target> [--track NAME] [--unit UNIT] [--status STATUS]
jot progress {task|chain|project} <ref> add <amount> [--track NAME]
jot progress {task|chain|project} <ref> subtract <amount> [--track NAME]
jot progress {task|chain|project} <ref>[,<ref>...] show [--track NAME] [--history N]
jot progress {task|chain|project} <ref> status <value> [--track NAME]
jot progress {task|chain|project} <ref> clear [--track NAME] --yes
```

All commands support `--json`.

Resource commands use an existing `Resources` or `References` heading in the
note. If neither exists, `jot attach` creates `Resources`.

`jot <task-ref>` is a shortcut: it opens the task note when the task is not
part of a Nautical chain, and the chain note when `chainID` is present.

## Templates

`jot` creates note files from templates when they exist. If you want to change
the default note layout, edit the files in `~/.task/jot/templates/`:

- `task-note.md`
- `chain-note.md`
- `project-note.md`

Templates can use tokens such as:

- `{description}`
- `{project}`
- `{chain_id}`
- `{date}`
- `{time}`
- `{datetime}`

If a template is missing or invalid, `jot` falls back to the built-in note
layout.

## Nautical Companion

`jot` is designed to complement Taskwarrior-Nautical.

When a task belongs to a Nautical chain, `jot` can keep:

- a note for the concrete task occurrence
- a note for the chain itself
- a note for the broader project the task belongs to

That gives you three layers of context without forcing everything into one note.

## Help and Version

```bash
jot --help
jot --version
```

## Tests

```bash
python3 -m py_compile jot jot_core/*.py jot_tui/*.py tests/test_jot.py
python3 -m unittest discover -s tests -v
```

The tests use a fake `task` binary and a temporary `HOME`, so they do not touch
your real Taskwarrior data.

## Notes

- `jot` does not install hooks yet
- Taskwarrior annotations are treated as the visible event stream
- Durable content lives in note files under `~/.task/jot/`
