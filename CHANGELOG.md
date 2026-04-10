# Changelog

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
