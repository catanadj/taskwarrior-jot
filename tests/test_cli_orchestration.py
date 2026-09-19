from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jot_core import cli
from jot_core.models import (
    CommandResult,
    HeadingCommandResult,
    NoteAppendCommandResult,
    NoteDeleteStorageResult,
    ResourceOperationResult,
    ResourceRecord,
    ResolvedTask,
    TaskRef,
)


class FakeEnvironment:
    executable = "/usr/bin/task"
    rc_path = Path("/tmp/.taskrc")
    rc_source = "default"
    data_path = Path("/tmp/.task")
    hooks_path = Path("/tmp/.task/hooks")
    warnings: list[str] = []


class CliOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="jot-cli-test-"))
        config = SimpleNamespace(
            config_path=self.root / "config-jot.toml",
            root_dir=self.root,
            trash_dir=self.root / ".jot_trash",
            tasks_dir=self.root / "tasks",
            chains_dir=self.root / "chains",
            projects_dir=self.root / "projects",
            templates_dir=self.root / "templates",
            color_mode="never",
            default_format="text",
            nautical_enabled=False,
        )
        self.ctx = SimpleNamespace(
            config=config,
            taskwarrior=SimpleNamespace(environment=lambda: FakeEnvironment()),
        )
        self.task = ResolvedTask(
            ref=TaskRef(raw="42"),
            task_uuid="2d6d7d7d-1111-2222-3333-444444444444",
            task_short_uuid="2d6d7d7d",
            description="Read book",
            project="study",
            tags=["focus"],
            task={"uuid": "2d6d7d7d-1111-2222-3333-444444444444", "chainID": "chain-1"},
        )
        self.ctx.taskwarrior.resolve_task = lambda _ref: self.task

    def tearDown(self) -> None:
        for path in sorted(self.root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        self.root.rmdir()

    def test_scoped_targets_accept_aliases_and_reject_missing_values(self) -> None:
        self.assertEqual(cli._parse_scoped_target(["t", "42"], default_scope="auto"), ("task", "42"))
        self.assertEqual(cli._parse_scoped_target(["ch", "abc"], default_scope="task"), ("chain", "abc"))
        self.assertEqual(cli._parse_scoped_target(["proj", "work", "deep"], default_scope="task"), ("project", "work deep"))
        self.assertEqual(cli._parse_scoped_target(["42"], default_scope="task"), ("task", "42"))
        with self.assertRaisesRegex(RuntimeError, "target is required"):
            cli._parse_scoped_target([], default_scope="task")
        with self.assertRaisesRegex(RuntimeError, "project target is required"):
            cli._parse_scoped_target(["p"], default_scope="task")

    def test_alias_dispatch_selects_the_requested_scope(self) -> None:
        with mock.patch("jot_core.cli._run_project", return_value=CommandResult("project", {})) as run_project:
            result = cli._run_open_alias(self.ctx, ["project", "work"])
        self.assertEqual(result.command, "project")
        run_project.assert_called_once_with(self.ctx, "work")

        with mock.patch("jot_core.cli._run_chain_cat", return_value=CommandResult("chain-cat", {})) as run_chain:
            result = cli._run_cat_alias(self.ctx, ["c", "42"])
        self.assertEqual(result.command, "chain-cat")
        run_chain.assert_called_once_with(self.ctx, "42")

    def test_note_and_recent_builders_normalize_filters(self) -> None:
        note = {"kind": "task-note", "id": "abcd1234", "title": "Read", "path": "/tmp/read.md"}
        args = SimpleNamespace(kinds=["task", "project"], project="study")
        with mock.patch("jot_core.cli.list_notes", return_value=[note]) as list_notes:
            result = cli._run_notes(self.ctx, args)
        self.assertEqual(result.command, "notes")
        self.assertEqual(result.data.project, "study")
        self.assertEqual(result.data.kinds, ("project-note", "task-note"))
        list_notes.assert_called_once()

        args = SimpleNamespace(limit=3, kinds=["event"])
        with mock.patch("jot_core.cli.recent_activity", return_value=[]):
            result = cli._run_recent(self.ctx, args)
        self.assertEqual(result.data.limit, 3)
        self.assertEqual(result.data.kinds, ("event",))

    def test_paths_command_uses_effective_taskwarrior_environment(self) -> None:
        captured: list[CommandResult] = []
        with mock.patch("jot_core.cli.build_app_context", return_value=self.ctx), mock.patch(
            "jot_core.cli.ensure_app_dirs"
        ), mock.patch("jot_core.cli.configure_output"), mock.patch(
            "jot_core.cli.emit_result", side_effect=lambda result, **_: captured.append(result)
        ):
            self.assertEqual(cli.main(["paths"]), 0)
        self.assertEqual(captured[0].command, "paths")
        self.assertEqual(captured[0].data.taskwarrior["data_path"], "/tmp/.task")
        self.assertEqual(captured[0].data.root_dir, str(self.root))

    def test_context_limits_return_machine_readable_error(self) -> None:
        output = io.StringIO()
        with mock.patch("jot_core.cli.build_app_context", return_value=self.ctx), mock.patch(
            "jot_core.cli.ensure_app_dirs"
        ), mock.patch("jot_core.cli.configure_output"), mock.patch("sys.stdout", output):
            result = cli.main(["--json", "context", "42", "--max-events", "-1"])
        self.assertEqual(result, 1)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "context_error")

    def test_no_arguments_prints_help_without_loading_context(self) -> None:
        output = io.StringIO()
        with mock.patch("sys.stdout", output), mock.patch("jot_core.cli.build_app_context") as build_context:
            self.assertEqual(cli.main([]), 0)
        self.assertIn("usage: jot", output.getvalue())
        build_context.assert_not_called()

    def test_timelog_orchestration_validates_and_routes_operations(self) -> None:
        pending_args = SimpleNamespace(timelog_command="pending")
        with mock.patch("jot_core.cli.list_time_sessions", return_value=[]):
            result = cli._run_timelog(self.ctx, pending_args)
        self.assertEqual(result.command, "timelog-pending")
        self.assertEqual(result.data.sessions, ())

        with self.assertRaisesRegex(RuntimeError, "requires --yes"):
            cli._run_timelog(self.ctx, SimpleNamespace(timelog_command="delete", yes=False, key="abc"))
        with self.assertRaisesRegex(RuntimeError, "two JSON lines"):
            with mock.patch("sys.stdin", io.StringIO("{}\n")):
                cli._run_timelog(self.ctx, SimpleNamespace(timelog_command="ingest", scope="auto", stopped_at=""))
        with self.assertRaisesRegex(RuntimeError, "invalid hook JSON"):
            with mock.patch("sys.stdin", io.StringIO("bad\n{}\n")):
                cli._run_timelog(self.ctx, SimpleNamespace(timelog_command="ingest", scope="auto", stopped_at=""))

    def test_timewarrior_and_search_orchestration_normalize_inputs(self) -> None:
        args = SimpleNamespace(
            timew_command="set",
            note_kind="project",
            note_ref="study",
            tags=["focus"],
        )
        with mock.patch(
            "jot_core.cli.set_timewarrior_tags",
            return_value={"operation": "set", "scope": "project", "reference": "study", "changed": True},
        ) as setter:
            result = cli._run_timewarrior(self.ctx, args)
        self.assertEqual(result.command, "timew")
        self.assertTrue(result.data.changed)
        setter.assert_called_once()

        args = SimpleNamespace(
            timew_command="clear",
            note_kind="project",
            note_ref="study",
        )
        with mock.patch(
            "jot_core.cli.clear_timewarrior_tags",
            return_value={"operation": "clear", "scope": "project", "reference": "study", "changed": False},
        ):
            result = cli._run_timewarrior(self.ctx, args)
        self.assertFalse(result.data.changed)

        with mock.patch("jot_core.cli.search_all", return_value=[]):
            result = cli._run_search(self.ctx, "book", ["task-note", "event"], " study ", " chain-1 ")
        self.assertEqual(result.data.query, "book")
        self.assertEqual(result.data.project, "study")
        self.assertEqual(result.data.chain_id, "chain-1")

    def test_resource_handlers_cover_attach_open_and_detach(self) -> None:
        resource = ResourceRecord(1, "docs", "https://example.test", "url", "exists", 1, "")
        operation = ResourceOperationResult(Path("/tmp/task.md"), resource, (resource,), opened=True)
        args = SimpleNamespace(note_kind="task", note_ref="42", target="https://example.test", label="docs")
        with mock.patch("jot_core.resource_cli.attach_task_resource_storage", return_value=operation) as attach:
            result = cli._run_attach(self.ctx, args)
        self.assertEqual(result.data.note_kind, "task")
        attach.assert_called_once()

        args = SimpleNamespace(note_kind="task", note_ref="42", resource_id=1)
        with mock.patch("jot_core.cli._existing_note_path_for_kind", return_value=(Path("/tmp/task.md"), {"task_short_uuid": "2d6d7d7d"})), mock.patch(
            "jot_core.resource_cli.list_note_resources", return_value=SimpleNamespace(resources=[resource.to_payload()])
        ), mock.patch("jot_core.resource_cli.open_resource_target", return_value=["xdg-open", "https://example.test"]):
            result = cli._run_open_resource(self.ctx, args)
        self.assertEqual(result.data.resource.target, "https://example.test")
        self.assertEqual(result.data.opener, ("xdg-open", "https://example.test"))

        args = SimpleNamespace(note_kind="project", note_ref="study", note_path="/tmp/project.md", resource_id=1)
        with mock.patch("jot_core.cli._existing_note_path_for_kind", return_value=(Path("/tmp/project.md"), {"project": "study"})), mock.patch(
            "jot_core.resource_cli.detach_project_resource_storage", return_value=operation
        ) as detach:
            result = cli._run_detach_resource(self.ctx, args)
        self.assertEqual(result.command, "detach-resource")
        detach.assert_called_once()

    def test_note_heading_append_delete_and_progress_handlers_build_results(self) -> None:
        mutation = HeadingCommandResult(
            note_kind="task",
            path=Path("/tmp/task.md"),
            opened=True,
            heading="Next steps",
            heading_match="fuzzy",
            timestamp="12:00",
            entry="Call vendor",
            identity={"task_short_uuid": "2d6d7d7d"},
        )
        args = SimpleNamespace(note_kind="task", note_ref="42", heading="Next", text="Call vendor", create_heading=False, heading_exact=False)
        with mock.patch.object(cli.JotService, "add_to_task_heading", return_value=mutation):
            result = cli._run_add_to(self.ctx, args)
        self.assertEqual(result.data.heading_match, "fuzzy")

        append = NoteAppendCommandResult(
            path=Path("/tmp/task.md"),
            opened=True,
            identity={"task_short_uuid": "2d6d7d7d"},
        )
        with mock.patch.object(cli.JotService, "append_task_note", return_value=append):
            result = cli._run_note_append(self.ctx, "42", "text")
        self.assertEqual(result.data.identity["task_short_uuid"], "2d6d7d7d")

        deleted = NoteDeleteStorageResult(Path("/tmp/task.md"), Path("/tmp/trash/task.md"), True)
        with mock.patch("jot_core.cli.delete_task_note_storage", return_value=deleted):
            result = cli._run_task_delete(self.ctx, "42")
        self.assertEqual(result.data.trash_path, Path("/tmp/trash/task.md"))

        args = SimpleNamespace(note_kind="task", note_ref="42", operation="add", value="2", unit=None, status=None, track="sets", confirm_clear=False)
        expected = CommandResult("progress", {"ok": True})
        with mock.patch("jot_core.cli._run_progress_command", return_value=expected) as progress:
            self.assertIs(cli._run_progress(self.ctx, args), expected)
        progress.assert_called_once()


if __name__ == "__main__":
    unittest.main()
