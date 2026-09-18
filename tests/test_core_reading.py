from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jot_core.events import collect_event_text, format_event_text, validate_event_type
from jot_core.models import AppConfig
from jot_core.schema import inspect_note_schema, inspect_note_schemas
from jot_core.search import (
    normalize_chain_id,
    normalize_kinds,
    normalize_project,
    search_all,
)
from jot_core.frontmatter import write_document


class CoreReadingTests(unittest.TestCase):
    def _config(self, root: Path) -> AppConfig:
        return AppConfig(
            config_path=root / "config-jot.toml",
            root_dir=root,
            trash_dir=root / ".jot_trash",
            tasks_dir=root / "tasks",
            chains_dir=root / "chains",
            projects_dir=root / "projects",
            templates_dir=root / "templates",
            editor_command="true",
            editor_show_diff_on_save=True,
            editor_diff_color="auto",
            editor_post_save_actions=True,
            color_mode="never",
            default_format="text",
            nautical_enabled=False,
            timewarrior_enabled=False,
        )

    def test_schema_inspection_classifies_current_legacy_future_and_invalid(self) -> None:
        with TemporaryDirectory(prefix="jot-schema-") as temporary:
            root = Path(temporary)
            paths = {
                "current": ({"kind": "task-note", "task_short_uuid": "abc", "schema_version": 1}, "current.md"),
                "legacy": ({"kind": "chain-note", "chain_id": "chain", "schema_version": 0}, "legacy.md"),
                "future": ({"kind": "project-note", "project": "work", "schema_version": 9}, "future.md"),
                "invalid": ({"kind": "task-note", "schema_version": 1}, "invalid.md"),
            }
            for metadata, name in paths.values():
                write_document(root / name, metadata, "body\n")

            self.assertEqual(inspect_note_schema(root / "current.md")["status"], "current")
            self.assertEqual(inspect_note_schema(root / "legacy.md")["status"], "legacy")
            self.assertEqual(inspect_note_schema(root / "future.md")["status"], "future")
            invalid = inspect_note_schema(root / "invalid.md")
            self.assertEqual(invalid["status"], "invalid")
            self.assertIn("missing required field", invalid["errors"][0])

            config = self._config(root)
            config.tasks_dir.mkdir()
            config.chains_dir.mkdir()
            config.projects_dir.mkdir()
            (config.tasks_dir / "current.md").write_text((root / "current.md").read_text(), encoding="utf-8")
            summary = inspect_note_schemas(config)
            self.assertEqual(summary["total"], 1)
            self.assertEqual(summary["counts"]["current"], 1)

    def test_event_text_validation_and_source_precedence(self) -> None:
        self.assertEqual(validate_event_type(" Status "), "status")
        self.assertEqual(format_event_text("note", "read"), "read")
        self.assertEqual(format_event_text("status", "read"), "status: read")
        self.assertEqual(
            collect_event_text(
                parts=["first", "second"],
                stdin_text="ignored",
                editor_command="true",
                task_short_uuid="abc",
                description="Task",
            ),
            "first second",
        )
        self.assertEqual(
            collect_event_text(
                parts=[],
                stdin_text="from stdin\n",
                editor_command="true",
                task_short_uuid="abc",
                description="Task",
            ),
            "from stdin",
        )
        with self.assertRaisesRegex(RuntimeError, "invalid event type"):
            validate_event_type("bad type")
        with self.assertRaisesRegex(RuntimeError, "event text is empty"):
            format_event_text("note", "")
        with self.assertRaisesRegex(RuntimeError, "event text is empty"):
            collect_event_text(
                parts=[],
                stdin_text="",
                editor_command="true",
                task_short_uuid="abc",
                description="Task",
            )

    def test_search_matches_notes_events_and_filters(self) -> None:
        with TemporaryDirectory(prefix="jot-search-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            for directory in (config.tasks_dir, config.chains_dir, config.projects_dir):
                directory.mkdir(parents=True)
            write_document(
                config.tasks_dir / "abc--task.md",
                {
                    "kind": "task-note",
                    "task_short_uuid": "abc",
                    "project": "work",
                    "chain_id": "chain-1",
                    "description": "Prepare vendor report",
                    "schema_version": 1,
                },
                "Details about the vendor contract.\n",
            )
            write_document(
                config.chains_dir / "chain-1--work.md",
                {"kind": "chain-note", "chain_id": "chain-1", "schema_version": 1},
                "Recurring vendor work.\n",
            )
            project_dir = config.projects_dir / "work"
            project_dir.mkdir()
            write_document(
                project_dir / "index.md",
                {"kind": "project-note", "project": "work", "schema_version": 1},
                "Project vendor notes.\n",
            )
            (config.root_dir / "ops.jsonl").write_text(
                json.dumps(
                    {
                        "op": "event_add",
                        "task_short_uuid": "abc",
                        "annotation": "waiting on vendor",
                        "ts": "2026-09-18T10:00:00Z",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            all_results = search_all(config, "vendor")
            self.assertEqual(len(all_results.notes), 3)

            results = search_all(config, "vendor", project="work", chain_id="chain-1")
            self.assertEqual(len(results.notes), 1)
            self.assertEqual(len(results.events), 1)
            self.assertEqual(results.events[0]["project"], "work")
            self.assertEqual(results.events[0]["chain_id"], "chain-1")
            self.assertEqual(search_all(config, "vendor", kinds={"project-note"}).events, ())

        self.assertEqual(normalize_kinds(None), {"task-note", "chain-note", "project-note", "event"})
        self.assertEqual(normalize_project(" work "), "work")
        self.assertEqual(normalize_chain_id(" chain-1 "), "chain-1")
        with self.assertRaisesRegex(RuntimeError, "unsupported kind"):
            normalize_kinds(["unknown"])
        with self.assertRaisesRegex(RuntimeError, "query is empty"):
            search_all(self._config(Path("/tmp")), "")


if __name__ == "__main__":
    unittest.main()
