# Compatibility

This page separates Jot's release targets from environments currently covered
by automated tests. The 1.0 release will not promise an environment until its
installation and core workflow pass the release checks.

## Release Targets

| Area | 1.0 target |
| --- | --- |
| Python | 3.11, 3.12, and 3.13 |
| Taskwarrior | 3.4.2 and newer 3.x releases |
| Operating systems | Linux and Termux |
| CLI | No optional Python dependencies |
| TUI | Textual `>=0.50.1`, with Rich `>=13.3.3` |
| Nautical | Current supported Nautical release and its Taskwarrior 3.4.2+ baseline |
| Timewarrior | Optional; tested when installed |

Jot uses POSIX shell installation scripts and Unix file-locking primitives.
Windows is not a 1.0 release target. macOS remains best effort until it has a
dedicated installation check.

## Current Evidence

- Python 3.11, 3.12, and 3.13 are present in the CI matrix.
- Taskwarrior 3.4.2 is available in the development environment and has passed
  a real export, path-resolution, and task-note write check.
- The minimum TUI test environment uses Textual 0.50.1 and Rich 13.3.3.
- The current TUI test environment uses Textual 6.1.0 and Rich 13.9.4.
- The CLI has been tested without Textual installed.

The newest supported Taskwarrior release and Termux installation still require
dedicated release tests.

## Stability Promise

Within Jot 1.x:

- Existing note data remains readable and migrations preserve backups.
- Existing configuration keys retain their meaning. New keys may be added.
- Versioned JSON envelopes retain their schema name and compatibility contract.
- Unsupported future note schemas are detected and left unchanged.
- CLI exit codes remain stable for successful commands and user errors.

Unversioned human-readable text remains presentation output and may improve
between releases. Scripts should use `--json` and the documented versioned
envelopes.
