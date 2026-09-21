# Operations and Recovery

## Inspect Before Changing Anything

Use these commands to see which Taskwarrior and Jot directories are active:

```bash
jot paths
jot doctor
jot integrity
```

`jot doctor` validates the installation and configuration. `jot integrity`
reports metadata or index drift without changing files. Use
`jot reconcile --dry-run` before applying a repair.

## Back Up Before an Upgrade

Jot stores its notes, index, operation log, configuration, and trash below the
active Taskwarrior data directory. Find that directory first:

```bash
jot paths
```

Then make a copy of the `jot` directory while Jot is not writing to it:

```bash
taskdata="${TASKDATA:-$HOME/.task}"
tar -C "$taskdata" -czf "$HOME/jot-backup-$(date +%Y%m%d-%H%M%S).tar.gz" jot
```

If `data.location` in `TASKRC` points elsewhere, use the path reported by
`jot paths` instead of `$TASKDATA`.

## Upgrade and Roll Back

The installer is designed to preserve notes and configuration. Install a
specific release when you need a controlled upgrade:

```bash
curl -fsSL https://raw.githubusercontent.com/catanadj/taskwarrior-jot/main/bootstrap.sh \
  | bash -s -- --version v0.9.0
```

After upgrading, run:

```bash
jot doctor
jot migrate --dry-run
```

Apply a migration only after reviewing its dry-run result:

```bash
jot migrate
```

Every changed note is backed up by the migration. The command reports the
backup directory. To restore that backup:

```bash
jot migrate --restore /path/to/migration-backup
```

To roll back the executable, reinstall the previous release with
`--version`. Restore the backed-up `jot` data directory only when the newer
release changed note metadata or data files. Do not downgrade without a
backup.

## Deleted Notes and Conflict Files

Deleted task, chain, and project notes are moved to `.jot_trash` rather than
removed immediately:

```bash
jot trash-list
jot trash-restore 1
jot cleanup --trash-older-than 365
jot cleanup --trash-older-than 365 --yes
```

When Syncthing creates a `*.sync-conflict-*` note, Jot reports the duplicate
instead of silently choosing one. Use the diff/merge workflow offered by the
CLI or TUI, review the result, and keep the conflict file until the merge is
verified.

## JSON and Note Stability

Use `--json` for scripts instead of parsing colored human-readable output:

```bash
jot --json paths
jot --json export 42
jot --json context 42
```

Agent-facing responses use a versioned envelope with `schema`,
`schema_version`, `ok`, and either `data`/`warnings` or `error`. Existing
command-specific JSON remains command-specific. Note front matter carries a
`schema_version`; supported migrations create backups, and future schema
versions are left unchanged rather than overwritten.

## Troubleshooting

**Jot uses the wrong Taskwarrior directory**

Run `jot paths`. Check `TASKDATA`, `TASKRC`, and `data.location` in the active
Taskwarrior configuration. Pass `--taskdata PATH` to the bootstrap installer
for the initial installation, then confirm the resolved path with `jot paths`.

**A note is reported as duplicated**

Look for Syncthing conflict files or two notes with the same identity. Do not
delete either file first. Use the structured diff/merge flow, then rerun
`jot integrity`.

**The TUI is unavailable**

Install the optional UI dependencies in the same Python environment as Jot:

```bash
python3 -m pip install 'jot-taskwarrior[tui]'
```

The CLI does not require Textual and remains available without it.

**A Taskwarrior hook does not run**

Run `jot doctor`, check `hooks.location` in Taskwarrior, and confirm that the
hook is executable. For mobile or other hookless workflows, record sessions
explicitly with `jot timelog start REF` and `jot timelog stop REF`.

**A repair is needed**

Preview first, then apply explicitly:

```bash
jot reconcile --dry-run
jot reconcile --apply
jot doctor --repair
```

Review the output and backup paths after every repair.
