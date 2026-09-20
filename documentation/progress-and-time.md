# Progress and Time

## Progress

Progress is content-agnostic. A track can represent pages, repetitions,
milestones, or any other quantity:

```bash
jot progress task 42 set 120/350 --unit pages --status active
jot progress task 42 add 20
jot progress task 42 show
```

A task can have several independent tracks:

```bash
jot progress task 42 set 3/12 --track chest --unit sets
jot progress task 42 set 4/12 --track legs --unit sets
jot progress task 42 show
```

History and trend information is kept with the progress data.

## Jot Timelog

When Taskwarrior hooks cannot run, Jot can record a session explicitly:

```bash
jot timelog start 42
jot timelog stop 42
jot timelog pending
```

Time is written to the chain note when a chain exists, otherwise to the task
note. Reports can group intervals by day, project, chain, or task:

```bash
jot timelog report today
jot timelog report week --project Work.Client --details
jot timelog report month --csv > time.csv
```

Intervals can be corrected later:

```bash
jot timelog add 42 --from 2026-07-14T09:00 --to 2026-07-14T10:30
jot timelog amend a1b2c3d4 --to 2026-07-14T10:45
jot timelog delete a1b2c3d4 --yes
```

## Timewarrior

Jot can start a Timewarrior tag when a Jot-managed session starts. It is
enabled by default and only acts when a tag is configured:

```bash
jot timew set task 42 focused-reading
jot timelog start 42
```

Disable the integration in `config-jot.toml` if needed:

```toml
[timewarrior]
enabled = false
```

Jot does not stop Timewarrior when the task stops. The tag remains active until
another tagged task starts or Timewarrior is changed directly.
