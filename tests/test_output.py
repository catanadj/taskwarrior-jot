from __future__ import annotations

import csv
import io
import json
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

from jot_core.models import CommandResult
from jot_core.output import (
    configure_output,
    emit_result,
    error_envelope,
    serialize_payload,
    success_envelope,
    warn,
)


class OutputEmitterTests(unittest.TestCase):
    def setUp(self) -> None:
        configure_output(color_mode="never")

    def tearDown(self) -> None:
        configure_output(color_mode="auto")

    def emit(self, command: str, payload: dict[str, object]) -> str:
        output = io.StringIO()
        with redirect_stdout(output):
            emit_result(CommandResult(command=command, data=payload))
        return output.getvalue()

    def test_inventory_and_note_emitters_cover_empty_and_populated_paths(self) -> None:
        self.assertIn("(none)", self.emit("project-list", {"projects": []}))
        notes = self.emit(
            "notes",
            {
                "notes": [
                    {
                        "kind": "task",
                        "id": "abcd1234",
                        "title": "Read",
                        "project": "study",
                        "chain_id": "abcd1234",
                        "updated": "today",
                        "path": "/tmp/read.md",
                        "preview": "Current chapter",
                    }
                ]
            },
        )
        self.assertIn("task abcd1234  Read", notes)
        self.assertIn("Current chapter", notes)
        self.assertIn("(empty)", self.emit("trash-list", {"items": []}))
        trash = self.emit(
            "trash-list",
            {
                "items": [
                    {
                        "id": 1,
                        "kind": "task",
                        "task_short_uuid": "abcd1234",
                        "deleted_at": "today",
                        "path": "/tmp/read.md",
                        "trash_path": "/tmp/.jot_trash/read.md",
                    }
                ]
            },
        )
        self.assertIn("task abcd1234", trash)
        self.assertIn("trash", trash)

    def test_project_list_rendering_uses_note_output_module(self) -> None:
        with mock.patch("jot_core.output_notes.emit_project_list", return_value=None) as render:
            emit_result(CommandResult(command="project-list", data={"projects": []}))
        render.assert_called_once()

    def test_note_mutation_resource_and_search_emitters(self) -> None:
        self.assertIn(
            "Created task note: /tmp/task.md",
            self.emit("note", {"path": "/tmp/task.md", "opened": False}),
        )
        self.assertIn(
            "Appended to project note",
            self.emit("project-append", {"path": "/tmp/project.md", "opened": True}),
        )
        self.assertIn(
            "Moved task note to trash",
            self.emit(
                "task-delete",
                {"path": "/tmp/task.md", "trash_path": "/tmp/trash/task.md"},
            ),
        )
        resources = self.emit(
            "resources",
            {
                "note_kind": "task",
                "path": "/tmp/task.md",
                "resources": [
                    {"id": 1, "label": "docs", "target": "https://example.test", "kind": "url", "status": "exists"},
                    {"id": 2, "label": "", "target": "/missing", "kind": "file", "status": "missing"},
                ],
            },
        )
        self.assertIn("docs", resources)
        self.assertIn("missing", resources)
        search = self.emit(
            "search",
            {
                "query": "chapter",
                "kinds": ["task"],
                "notes": [{"kind": "task", "path": "/tmp/task.md", "match": "chapter 2"}],
                "events": [{"task_short_uuid": "abcd1234", "annotation": "chapter 2", "ts": "today"}],
            },
        )
        self.assertIn("Query", search)
        self.assertIn("chapter 2", search)

    def test_timelog_emitters_cover_status_variants_and_csv(self) -> None:
        self.assertIn(
            "Time log skipped",
            self.emit("timelog-ingest", {"written": False, "reason": "duplicate"}),
        )
        started = self.emit(
            "timelog-start",
            {
                "task_short_uuid": "abcd1234",
                "started": "2026-09-18 10:00",
                "timewarrior": {"enabled": True, "started": True, "tags": ["study"]},
            },
        )
        self.assertIn("Timewarrior started: study", started)
        stopped = self.emit(
            "timelog-stop-all",
            {
                "count": 1,
                "errors": [{"task_uuid": "full", "error": "unavailable"}],
                "items": [{"task_short_uuid": "abcd1234", "duration_minutes": 30, "written": True}],
            },
        )
        self.assertIn("Errors: 1", stopped)
        self.assertIn("written", stopped)
        report = self.emit(
            "timelog-report",
            {
                "period": "week",
                "total": "1h",
                "entry_count": 1,
                "by_day": [{"name": "today", "duration": "1h", "entry_count": 1}],
                "by_project": [],
                "by_chain": [],
                "by_task": [],
                "details": True,
                "entries": [{"day": "today", "duration": "1h", "display_range": "10:00-11:00", "project": "study"}],
            },
        )
        self.assertIn("By day", report)
        self.assertIn("Details", report)
        csv_output = self.emit(
            "timelog-report-csv",
            {"entries": [{"key": "k1", "task_uuid": "full", "minutes": 30}]},
        )
        self.assertEqual(next(csv.DictReader(io.StringIO(csv_output)))['key'], "k1")

    def test_timelog_rendering_uses_timelog_output_module(self) -> None:
        with mock.patch("jot_core.output_timelog.emit_timelog", return_value=None) as render:
            emit_result(CommandResult(command="timelog-start", data={}))
        render.assert_called_once()

    def test_progress_timewarrior_and_context_emitters(self) -> None:
        progress = self.emit(
            "progress",
            {
                "operation": "show",
                "task_short_uuid": "abcd1234",
                "tracks": [{"track": "pages", "current": "50", "target": "100", "percentage": "50", "unit": "pages"}],
            },
        )
        self.assertIn("pages", progress)
        self.assertIn("50", progress)
        timewarrior = self.emit(
            "timew",
            {"operation": "show", "task_short_uuid": "abcd1234", "enabled": True, "tags": ["study"], "source": {"scope": "task", "reference": "abcd1234", "path": "/tmp/task.md"}},
        )
        self.assertIn("Timewarrior tags", timewarrior)
        context = self.emit(
            "context",
            {"data": {"task": {"uuid": "full", "description": "Read", "project": "study"}, "notes": {"task": {"exists": True}}}, "warnings": ["stale index"]},
        )
        self.assertIn("Task note: available", context)
        self.assertIn("Warning: stale index", context)


class OutputSerializationTests(unittest.TestCase):
    def test_serialize_payload_handles_nested_supported_values(self) -> None:
        @dataclass
        class Payload:
            path: Path
            values: set[str]

        rendered = serialize_payload(Payload(Path("/tmp/jot"), {"a", "b"}))
        self.assertEqual(rendered["path"], "/tmp/jot")
        self.assertEqual(set(rendered["values"]), {"a", "b"})

    def test_envelopes_and_unknown_command_are_stable(self) -> None:
        self.assertEqual(success_envelope("test", {"ok": 1})["schema_version"], 1)
        self.assertEqual(error_envelope("test", "bad", "Nope")["ok"], False)
        output = io.StringIO()
        with redirect_stdout(output):
            emit_result(CommandResult(command="unknown", data={"message": "fallback"}))
        self.assertEqual(json.loads(output.getvalue())["message"], "fallback")

    def test_warn_writes_to_stderr(self) -> None:
        output = io.StringIO()
        import sys

        with mock.patch.object(sys, "stderr", output):
            warn("careful")
        self.assertIn("careful", output.getvalue())


if __name__ == "__main__":
    unittest.main()
