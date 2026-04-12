# jot

`jot` is a note-first companion to Taskwarrior and, especially, to
Taskwarrior-Nautical.

It keeps durable task notes and Nautical chain notes as Markdown files under
`~/.task/jot/`, while using Taskwarrior annotations as the visible event stream.
It also supports durable project notes for Taskwarrior project namespaces.

Current status: usable CLI core, no hooks yet.

## Install

From the repo root:

```bash
./install.sh
```

That installs:

- `~/.local/lib/jot/`
- `~/.local/bin/jot`

If `~/.local/bin` is not on your `PATH`, add:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Alternative:

```bash
python3 -m pip install .
```

## What It Does

- opens or creates a task note
- opens or creates a Nautical chain note
- appends plain text to either kind of note
- adds short task events as annotations
- lists the current event stream for a task
- exports task summary data
- searches notes and logged events
- maintains rebuildable sidecar state

## Current Commands

```bash
jot doctor
jot paths
jot rebuild-index
jot stats
jot tui
jot project-list
jot report recent [--limit N]
jot report recent --kind event --limit 10
jot note <task-ref>
jot chain <task-ref>
jot task-cat <task-ref>
jot chain-cat <task-ref>
jot project <project-name>
jot project-show <project-name>
jot project-cat <project-name>
jot note-append <task-ref> [text...]
jot chain-append <task-ref> [text...]
jot project-append <project-name> [text...]
jot add-to {task|chain|project} <ref> --heading <title> [--create-heading] [--heading-exact] [--text "..."]
jot add [--type TYPE] <task-ref> [text...]
jot list <task-ref>
jot show <task-ref>
jot export <task-ref>
jot search [--kind KIND] [--project NAME] [--chain ID] <query>
```

All commands support `--json`.

`jot tui` launches a terminal UI. It requires `textual`:

```bash
pip install textual
```

TUI keybinds:

- `q` quit
- `r` refresh data
- `/` focus search input
- `e` open editor for selected task note (select a task row in Recent first)
- `a` add a timestamped entry under a heading for selected task
- `c` add a timestamped entry under a heading for selected chain note (from selected task)
- `p` add a timestamped entry under a heading for selected project (project row or selected task project)

The CLI also supports:

```bash
jot --version
```

Supported task references:

- numeric task ID
- full UUID
- short UUID if unique

## Storage Model

User data lives in `~/.task/jot/`:

- `tasks/<task_short_uuid>--<slug>.md`
- `chains/<chain_id>--<slug>.md`
- `projects/<project path>/index.md`
- `templates/task-note.md`
- `templates/chain-note.md`
- `templates/project-note.md`
- `index.json`
- `ops.jsonl`
- `config-jot.toml`

Rules:

- note files are the source of truth
- annotations are the visible event stream
- `index.json` is rebuildable cache
- `ops.jsonl` is append-only audit state

## Templates

`jot` supports per-kind templates in `~/.task/jot/templates/`:

- `task-note.md`
- `chain-note.md`
- `project-note.md`

If a template file is missing, empty, or cannot be parsed, `jot` falls back to the built-in starter body for that note kind.

Supported tokens in templates:

- `{{task_short_uuid}}`
- `{{task_uuid}}`
- `{{description}}`
- `{{project}}`
- `{{chain_id}}`
- `{{link}}`
- `{{created}}`
- `{{updated}}`
- `{{project_path}}`

`add-to` behavior:

- resolves headings with fuzzy matching by default
- supports strict matching with `--heading-exact`
- creates missing headings with `--create-heading`
- writes entries as timestamped bullets, for example:
  `- [2026-04-12T13:30:00Z] call vendor`

## Nautical Companion

`jot` is designed to complement Nautical’s recurrence model.

When a task has Nautical fields such as `chainID`, `anchor`, `cp`, or `link`,
`jot` can:

- keep an occurrence note for the concrete task
- keep a chain note for the whole recurrence line
- surface the matching project note when the task belongs to a project
- include Nautical context in `show`, `list`, and `export`

Chain notes are keyed by `chainID`.

## Examples

```bash
jot note 42
jot chain 42
jot task-cat 42
jot chain-cat 42
jot project Finances.Expense
jot project-show Finances.Expense
jot project-cat Finances.Expense
jot paths
jot rebuild-index
jot stats
jot project-list
jot report recent --limit 10
jot search --kind project-note vendor
jot search --project finance.audit vendor
jot search --chain a4bf5egh vendor
jot add-to task 42 --heading "Next steps" --text "Call vendor Monday"
jot note-append 42 Followed up with vendor
jot project-append Finances.Expense waiting on reimbursement rules
jot add --type status 42 waiting on vendor
jot list 42
jot --json export 42
jot search vendor
```

## Tests

```bash
python3 -m py_compile jot jot_core/*.py tests/test_jot.py
python3 -m unittest discover -s tests -v
```

The tests use a fake `task` binary and temporary `HOME`, so they do not touch
live Taskwarrior data.

## Current Limits

- no hooks yet
- no advanced filter-expression task resolution yet
- no event editing/removal workflow
