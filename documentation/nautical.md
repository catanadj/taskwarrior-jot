# Taskwarrior-Nautical Integration

Jot and Nautical solve different parts of the workflow:

- Nautical manages recurring task generation and chain behavior.
- Jot stores durable context for tasks, chains, and projects.

Use a task note for one occurrence. Use a chain note for knowledge that should
survive into future occurrences:

```bash
jot note 42
jot chain 42
jot chain-append 42 "The exercise can be shortened when time is limited"
```

When `jot 42` is used, Jot opens the chain note if the task has a chain and
the task note otherwise.

For recurring-task completion, keep Nautical hooks enabled when completing
through Jot so Nautical can create the next occurrence.
