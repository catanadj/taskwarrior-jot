# Jot Usability Checklist

Work through these in order. Mark each item complete after the behavior and its tests pass.

## 1. Finish Post-Edit Delete Feedback

- [x] Show "Moved note to trash" after deleting a note from the post-edit menu, including the trash destination and a restore hint.
- [x] Render the result through the active note output path for task, chain, and project notes.
- [x] Correct the typed post-save action model so it accepts the structured delete and complete results.
- [x] Test the visible result for each note type and verify the note can be restored.

## 2. Show Trash Matches in TUI Search

- [x] Display trash matches in their own section, separate from active notes and events.
- [x] Show the note type, title or description, matching excerpt, and original location.
- [x] Let the user preview a trashed note and restore it from the selected result.
- [x] Keep the results and selection accurate after a restore or a new search.
- [x] Test search, selection, preview, and restore in the TUI.

## 3. Filter `jot list` by Touch Date

- [x] Support `:day` for today in the local timezone.
- [x] Support `:week` for the current calendar week.
- [x] Support `:month` for the current calendar month.
- [x] Support `:year` for the current calendar year.
- [x] Support `:lastyear` for the previous calendar year.
- [x] Define and support an explicit start-to-end date range.
- [x] Filter by each note's `updated` timestamp, with clear local date boundaries and inclusive end dates.
- [x] Show the resolved date range in human output; apply the same filter to JSON output.
- [x] Handle missing timestamps and invalid ranges predictably; test boundary dates and empty results.

## 4. Make TUI Search Easier to Scan

- [x] Put note title or description and matching excerpt in the results table; show full paths in a detail view.
- [x] Keep active notes, trash, and events legible on narrow terminals.
- [x] Show result counts and a clear empty state for each section.
- [x] Preserve the search query and current selection when moving between results and previews.
- [x] Update TUI documentation and test keyboard navigation at narrow and normal terminal widths.

## 5. Expand Text Consistently

- [x] Use one expansion engine for new text in CLI and TUI note creation, append, and add-to flows.
- [x] Resolve date and time from one local-time snapshot and task fields from the selected task, chain, or project; prefer the task's short UUID in user-facing text.
- [x] Preserve unknown placeholders and warn rather than silently replacing them with empty text; support escaping literal placeholders.
- [x] On editor save, show proposed substitutions and ask for confirmation before applying them. Declining must preserve the text as written.
- [x] Add a config toggle to skip the editor-save confirmation prompt while keeping substitution enabled.
- [x] Test replacement, escaping, unknown tokens, local time, each note type, editor confirmation, and the confirmation-disabled setting.

## 6. Add Per-Edit Note History

- [x] Save a snapshot before a successful change to a task, chain, or project note; skip unchanged saves.
- [x] Cover editor saves and Jot-managed writes without recording duplicate snapshots for one operation.
- [x] List revisions and show a diff against the current note before restoring one.
- [x] Make restore an explicit, atomic action that keeps the pre-restore version recoverable.
- [x] Bound retained history with a documented policy; keep snapshots separate from active notes and trash.
- [x] Test repeated edits, no-op saves, failed writes, restore, and retention across CLI and TUI paths.

## 7. Rank Search Results

- [x] Preserve current case-insensitive matching and kind, project, and chain filters.
- [x] Rank description or project-name matches first, heading matches next, then body-only matches; use recency and a stable tie-breaker within each group.
- [x] Keep active notes, trash, and events in separate result sections rather than mixing their ranks.
- [x] Apply the same ordering to CLI, JSON, and TUI results, with a visible match excerpt.
- [x] Test rank order, ties, filters, missing timestamps, and matches in each result section.

## Future Implementations (Deferred)

These are ideas to revisit after more time using Jot. Capture concrete workflow needs before choosing their form or scheduling implementation.

- [ ] Review view: determine from real use whether Jot should surface recent changes, work needing attention, or something else.
- [ ] Links between task, chain, and project notes: identify actual navigation needs before deciding on link syntax, backlinks, or automatic linking.
