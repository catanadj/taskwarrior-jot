# Command Reference

Run `jot --help` for the live command list. Common commands:

```text
jot [ID]                         Open a task or chain note
jot list :week                   List notes touched this calendar week
jot list :2026-04-01..2026-04-30 List notes touched in an inclusive date range
jot note ID                      Edit a task note
jot chain ID                     Edit a chain note
jot project NAME                 Edit a project note
jot note-append ID TEXT          Append to a task note
jot chain-append ID TEXT         Append to a chain note
jot project-append NAME TEXT     Append to a project note
jot history list task ID         List saved revisions for a note
jot history diff task ID REV     Compare a revision with the current note
jot history restore task ID REV  Preview and restore a revision
jot add-to KIND REF              Add a timestamped heading entry
jot headings KIND REF            List headings
jot attach KIND REF FILE         Add a file or link resource
jot resources KIND REF           List resources
jot progress KIND REF ...        Set, add, show, or inspect progress
jot timelog ...                  Record and report time expenditure
jot timew ...                    Configure Timewarrior tags
jot search TEXT                  Search active notes, trash, and events
jot recent                       Show recent edits
jot export REF --json            Export structured context
jot tui                          Start the terminal UI
jot completion bash              Print Bash completion code
jot paths                        Show effective paths
jot doctor                      Check and repair the installation
jot migrate                     Apply note migrations
```

Most read and inspection commands accept `--json`. Command names and common
subcommands support unambiguous partial matching, for example `jot prog t 42
sh`.

`jot list` accepts `:day`, `:week`, `:month`, `:year`, `:lastyear`, or an
inclusive local date range in `:YYYY-MM-DD..YYYY-MM-DD` form. It filters notes
by their last updated timestamp. A positional task reference still shows the
task summary, as in `jot list 42`.

Note templates and text entry support `{date}`, `{time}`, `{datetime}`,
`{timezone}`, `{task_short_uuid}`, `{task_uuid}`, `{description}`, `{project}`,
`{chain_id}`, `{project_path}`, `{link}`, `{created}`, and `{updated}`. Date and
time use the local timezone at the time text is entered; task identifiers use
the short UUID where intended for user-facing text. Unknown placeholders stay
literal and produce a warning. Prefix a placeholder with `\\` to keep it
literal, for example `\\{date}`. After editing a note, Jot shows the proposed
substitutions and asks before applying them. Set
`[templates].confirm_expansion_on_save = false` in `config-jot.toml` to apply
editor substitutions without the prompt.

Search keeps active notes, deleted notes, and events in separate sections. Note
matches rank description/project-name first, heading matches next, and body
matches last; newer notes come first within each class. Each hit includes the
matching excerpt and its match type, and filters preserve this order.

Jot keeps the latest 50 revisions per note in a hidden `.jot_history` folder
beside that note's storage directory. History is separate from active notes
and trash. Empty saves and timestamp-only touches do not create revisions.
Restoring always shows the revision diff first; use `--yes` only
when a restore is intentionally non-interactive. The current version is saved
as a revision before a restore is applied.

For complete options and examples:

```bash
jot COMMAND --help
```
