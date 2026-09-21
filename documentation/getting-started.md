# Getting Started

## Install

For a direct install of the latest tagged release:

```bash
curl -fsSL https://raw.githubusercontent.com/catanadj/taskwarrior-jot/main/bootstrap.sh | bash
```

For an audited install, download `bootstrap.sh`, inspect it, and run it locally.
Use `--dry-run` to validate the release without installing it.
For a checksummed release asset, pass its digest explicitly or provide a
checksum manifest URL:

```bash
./bootstrap.sh --version v1.0.0 --sha256 SHA256_DIGEST
./bootstrap.sh --version v1.0.0 --checksum-url CHECKSUM_FILE_URL
```

From a local repository checkout:

```bash
./install.sh
```

The bootstrap and local installer both preserve existing notes, configuration,
templates, and non-Jot hooks. Use `--taskdata` or `TASKDATA` when the
Taskwarrior data directory is not `~/.task`.

The installer discovers the active Taskwarrior data directory and installs
`jot` to `~/.local/bin/jot`. Run `jot paths` to inspect the paths it selected,
or `jot doctor` to check the installation.

## The Basic Workflow

Create a task as usual:

```bash
task add project:Home "Fix the leaking tap"
```

Open its Jot note using the Taskwarrior ID:

```bash
jot 42
```

Write a quick update:

```bash
jot note-append 42 "The washer is the likely cause"
```

Open the full note when you need more space:

```bash
jot note 42
```

Find it later:

```bash
jot search washer
jot recent
```

Search results keep deleted matches in a separate `Trash` section. The JSON
form exposes them under `trash`, including the original note path.

## Add Useful Structure

Jot creates headings only when a template or command needs them. Add a
heading-specific entry with fuzzy heading matching:

```bash
jot add-to task 42 --heading "next" --text "Buy a replacement washer"
```

The entry is timestamped automatically.

## Choose Your Interface

Use commands for fast, scriptable actions:

```bash
jot show 42
jot export 42 --json
```

Enable shell completion when you use Jot frequently:

```bash
eval "$(jot completion bash)"
```

Use `jot completion zsh` or `jot completion fish` for the other supported
shells. For a persistent setup, save the generated output in your shell's
completion directory.

Use the TUI when you want to browse tasks, projects, notes, and recent edits:

```bash
jot tui
```

All commands support `--json` where structured output is useful.
