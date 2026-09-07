# Changelog

## 0.8.0 — 2026-09-07

- Added effective Taskwarrior environment resolution, including XDG settings,
  rc overrides, hooks locations, and Hooks v2 data-location arguments.
- Added versioned, bounded `jot context <task-ref> --json` output for agents.
- Added retry-safe `jot agent-append` mutations with operation and entry IDs.
- Added canonical full-UUID index writes with legacy compatibility and
  collision reporting.
- Added read-only `jot integrity` scans and explicit `jot reconcile` repairs
  with backups.
- Preserved the complete Nautical recurrence UDA set and delegation metadata.
- Improved `jot paths`, `jot doctor`, installer behavior, and documentation.
