# Typed Payload Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce explicit typed contracts for Jot's stable task, note, project, and command-result boundaries without breaking existing CLI JSON or dynamic metadata.

**Architecture:** Keep raw dictionaries in Taskwarrior, frontmatter, index, and persistence adapters. Normalize stable records into frozen dataclasses, pass typed result objects through services and renderers, and convert them to the existing JSON-compatible shape only at the output boundary.

**Tech Stack:** Python 3.11+, `dataclasses`, `typing.TypedDict`, `typing.TypeAlias`, `unittest`; no new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-09-16-typed-payload-boundaries-design.md`

## Global Constraints

- Preserve existing CLI command names and `--json` field names.
- Preserve arbitrary Taskwarrior UDAs through a read-only raw mapping.
- Keep note frontmatter and index persistence mapping-based.
- Do not add a third-party runtime dependency.
- Run focused tests after each task and the complete unittest suite before each commit.

---

### Task 1: Define Shared JSON and Task Contracts

**Files:**
- Modify: `jot_core/models.py`
- Modify: `jot_core/taskwarrior.py`
- Test: `tests/test_jot.py`

**Interfaces:**
- Produces `JsonValue`, `RawTask`, and frozen `Task` models.
- Produces `Task.from_raw(raw: Mapping[str, JsonValue]) -> Task` or an equivalent module-level normalizer.
- Existing `ResolvedTask.task` remains available during this first slice for compatibility.

- [ ] **Step 1: Write failing tests**

Add tests asserting that a raw Taskwarrior record normalizes stable fields, converts missing optional fields to safe defaults, and preserves arbitrary UDA values in `raw`.

```python
def test_task_normalization_preserves_stable_fields_and_udas():
    task = normalize_task({
        "uuid": "full-uuid",
        "description": "Read",
        "status": "pending",
        "project": "study.books",
        "chainID": "chain-id",
        "tags": ["book"],
        "timew_tag": "reading",
    })
    assert task.uuid == "full-uuid"
    assert task.project == "study.books"
    assert task.tags == ("book",)
    assert task.raw["timew_tag"] == "reading"
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run: `python3 -m unittest tests.test_jot -k normalization -v`

Expected: FAIL because the typed normalizer and model do not exist.

- [ ] **Step 3: Implement the minimal contracts**

Define a recursive JSON type alias, a `RawTask` `TypedDict(total=False)`, and a frozen `Task` dataclass. Normalize UUID, description, status, project, chain ID, and tags without rejecting unknown keys. Copy the incoming mapping into `raw: Mapping[str, JsonValue]` so later mutations of the Taskwarrior response cannot change the domain object; keep serialization of this dynamic mapping at the output boundary.

- [ ] **Step 4: Run focused and existing Taskwarrior tests**

Run: `python3 -m unittest tests.test_jot -k 'normalization or task' -v`

Expected: PASS with no regressions.

- [ ] **Step 5: Commit**

```bash
git add jot_core/models.py jot_core/taskwarrior.py tests/test_jot.py
git commit -m "Add typed Taskwarrior task contract"
```

### Task 2: Add Typed Read Models for Tasks, Notes, and Projects

**Files:**
- Modify: `jot_core/models.py`
- Modify: `jot_core/report.py`
- Modify: `jot_core/services.py`
- Test: `tests/test_jot.py`

**Interfaces:**
- Produces `TaskSummary`, `NoteSummary`, and `ProjectTreeRow` frozen dataclasses.
- Service methods may return tuples of these models for read paths.
- Dynamic note metadata remains a mapping field where required.

- [ ] **Step 1: Write failing tests**

Test that task summaries, note listings, and project tree rows expose named attributes while retaining the same values currently emitted in CLI/TUI payloads.

```python
def test_project_tree_row_has_named_fields():
    row = service.project_tree_rows()[0]
    assert row.project == "study"
    assert row.depth == 0
    assert row.selectable is True
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python3 -m unittest tests.test_jot -k 'project_tree or task_summary or note_listing' -v`

Expected: FAIL because these methods currently return untyped dictionaries.

- [ ] **Step 3: Implement the read models and adapters**

Convert only stable fields. Keep display-only labels and compatibility aliases explicit rather than relying on arbitrary dictionary mutation. Update service return annotations and adapt existing callers as needed.

- [ ] **Step 4: Run focused CLI and TUI tests**

Run: `python3 -m unittest tests.test_jot -k 'project or task or note' -v`

Expected: PASS with unchanged user-visible behavior.

