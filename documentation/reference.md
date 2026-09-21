# Command Reference

Run `jot --help` for the live command list. Common commands:

```text
jot [ID]                         Open a task or chain note
jot note ID                      Edit a task note
jot chain ID                     Edit a chain note
jot project NAME                 Edit a project note
jot note-append ID TEXT          Append to a task note
jot chain-append ID TEXT         Append to a chain note
jot project-append NAME TEXT     Append to a project note
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

For complete options and examples:

```bash
jot COMMAND --help
```
