# Typed Payload Boundaries Design

## Goal

Replace the highest-value internal `dict[str, Any]` contracts with explicit typed models while preserving compatibility with Taskwarrior JSON, note metadata, persisted indexes, and existing CLI JSON output.

## Principles

- Keep dictionaries at external and dynamic boundaries.
- Normalize stable Taskwarrior records into immutable domain models.
- Use command-specific result models for stable application responses.
- Serialize typed results only at the CLI/output boundary.
- Do not add a runtime validation dependency such as Pydantic.
- Preserve existing command names and JSON field names during migration.

## Target Shape

`jot_core/taskwarrior.py` will accept raw Taskwarrior mappings and produce a typed `Task` model. The model will expose stable fields such as UUID, description, status, project, chain ID, and tags, while retaining the original mapping as read-only `raw` data for UDAs and future fields.

`CommandResult` will become generic and carry typed `data` plus warnings. A serialization adapter will convert dataclasses, paths, tuples, and nested mappings into the existing JSON-compatible shape. Existing raw payload commands can temporarily use a compatibility mapping type while their domain-specific result models are introduced.

The first migration slice covers task summaries, task lists, project tree rows, and note summaries because these are consumed by both the CLI and TUI. Timelog, progress, maintenance, and storage-record payloads will be migrated in later slices using the same boundary pattern.

## Compatibility

- Existing `--json` field names remain unchanged.
- Taskwarrior’s arbitrary UDAs remain available through `Task.raw`.
- Note frontmatter and index persistence remain mapping-based.
- No new third-party runtime dependency is introduced.

## Verification

- Unit tests assert raw Taskwarrior records normalize to typed models.
- CLI JSON snapshots retain the existing shape.
- TUI/service callers consume typed models without changing user-visible behavior.
- Full unittest discovery remains green after every migration slice.