- [ ] **Step 5: Commit**

```bash
git add jot_core/models.py jot_core/report.py jot_core/services.py tests/test_jot.py
git commit -m "Type task and note read models"
```

### Task 3: Introduce Generic Command Results and Serialization

**Files:**
- Modify: `jot_core/models.py`
- Modify: `jot_core/output.py`
- Modify: `jot_core/cli.py`
- Test: `tests/test_jot.py`

**Interfaces:**
- `CommandResult[T]` exposes `command: str`, `data: T`, and `warnings: tuple[str, ...]`.
- A single output adapter converts typed data to JSON-compatible values.
- A compatibility constructor supports existing raw payloads while migration continues.

- [ ] **Step 1: Write failing tests**

Assert that a typed result serializes to the current JSON shape and that paths, tuples, nested dataclasses, and mappings are handled consistently.

```python
def test_command_result_serializes_typed_data_without_shape_change():
    result = CommandResult("show", TaskSummary(...))
    assert serialize_result(result)["uuid"] == "full-uuid"
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `python3 -m unittest tests.test_jot -k 'command_result or json_output' -v`

Expected: FAIL because `CommandResult` has no typed data contract or serializer.

- [ ] **Step 3: Implement generic results and one serialization boundary**

Keep machine-readable envelope helpers unchanged initially. Update `emit_result` to receive normalized data through the serializer while preserving existing renderer dispatch.

- [ ] **Step 4: Run JSON compatibility tests**

Run: `python3 -m unittest tests.test_jot -k 'json or output or show or list' -v`

Expected: PASS with unchanged keys and values.

- [ ] **Step 5: Commit**

```bash
git add jot_core/models.py jot_core/output.py jot_core/cli.py tests/test_jot.py
git commit -m "Add typed command result boundary"
```

### Task 4: Move CLI and TUI Read Paths to Typed Results

**Files:**
- Modify: `jot_core/cli.py`
- Modify: `jot_core/output.py`
- Modify: `jot_tui/app.py`
- Modify: `jot_tui/launcher.py`
- Test: `tests/test_jot.py`
- Test: `tests/test_tui.py`

**Interfaces:**
- CLI renderers consume typed task/note/project models for migrated commands.
- TUI browse and latest-edit screens consume the same read models.
- No renderer accesses migrated fields through `.get()`.

- [ ] **Step 1: Write failing attribute-access tests**

Cover task browse, project tree, latest edits, and task detail rendering with typed objects.

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `python3 -m unittest discover -s tests -p '*tui*' -v`

Expected: FAIL at the first migrated dictionary-only access.

- [ ] **Step 3: Update consumers**

Replace dictionary field access with model attributes and isolate any compatibility conversion at the CLI boundary.

- [ ] **Step 4: Run the complete suite**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m unittest discover -s tests -q`

Expected: PASS with the existing skip count unchanged.

- [ ] **Step 5: Commit**

```bash
git add jot_core/cli.py jot_core/output.py jot_tui tests
git commit -m "Use typed models in CLI and TUI read paths"
```

### Task 5: Document Remaining Dynamic Payloads

**Files:**
- Modify: `docs/superpowers/specs/2026-09-16-typed-payload-boundaries-design.md`
- Modify: `docs/superpowers/plans/2026-09-16-typed-payload-boundaries-plan.md`

**Interfaces:**
- No production behavior changes in this task.
- Produces a categorized list of remaining dynamic versus stable payloads and identifies the next independently implementable migration slice.

- [ ] **Step 1: Review the remaining payload families**

Review `jot_core/timelog.py`, `jot_core/progress.py`, `jot_core/trash.py`, `jot_core/integrity.py`, and `jot_core/migrations.py`. Classify each return shape as stable application data or dynamic/persisted data.

- [ ] **Step 2: Record the next migration slice**

Add the chosen payload family, its stable fields, current callers, and its focused unittest command to the design document. The selection must be based on call-site traffic and contract stability, not file size.

- [ ] **Step 3: Document dynamic exceptions**

Mark frontmatter, indexes, arbitrary UDAs, and compatibility envelopes as intentionally mapping-based. Do not introduce placeholder dataclasses for unstable schemas.

- [ ] **Step 4: Run the complete suite and static checks**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python3 -m unittest discover -s tests -q`

Expected: PASS with no behavior changes.

- [ ] **Step 5: Commit the audit and next-slice decision**

```bash
git add jot_core docs/superpowers
git commit -m "Document remaining payload typing boundaries"
```
