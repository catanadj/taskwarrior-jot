# Configuration

## Paths

Jot follows Taskwarrior's active configuration, including `TASKDATA`,
`TASKRC`, XDG defaults, and `data.location` in `.taskrc`.

Inspect the effective paths with:

```bash
jot paths
jot doctor
```

## Config File

The user configuration is:

```text
~/.task/jot/config-jot.toml
```

The exact root follows the active Taskwarrior data directory. The repository
contains a starter `config-jot.toml` that the installer can copy.

## Templates

Templates live under:

```text
~/.task/jot/templates/
```

Available files are `task-note.md`, `chain-note.md`, and `project-note.md`.
Useful expansions include `{description}`, `{project}`, `{chain_id}`, `{date}`,
`{time}`, and `{datetime}`.

## Output

Jot colors CLI output automatically when writing to a terminal. Override this
with:

```toml
[display]
color = "always"
```

Use `color = "never"` for plain output. `NO_COLOR` always disables styling.

## Timelog Hook

The remote bootstrap leaves the hook disabled unless explicitly requested:

```bash
curl -fsSL https://raw.githubusercontent.com/catanadj/taskwarrior-jot/main/bootstrap.sh \
  | bash -s -- --with-timelog-hook
```

The installer can optionally install the Taskwarrior timelog hook:

```bash
./install.sh --with-timelog-hook
```

Use `--replace-timelog-hook` only when intentionally replacing an existing
hook. Uninstalling Jot preserves notes and hooks unless
`--remove-timelog-hook` is supplied.
