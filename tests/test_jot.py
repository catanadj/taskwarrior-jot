from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from jot_core.frontmatter import parse_document, render_document


PROJECT_ROOT = Path(__file__).resolve().parents[1]
JOT_SCRIPT = PROJECT_ROOT / "jot"


def _write_fake_task_script(bin_dir: Path, state_path: Path) -> None:
    script = textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        import json
        import pathlib
        import sys

        state_path = pathlib.Path({str(state_path)!r})
        state = json.loads(state_path.read_text())
        args = sys.argv[1:]

        if args == ['--version']:
            print(state.get('version', '2.6.2'))
            raise SystemExit(0)

        if 'annotate' in args:
            idx = args.index('annotate')
            text = args[idx + 1]
            export_key = state.get('annotate_key', 'single')
            task = state[export_key][0]
            seq = len(task.setdefault('annotations', [])) + 1
            task['annotations'].append({{"entry": f"20260405T1715{{seq:02d}}Z", "description": text}})
            state_path.write_text(json.dumps(state))
            raise SystemExit(0)

        if 'export' in args:
            export_key = 'single'
            for arg in args:
                if arg.startswith('uuid:'):
                    export_key = arg
                    break
                if arg.isdigit():
                    export_key = arg
                    break
            print(json.dumps(state.get(export_key, state.get('single', []))))
            raise SystemExit(0)

        print('[]')
        """
    )
    path = bin_dir / "task"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)


class JotCliTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="jot-test-")
        self.addCleanup(self.tempdir.cleanup)
        self.root = Path(self.tempdir.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.state_path = self.root / "task_state.json"

    def write_state(self, state: dict) -> None:
        self.state_path.write_text(json.dumps(state), encoding="utf-8")
        _write_fake_task_script(self.bin_dir, self.state_path)

    def run_jot(self, *args: str, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["PATH"] = f"{self.bin_dir}:{env['PATH']}"
        env["EDITOR"] = "true"
        return subprocess.run(
            [sys.executable, str(JOT_SCRIPT), *args],
            cwd=PROJECT_ROOT,
            env=env,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_jot_with_env(
        self,
        *args: str,
        input_text: str | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["PATH"] = f"{self.bin_dir}:{env['PATH']}"
        env["EDITOR"] = "true"
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, str(JOT_SCRIPT), *args],
            cwd=PROJECT_ROOT,
            env=env,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )


class FrontMatterTests(unittest.TestCase):
    def test_round_trip_preserves_lists_and_nulls(self) -> None:
        source = textwrap.dedent(
            """\
            ---
            kind: task-note
            task_short_uuid: 2d6d7d7d
            tags:
              - ann
              - ops
            chain_id: a4bf5egh
            anchor: null
            ---

            # Heading
            """
        )
        metadata, body = parse_document(source)
        self.assertEqual(metadata["task_short_uuid"], "2d6d7d7d")
        self.assertEqual(metadata["tags"], ["ann", "ops"])
        self.assertIsNone(metadata["anchor"])
        rendered = render_document(metadata, body)
        reparsed, rebody = parse_document(rendered)
        self.assertEqual(metadata, reparsed)
        self.assertEqual(body, rebody)


class CliIntegrationTests(JotCliTestCase):
    def test_no_arguments_prints_command_overview(self) -> None:
        result = self.run_jot()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage: jot", result.stdout)
        self.assertIn("Note-first companion for Taskwarrior and Taskwarrior-Nautical", result.stdout)
        self.assertIn("jot add-to task 42 --heading \"Next steps\" --text \"Call vendor Monday\"", result.stdout)
        self.assertIn("jot report recent --limit 10", result.stdout)
        self.assertIn("jot tui", result.stdout)

    def test_version_flag(self) -> None:
        result = self.run_jot("--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "jot 0.1.0")

    def test_doctor_reports_hardened_checks(self) -> None:
        result = self.run_jot("--json", "doctor")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        checks = {item["name"]: item for item in payload["checks"]}
        for name in (
            "config",
            "storage",
            "root_dir",
            "trash_dir",
            "tasks_dir",
            "chains_dir",
            "projects_dir",
            "templates_dir",
            "editor",
            "ops",
            "index",
            "taskwarrior",
        ):
            self.assertIn(name, checks)

    def test_doctor_reports_invalid_config_without_crashing(self) -> None:
        bad_config = self.root / "broken.toml"
        bad_config.write_text("[paths\nroot = '/tmp'\n", encoding="utf-8")
        result = self.run_jot_with_env("--json", "doctor", extra_env={"JOT_CONFIG": str(bad_config)})
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        checks = {item["name"]: item for item in payload["checks"]}
        self.assertFalse(checks["config"]["ok"])
        self.assertIn("failed to load config", checks["config"]["detail"])
    def test_paths_reports_resolved_storage_locations(self) -> None:
        result = self.run_jot("--json", "paths")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["config_path"].endswith(".task/jot/config-jot.toml"))
        self.assertTrue(payload["root_dir"].endswith(".task/jot"))
        self.assertTrue(payload["trash_dir"].endswith(".task/jot/.jot_trash"))
        self.assertTrue(payload["projects_dir"].endswith(".task/jot/projects"))
        self.assertTrue(payload["index_path"].endswith(".task/jot/index.json"))
        self.assertTrue(payload["ops_path"].endswith(".task/jot/ops.jsonl"))

    def test_note_append_updates_index_and_ops(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "link": 3,
            "anchor": "m:last-fri",
            "anchor_mode": "skip",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        result = self.run_jot("note-append", "1", "first", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)

        note_files = list((self.home / ".task" / "jot" / "tasks").glob("*.md"))
        self.assertEqual(len(note_files), 1)
        note_text = note_files[0].read_text(encoding="utf-8")
        self.assertIn("first entry", note_text)
        self.assertIn("updated:", note_text)

        index_data = json.loads((self.home / ".task" / "jot" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index_data["tasks"]["2d6d7d7d"]["chain_id"], "a4bf5egh")
        self.assertTrue(index_data["tasks"]["2d6d7d7d"]["note_path"].startswith("tasks/"))

        ops_lines = (self.home / ".task" / "jot" / "ops.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(ops_lines), 1)
        self.assertIn('"op":"task_note_append"', ops_lines[0])

    def test_note_templates_are_applied_for_task_chain_and_project(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "link": 3,
            "anchor": "m:last-fri",
            "anchor_mode": "skip",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        templates_dir = self.home / ".task" / "jot" / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)
        (templates_dir / "task-note.md").write_text(
            textwrap.dedent(
                """\
                ---
                kind: bad-kind
                custom: "{{task_short_uuid}}"
                ---

                # TASK {{task_short_uuid}}
                """
            ),
            encoding="utf-8",
        )
        (templates_dir / "chain-note.md").write_text(
            textwrap.dedent(
                """\
                # CHAIN {{chain_id}}
                """
            ),
            encoding="utf-8",
        )
        (templates_dir / "project-note.md").write_text(
            textwrap.dedent(
                """\
                # PROJECT {{project}}
                """
            ),
            encoding="utf-8",
        )

        self.run_jot("note-append", "1", "task body")
        self.run_jot("chain-append", "1", "chain body")
        self.run_jot("project-append", "finance.audit", "project body")

        task_note = list((self.home / ".task" / "jot" / "tasks").glob("*.md"))[0].read_text(encoding="utf-8")
        self.assertIn("# TASK 2d6d7d7d", task_note)
        self.assertIn("kind: task-note", task_note)
        self.assertIn('custom: "2d6d7d7d"', task_note)
        self.assertNotIn("kind: bad-kind", task_note)

        chain_note = list((self.home / ".task" / "jot" / "chains").glob("*.md"))[0].read_text(encoding="utf-8")
        self.assertIn("# CHAIN a4bf5egh", chain_note)

        project_note = (
            self.home / ".task" / "jot" / "projects" / "finance" / "audit" / "index.md"
        ).read_text(encoding="utf-8")
        self.assertIn("# PROJECT finance.audit", project_note)

    def test_empty_template_falls_back_to_builtin_body(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        templates_dir = self.home / ".task" / "jot" / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)
        (templates_dir / "task-note.md").write_text("", encoding="utf-8")

        result = self.run_jot("note-append", "1", "entry")
        self.assertEqual(result.returncode, 0, result.stderr)
        task_note = list((self.home / ".task" / "jot" / "tasks").glob("*.md"))[0].read_text(encoding="utf-8")
        self.assertIn("## Context", task_note)
        self.assertIn("## Notes", task_note)

    def test_project_note_append_uses_project_hierarchy_and_updates_index(self) -> None:
        result = self.run_jot("project-append", "Finances.Expense", "reimbursement", "policy")
        self.assertEqual(result.returncode, 0, result.stderr)

        note_path = self.home / ".task" / "jot" / "projects" / "finances" / "expense" / "index.md"
        self.assertTrue(note_path.exists())
        note_text = note_path.read_text(encoding="utf-8")
        self.assertIn("project: Finances.Expense", note_text)
        self.assertIn("project_path:", note_text)
        self.assertIn("reimbursement policy", note_text)

        index_data = json.loads((self.home / ".task" / "jot" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(
            index_data["projects"]["Finances.Expense"]["note_path"],
            "projects/finances/expense/index.md",
        )

        ops_lines = (self.home / ".task" / "jot" / "ops.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(ops_lines), 1)
        self.assertIn('"op":"project_note_append"', ops_lines[0])

    def test_project_show_and_cat_contracts(self) -> None:
        self.run_jot("project-append", "finance.audit", "vendor escalation policy")

        show_result = self.run_jot("--json", "project-show", "finance.audit")
        self.assertEqual(show_result.returncode, 0, show_result.stderr)
        show_payload = json.loads(show_result.stdout)
        self.assertEqual(show_payload["kind"], "project-summary")
        self.assertEqual(show_payload["project"], "finance.audit")
        self.assertTrue(show_payload["note"]["exists"])
        self.assertTrue(show_payload["note"]["path"].endswith("projects/finance/audit/index.md"))
        self.assertIn("Purpose", show_payload["note"]["preview"])

        cat_result = self.run_jot("project-cat", "finance.audit")
        self.assertEqual(cat_result.returncode, 0, cat_result.stderr)
        self.assertIn("project: finance.audit", cat_result.stdout)
        self.assertIn("vendor escalation policy", cat_result.stdout)

        missing_show = self.run_jot("--json", "project-show", "missing.project")
        self.assertEqual(missing_show.returncode, 0, missing_show.stderr)
        missing_payload = json.loads(missing_show.stdout)
        self.assertFalse(missing_payload["note"]["exists"])
        self.assertTrue(missing_payload["note"]["path"].endswith("projects/missing/project/index.md"))

        missing_cat = self.run_jot("project-cat", "missing.project")
        self.assertNotEqual(missing_cat.returncode, 0)
        self.assertIn("project note does not exist", missing_cat.stderr)

        text_show = self.run_jot("project-show", "finance.audit")
        self.assertEqual(text_show.returncode, 0, text_show.stderr)
        self.assertIn("Project finance.audit", text_show.stdout)
        self.assertIn("Note:", text_show.stdout)
        self.assertIn("path", text_show.stdout)
        self.assertIn("preview", text_show.stdout)

    def test_delete_commands_move_notes_to_trash_and_update_index(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "link": 3,
            "anchor": "m:last-fri",
            "anchor_mode": "skip",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        self.assertEqual(self.run_jot("note-append", "1", "task note body").returncode, 0)
        self.assertEqual(self.run_jot("chain-append", "1", "chain note body").returncode, 0)
        self.assertEqual(self.run_jot("project-append", "finance.audit", "project note body").returncode, 0)

        task_delete = self.run_jot("task-delete", "1")
        self.assertEqual(task_delete.returncode, 0, task_delete.stderr)
        chain_delete = self.run_jot("chain-delete", "1")
        self.assertEqual(chain_delete.returncode, 0, chain_delete.stderr)
        project_delete = self.run_jot("project-delete", "finance.audit")
        self.assertEqual(project_delete.returncode, 0, project_delete.stderr)

        trash_root = self.home / ".task" / "jot" / ".jot_trash"
        trashed_notes = sorted(trash_root.rglob("*.md"))
        self.assertEqual(len(trashed_notes), 3)

        original_task_note = self.home / ".task" / "jot" / "tasks" / "2d6d7d7d--fix-billing-discrepancy.md"
        self.assertFalse(original_task_note.exists())
        original_chain_note = self.home / ".task" / "jot" / "chains" / "a4bf5egh--fix-billing-discrepancy.md"
        self.assertFalse(original_chain_note.exists())
        original_project_note = self.home / ".task" / "jot" / "projects" / "finance" / "audit" / "index.md"
        self.assertFalse(original_project_note.exists())

        index_data = json.loads((self.home / ".task" / "jot" / "index.json").read_text(encoding="utf-8"))
        self.assertNotIn("2d6d7d7d", index_data["tasks"])
        self.assertNotIn("a4bf5egh", index_data["chains"])
        self.assertNotIn("finance.audit", index_data["projects"])

    def test_task_and_chain_cat_contracts(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "link": 3,
            "anchor": "m:last-fri",
            "anchor_mode": "skip",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        self.run_jot("note-append", "1", "task note body")
        self.run_jot("chain-append", "1", "chain note body")

        task_cat = self.run_jot("task-cat", "1")
        self.assertEqual(task_cat.returncode, 0, task_cat.stderr)
        self.assertIn("task_short_uuid: 2d6d7d7d", task_cat.stdout)
        self.assertIn("task note body", task_cat.stdout)

        chain_cat = self.run_jot("chain-cat", "1")
        self.assertEqual(chain_cat.returncode, 0, chain_cat.stderr)
        self.assertIn("chain_id: a4bf5egh", chain_cat.stdout)
        self.assertIn("chain note body", chain_cat.stdout)

        missing_task = self.run_jot("task-cat", "1")
        self.assertEqual(missing_task.returncode, 0, missing_task.stderr)

        fresh_task = {
            "uuid": "3e6d7d7d-1111-2222-3333-444444444444",
            "description": "Unnoted task",
            "project": "",
            "tags": [],
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [fresh_task], "2": [fresh_task]})
        missing_task_cat = self.run_jot("task-cat", "2")
        self.assertNotEqual(missing_task_cat.returncode, 0)
        self.assertIn("task note does not exist", missing_task_cat.stderr)

        missing_chain_cat = self.run_jot("chain-cat", "2")
        self.assertNotEqual(missing_chain_cat.returncode, 0)
        self.assertIn("chain note does not exist", missing_chain_cat.stderr)

    def test_add_to_task_heading_fuzzy_adds_timestamped_entry(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        result = self.run_jot(
            "add-to",
            "task",
            "1",
            "--heading",
            "next stps",
            "--text",
            "call vendor monday",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        note_text = list((self.home / ".task" / "jot" / "tasks").glob("*.md"))[0].read_text(encoding="utf-8")
        self.assertIn("## Next steps", note_text)
        self.assertRegex(note_text, r"- \[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\] call vendor monday")

    def test_add_to_chain_heading_exact_can_fail_cleanly(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        result = self.run_jot(
            "add-to",
            "chain",
            "1",
            "--heading",
            "operating ntes",
            "--heading-exact",
            "--text",
            "skip holidays",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("heading not found", result.stderr)

    def test_add_to_project_heading_can_create_missing_heading(self) -> None:
        self.run_jot("project-append", "finance.audit", "baseline entry")

        result = self.run_jot(
            "add-to",
            "project",
            "finance.audit",
            "--heading",
            "Risks",
            "--create-heading",
            "--text",
            "vendor dependency",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        note_path = self.home / ".task" / "jot" / "projects" / "finance" / "audit" / "index.md"
        note_text = note_path.read_text(encoding="utf-8")
        self.assertIn("## Risks", note_text)
        self.assertRegex(note_text, r"- \[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\] vendor dependency")

    def test_add_and_list_events(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "link": 3,
            "anchor": "m:last-fri",
            "anchor_mode": "skip",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task], "annotate_key": "1"})

        first = self.run_jot("add", "--type", "status", "1", "waiting", "on", "vendor")
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_jot("add", "1", input_text="piped note\n")
        self.assertEqual(second.returncode, 0, second.stderr)
        listed = self.run_jot("list", "1")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("status: waiting on vendor", listed.stdout)
        self.assertIn("piped note", listed.stdout)

        index_data = json.loads((self.home / ".task" / "jot" / "index.json").read_text(encoding="utf-8"))
        self.assertIsNotNone(index_data["tasks"]["2d6d7d7d"]["last_event_at"])

    def test_export_json_contract(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "link": 3,
            "anchor": "m:last-fri",
            "anchor_mode": "skip",
            "annotations": [
                {"entry": "20260405T171501Z", "description": "status: waiting on vendor"},
                {"entry": "20260405T171502Z", "description": "piped note"},
            ],
        }
        jot_root = self.home / ".task" / "jot"
        (jot_root / "tasks").mkdir(parents=True, exist_ok=True)
        (jot_root / "chains").mkdir(parents=True, exist_ok=True)
        (jot_root / "tasks" / "2d6d7d7d--fix-billing-discrepancy.md").write_text(
            textwrap.dedent(
                """\
                ---
                kind: task-note
                task_short_uuid: 2d6d7d7d
                description: Fix billing discrepancy
                project: finance.audit
                tags:
                  - ann
                chain_id: a4bf5egh
                link: 3
                created: 2026-04-05T12:00:00Z
                updated: 2026-04-05T12:00:00Z
                ---

                # Fix billing discrepancy
                """
            ),
            encoding="utf-8",
        )
        (jot_root / "chains" / "a4bf5egh--monthly-review.md").write_text(
            textwrap.dedent(
                """\
                ---
                kind: chain-note
                chain_id: a4bf5egh
                description: Monthly review
                anchor: m:last-fri
                cp: null
                anchor_mode: skip
                created: 2026-04-05T12:00:00Z
                updated: 2026-04-05T12:00:00Z
                ---

                # Monthly review
                """
            ),
            encoding="utf-8",
        )
        (jot_root / "projects" / "finance" / "audit").mkdir(parents=True, exist_ok=True)
        (jot_root / "projects" / "finance" / "audit" / "index.md").write_text(
            textwrap.dedent(
                """\
                ---
                kind: project-note
                project: finance.audit
                project_path:
                  - finance
                  - audit
                created: 2026-04-05T12:00:00Z
                updated: 2026-04-05T12:00:00Z
                ---

                # finance.audit
                """
            ),
            encoding="utf-8",
        )
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        result = self.run_jot("--json", "export", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["kind"], "task-summary")
        self.assertEqual(payload["task"]["short_uuid"], "2d6d7d7d")
        self.assertEqual(payload["task"]["uuid"], "2d6d7d7d-1111-2222-3333-444444444444")
        self.assertEqual(len(payload["events"]), 2)
        self.assertIn("nautical", payload)
        self.assertIn("exported_at", payload)
        self.assertTrue(payload["notes"]["task"]["exists"])
        self.assertTrue(payload["notes"]["task"]["path"].endswith("2d6d7d7d--fix-billing-discrepancy.md"))
        self.assertTrue(payload["notes"]["chain"]["exists"])
        self.assertTrue(payload["notes"]["chain"]["path"].endswith("a4bf5egh--monthly-review.md"))
        self.assertTrue(payload["notes"]["project"]["exists"])
        self.assertTrue(payload["notes"]["project"]["path"].endswith("projects/finance/audit/index.md"))

    def test_search_finds_notes_and_events_and_has_json_contract(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "link": 3,
            "anchor": "m:last-fri",
            "anchor_mode": "skip",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task], "annotate_key": "1"})

        self.run_jot("note-append", "1", "vendor call recap")
        self.run_jot("project-append", "finance.audit", "vendor escalation policy")
        self.run_jot("add", "--type", "status", "1", "waiting", "on", "vendor")

        text_result = self.run_jot("search", "vendor")
        self.assertEqual(text_result.returncode, 0, text_result.stderr)
        self.assertIn("Notes:", text_result.stdout)
        self.assertIn("Events:", text_result.stdout)

        json_result = self.run_jot("--json", "search", "vendor")
        self.assertEqual(json_result.returncode, 0, json_result.stderr)
        payload = json.loads(json_result.stdout)
        self.assertEqual(payload["query"], "vendor")
        self.assertGreaterEqual(len(payload["notes"]), 1)
        self.assertGreaterEqual(len(payload["events"]), 1)
        self.assertEqual(payload["events"][0]["kind"], "event")
        self.assertIn("project-note", {item["kind"] for item in payload["notes"]})
        filtered = self.run_jot("--json", "search", "--kind", "project-note", "vendor")
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        filtered_payload = json.loads(filtered.stdout)
        self.assertEqual(filtered_payload["kinds"], ["project-note"])
        self.assertGreaterEqual(len(filtered_payload["notes"]), 1)
        self.assertEqual(filtered_payload["events"], [])
        self.assertEqual({item["kind"] for item in filtered_payload["notes"]}, {"project-note"})

        project_filtered = self.run_jot("--json", "search", "--project", "finance.audit", "vendor")
        self.assertEqual(project_filtered.returncode, 0, project_filtered.stderr)
        project_payload = json.loads(project_filtered.stdout)
        self.assertEqual(project_payload["project"], "finance.audit")
        self.assertGreaterEqual(len(project_payload["notes"]), 1)
        self.assertGreaterEqual(len(project_payload["events"]), 1)
        self.assertTrue(
            all(item.get("project") == "finance.audit" for item in project_payload["notes"] if item.get("project"))
        )
        self.assertTrue(all(item.get("project") == "finance.audit" for item in project_payload["events"]))

        chain_filtered = self.run_jot("--json", "search", "--chain", "a4bf5egh", "vendor")
        self.assertEqual(chain_filtered.returncode, 0, chain_filtered.stderr)
        chain_payload = json.loads(chain_filtered.stdout)
        self.assertEqual(chain_payload["chain_id"], "a4bf5egh")
        self.assertGreaterEqual(len(chain_payload["notes"]), 1)
        self.assertGreaterEqual(len(chain_payload["events"]), 1)
        note_chain_ids = {item["chain_id"] for item in chain_payload["notes"] if item.get("chain_id")}
        self.assertEqual(note_chain_ids, {"a4bf5egh"})
        self.assertEqual({item["chain_id"] for item in chain_payload["events"]}, {"a4bf5egh"})

    def test_list_json_contract(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "link": 3,
            "anchor": "m:last-fri",
            "anchor_mode": "skip",
            "annotations": [{"entry": "20260405T171501Z", "description": "status: waiting on vendor"}],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})
        self.run_jot("project-append", "finance.audit", "project context")
        result = self.run_jot("--json", "list", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["kind"], "task-summary")
        self.assertEqual(payload["task"]["short_uuid"], "2d6d7d7d")
        self.assertEqual(payload["events"][0]["description"], "status: waiting on vendor")
        self.assertTrue(payload["notes"]["project"]["exists"])
        self.assertTrue(payload["notes"]["project"]["path"].endswith("projects/finance/audit/index.md"))

    def test_show_json_contract_is_summary_only(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "link": 3,
            "anchor": "m:last-fri",
            "anchor_mode": "skip",
            "annotations": [{"entry": "20260405T171501Z", "description": "status: waiting on vendor"}],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})
        self.run_jot("project-append", "finance.audit", "project context")

        result = self.run_jot("--json", "show", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["kind"], "task-summary")
        self.assertEqual(payload["task"]["short_uuid"], "2d6d7d7d")
        self.assertNotIn("events", payload)
        self.assertTrue(payload["notes"]["task"]["available"])
        self.assertTrue(payload["notes"]["project"]["exists"])

        text_result = self.run_jot("show", "1")
        self.assertEqual(text_result.returncode, 0, text_result.stderr)
        self.assertIn("Task 2d6d7d7d", text_result.stdout)
        self.assertIn("description", text_result.stdout)
        self.assertIn("Notes:", text_result.stdout)
        self.assertIn("Nautical:", text_result.stdout)

    def test_corrupt_index_is_rebuilt(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "link": 3,
            "anchor": "m:last-fri",
            "anchor_mode": "skip",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})
        jot_root = self.home / ".task" / "jot"
        (jot_root / "tasks").mkdir(parents=True, exist_ok=True)
        (jot_root / "tasks" / "2d6d7d7d--fix-billing-discrepancy.md").write_text(
            textwrap.dedent(
                """\
                ---
                kind: task-note
                task_short_uuid: 2d6d7d7d
                description: Fix billing discrepancy
                project: finance.audit
                tags:
                  - ann
                chain_id: a4bf5egh
                link: 3
                created: 2026-04-05T12:00:00Z
                updated: 2026-04-05T12:00:00Z
                ---

                # Fix billing discrepancy
                """
            ),
            encoding="utf-8",
        )
        (jot_root / "index.json").write_text("not json\n", encoding="utf-8")

        result = self.run_jot("note-append", "1", "repaired")
        self.assertEqual(result.returncode, 0, result.stderr)

        rebuilt = json.loads((jot_root / "index.json").read_text(encoding="utf-8"))
        self.assertIn("2d6d7d7d", rebuilt["tasks"])
        self.assertEqual(rebuilt["tasks"]["2d6d7d7d"]["chain_id"], "a4bf5egh")

    def test_rebuild_index_command_reports_counts(self) -> None:
        jot_root = self.home / ".task" / "jot"
        (jot_root / "tasks").mkdir(parents=True, exist_ok=True)
        (jot_root / "chains").mkdir(parents=True, exist_ok=True)
        (jot_root / "projects" / "finance" / "audit").mkdir(parents=True, exist_ok=True)

        (jot_root / "tasks" / "2d6d7d7d--fix-billing-discrepancy.md").write_text(
            textwrap.dedent(
                """\
                ---
                kind: task-note
                task_short_uuid: 2d6d7d7d
                description: Fix billing discrepancy
                project: finance.audit
                tags:
                  - ann
                chain_id: a4bf5egh
                created: 2026-04-05T12:00:00Z
                updated: 2026-04-05T12:00:00Z
                ---

                # Fix billing discrepancy
                """
            ),
            encoding="utf-8",
        )
        (jot_root / "chains" / "a4bf5egh--monthly-review.md").write_text(
            textwrap.dedent(
                """\
                ---
                kind: chain-note
                chain_id: a4bf5egh
                description: Monthly review
                created: 2026-04-05T12:00:00Z
                updated: 2026-04-05T12:00:00Z
                ---

                # Monthly review
                """
            ),
            encoding="utf-8",
        )
        (jot_root / "projects" / "finance" / "audit" / "index.md").write_text(
            textwrap.dedent(
                """\
                ---
                kind: project-note
                project: finance.audit
                project_path:
                  - finance
                  - audit
                created: 2026-04-05T12:00:00Z
                updated: 2026-04-05T12:00:00Z
                ---

                # finance.audit
                """
            ),
            encoding="utf-8",
        )
        (jot_root / "index.json").write_text("broken\n", encoding="utf-8")

        result = self.run_jot("--json", "rebuild-index")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["counts"]["tasks"], 1)
        self.assertEqual(payload["counts"]["chains"], 1)
        self.assertEqual(payload["counts"]["projects"], 1)
        self.assertTrue(payload["index_path"].endswith(".task/jot/index.json"))

    def test_stats_reports_note_ops_and_index_status(self) -> None:
        jot_root = self.home / ".task" / "jot"
        (jot_root / "tasks").mkdir(parents=True, exist_ok=True)
        (jot_root / "chains").mkdir(parents=True, exist_ok=True)
        (jot_root / "projects" / "finance" / "audit").mkdir(parents=True, exist_ok=True)

        (jot_root / "tasks" / "2d6d7d7d--fix-billing-discrepancy.md").write_text(
            textwrap.dedent(
                """\
                ---
                kind: task-note
                task_short_uuid: 2d6d7d7d
                description: Fix billing discrepancy
                project: finance.audit
                tags:
                  - ann
                chain_id: a4bf5egh
                created: 2026-04-05T12:00:00Z
                updated: 2026-04-05T12:00:00Z
                ---

                # Fix billing discrepancy
                """
            ),
            encoding="utf-8",
        )
        (jot_root / "chains" / "a4bf5egh--monthly-review.md").write_text(
            textwrap.dedent(
                """\
                ---
                kind: chain-note
                chain_id: a4bf5egh
                description: Monthly review
                created: 2026-04-05T12:00:00Z
                updated: 2026-04-05T12:00:00Z
                ---

                # Monthly review
                """
            ),
            encoding="utf-8",
        )
        (jot_root / "projects" / "finance" / "audit" / "index.md").write_text(
            textwrap.dedent(
                """\
                ---
                kind: project-note
                project: finance.audit
                project_path:
                  - finance
                  - audit
                created: 2026-04-05T12:00:00Z
                updated: 2026-04-05T12:00:00Z
                ---

                # finance.audit
                """
            ),
            encoding="utf-8",
        )
        (jot_root / "ops.jsonl").write_text(
            '{"ts":"2026-04-05T12:00:00Z","op":"event_add","ok":true,"task_short_uuid":"2d6d7d7d","annotation":"status: waiting on vendor"}\n',
            encoding="utf-8",
        )
        (jot_root / "index.json").write_text(
            textwrap.dedent(
                """\
                {
                  "version": 1,
                  "updated": "2026-04-05T11:00:00Z",
                  "tasks": {},
                  "chains": {},
                  "projects": {}
                }
                """
            ),
            encoding="utf-8",
        )

        result = self.run_jot("--json", "stats")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["notes"]["tasks"], 1)
        self.assertEqual(payload["notes"]["chains"], 1)
        self.assertEqual(payload["notes"]["projects"], 1)
        self.assertEqual(payload["ops"]["entries"], 1)
        self.assertEqual(payload["ops"]["event_add"], 1)
        self.assertTrue(payload["index"]["exists"])
        self.assertTrue(payload["index"]["valid"])
        self.assertTrue(payload["index"]["stale"])

    def test_project_list_reports_known_project_notes(self) -> None:
        self.run_jot("project-append", "finance.audit", "project context")
        self.run_jot("project-append", "ops.runbook", "ops context")

        result = self.run_jot("--json", "project-list")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual([item["project"] for item in payload["projects"]], ["finance.audit", "ops.runbook"])
        self.assertTrue(payload["projects"][0]["path"].endswith("projects/finance/audit/index.md"))

    def test_report_recent_combines_notes_and_events(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "link": 3,
            "anchor": "m:last-fri",
            "anchor_mode": "skip",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task], "annotate_key": "1"})

        self.run_jot("note-append", "1", "task note body")
        self.run_jot("chain-append", "1", "chain note body")
        self.run_jot("project-append", "finance.audit", "project context")
        self.run_jot("add", "--type", "status", "1", "waiting", "on", "vendor")

        result = self.run_jot("--json", "report", "recent", "--limit", "10")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["limit"], 10)
        kinds = {item["kind"] for item in payload["items"]}
        self.assertIn("task-note", kinds)
        self.assertIn("chain-note", kinds)
        self.assertIn("project-note", kinds)
        self.assertIn("event", kinds)
        filtered = self.run_jot("--json", "report", "recent", "--kind", "event", "--limit", "10")
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        filtered_payload = json.loads(filtered.stdout)
        self.assertEqual(filtered_payload["kinds"], ["event"])
        self.assertTrue(filtered_payload["items"])
        self.assertEqual({item["kind"] for item in filtered_payload["items"]}, {"event"})

    def test_ambiguous_short_uuid_returns_error(self) -> None:
        task_a = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Task A",
            "project": "",
            "tags": [],
            "annotations": [],
        }
        task_b = {
            "uuid": "2d6d7d7d-aaaa-bbbb-cccc-555555555555",
            "description": "Task B",
            "project": "",
            "tags": [],
            "annotations": [],
        }
        self.write_state(
            {
                "version": "2.6.2",
                "single": [task_a],
                "uuid:2d6d7d7d": [task_a, task_b],
            }
        )
        result = self.run_jot("show", "2d6d7d7d")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ambiguous", result.stderr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
