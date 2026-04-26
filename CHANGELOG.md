# Changelog

## Unreleased

`jot` has grown from the initial note/core release into a more complete
Taskwarrior companion with a usable TUI, richer note scaffolding, and better
retrieval and diagnostics.

### Core Notes

- Task notes, chain notes, and project notes remain the durable source of truth
- Notes are stored as Markdown files with rebuildable sidecar state
- Project notes use hierarchy-aware paths for dotted Taskwarrior project names
- Soft delete moves notes into `~/.task/jot/.jot_trash/` instead of deleting
  them permanently

### Templates And Scaffolding

- Per-kind templates for task, chain, and project notes
- Template token expansion for identifiers, dates, times, and timestamps
- Built-in fallback scaffolds stay available when templates are missing or invalid
- Timestamped `add-to` entries under fuzzy-matched note headings

### CLI And Retrieval

- Task, chain, and project note open/show/cat/delete commands
- `add`, `add-to`, `note-append`, `chain-append`, and `project-append`
- `project-list`, `report recent`, `paths`, `stats`, and `rebuild-index`
- Search filters for kind, project, and Nautical chain ID
- Help output when `jot` is run without a command
- `--version` for release verification

### TUI

- `jot tui` terminal interface with browse, latest-edits, and search tabs
- Task workspace and project workspace views with note previews
- Hierarchical project browser built from actual Taskwarrior projects
- Focused refresh with `u`
- Global `ctrl+p` command palette for common actions
- In-TUI note editing, add-to, and delete flows

### Diagnostics And Packaging

- Hardened `doctor` checks for config, editor, storage, ops, index, and Taskwarrior
- `config-jot.toml` as the default config file name
- Lightweight `install.sh` and `uninstall.sh` scripts
- README documentation for the current workflow and TUI keybinds

### Companion To Nautical

- Chain-aware note handling for Nautical recurrence IDs
- Nautical context surfaced in task summaries and workspaces
- Project notes complement task and chain notes as a third durable context layer

## v0.1.0 - 2026-04-10

Initial public release of `jot`, a note-first companion to Taskwarrior and
Taskwarrior-Nautical.

### Highlights

- Durable task notes stored as Markdown files under `~/.task/jot/tasks/`
- Nautical-aware chain notes stored under `~/.task/jot/chains/`
- Project notes keyed by Taskwarrior project name and stored under
  `~/.task/jot/projects/`
- Append-first event capture projected into Taskwarrior annotations
- Read-only note access with `task-cat`, `chain-cat`, and `project-cat`
- Summary and export commands for tasks and projects
- Local sidecar state with rebuildable `index.json` and append-only `ops.jsonl`
- Lightweight install and uninstall scripts that do not require `pip`

### Admin And Diagnostics

- `doctor` for configuration and environment checks
- `paths` for resolved storage/config locations
- `rebuild-index` for forced index regeneration
- `stats` for local note, ops, and index status
- `--version` for release verification

### Notes

- Hooks are intentionally out of scope for `v0.1.0`
- Taskwarrior annotations are treated as the visible event stream, not as the
  durable source of truth
- Durable content lives in note files
