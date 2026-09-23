from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jot_core.frontmatter import write_document
from jot_core.models import AppConfig
from jot_core.search import search_all


class SearchRankingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = TemporaryDirectory(prefix="jot-search-rank-")
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
            editor_show_diff_on_save=True,
            editor_diff_color="never",
            editor_post_save_actions=True,
            color_mode="never",
            default_format="text",
            nautical_enabled=False,
            timewarrior_enabled=False,
        )
        for path in (
            self.config.tasks_dir,
            self.config.chains_dir,
            self.config.projects_dir,
            self.config.trash_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_titles_rank_before_headings_and_body_then_recency(self) -> None:
        write_document(
            self.config.tasks_dir / "task.md",
            {"kind": "task-note", "description": "Orchid care", "updated": "2020-01-01T00:00:00Z"},
            "No match in body",
        )
        write_document(
            self.config.chains_dir / "chain.md",
            {"kind": "chain-note", "description": "Daily routine", "updated": "2025-01-01T00:00:00Z"},
            "## Orchid checklist\nWater every morning",
        )
        write_document(
            self.config.projects_dir / "garden" / "index.md",
            {"kind": "project-note", "project": "garden", "updated": "2026-01-01T00:00:00Z"},
            "Orchid notes and seasonal care",
        )

        results = search_all(self.config, "orchid")
        self.assertEqual(
            [item.kind for item in results.notes],
            ["task-note", "chain-note", "project-note"],
        )
        self.assertEqual([item.raw["match_type"] for item in results.notes], ["title", "heading", "content"])
        self.assertIn("Orchid", results.notes[0].match)
        self.assertIn("Orchid", results.notes[1].match)
        self.assertIn("Orchid", results.notes[2].match)

    def test_equal_rank_and_recency_use_stable_path_order_and_filters_remain(self) -> None:
        for filename, timestamp in (
            ("z-task.md", "2026-01-01T00:00:00Z"),
            ("a-task.md", "2026-01-01T00:00:00Z"),
            ("m-task.md", ""),
        ):
            metadata = {"kind": "task-note", "description": "Orchid log", "project": "garden"}
            if timestamp:
                metadata["updated"] = timestamp
            write_document(
                self.config.tasks_dir / filename,
                metadata,
                "Details",
            )

        all_results = search_all(self.config, "orchid")
        self.assertEqual(
            [Path(item.path).name for item in all_results.notes],
            ["a-task.md", "z-task.md", "m-task.md"],
        )
        filtered = search_all(self.config, "orchid", kinds={"task-note"}, project="garden")
        self.assertEqual(len(filtered.notes), 3)
        self.assertEqual(filtered.trash, ())

    def test_trash_is_ranked_independently_and_events_are_recency_sorted(self) -> None:
        older = self.config.trash_dir / "old.md"
        newer = self.config.trash_dir / "new.md"
        write_document(older, {"kind": "task-note", "description": "Orchid archive"}, "old body")
        write_document(newer, {"kind": "task-note", "description": "Other task"}, "orchid body")
        for path, deleted in ((older, "2024-01-01T00:00:00Z"), (newer, "2026-01-01T00:00:00Z")):
            manifest = path.with_name(f".{path.name}.jot-manifest.json")
            manifest.write_text(
                json.dumps({"kind": "task-note", "deleted_at": deleted, "path": str(path)}),
                encoding="utf-8",
            )
        ops = self.config.root_dir / "ops.jsonl"
        ops.write_text(
            "\n".join(
                json.dumps({"op": "event_add", "task_short_uuid": "a", "ts": ts, "annotation": "orchid note"})
                for ts in ("2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
            ) + "\n",
            encoding="utf-8",
        )

        results = search_all(self.config, "orchid")
        self.assertEqual([Path(item.path).name for item in results.trash], ["old.md", "new.md"])
        self.assertEqual([item.raw["ts"] for item in results.events], ["2026-01-01T00:00:00Z", "2025-01-01T00:00:00Z"])


if __name__ == "__main__":
    unittest.main()
