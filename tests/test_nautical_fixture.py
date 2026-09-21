from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jot_core.frontmatter import write_document
from jot_core.models import AppConfig, ResolvedTask, TaskRef
from jot_core.nautical import chain_id_for_task, has_nautical_context, nautical_snapshot
from jot_core.notes import find_chain_note


FIXTURE = Path(__file__).parent / "fixtures" / "nautical" / "task-export.json"


class NauticalFixtureTests(unittest.TestCase):
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
            editor_diff_color="never",
            editor_post_save_actions=True,
            color_mode="never",
            default_format="text",
            nautical_enabled=True,
            timewarrior_enabled=False,
        )

    def test_pending_nautical_link_resolves_shared_chain_note(self) -> None:
        tasks = json.loads(FIXTURE.read_text(encoding="utf-8"))
        pending = next(task for task in tasks if task["status"] == "pending")
        chain_id = chain_id_for_task(pending)

        self.assertEqual(chain_id, "0a5ea03d")
        self.assertTrue(has_nautical_context(pending))
        self.assertEqual(nautical_snapshot(pending)["fields"]["prevLink"], "0a5ea03d")

        with TemporaryDirectory(prefix="jot-nautical-fixture-") as temporary:
            root = Path(temporary)
            config = self._config(root)
            config.chains_dir.mkdir(parents=True)
            note_path = config.chains_dir / "0a5ea03d--offline-readiness-drill.md"
            write_document(
                note_path,
                {
                    "schema_version": 1,
                    "kind": "chain-note",
                    "chain_id": chain_id,
                    "description": pending["description"],
                },
                "## Notes\n\nNautical chain context.\n",
            )
            task = ResolvedTask(
                ref=TaskRef(raw=pending["uuid"]),
                task_uuid=pending["uuid"],
                task_short_uuid=pending["uuid"].split("-", 1)[0],
                description=pending["description"],
                project="",
                tags=[],
                task=pending,
            )

            self.assertEqual(find_chain_note(config, task), note_path)


if __name__ == "__main__":
    unittest.main()
