# Terminal UI

Start the TUI with:

```bash
jot tui
```

The main areas are:

- **Browse**: task and project trees with task details
- **Notes**: find and edit notes
- **Latest Edits**: inspect recent changes without leaving the view
- **Search**: search active notes, deleted notes, and events
- **Time**: inspect and manage time intervals and reports

Search results are split into Notes, Trash, and Events tabs. The tables show a
short title and matching text; selecting a row shows its full location and
match details. Open a Trash result to preview the note and restore it.

Useful keys include:

| Key | Action |
| --- | --- |
| `Enter` | Open the selected item |
| `e` | Edit the selected note |
| `a` | Add an entry under a task heading |
| `c` | Add an entry under a chain heading |
| `g` | Open progress actions |
| `f` | Attach a resource |
| `m` | Open context actions |
| `/` | Search |
| `q` | Quit |

Choose **Note history** from the context actions to select a saved revision,
review its diff against the current note, and explicitly restore it. The
current version is kept as another revision.

The TUI is optional. The CLI remains fully usable without the `textual`
package.
