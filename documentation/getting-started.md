# Getting Started

## Install

From the repository:

```bash
./install.sh
```

The installer discovers the active Taskwarrior data directory and installs
`jot` to `~/.local/bin/jot`. Run `jot paths` to inspect the paths it selected,
or `jot doctor` to check the installation.

## The Basic Workflow

Create a task as usual:

```bash
task add project:Home "Fix the leaking tap"
```

Open its Jot note using the Taskwarrior ID:

```bash
jot 42
```

Write a quick update:

```bash
jot note-append 42 "The washer is the likely cause"
```

Open the full note when you need more space:

```bash
jot note 42
```

Find it later:

```bash
jot search washer
jot recent
```

## Add Useful Structure

Jot creates headings only when a template or command needs them. Add a
heading-specific entry with fuzzy heading matching:

```bash
jot add-to task 42 --heading "next" --text "Buy a replacement washer"
```

The entry is timestamped automatically.

## Choose Your Interface

Use commands for fast, scriptable actions:

```bash
jot show 42
jot export 42 --json
```

Use the TUI when you want to browse tasks, projects, notes, and recent edits:

```bash
jot tui
```

All commands support `--json` where structured output is useful.
