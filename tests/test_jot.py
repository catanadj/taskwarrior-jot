from __future__ import annotations

import json
import os
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
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        result = self.run_jot("--json", "export", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["task_short_uuid"], "2d6d7d7d")
        self.assertEqual(len(payload["events"]), 2)
        self.assertIn("nautical", payload)
        self.assertTrue(payload["task_note"].endswith("2d6d7d7d--fix-billing-discrepancy.md"))
        self.assertTrue(payload["chain_note"].endswith("a4bf5egh--monthly-review.md"))

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
        result = self.run_jot("--json", "list", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["task_short_uuid"], "2d6d7d7d")
        self.assertEqual(payload["events"][0]["description"], "status: waiting on vendor")

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
