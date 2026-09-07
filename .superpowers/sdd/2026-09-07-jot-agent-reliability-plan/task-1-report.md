# Task 1 report

Implemented versioned JSON envelope helpers and normalized `--json` argument handling.

## Files changed

- `jot_core/output.py`: added `success_envelope` and `error_envelope` with schema version 1 and stable structured error fields.
- `jot_core/cli.py`: accepts `--json` before or after a subcommand (including `jot export 42 --json`), and documents the contract in CLI help.
- `jot_core/command_help.py`: documents normalized JSON placement and the versioned envelope for export help.
- `tests/test_jot.py`: added envelope, Unicode serialization, and parser regression tests.

## Tests

- Initial focused run failed as expected because the new helpers were absent (`ImportError`).
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_jot.JsonEnvelopeTests tests.test_jot.OutputColorTests -q` — 9 tests, OK.
- `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_jot -q` — 143 tests, OK.
- Focused help/prefix/envelope run — 12 tests, OK.
- `git diff --check` — OK.

## Concerns

Existing JSON command payloads remain unchanged; envelope helpers are provided for new machine-facing consumers. The global flag is normalized when present as an exact `--json` argument.

## Review fixes

- Normalization now stops at `--`, preserving `--json` supplied as literal command text.
- Help text now distinguishes legacy raw JSON command payloads from the versioned envelope used by new agent surfaces and names the envelope fields.
- Added a regression test for the argument delimiter behavior.

Review verification: focused suite — 13 tests, OK; full suite — 147 tests, 3 skipped, OK.
