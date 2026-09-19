from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jot_core.frontmatter import write_document
from jot_core.models import AppConfig, NotePaths, ResourceOperationResult, ResourceRecord, ResolvedTask, TaskRef
from jot_core.services import JotService


class ServiceEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="jot-service-edge-")
        root = Path(self.tempdir.name)
        self.config = AppConfig(
            config_path=root / "config-jot.toml",
            root_dir=root,
            trash_dir=root / ".jot_trash",
            tasks_dir=root / "tasks",
            chains_dir=root / "chains",
            projects_dir=root / "projects",
            templates_dir=root / "templates",
            editor_command="true",
            editor_show_diff_on_save=False,
            editor_diff_color="never",
            editor_post_save_actions=False,
            color_mode="never",
            default_format="text",
            nautical_enabled=False,
            timewarrior_enabled=False,
        )
        for path in (self.config.tasks_dir, self.config.chains_dir, self.config.projects_dir):
            path.mkdir(parents=True)
        self.task = ResolvedTask(
            ref=TaskRef(raw="42"),
            task_uuid="2d6d7d7d-1111-2222-3333-444444444444",
            task_short_uuid="2d6d7d7d",
            description="Read book",
            project="study.deep",
            tags=["focus"],
            task={"uuid": "2d6d7d7d-1111-2222-3333-444444444444", "description": "Read book", "project": "study.deep", "chainID": "chain-1", "status": "pending"},
        )
        self.taskwarrior = SimpleNamespace(
            resolve_task=lambda _ref: self.task,
            resolve_first_for_filter=lambda _filter: self.task,
            annotations_for_task=lambda _task: [
                {"entry": str(index), "description": f"event {index}"}
                for index in range(3)
            ],
            list_tasks=lambda **_kwargs: [],
            complete_task=mock.Mock(),
        )
        self.service = JotService(config=self.config, taskwarrior=self.taskwarrior)  # type: ignore[arg-type]

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_agent_context_bounds_note_body_events_and_project_ancestors(self) -> None:
        task_note = self.config.tasks_dir / "2d6d7d7d--read-book.md"
        write_document(
            task_note,
            {"revision": "3", "task_short_uuid": "2d6d7d7d", "task_uuid": self.task.task_uuid},
            "0123456789abcdef",
        )
        context = self.service.agent_context("42", max_body_bytes=5, max_events=1)
        self.assertEqual(context.task["uuid"], self.task.task_uuid)
        self.assertEqual(context.notes["task"]["body"], "01234")
        self.assertTrue(context.notes["task"]["truncated"])
        self.assertEqual(context.events["items"][0]["entry"], "2")
        self.assertTrue(context.events["truncated"])
        self.assertEqual(context.context["projects"], ["study", "study.deep"])
        self.assertTrue(any("truncated" in warning for warning in context.warnings))

    def test_project_workspace_and_note_resource_queries_handle_missing_paths(self) -> None:
        workspace = self.service.project_workspace("missing.project")
        self.assertEqual(workspace.note["body"], "")
        self.assertEqual(self.service.note_resources("/does/not/exist"), [])

        note = self.config.tasks_dir / "2d6d7d7d--read-book.md"
        write_document(note, {}, "## Resources\n\n- [Docs](https://example.test)\n")
        resources = self.service.note_resources(str(note))
        self.assertIsInstance(resources[0], ResourceRecord)
        self.assertEqual(resources[0]["target"], "https://example.test")

    def test_resource_routing_supports_task_chain_project_and_rejects_unknown_kind(self) -> None:
        resource = ResourceRecord(1, "docs", "https://example.test", "url", "exists", 1, "")
        operation = ResourceOperationResult(Path("/tmp/note.md"), resource, (resource,), opened=True)
        with mock.patch("jot_core.services.attach_task_resource_storage", return_value=operation) as task_attach:
            result = self.service.attach_resource("task", task_ref="42", target="https://example.test", label="docs")
        self.assertEqual(result.resource.target, "https://example.test")
        task_attach.assert_called_once()

        with mock.patch("jot_core.services.attach_chain_resource_storage", return_value=operation):
            self.assertEqual(self.service.attach_resource("chain", task_ref="42", target="x").opened, True)
        with mock.patch("jot_core.services.attach_project_resource_storage", return_value=operation):
            self.assertEqual(self.service.attach_resource("project", project_name="study", target="x").opened, True)
        with self.assertRaisesRegex(RuntimeError, "unknown resource target kind"):
            self.service.attach_resource("bad", target="x", project_name="study")

    def test_progress_update_routes_operations_and_requires_clear_confirmation(self) -> None:
        with mock.patch.object(JotService, "set_progress", return_value={"operation": "set"}) as setter:
            result = self.service.update_progress("task", task_ref="42", operation="set", value="1/2")
        self.assertEqual(result["operation"], "set")
        setter.assert_called_once()

        with mock.patch.object(JotService, "adjust_progress", return_value={"operation": "add"}) as adjust:
            self.service.update_progress("task", task_ref="42", operation="add", value="1")
        adjust.assert_called_once()
        with mock.patch.object(JotService, "set_progress_status", return_value={"operation": "status"}):
            self.service.update_progress("task", task_ref="42", operation="status", value="active")
        with self.assertRaisesRegex(RuntimeError, "requires confirmation"):
            self.service.update_progress("task", task_ref="42", operation="clear")
        with mock.patch.object(JotService, "clear_progress", return_value={"operation": "clear"}):
            self.assertEqual(
                self.service.update_progress("task", task_ref="42", operation="clear", confirm_clear=True)["operation"],
                "clear",
            )

    def test_timelog_wrappers_delegate_each_lifecycle_operation(self) -> None:
        cases = (
            ("start_time_session", "timelog_start", ("42",), {"started_at": "now"}),
            ("stop_time_session", "timelog_stop", ("42",), {"stopped_at": "now", "scope": "task"}),
            ("cancel_time_session", "timelog_cancel", ("42",), {}),
            ("add_time_log", "timelog_add", ("42",), {"started_at": "start", "stopped_at": "stop", "scope": "auto"}),
            ("amend_time_log", "timelog_amend", ("key",), {"started_at": "start", "stopped_at": "stop"}),
            ("delete_time_log", "timelog_delete", ("key",), {}),
            ("restore_deleted_time_log", "timelog_restore", ("key",), {}),
        )
        for function_name, method_name, args, kwargs in cases:
            with self.subTest(method=method_name), mock.patch(
                f"jot_core.services.{function_name}", return_value=method_name
            ) as operation:
                result = getattr(self.service, method_name)(*args, **kwargs)
            self.assertEqual(result, method_name)
            self.assertTrue(operation.called)

        with mock.patch("jot_core.services.list_time_sessions", return_value=["pending"]):
            self.assertEqual(self.service.timelog_pending(), ["pending"])
        with mock.patch("jot_core.services.list_deleted_time_logs", return_value=[{"key": "old"}]):
            self.assertEqual(self.service.timelog_trash(), [{"key": "old"}])
        with mock.patch("jot_core.services.report_time_logs", return_value="report") as report:
            self.assertEqual(self.service.timelog_report("month", details=False), "report")
        report.assert_called_once_with(self.config, period="month", details=False)

    def test_editor_completion_heading_delete_and_detach_wrappers_route(self) -> None:
        note = NotePaths(self.config.tasks_dir / "task.md", False)
        with mock.patch("jot_core.services.ensure_task_note", return_value=note), mock.patch.object(
            JotService, "_open_note_in_editor"
        ), mock.patch("jot_core.services.finalize_task_note_edit") as finalize:
            self.assertEqual(self.service.open_task_note_in_editor("42"), str(note.note_path))
        finalize.assert_called_once()

        chain_note = NotePaths(self.config.chains_dir / "chain.md", False)
        with mock.patch("jot_core.services.ensure_chain_note", return_value=chain_note), mock.patch.object(
            JotService, "_open_note_in_editor"
        ), mock.patch("jot_core.services.finalize_chain_note_edit"):
            self.assertEqual(self.service.open_chain_note_in_editor("42"), str(chain_note.note_path))

        project_note = NotePaths(self.config.projects_dir / "study.md", False)
        with mock.patch("jot_core.services.ensure_project_note", return_value=project_note), mock.patch.object(
            JotService, "_open_note_in_editor"
        ), mock.patch("jot_core.services.finalize_project_note_edit"):
            self.assertEqual(self.service.open_project_note_in_editor("study"), str(project_note.note_path))

        self.service.complete_task("42")
        self.taskwarrior.complete_task.assert_called_once_with(self.task.task_uuid)
        self.assertEqual(self.service.task_ref_for_chain_id("chain-1"), "2d6d7d7d")

        resource = ResourceRecord(1, "docs", "https://example.test", "url", "exists", 1, "")
        operation = ResourceOperationResult(Path("/tmp/note.md"), resource, (resource,))
        with mock.patch("jot_core.services.detach_chain_resource_storage", return_value=operation):
            self.service.detach_resource("chain", task_ref="42", note_path="/tmp/note.md", resource_id=1)
        with mock.patch("jot_core.services.detach_project_resource_storage", return_value=operation):
            self.service.detach_resource("project", project_name="study", note_path="/tmp/note.md", resource_id=1)

        progress_path = self.config.tasks_dir / "progress.md"
        progress_path.write_text("", encoding="utf-8")
        with mock.patch("jot_core.services.find_task_note", return_value=progress_path), mock.patch(
            "jot_core.services.read_note_progress", return_value=SimpleNamespace(tracks=({"track": "pages"},))
        ):
            self.assertEqual(self.service.progress_track_names("task", task_ref="42"), ["pages"])
        self.assertEqual(self.service.progress_track_names("project", project_name="missing"), [])


if __name__ == "__main__":
    unittest.main()
