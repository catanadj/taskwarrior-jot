# Notes and Resources

## Task Notes

Task notes hold information specific to one task occurrence:

```bash
jot note 42
jot note-append 42 "Waiting for the supplier"
```

## Chain Notes

For a Nautical recurring task, chain notes hold durable knowledge shared by
all occurrences:

```bash
jot chain 42
jot chain-append 42 "Use the fallback route on public holidays"
```

Running `jot 42` opens the chain note when the task belongs to a chain;
otherwise it opens the task note.

## Project Notes

Project notes are useful for policies, standards, decisions, and links shared
by many tasks:

```bash
jot project Work.Client
jot project-append Work.Client "Use the client's staging environment"
jot project-report Work.Client
```

Projects can be browsed as a tree in the TUI.

## Links and Files

Keep related resources in the note instead of searching for them again:

```bash
jot attach task 42 ~/documents/quote.pdf --label quote
jot resources task 42
jot open-resource task 42 1
```

Links are stored in the note and can be listed or opened from the CLI and TUI.

## Editing Safely

Jot uses file locks for writes and keeps deleted material in `.jot_trash`.
When synchronized notes produce a conflict file, Jot can show a structured
diff and offer an automatic or manual merge path.
