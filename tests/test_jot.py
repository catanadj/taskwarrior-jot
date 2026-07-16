from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jot_core.cli import _offer_post_save_task_action, build_parser
from jot_core.command_help import build_command_catalog
from jot_core.command_prefix import AmbiguousCommandPrefix, expand_command_prefixes
from jot_core.editor import colorize_diff, note_diff
from jot_core.frontmatter import atomic_write_text, parse_document, read_document, render_document, write_document
from jot_core.models import AppConfig, CommandResult
from jot_core.output import (
    _progress_bar,
    _progress_color,
    _style,
    configure_output,
    emit_result,
)
from jot_core.progress import (
    adjust_note_progress,
    format_progress_summary,
    format_progress_tracks_summary,
    parse_progress_pair,
    parse_progress_value,
    set_note_progress,
)
from jot_core.services import JotService
from jot_core.taskwarrior import TaskwarriorClient
from jot_tui.app import (
    NEW_PROGRESS_TRACK,
    initial_progress_track,
    resolve_progress_track,
    tui_actions_block,
    tui_context_action_entries,
    tui_default_time_range,
    tui_next_actions,
    tui_note_empty_guidance,
    tui_time_input_value,
)
from jot_tui.palette import PaletteEntry, filter_palette_entries


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

        if args and args[-1] == 'done':
            task_uuid = args[-2]
            state.setdefault('completed_tasks', []).append(task_uuid)
            state.setdefault('completed_task_args', []).append(args)
            for value in state.values():
                if not isinstance(value, list):
                    continue
                for task in value:
                    if isinstance(task, dict) and task.get('uuid') == task_uuid:
                        task['status'] = 'completed'
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
                if arg.startswith('status:') or arg.startswith('limit:'):
                    export_key = 'tasks'
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

    def test_atomic_write_preserves_original_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jot-atomic-") as tempdir:
            path = Path(tempdir) / "note.md"
            path.write_text("original\n", encoding="utf-8")
            with mock.patch("jot_core.frontmatter.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    atomic_write_text(path, "replacement\n")
            self.assertEqual(path.read_text(encoding="utf-8"), "original\n")
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_file_lock_falls_back_when_flock_is_unavailable(self) -> None:
        import errno

        with tempfile.TemporaryDirectory(prefix="jot-lock-fallback-") as tempdir:
            path = Path(tempdir) / "note.md"
            write_document(path, OrderedDict([("kind", "task-note")]), "# Note\n")
            with mock.patch("jot_core.frontmatter.fcntl.flock", side_effect=OSError(errno.ENOSYS, "Function not implemented")):
                set_note_progress(path, Decimal("1"), Decimal("2"))

            metadata, body = read_document(path)
            self.assertEqual(metadata["progress_current"], "1")
            self.assertIn("## Progress", body)
            self.assertFalse((path.parent / ".note.md.lock.d").exists())

    def test_fallback_lock_recovers_a_dead_owner(self) -> None:
        import errno

        with tempfile.TemporaryDirectory(prefix="jot-stale-lock-") as tempdir:
            path = Path(tempdir) / "note.md"
            write_document(path, OrderedDict([("kind", "task-note")]), "# Note\n")
            lock_dir = path.parent / ".note.md.lock.d"
            lock_dir.mkdir()
            (lock_dir / "owner.json").write_text(
                json.dumps({"pid": 999999, "created": 0}),
                encoding="utf-8",
            )
            with mock.patch(
                "jot_core.frontmatter.fcntl.flock",
                side_effect=OSError(errno.ENOSYS, "Function not implemented"),
            ), mock.patch("jot_core.frontmatter._process_exists", return_value=False):
                set_note_progress(path, Decimal("1"), Decimal("2"))

            metadata, _body = read_document(path)
            self.assertEqual(metadata["progress_current"], "1")
            self.assertFalse(lock_dir.exists())

    def test_fallback_lock_times_out_for_an_active_owner(self) -> None:
        import errno

        with tempfile.TemporaryDirectory(prefix="jot-active-lock-") as tempdir:
            path = Path(tempdir) / "note.md"
            write_document(path, OrderedDict([("kind", "task-note")]), "# Note\n")
            lock_dir = path.parent / ".note.md.lock.d"
            lock_dir.mkdir()
            (lock_dir / "owner.json").write_text(
                json.dumps({"pid": os.getpid(), "created": 0}),
                encoding="utf-8",
            )
            with mock.patch(
                "jot_core.frontmatter.fcntl.flock",
                side_effect=OSError(errno.ENOSYS, "Function not implemented"),
            ), mock.patch.dict(os.environ, {"JOT_LOCK_TIMEOUT": "0.05"}):
                with self.assertRaisesRegex(RuntimeError, "timed out waiting for file lock"):
                    set_note_progress(path, Decimal("1"), Decimal("2"))

            (lock_dir / "owner.json").unlink()
            lock_dir.rmdir()

    def test_concurrent_progress_adjustments_are_not_lost(self) -> None:
        with tempfile.TemporaryDirectory(prefix="jot-lock-") as tempdir:
            path = Path(tempdir) / "note.md"
            write_document(path, OrderedDict([("kind", "task-note")]), "# Note\n")
            set_note_progress(path, Decimal("0"), Decimal("100"))

            with ThreadPoolExecutor(max_workers=8) as executor:
                results = list(
                    executor.map(
                        lambda _item: adjust_note_progress(path, Decimal("1")),
                        range(40),
                    )
                )

            metadata, body = read_document(path)
            self.assertEqual(metadata["progress_current"], "40")
            self.assertEqual(len(results), 40)
            self.assertEqual(body.count("change +1"), 40)
            self.assertTrue((path.parent / f".{path.name}.lock").exists())


class EditorDiffTests(unittest.TestCase):
    def test_note_diff_returns_unified_diff_for_changed_note(self) -> None:
        path = Path("/tmp/example-note.md")
        diff = note_diff("one\nold\n", "one\nnew\n", path=path)
        self.assertIn("--- /tmp/example-note.md (before)", diff)
        self.assertIn("+++ /tmp/example-note.md (after)", diff)
        self.assertIn("-old", diff)
        self.assertIn("+new", diff)

    def test_note_diff_is_empty_for_unchanged_note(self) -> None:
        self.assertEqual(note_diff("same\n", "same\n", path=Path("/tmp/example-note.md")), "")

    def test_colorize_diff_can_be_forced_or_disabled(self) -> None:
        diff = "--- before\n+++ after\n@@ -1 +1 @@\n-old\n+new\n"
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertIn("\033[31m-old\033[0m", colorize_diff(diff, color_mode="always"))
            self.assertIn("\033[32m+new\033[0m", colorize_diff(diff, color_mode="always"))
        self.assertEqual(colorize_diff(diff, color_mode="never"), diff)


class PaletteTests(unittest.TestCase):
    def test_tui_time_inputs_are_local_and_keep_the_same_instant(self) -> None:
        converted = tui_time_input_value("2026-07-14T09:30:00Z")
        self.assertEqual(
            datetime.fromisoformat(converted).astimezone(timezone.utc),
            datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc),
        )
        started, stopped = tui_default_time_range(datetime(2026, 7, 14, 10, 0, tzinfo=timezone.utc))
        self.assertEqual(
            datetime.fromisoformat(stopped) - datetime.fromisoformat(started),
            timedelta(hours=1),
        )

    def test_filter_palette_entries_prefers_relevant_matches(self) -> None:
        entries = [
            PaletteEntry("refresh-all", "Refresh all", "Reload everything"),
            PaletteEntry("browse-projects", "Browse projects", "Open the project browser"),
            PaletteEntry("edit-note", "Edit active note", "Open the active note", enabled=False),
        ]
        filtered = filter_palette_entries(entries, "project")
        self.assertEqual([item.id for item in filtered], ["browse-projects"])

    def test_progress_track_selector_infers_only_safe_choices(self) -> None:
        self.assertEqual(initial_progress_track(["default", "chest"]), "default")
        self.assertEqual(initial_progress_track(["chest"]), "chest")
        self.assertIsNone(initial_progress_track(["chest", "legs"]))
        self.assertIsNone(initial_progress_track([]))

    def test_new_progress_track_requires_set_and_a_name(self) -> None:
        self.assertEqual(
            resolve_progress_track(NEW_PROGRESS_TRACK, " upper body ", "set"),
            "upper body",
        )
        with self.assertRaisesRegex(RuntimeError, "only be used with the set"):
            resolve_progress_track(NEW_PROGRESS_TRACK, "chest", "add")
        with self.assertRaisesRegex(RuntimeError, "name is required"):
            resolve_progress_track(NEW_PROGRESS_TRACK, "", "set")
        with self.assertRaisesRegex(RuntimeError, "Select a progress track"):
            resolve_progress_track(None, "", "add")

    def test_tui_guidance_helpers_explain_empty_notes_and_next_actions(self) -> None:
        empty = tui_note_empty_guidance("Task Note", "/tmp/task.md")
        self.assertIn("No note text yet", empty)
        self.assertIn("Press e", empty)
        self.assertIn("/tmp/task.md", empty)

        actions = tui_next_actions(
            scope="task",
            has_note=True,
            has_resources=True,
            has_progress=False,
            has_chain=True,
            has_project=True,
        )
        self.assertIn("a add to task heading", actions)
        self.assertIn("c add to chain heading", actions)
        self.assertIn("p open project workspace", actions)
        self.assertIn("o open resource", actions)
        self.assertIn("g start progress tracking", actions)
        block = tui_actions_block(actions)
        self.assertTrue(block.startswith("Next actions:"))
        self.assertIn("- e edit/open note", block)

        entries = tui_context_action_entries(
            scope="task",
            has_note=True,
            has_resources=True,
            has_progress=True,
            has_chain=True,
            has_project=True,
        )
        ids = [entry.id for entry in entries]
        self.assertIn("edit-note", ids)
        self.assertIn("add-task", ids)
        self.assertIn("add-chain", ids)
        self.assertIn("open-resource", ids)
        self.assertIn("detach-resource", ids)
        self.assertIn("update-progress", ids)


class CommandHelpTests(unittest.TestCase):
    def test_catalog_is_derived_from_parser_commands(self) -> None:
        catalog = build_command_catalog(build_parser())
        by_name = {item.name: item for item in catalog}

        self.assertIn("note", by_name)
        self.assertIn("attach", by_name)
        self.assertIn("report recent", by_name)
        self.assertEqual(by_name["attach"].category, "Resources")
        self.assertIn("jot attach", by_name["attach"].usage)
        self.assertIn("file path or URL", by_name["attach"].description)
        self.assertEqual(
            by_name["attach"].example,
            "jot attach task 42 ~/documents/invoice.pdf --label invoice",
        )
        self.assertTrue(any("--label" in item for item in by_name["attach"].arguments))

    def test_catalog_contains_unique_leaf_commands(self) -> None:
        catalog = build_command_catalog(build_parser())
        names = [item.name for item in catalog]
        self.assertEqual(len(names), len(set(names)))
        self.assertNotIn("report", names)
        missing_examples = [item.name for item in catalog if not item.example]
        self.assertEqual(missing_examples, [])


class CommandPrefixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = build_parser()

    def test_expands_unique_top_level_prefix(self) -> None:
        self.assertEqual(
            expand_command_prefixes(self.parser, ["proj-r", "Finances.Expense"]),
            ["project-report", "Finances.Expense"],
        )

    def test_exact_command_takes_precedence_over_longer_matches(self) -> None:
        self.assertEqual(
            expand_command_prefixes(self.parser, ["project", "Finances"]),
            ["project", "Finances"],
        )

    def test_expands_nested_command_prefixes(self) -> None:
        self.assertEqual(
            expand_command_prefixes(self.parser, ["report", "rec", "--limit", "5"]),
            ["report", "recent", "--limit", "5"],
        )
        self.assertEqual(
            expand_command_prefixes(self.parser, ["progress", "task", "42", "sub", "5"]),
            ["progress", "task", "42", "subtract", "5"],
        )

    def test_expands_positional_choice_prefixes(self) -> None:
        self.assertEqual(
            expand_command_prefixes(self.parser, ["prog", "ch", "53", "sh"]),
            ["progress", "chain", "53", "show"],
        )
        self.assertEqual(
            expand_command_prefixes(self.parser, ["prog", "t", "53", "sh"]),
            ["progress", "task", "53", "show"],
        )
        self.assertEqual(
            expand_command_prefixes(self.parser, ["head", "pr", "Finances"]),
            ["headings", "project", "Finances"],
        )

    def test_preserves_global_options_before_command(self) -> None:
        self.assertEqual(
            expand_command_prefixes(self.parser, ["--json", "sta"]),
            ["--json", "stats"],
        )

    def test_rejects_ambiguous_prefix(self) -> None:
        with self.assertRaises(AmbiguousCommandPrefix) as raised:
            expand_command_prefixes(self.parser, ["pro"])
        self.assertIn("progress", raised.exception.matches)
        self.assertIn("project", raised.exception.matches)


class ProgressValueTests(unittest.TestCase):
    def test_progress_values_accept_decimals_and_reject_invalid_values(self) -> None:
        self.assertEqual(str(parse_progress_value("-1.25")), "-1.25")
        self.assertEqual(tuple(str(value) for value in parse_progress_pair("1.5/3")), ("1.5", "3"))
        for value in ("", "abc", "NaN", "Infinity"):
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError):
                    parse_progress_value(value)
        with self.assertRaises(RuntimeError):
            parse_progress_pair("1")

    def test_progress_summary_is_compact_and_optional(self) -> None:
        progress = {
            "current": "120",
            "target": "350",
            "unit": "pages",
            "percentage": "34.29",
        }
        self.assertEqual(format_progress_summary(progress), "120/350 pages (34.29%)")
        self.assertEqual(format_progress_summary(progress, prefix="T"), "T 120/350 pages (34.29%)")
        self.assertEqual(format_progress_summary(None), "")
        tracks = [
            {**progress, "track": "chest"},
            {**progress, "track": "legs", "current": "60", "percentage": "17.14"},
            {**progress, "track": "back"},
        ]
        self.assertEqual(
            format_progress_tracks_summary(tracks),
            "chest: 120/350 pages (34.29%) | legs: 60/350 pages (17.14%) | +1 more",
        )

    def test_progress_bar_handles_partial_and_out_of_range_values(self) -> None:
        self.assertEqual(_progress_bar("50", width=8), "【████░░░░】")
        self.assertEqual(_progress_bar("12.5", width=8), "【█░░░░░░░】")
        self.assertEqual(_progress_bar("150", width=4), "【████】")
        self.assertEqual(_progress_bar("-5", width=4), "【░░░░】")

    def test_progress_colors_follow_red_to_bright_green_scale(self) -> None:
        expected = (
            ("0", "red"),
            ("19.99", "red"),
            ("20", "orange"),
            ("40", "yellow"),
            ("60", "yellow_green"),
            ("80", "bright_green"),
            ("99.99", "bright_green"),
            ("100", "green"),
        )
        for percentage, color in expected:
            with self.subTest(percentage=percentage):
                self.assertEqual(_progress_color(Decimal(percentage)), color)

    def test_final_green_bands_use_distinct_explicit_rgb_colors(self) -> None:
        with mock.patch("jot_core.output._use_color", return_value=True):
            near_complete = _style("bar", color="bright_green")
            complete = _style("bar", color="green")
        self.assertIn("\033[38;2;52;190;90m", near_complete)
        self.assertIn("\033[38;2;0;255;70m", complete)
        self.assertNotEqual(near_complete, complete)


class OutputColorTests(unittest.TestCase):
    def tearDown(self) -> None:
        configure_output(color_mode="auto")

    def _emit(self, result: CommandResult, *, json_mode: bool = False) -> str:
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            emit_result(result, json_mode=json_mode)
        return output.getvalue()

    def test_human_output_uses_semantic_colors_when_forced(self) -> None:
        configure_output(color_mode="always")
        result = CommandResult(
            command="show",
            payload={
                "task": {
                    "short_uuid": "2d6d7d7d",
                    "description": "Read book",
                    "project": "reading",
                },
                "notes": {},
            },
        )

        with mock.patch.dict(os.environ):
            os.environ.pop("NO_COLOR", None)
            output = self._emit(result)

        self.assertIn("\033[1;38;5;45mTask 2d6d7d7d\033[0m", output)
        self.assertIn("\033[1;38;5;109mdescription\033[0m", output)
        self.assertIn("\033[38;5;220mreading\033[0m", output)

    def test_color_can_be_disabled_and_no_color_takes_precedence(self) -> None:
        result = CommandResult(command="paths", payload={"root_dir": "/tmp/jot"})
        configure_output(color_mode="never")
        self.assertNotIn("\033[", self._emit(result))

        configure_output(color_mode="always")
        with mock.patch.dict(os.environ, {"NO_COLOR": "1"}):
            self.assertNotIn("\033[", self._emit(result))

    def test_machine_readable_output_never_contains_color(self) -> None:
        configure_output(color_mode="always")
        payload = {"task": {"short_uuid": "2d6d7d7d"}}
        json_output = self._emit(CommandResult(command="show", payload=payload), json_mode=True)
        self.assertEqual(json.loads(json_output), payload)
        self.assertNotIn("\033[", json_output)

        csv_output = self._emit(
            CommandResult(
                command="timelog-report-csv",
                payload={"entries": [{"key": "a1b2", "minutes": 30}]},
            )
        )
        self.assertNotIn("\033[", csv_output)
        self.assertEqual(list(csv.DictReader(csv_output.splitlines()))[0]["key"], "a1b2")

    def test_color_styling_does_not_change_human_readable_text(self) -> None:
        result = CommandResult(
            command="timelog-report",
            payload={
                "period": "week",
                "total": "1h 30m",
                "entry_count": 2,
                "filters": {"project": "reading"},
                "by_day": [
                    {
                        "name": "2026-07-14",
                        "duration": "1h 30m",
                        "entry_count": 2,
                    }
                ],
                "by_project": [],
                "by_chain": [],
                "by_task": [],
            },
        )
        configure_output(color_mode="never")
        plain = self._emit(result)

        configure_output(color_mode="always")
        with mock.patch.dict(os.environ):
            os.environ.pop("NO_COLOR", None)
            colored = self._emit(result)

        self.assertEqual(re.sub(r"\033\[[0-9;]*m", "", colored), plain)

    def test_post_save_actions_use_stderr_semantic_colors(self) -> None:
        class TtyInput(io.StringIO):
            def isatty(self) -> bool:
                return True

        taskwarrior = mock.Mock()
        ctx = SimpleNamespace(
            config=SimpleNamespace(editor_post_save_actions=True),
            taskwarrior=taskwarrior,
        )
        task = SimpleNamespace(
            task_uuid="2d6d7d7d-1111-2222-3333-444444444444",
            task_short_uuid="2d6d7d7d",
            description="Read book",
        )
        stdin = TtyInput("c\n")
        stderr = io.StringIO()
        configure_output(color_mode="always")

        with mock.patch.dict(os.environ):
            os.environ.pop("NO_COLOR", None)
            with mock.patch("sys.stdin", stdin), mock.patch("sys.stderr", stderr):
                result = _offer_post_save_task_action(ctx, task)

        output = stderr.getvalue()
        self.assertIn("\033[1;38;5;45mPost-save actions\033[0m", output)
        self.assertIn("\033[1;38;5;220m2d6d7d7d\033[0m", output)
        self.assertIn("\033[1;38;5;42mc\033[0m", output)
        self.assertEqual(result["action"], "complete-task")
        taskwarrior.complete_task.assert_called_once_with(task.task_uuid)


class ServiceProgressRowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(prefix="jot-service-test-")
        self.addCleanup(self.tempdir.cleanup)
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
            editor_diff_color="auto",
            editor_post_save_actions=True,
            color_mode="auto",
            default_format="text",
            nautical_enabled=True,
            timewarrior_enabled=False,
        )
        for path in (
            self.config.tasks_dir,
            self.config.chains_dir,
            self.config.projects_dir,
            self.config.templates_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def test_task_and_project_rows_include_progress_summaries(self) -> None:
        task_path = self.config.tasks_dir / "2d6d7d7d--read-book.md"
        chain_path = self.config.chains_dir / "a4bf5egh--reading-cycle.md"
        project_path = self.config.projects_dir / "reading" / "index.md"
        write_document(
            task_path,
            OrderedDict(
                [
                    ("kind", "task-note"),
                    ("task_short_uuid", "2d6d7d7d"),
                    ("progress_current", "120"),
                    ("progress_target", "350"),
                    ("progress_unit", "pages"),
                    ("progress_updated", "2026-06-12T10:00:00Z"),
                ]
            ),
            "# Read book",
        )
        write_document(
            chain_path,
            OrderedDict(
                [
                    ("kind", "chain-note"),
                    ("chain_id", "a4bf5egh"),
                    ("progress_current", "3"),
                    ("progress_target", "12"),
                    ("progress_unit", "sessions"),
                    ("progress_updated", "2026-06-12T10:00:00Z"),
                ]
            ),
            "# Reading cycle",
        )
        write_document(
            project_path,
            OrderedDict(
                [
                    ("kind", "project-note"),
                    ("project", "reading"),
                    ("project_path", ["reading"]),
                    ("updated", "2026-06-12T10:00:00Z"),
                    ("progress_current", "2"),
                    ("progress_target", "10"),
                    ("progress_unit", "books"),
                    ("progress_updated", "2026-06-12T10:00:00Z"),
                ]
            ),
            "# reading",
        )

        class FakeTaskwarrior:
            def list_tasks(self, *, limit: int, status: str) -> list[dict[str, object]]:
                return [
                    {
                        "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
                        "short_uuid": "2d6d7d7d",
                        "description": "Read book",
                        "project": "reading",
                        "tags": [],
                        "chain_id": "a4bf5egh",
                        "status": "pending",
                        "due": None,
                    }
                ]

        service = JotService(config=self.config, taskwarrior=FakeTaskwarrior())  # type: ignore[arg-type]
        task_rows = service.tasks()
        self.assertEqual(
            task_rows[0]["progress"],
            "T 120/350 pages (34.29%) | C 3/12 sessions (25%)",
        )
        project_rows = service.project_tree_rows()
        self.assertEqual(project_rows[0]["progress"], "2/10 books (20%)")

    def test_timelog_report_service_returns_detailed_tui_data(self) -> None:
        record = {
            "v": 1,
            "key": "a1b2c3d4e5f60708",
            "note_kind": "task",
            "task_uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "task_short_uuid": "2d6d7d7d",
            "chain_id": "",
            "project": "reading",
            "tags": [],
            "started": "2026-07-03T09:00:00Z",
            "stopped": "2026-07-03T10:00:00Z",
            "minutes": 60,
        }
        write_document(
            self.config.tasks_dir / "2d6d7d7d--read-book.md",
            OrderedDict([("kind", "task-note"), ("task_short_uuid", "2d6d7d7d")]),
            "# Read book\n\n## Time log\n\n"
            f"- interval <!-- jot-time-log {json.dumps(record, separators=(',', ':'))} -->",
        )

        class FakeTaskwarrior:
            pass

        service = JotService(config=self.config, taskwarrior=FakeTaskwarrior())  # type: ignore[arg-type]
        report = service.timelog_report("all")
        self.assertEqual(report["total_minutes"], 60)
        self.assertEqual(report["by_project"][0]["name"], "reading")
        self.assertEqual(report["entries"][0]["key"], "a1b2c3d4e5f60708")

    def test_timelog_service_exposes_tui_mutation_lifecycle(self) -> None:
        task_json = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Read book",
            "project": "reading",
            "tags": [],
        }

        class FakeTaskwarrior:
            def resolve_task(self, task_ref: str):
                from jot_core.models import ResolvedTask, TaskRef

                return ResolvedTask(
                    ref=TaskRef(raw=task_ref),
                    task_uuid=str(task_json["uuid"]),
                    task_short_uuid="2d6d7d7d",
                    description="Read book",
                    project="reading",
                    tags=[],
                    task=task_json,
                )

        service = JotService(config=self.config, taskwarrior=FakeTaskwarrior())  # type: ignore[arg-type]
        added = service.timelog_add(
            "2d6d7d7d",
            started_at="2026-07-14T09:00:00Z",
            stopped_at="2026-07-14T10:00:00Z",
        )
        amended = service.timelog_amend(
            str(added["timelog_key"]),
            started_at="2026-07-14T09:00:00Z",
            stopped_at="2026-07-14T10:30:00Z",
        )
        deleted = service.timelog_delete(str(amended["new_timelog_key"]))
        self.assertEqual(service.timelog_report("all")["entry_count"], 0)
        self.assertEqual(service.timelog_trash()[0]["key"], deleted["timelog_key"])
        restored = service.timelog_restore("#1")
        self.assertEqual(restored["timelog_key"], deleted["timelog_key"])
        self.assertEqual(service.timelog_report("all")["total_minutes"], 90)

    def test_timelog_service_exposes_live_session_lifecycle(self) -> None:
        task_json = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Read book",
            "project": "reading",
            "tags": [],
        }

        class FakeTaskwarrior:
            def resolve_task(self, task_ref: str):
                from jot_core.models import ResolvedTask, TaskRef

                return ResolvedTask(
                    ref=TaskRef(raw=task_ref),
                    task_uuid=str(task_json["uuid"]),
                    task_short_uuid="2d6d7d7d",
                    description="Read book",
                    project="reading",
                    tags=[],
                    task=task_json,
                )

        service = JotService(config=self.config, taskwarrior=FakeTaskwarrior())  # type: ignore[arg-type]
        started = service.timelog_start("2d6d7d7d", started_at="2026-07-14T09:00:00Z")
        self.assertNotIn("already_started", started)
        self.assertEqual(service.timelog_pending()[0]["task_short_uuid"], "2d6d7d7d")
        duplicate = service.timelog_start("2d6d7d7d", started_at="2026-07-14T09:15:00Z")
        self.assertTrue(duplicate["already_started"])

        cancelled = service.timelog_cancel("2d6d7d7d")
        self.assertEqual(cancelled["task_short_uuid"], "2d6d7d7d")
        self.assertEqual(service.timelog_pending(), [])

        service.timelog_start("2d6d7d7d", started_at="2026-07-14T10:00:00Z")
        stopped = service.timelog_stop("2d6d7d7d", stopped_at="2026-07-14T10:30:00Z")
        self.assertEqual(stopped["duration_minutes"], 30)
        self.assertEqual(service.timelog_pending(), [])

        service.timelog_start("2d6d7d7d", started_at="2026-07-14T11:00:00Z")
        stopped_all = service.timelog_stop_all(stopped_at="2026-07-14T11:20:00Z")
        self.assertEqual(stopped_all["count"], 1)
        self.assertEqual(stopped_all["error_count"], 0)
        self.assertEqual(service.timelog_report("all")["total_minutes"], 50)

    def test_progress_track_names_reads_each_note_scope(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Workout",
            "project": "fitness",
            "tags": [],
            "chainID": "a4bf5egh",
        }
        task_path = self.config.tasks_dir / "2d6d7d7d--workout.md"
        chain_path = self.config.chains_dir / "a4bf5egh--workout.md"
        project_path = self.config.projects_dir / "fitness" / "index.md"
        named_tracks = (
            '[{"track":"chest","current":"3","target":"10"},'
            '{"track":"legs","current":"4","target":"10"}]'
        )
        write_document(
            task_path,
            OrderedDict(
                [
                    ("kind", "task-note"),
                    ("task_short_uuid", "2d6d7d7d"),
                    ("progress_tracks", named_tracks),
                ]
            ),
            "# Workout",
        )
        write_document(
            chain_path,
            OrderedDict(
                [
                    ("kind", "chain-note"),
                    ("chain_id", "a4bf5egh"),
                    ("progress_current", "2"),
                    ("progress_target", "5"),
                ]
            ),
            "# Workout chain",
        )
        write_document(
            project_path,
            OrderedDict(
                [
                    ("kind", "project-note"),
                    ("project", "fitness"),
                    ("progress_tracks", named_tracks),
                ]
            ),
            "# Fitness",
        )

        class FakeTaskwarrior:
            def resolve_task(self, task_ref: str):
                from jot_core.models import ResolvedTask, TaskRef

                return ResolvedTask(
                    ref=TaskRef(raw=task_ref),
                    task_uuid=str(task["uuid"]),
                    task_short_uuid="2d6d7d7d",
                    description="Workout",
                    project="fitness",
                    tags=[],
                    task=task,
                )

        service = JotService(config=self.config, taskwarrior=FakeTaskwarrior())  # type: ignore[arg-type]
        self.assertEqual(
            service.progress_track_names("task", task_ref="2d6d7d7d"),
            ["chest", "legs"],
        )
        self.assertEqual(
            service.progress_track_names("chain", task_ref="2d6d7d7d"),
            ["default"],
        )
        self.assertEqual(
            service.progress_track_names("project", project_name="fitness"),
            ["chest", "legs"],
        )

    def test_notes_service_lists_inventory_with_progress_and_resources(self) -> None:
        task_path = self.config.tasks_dir / "2d6d7d7d--workout.md"
        write_document(
            task_path,
            OrderedDict(
                [
                    ("kind", "task-note"),
                    ("task_short_uuid", "2d6d7d7d"),
                    ("description", "Workout"),
                    ("project", "fitness"),
                    ("updated", "2026-06-12T10:00:00Z"),
                    ("progress_current", "3"),
                    ("progress_target", "10"),
                    ("progress_unit", "sets"),
                ]
            ),
            "# Workout\n\n## Resources\n\n- [plan](https://example.com/plan)\n",
        )

        class FakeTaskwarrior:
            pass

        service = JotService(config=self.config, taskwarrior=FakeTaskwarrior())  # type: ignore[arg-type]
        rows = service.notes(kind="task", project="fitness")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "task-note")
        self.assertEqual(rows[0]["resources"], 1)
        self.assertEqual(rows[0]["progress"], "3/10 sets (30%)")

    def test_tui_chain_and_project_editor_paths_finalize_index_and_ops(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Workout",
            "project": "fitness",
            "tags": [],
            "chainID": "a4bf5egh",
        }

        class FakeTaskwarrior:
            def resolve_task(self, task_ref: str):
                from jot_core.models import ResolvedTask, TaskRef

                return ResolvedTask(
                    ref=TaskRef(raw=task_ref),
                    task_uuid=str(task["uuid"]),
                    task_short_uuid="2d6d7d7d",
                    description="Workout",
                    project="fitness",
                    tags=[],
                    task=task,
                )

        service = JotService(config=self.config, taskwarrior=FakeTaskwarrior())  # type: ignore[arg-type]

        chain_path = Path(service.open_chain_note_in_editor("2d6d7d7d"))
        project_path = Path(service.open_project_note_in_editor("fitness"))

        index_data = json.loads((self.config.root_dir / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index_data["chains"]["a4bf5egh"]["note_path"], str(chain_path.relative_to(self.config.root_dir)))
        self.assertEqual(index_data["projects"]["fitness"]["note_path"], str(project_path.relative_to(self.config.root_dir)))
        chain_metadata, _chain_body = read_document(chain_path)
        project_metadata, _project_body = read_document(project_path)
        self.assertIn("updated", chain_metadata)
        self.assertIn("updated", project_metadata)

        ops = [
            json.loads(line)
            for line in (self.config.root_dir / "ops.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual([item["op"] for item in ops], ["chain_note_edit", "project_note_edit"])
        self.assertEqual(ops[0]["chain_id"], "a4bf5egh")
        self.assertEqual(ops[1]["project"], "fitness")


class CliIntegrationTests(JotCliTestCase):
    def test_timelog_ingest_writes_chain_note_for_chain_task_stop(self) -> None:
        task_uuid = "2d6d7d7d-1111-2222-3333-444444444444"
        old = {
            "uuid": task_uuid,
            "description": "Read chapter",
            "project": "reading",
            "tags": ["book"],
            "chainID": "2d6d7d7d",
            "start": "20260703T060000Z",
        }
        new = {
            "uuid": task_uuid,
            "description": "Read chapter",
            "project": "reading",
            "tags": ["book"],
            "chainID": "2d6d7d7d",
        }

        result = self.run_jot(
            "--json",
            "timelog",
            "ingest",
            "--stopped-at",
            "20260703T064500Z",
            input_text=json.dumps(old) + "\n" + json.dumps(new) + "\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["written"])
        self.assertEqual(payload["note_kind"], "chain")
        self.assertEqual(payload["duration_minutes"], 45)
        note_path = Path(payload["path"])
        note_text = note_path.read_text(encoding="utf-8")
        self.assertIn("## Time log", note_text)
        self.assertIn("45m, ", note_text)
        self.assertRegex(note_text, r"45m, \d{2}:\d{2}-\d{2}:\d{2} [^;]+")
        self.assertIn("reading", note_text)
        self.assertIn("#book", note_text)
        self.assertIn("timelog:", note_text)
        self.assertIn("jot-time-log", note_text)
        self.assertNotIn("uuid 2d6d7d7d-1111-2222-3333-444444444444", note_text)
        self.assertNotIn("task 2d6d7d7d", note_text)

        replay = self.run_jot(
            "--json",
            "timelog",
            "ingest",
            "--stopped-at",
            "20260703T064500Z",
            input_text=json.dumps(old) + "\n" + json.dumps(new) + "\n",
        )

        self.assertEqual(replay.returncode, 0, replay.stderr)
        replay_payload = json.loads(replay.stdout)
        self.assertFalse(replay_payload["written"])
        self.assertTrue(replay_payload["duplicate"])
        self.assertEqual(replay_payload["reason"], "duplicate time log")
        replayed_note_text = note_path.read_text(encoding="utf-8")
        self.assertEqual(replayed_note_text.count("45m, "), 1)
        self.assertEqual(replayed_note_text.count("timelog:"), 1)

    def test_timelog_ingest_skips_non_stop_changes(self) -> None:
        old = {"uuid": "2d6d7d7d-1111-2222-3333-444444444444", "description": "Read"}
        new = {**old, "start": "20260703T060000Z"}

        result = self.run_jot(
            "--json",
            "timelog",
            "ingest",
            input_text=json.dumps(old) + "\n" + json.dumps(new) + "\n",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["written"])
        self.assertEqual(payload["reason"], "not a task stop")

    def test_jot_timelog_hook_preserves_task_json_stdout(self) -> None:
        task_uuid = "2d6d7d7d-1111-2222-3333-444444444444"
        old = {
            "uuid": task_uuid,
            "description": "Read chapter",
            "project": "reading",
            "chainID": "2d6d7d7d",
            "start": "20260703T060000Z",
        }
        new = {
            "uuid": task_uuid,
            "description": "Read chapter",
            "project": "reading",
            "chainID": "2d6d7d7d",
        }
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["PATH"] = f"{PROJECT_ROOT}:{env['PATH']}"
        env["EDITOR"] = "true"

        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "hooks" / "on-modify_jot_timelog.py")],
            cwd=PROJECT_ROOT,
            env=env,
            input=json.dumps(old) + "\n" + json.dumps(new) + "\n",
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), new)

    def test_jot_timelog_hook_fails_open_when_jot_cannot_start(self) -> None:
        old = {"uuid": "2d6d7d7d-1111-2222-3333-444444444444", "start": "20260703T060000Z"}
        new = {"uuid": old["uuid"], "description": "Read chapter"}
        env = os.environ.copy()
        env["JOT_BIN"] = str(self.root / "missing-jot")

        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "hooks" / "on-modify_jot_timelog.py")],
            cwd=PROJECT_ROOT,
            env=env,
            input=json.dumps(old) + "\n" + json.dumps(new) + "\n",
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), new)
        self.assertIn("could not run jot", result.stderr)

    def test_jot_timelog_hook_fails_open_on_timeout(self) -> None:
        old = {"uuid": "2d6d7d7d-1111-2222-3333-444444444444", "start": "20260703T060000Z"}
        new = {"uuid": old["uuid"], "description": "Read chapter"}
        slow_jot = self.root / "slow-jot"
        slow_jot.write_text(
            "#!/usr/bin/env python3\nimport time\ntime.sleep(1)\n",
            encoding="utf-8",
        )
        slow_jot.chmod(0o755)
        env = os.environ.copy()
        env["JOT_BIN"] = str(slow_jot)
        env["JOT_TIMELOG_TIMEOUT"] = "0.05"

        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "hooks" / "on-modify_jot_timelog.py")],
            cwd=PROJECT_ROOT,
            env=env,
            input=json.dumps(old) + "\n" + json.dumps(new) + "\n",
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), new)
        self.assertIn("ingest timed out", result.stderr)

    def test_timewarrior_metadata_resolves_task_chain_and_project_precedence(self) -> None:
        task_uuid = "2d6d7d7d-1111-2222-3333-444444444444"
        task = {
            "uuid": task_uuid,
            "description": "Read chapter",
            "project": "personal.reading.books",
            "tags": ["book"],
            "chainID": "2d6d7d7d",
            "status": "pending",
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        project_set = self.run_jot(
            "--json", "timew", "set", "project", "personal.reading", "learning", "quiet"
        )
        self.assertEqual(project_set.returncode, 0, project_set.stderr)
        project_payload = json.loads(project_set.stdout)
        self.assertEqual(project_payload["tags"], ["learning", "quiet"])

        project_show = self.run_jot("--json", "timew", "show", "1")
        self.assertEqual(project_show.returncode, 0, project_show.stderr)
        project_resolution = json.loads(project_show.stdout)
        self.assertEqual(project_resolution["tags"], ["learning", "quiet"])
        self.assertEqual(project_resolution["source"]["scope"], "project")
        self.assertEqual(project_resolution["source"]["reference"], "personal.reading")

        chain_set = self.run_jot("--json", "timew", "se", "ch", "1", "workout")
        self.assertEqual(chain_set.returncode, 0, chain_set.stderr)
        chain_show = json.loads(self.run_jot("--json", "timew", "sh", "1").stdout)
        self.assertEqual(chain_show["tags"], ["workout"])
        self.assertEqual(chain_show["source"]["scope"], "chain")

        task_set = self.run_jot("--json", "timew", "set", "task", "1", "focused-reading")
        self.assertEqual(task_set.returncode, 0, task_set.stderr)
        task_show = json.loads(self.run_jot("--json", "timew", "show", "1").stdout)
        self.assertEqual(task_show["tags"], ["focused-reading"])
        self.assertEqual(task_show["source"]["scope"], "task")

        cleared = self.run_jot("--json", "timew", "clear", "task", "1")
        self.assertEqual(cleared.returncode, 0, cleared.stderr)
        cleared_show = json.loads(self.run_jot("--json", "timew", "show", "1").stdout)
        self.assertEqual(cleared_show["tags"], [])
        self.assertEqual(cleared_show["source"]["scope"], "task")
        self.assertTrue(cleared_show["explicitly_disabled"])

        inherited = self.run_jot("--json", "timew", "inherit", "task", "1")
        self.assertEqual(inherited.returncode, 0, inherited.stderr)
        inherited_show = json.loads(self.run_jot("--json", "timew", "show", "1").stdout)
        self.assertEqual(inherited_show["tags"], ["workout"])
        self.assertEqual(inherited_show["source"]["scope"], "chain")

    def test_timewarrior_chain_metadata_rejects_non_chain_task(self) -> None:
        task = {
            "uuid": "986e9d97-1111-2222-3333-444444444444",
            "description": "One-off task",
            "project": "personal",
            "tags": [],
            "status": "pending",
        }
        self.write_state({"version": "2.6.2", "single": [task], "2": [task]})

        result = self.run_jot("timew", "set", "chain", "2", "focus")

        self.assertEqual(result.returncode, 1)
        self.assertIn("not part of a Nautical chain", result.stderr)

    def test_timelog_start_stop_records_session_and_writes_note(self) -> None:
        task_uuid = "2d6d7d7d-1111-2222-3333-444444444444"
        task = {
            "uuid": task_uuid,
            "description": "Read chapter",
            "project": "reading",
            "tags": ["book"],
            "chainID": "2d6d7d7d",
            "status": "pending",
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        started = self.run_jot("--json", "timelog", "start", "1", "--at", "20260703T060000Z")
        self.assertEqual(started.returncode, 0, started.stderr)
        start_payload = json.loads(started.stdout)
        self.assertEqual(start_payload["started"], "2026-07-03T06:00:00Z")

        duplicate_start = self.run_jot("--json", "timelog", "start", "1", "--at", "20260703T070000Z")
        self.assertEqual(duplicate_start.returncode, 0, duplicate_start.stderr)
        duplicate_payload = json.loads(duplicate_start.stdout)
        self.assertTrue(duplicate_payload["already_started"])
        self.assertEqual(duplicate_payload["started"], "2026-07-03T06:00:00Z")

        pending = self.run_jot("--json", "timelog", "pending")
        self.assertEqual(pending.returncode, 0, pending.stderr)
        pending_payload = json.loads(pending.stdout)
        self.assertEqual(len(pending_payload["sessions"]), 1)
        self.assertIn("elapsed", pending_payload["sessions"][0])
        self.assertIn("elapsed_minutes", pending_payload["sessions"][0])

        stopped = self.run_jot("--json", "timelog", "stop", "1", "--at", "20260703T064500Z")
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        stop_payload = json.loads(stopped.stdout)
        self.assertTrue(stop_payload["written"])
        self.assertTrue(stop_payload["session_cleared"])
        self.assertEqual(stop_payload["duration_minutes"], 45)

        note_text = Path(stop_payload["path"]).read_text(encoding="utf-8")
        self.assertIn("45m, ", note_text)
        self.assertIn("timelog:", note_text)

        second_started = self.run_jot("--json", "timelog", "start", "1", "--at", "20260703T070000Z")
        self.assertEqual(second_started.returncode, 0, second_started.stderr)
        second_stopped = self.run_jot("--json", "timelog", "stop", "1", "--at", "20260703T073000Z")
        self.assertEqual(second_stopped.returncode, 0, second_stopped.stderr)
        updated_note_text = Path(stop_payload["path"]).read_text(encoding="utf-8")
        timelog_lines = [line for line in updated_note_text.splitlines() if "timelog:" in line]
        self.assertEqual(len(timelog_lines), 2)
        self.assertIn("\n".join(timelog_lines), updated_note_text)

        pending_after = self.run_jot("--json", "timelog", "pending")
        self.assertEqual(json.loads(pending_after.stdout)["sessions"], [])

    def test_timelog_stop_all_closes_all_pending_sessions(self) -> None:
        first_uuid = "2d6d7d7d-1111-2222-3333-444444444444"
        second_uuid = "986e9d97-1111-2222-3333-444444444444"
        first = {
            "uuid": first_uuid,
            "description": "Read chapter",
            "project": "reading",
            "tags": ["book"],
            "chainID": "2d6d7d7d",
            "status": "pending",
        }
        second = {
            "uuid": second_uuid,
            "description": "Draft notes",
            "project": "writing",
            "tags": [],
            "status": "pending",
        }
        self.write_state(
            {
                "version": "2.6.2",
                "single": [first],
                "1": [first],
                "2": [second],
                f"uuid:{first_uuid}": [first],
                f"uuid:{second_uuid}": [second],
            }
        )

        self.assertEqual(self.run_jot("timelog", "start", "1", "--at", "20260703T060000Z").returncode, 0)
        self.assertEqual(self.run_jot("timelog", "start", "2", "--at", "20260703T061500Z").returncode, 0)

        stopped = self.run_jot("--json", "timelog", "stop", "--all", "--at", "20260703T070000Z")

        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        payload = json.loads(stopped.stdout)
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["error_count"], 0)
        durations = sorted(item["duration_minutes"] for item in payload["items"])
        self.assertEqual(durations, [45, 60])
        self.assertTrue(all(item["session_cleared"] for item in payload["items"]))
        pending = self.run_jot("--json", "timelog", "pending")
        self.assertEqual(json.loads(pending.stdout)["sessions"], [])

    def test_timelog_report_summarizes_structured_entries(self) -> None:
        first_uuid = "2d6d7d7d-1111-2222-3333-444444444444"
        second_uuid = "986e9d97-1111-2222-3333-444444444444"
        first = {
            "uuid": first_uuid,
            "description": "Read chapter",
            "project": "reading",
            "tags": ["book"],
            "chainID": "2d6d7d7d",
            "status": "pending",
        }
        second = {
            "uuid": second_uuid,
            "description": "Draft notes",
            "project": "writing",
            "tags": [],
            "status": "pending",
        }
        self.write_state({"version": "2.6.2", "single": [first], "1": [first], "2": [second]})

        self.assertEqual(self.run_jot("timelog", "start", "1", "--at", "20260703T060000Z").returncode, 0)
        self.assertEqual(self.run_jot("timelog", "stop", "1", "--at", "20260703T064500Z").returncode, 0)
        self.assertEqual(self.run_jot("timelog", "start", "2", "--at", "20260703T070000Z").returncode, 0)
        self.assertEqual(self.run_jot("timelog", "stop", "2", "--at", "20260703T080000Z").returncode, 0)

        report = self.run_jot("--json", "timelog", "report")
        self.assertEqual(report.returncode, 0, report.stderr)
        payload = json.loads(report.stdout)
        self.assertEqual(payload["total_minutes"], 105)
        self.assertEqual(payload["entry_count"], 2)
        self.assertFalse(payload["details"])
        self.assertEqual(payload["entries"], [])
        self.assertEqual({item["name"]: item["minutes"] for item in payload["by_project"]}, {"writing": 60.0, "reading": 45.0})
        self.assertEqual({item["name"]: item["minutes"] for item in payload["by_chain"]}, {"(no chain)": 60.0, "2d6d7d7d": 45.0})
        self.assertEqual(payload["by_day"][0]["name"], "2026-07-03")
        self.assertEqual(payload["by_day"][0]["minutes"], 105)

        filtered = self.run_jot("--json", "timelog", "report", "all", "--project", "reading")
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        filtered_payload = json.loads(filtered.stdout)
        self.assertEqual(filtered_payload["total_minutes"], 45)
        self.assertEqual(filtered_payload["entry_count"], 1)

        detailed = self.run_jot("--json", "timelog", "report", "--details")
        self.assertEqual(detailed.returncode, 0, detailed.stderr)
        detailed_payload = json.loads(detailed.stdout)
        self.assertTrue(detailed_payload["details"])
        self.assertEqual(len(detailed_payload["entries"]), 2)
        self.assertIn("display_range", detailed_payload["entries"][0])
        self.assertIn("duration", detailed_payload["entries"][0])

        human = self.run_jot("timelog", "report", "--details")
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertIn("Timelog report: all", human.stdout)
        self.assertIn("By day", human.stdout)
        self.assertIn("By project", human.stdout)
        self.assertIn("Details", human.stdout)
        self.assertIn("reading", human.stdout)

    def test_timelog_report_clips_and_splits_cross_midnight_intervals(self) -> None:
        task_uuid = "2d6d7d7d-1111-2222-3333-444444444444"
        task = {
            "uuid": task_uuid,
            "description": "Overnight maintenance",
            "project": "operations",
            "tags": [],
            "status": "pending",
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})
        env = {"TZ": "UTC"}
        started = self.run_jot_with_env(
            "timelog", "start", "1", "--at", "2026-07-03T23:30:00Z", extra_env=env
        )
        stopped = self.run_jot_with_env(
            "timelog", "stop", "1", "--at", "2026-07-04T00:30:00Z", extra_env=env
        )
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertEqual(stopped.returncode, 0, stopped.stderr)

        report = self.run_jot_with_env(
            "--json",
            "timelog",
            "report",
            "--since",
            "2026-07-03T23:45:00Z",
            "--until",
            "2026-07-04T00:15:00Z",
            "--details",
            extra_env=env,
        )
        self.assertEqual(report.returncode, 0, report.stderr)
        payload = json.loads(report.stdout)
        self.assertEqual(payload["period"], "custom")
        self.assertEqual(payload["total_minutes"], 30)
        self.assertEqual(
            {item["name"]: item["minutes"] for item in payload["by_day"]},
            {"2026-07-03": 15.0, "2026-07-04": 15.0},
        )
        self.assertTrue(payload["entries"][0]["clipped"])
        self.assertEqual(payload["entries"][0]["stored_minutes"], 60)

        csv_result = self.run_jot_with_env("timelog", "report", "--csv", extra_env=env)
        self.assertEqual(csv_result.returncode, 0, csv_result.stderr)
        rows = list(csv.DictReader(csv_result.stdout.splitlines()))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task_short_uuid"], "2d6d7d7d")
        self.assertEqual(rows[0]["minutes"], "60.0")

        invalid = self.run_jot_with_env(
            "timelog", "report", "week", "--since", "2026-07-01", extra_env=env
        )
        self.assertEqual(invalid.returncode, 1)
        self.assertIn("cannot be combined", invalid.stderr)

    def test_timelog_manual_add_amend_and_archived_delete(self) -> None:
        task_uuid = "2d6d7d7d-1111-2222-3333-444444444444"
        task = {
            "uuid": task_uuid,
            "description": "Manual work",
            "project": "operations",
            "tags": ["field"],
            "status": "pending",
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})
        env = {"TZ": "UTC"}

        added = self.run_jot_with_env(
            "--json",
            "timelog",
            "add",
            "1",
            "--from",
            "2026-07-03T09:00:00",
            "--to",
            "2026-07-03T10:00:00",
            extra_env=env,
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        added_payload = json.loads(added.stdout)
        old_key = added_payload["timelog_key"]
        self.assertEqual(added_payload["duration_minutes"], 60)

        amended = self.run_jot_with_env(
            "--json",
            "timelog",
            "amend",
            old_key[:8],
            "--to",
            "2026-07-03T10:30:00",
            extra_env=env,
        )
        self.assertEqual(amended.returncode, 0, amended.stderr)
        amended_payload = json.loads(amended.stdout)
        new_key = amended_payload["new_timelog_key"]
        self.assertNotEqual(new_key, old_key)
        self.assertEqual(amended_payload["duration_minutes"], 90)
        amend_archive = Path(amended_payload["archive_path"])
        self.assertTrue(amend_archive.exists())
        self.assertEqual(json.loads(amend_archive.read_text(encoding="utf-8"))["action"], "amend")

        report = self.run_jot_with_env("--json", "timelog", "report", "--details", extra_env=env)
        self.assertEqual(report.returncode, 0, report.stderr)
        report_payload = json.loads(report.stdout)
        self.assertEqual(report_payload["total_minutes"], 90)
        self.assertEqual(report_payload["entries"][0]["key"], new_key)

        unconfirmed = self.run_jot_with_env("timelog", "delete", new_key[:8], extra_env=env)
        self.assertEqual(unconfirmed.returncode, 1)
        self.assertIn("requires --yes", unconfirmed.stderr)

        deleted = self.run_jot_with_env(
            "--json", "timelog", "delete", new_key[:8], "--yes", extra_env=env
        )
        self.assertEqual(deleted.returncode, 0, deleted.stderr)
        deleted_payload = json.loads(deleted.stdout)
        delete_archive = Path(deleted_payload["archive_path"])
        self.assertTrue(delete_archive.exists())
        self.assertEqual(json.loads(delete_archive.read_text(encoding="utf-8"))["action"], "delete")

        empty = self.run_jot_with_env("--json", "timelog", "report", extra_env=env)
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertEqual(json.loads(empty.stdout)["entry_count"], 0)

        trash = self.run_jot_with_env("--json", "timelog", "trash", extra_env=env)
        self.assertEqual(trash.returncode, 0, trash.stderr)
        trash_items = json.loads(trash.stdout)["items"]
        self.assertEqual(len(trash_items), 1)
        self.assertEqual(trash_items[0]["key"], new_key)
        self.assertNotIn("record", trash_items[0])
        self.assertNotIn("line", trash_items[0])

        restored = self.run_jot_with_env("--json", "timelog", "restore", "#1", extra_env=env)
        self.assertEqual(restored.returncode, 0, restored.stderr)
        restored_payload = json.loads(restored.stdout)
        self.assertEqual(restored_payload["timelog_key"], new_key)
        restored_note = Path(restored_payload["path"]).read_text(encoding="utf-8")
        archived_line = json.loads(delete_archive.read_text(encoding="utf-8"))["line"]
        self.assertIn(archived_line, restored_note)

        restored_report = self.run_jot_with_env("--json", "timelog", "report", "--details", extra_env=env)
        self.assertEqual(restored_report.returncode, 0, restored_report.stderr)
        restored_report_payload = json.loads(restored_report.stdout)
        self.assertEqual(restored_report_payload["total_minutes"], 90)
        self.assertEqual(restored_report_payload["entries"][0]["key"], new_key)

        empty_trash = self.run_jot_with_env("--json", "timelog", "trash", extra_env=env)
        self.assertEqual(json.loads(empty_trash.stdout)["items"], [])
        repeated_restore = self.run_jot_with_env("timelog", "restore", new_key[:8], extra_env=env)
        self.assertEqual(repeated_restore.returncode, 1)
        self.assertIn("not found", repeated_restore.stderr)

        short_key = self.run_jot_with_env("timelog", "delete", "abc", "--yes", extra_env=env)
        self.assertEqual(short_key.returncode, 1)
        self.assertIn("at least 4", short_key.stderr)

    def test_timelog_cancel_removes_pending_session(self) -> None:
        task_uuid = "2d6d7d7d-1111-2222-3333-444444444444"
        task = {
            "uuid": task_uuid,
            "description": "Read chapter",
            "project": "reading",
            "tags": [],
            "status": "pending",
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        self.assertEqual(self.run_jot("timelog", "start", "1", "--at", "20260703T060000Z").returncode, 0)
        cancelled = self.run_jot("--json", "timelog", "cancel", "1")

        self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
        payload = json.loads(cancelled.stdout)
        self.assertEqual(payload["task_short_uuid"], "2d6d7d7d")
        pending = self.run_jot("--json", "timelog", "pending")
        self.assertEqual(json.loads(pending.stdout)["sessions"], [])

    def test_taskwarrior_completion_uses_task_uuid(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Workout",
            "project": "fitness",
            "tags": [],
            "status": "pending",
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        client = TaskwarriorClient(task_bin=str(self.bin_dir / "task"))
        client.complete_task(task["uuid"])

        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["completed_tasks"], [task["uuid"]])
        self.assertEqual(state["completed_task_args"], [["rc.verbose=nothing", "rc.confirmation=off", task["uuid"], "done"]])
        self.assertNotIn("rc.hooks=off", state["completed_task_args"][0])
        self.assertEqual(state["single"][0]["status"], "completed")

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
        self.assertEqual(result.stdout.strip(), "jot 0.7.0")

    def test_unique_command_prefix_runs_command(self) -> None:
        result = self.run_jot("sta")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Stats", result.stdout)

    def test_ambiguous_command_prefix_lists_matches(self) -> None:
        result = self.run_jot("pro")
        self.assertEqual(result.returncode, 2)
        self.assertIn("ambiguous command 'pro'", result.stderr)
        self.assertIn("progress", result.stderr)
        self.assertIn("project", result.stderr)

    def test_task_ref_shorthand_opens_task_note_without_chain(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Plain task",
            "project": "finance.audit",
            "tags": ["ann"],
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        result = self.run_jot("1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("task note", result.stdout)
        self.assertEqual(len(list((self.home / ".task" / "jot" / "tasks").glob("*.md"))), 1)
        self.assertEqual(len(list((self.home / ".task" / "jot" / "chains").glob("*.md"))), 0)
        metadata, _body = read_document(next((self.home / ".task" / "jot" / "tasks").glob("*.md")))
        self.assertEqual(metadata["schema_version"], "1")
        self.assertEqual(metadata["task_uuid"], task["uuid"])

    def test_task_ref_shorthand_opens_chain_note_when_chain_exists(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Recurring task",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        result = self.run_jot("--json", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["path"].endswith("chains/a4bf5egh--recurring-task.md"))
        self.assertEqual(len(list((self.home / ".task" / "jot" / "tasks").glob("*.md"))), 0)
        self.assertEqual(len(list((self.home / ".task" / "jot" / "chains").glob("*.md"))), 1)

    def test_nautical_disabled_keeps_auto_note_on_task(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Recurring task",
            "project": "finance.audit",
            "tags": [],
            "chainID": "a4bf5egh",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})
        config = self.root / "no-nautical.toml"
        config.write_text("[nautical]\nenabled = false\n", encoding="utf-8")

        result = self.run_jot_with_env("--json", "1", extra_env={"JOT_CONFIG": str(config)})
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertIn("/tasks/", payload["path"])

    def test_note_edit_prints_diff_to_stderr_after_save(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Plain task",
            "project": "finance.audit",
            "tags": [],
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})
        editor = self.root / "append_editor.py"
        editor.write_text(
            textwrap.dedent(
                """\
                import pathlib
                import sys

                path = pathlib.Path(sys.argv[-1])
                with path.open("a", encoding="utf-8") as handle:
                    handle.write("\\nmanual edit\\n")
                """
            ),
            encoding="utf-8",
        )

        result = self.run_jot_with_env("note", "1", extra_env={"EDITOR": f"{sys.executable} {editor}"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("task note", result.stdout)
        self.assertIn("--- ", result.stderr)
        self.assertIn("+++ ", result.stderr)
        self.assertIn("+manual edit", result.stderr)

    def test_note_edit_diff_can_be_disabled_in_config(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Plain task",
            "project": "finance.audit",
            "tags": [],
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})
        editor = self.root / "append_editor.py"
        editor.write_text(
            textwrap.dedent(
                """\
                import pathlib
                import sys

                path = pathlib.Path(sys.argv[-1])
                with path.open("a", encoding="utf-8") as handle:
                    handle.write("\\nmanual edit\\n")
                """
            ),
            encoding="utf-8",
        )
        config = self.root / "config-jot.toml"
        config.write_text("[editor]\nshow_diff_on_save = false\n", encoding="utf-8")

        result = self.run_jot_with_env(
            "note",
            "1",
            extra_env={
                "EDITOR": f"{sys.executable} {editor}",
                "JOT_CONFIG": str(config),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("--- ", result.stderr)
        self.assertNotIn("+manual edit", result.stderr)
        note_text = list((self.home / ".task" / "jot" / "tasks").glob("*.md"))[0].read_text(encoding="utf-8")
        self.assertIn("manual edit", note_text)

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
            "tui",
            "locks",
            "note_schema",
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

    def test_paths_default_to_taskdata_when_set(self) -> None:
        taskdata = self.root / "custom-taskdata"
        result = self.run_jot_with_env("--json", "paths", extra_env={"TASKDATA": str(taskdata)})
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["root_dir"], str(taskdata / "jot"))
        self.assertEqual(payload["config_path"], str(taskdata / "jot" / "config-jot.toml"))

    def test_paths_honor_jot_home_at_runtime(self) -> None:
        jot_home = self.root / "custom-jot-home"
        result = self.run_jot_with_env("--json", "paths", extra_env={"JOT_HOME": str(jot_home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["root_dir"], str(jot_home))
        self.assertEqual(payload["config_path"], str(jot_home / "config-jot.toml"))

    def test_config_default_format_can_enable_json_output(self) -> None:
        jot_home = self.root / "json-jot-home"
        jot_home.mkdir()
        (jot_home / "config-jot.toml").write_text(
            "[display]\ndefault_format = \"json\"\n",
            encoding="utf-8",
        )
        result = self.run_jot_with_env("paths", extra_env={"JOT_HOME": str(jot_home)})
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["root_dir"], str(jot_home))

    def test_doctor_reports_invalid_config_choices(self) -> None:
        config = self.root / "invalid-choice.toml"
        config.write_text("[display]\ncolor = \"sometimes\"\n", encoding="utf-8")
        result = self.run_jot_with_env("--json", "doctor", extra_env={"JOT_CONFIG": str(config)})
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        checks = {item["name"]: item for item in payload["checks"]}
        self.assertFalse(checks["config"]["ok"])
        self.assertIn("invalid display.color value", checks["config"]["detail"])

    def test_migrate_dry_run_then_apply_backs_up_legacy_notes(self) -> None:
        jot_root = self.home / ".task" / "jot"
        note_path = jot_root / "tasks" / "2d6d7d7d--legacy.md"
        original_body = "# Legacy\n\nKeep this body exactly.\n"
        write_document(
            note_path,
            OrderedDict(
                [
                    ("kind", "task-note"),
                    ("task_short_uuid", "2d6d7d7d"),
                    ("description", "Legacy"),
                ]
            ),
            original_body,
        )
        _original_metadata, original_body = read_document(note_path)

        dry_run = self.run_jot("--json", "migrate", "--dry-run")
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        dry_payload = json.loads(dry_run.stdout)
        self.assertEqual(dry_payload["planned"], 1)
        self.assertEqual(dry_payload["migrated"], 0)
        metadata, body = read_document(note_path)
        self.assertNotIn("schema_version", metadata)
        self.assertEqual(body, original_body)

        applied = self.run_jot("--json", "migrate")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        payload = json.loads(applied.stdout)
        self.assertEqual(payload["planned"], 1)
        self.assertEqual(payload["migrated"], 1)
        backup_root = Path(payload["backup_path"])
        backup_path = backup_root / "tasks" / note_path.name
        self.assertTrue(backup_path.exists())
        backup_metadata, backup_body = read_document(backup_path)
        self.assertNotIn("schema_version", backup_metadata)
        self.assertEqual(backup_body, original_body)
        metadata, body = read_document(note_path)
        self.assertEqual(metadata["schema_version"], "1")
        self.assertEqual(body, original_body)

        stats = self.run_jot("--json", "stats")
        self.assertEqual(stats.returncode, 0, stats.stderr)
        self.assertFalse(json.loads(stats.stdout)["index"]["stale"])

    def test_migrate_blocks_future_note_schemas_without_writing(self) -> None:
        note_path = self.home / ".task" / "jot" / "tasks" / "2d6d7d7d--future.md"
        write_document(
            note_path,
            OrderedDict(
                [
                    ("schema_version", "99"),
                    ("kind", "task-note"),
                    ("task_short_uuid", "2d6d7d7d"),
                ]
            ),
            "# Future\n",
        )
        before = note_path.read_text(encoding="utf-8")

        result = self.run_jot("--json", "migrate")
        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["blocked"], 1)
        self.assertEqual(payload["migrated"], 0)
        self.assertIsNone(payload["backup_path"])
        self.assertEqual(note_path.read_text(encoding="utf-8"), before)

    def test_doctor_repair_migrates_notes_removes_stale_locks_and_rebuilds_index(self) -> None:
        jot_root = self.home / ".task" / "jot"
        note_path = jot_root / "projects" / "reading" / "index.md"
        write_document(
            note_path,
            OrderedDict([("kind", "project-note"), ("project", "reading")]),
            "# Reading\n",
        )
        stale_lock = jot_root / ".orphan.lock.d"
        stale_lock.mkdir(parents=True)
        (stale_lock / "owner.json").write_text(
            json.dumps({"pid": 999999, "created": 0}),
            encoding="utf-8",
        )

        before = self.run_jot("--json", "doctor")
        self.assertEqual(before.returncode, 0, before.stderr)
        before_checks = {item["name"]: item for item in json.loads(before.stdout)["checks"]}
        self.assertFalse(before_checks["locks"]["ok"])
        self.assertFalse(before_checks["note_schema"]["ok"])

        repaired = self.run_jot("--json", "doctor", "--repair")
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        payload = json.loads(repaired.stdout)
        actions = {item["action"] for item in payload["repairs"]}
        self.assertEqual(actions, {"stale-locks", "note-schema", "index"})
        checks = {item["name"]: item for item in payload["checks"]}
        self.assertTrue(checks["locks"]["ok"])
        self.assertTrue(checks["note_schema"]["ok"])
        self.assertFalse(stale_lock.exists())
        metadata, _body = read_document(note_path)
        self.assertEqual(metadata["schema_version"], "1")
        self.assertTrue((jot_root / "index.json").exists())

    def test_paths_default_to_taskrc_data_location(self) -> None:
        taskdata = self.root / "taskrc-taskdata"
        taskrc = self.root / "custom.taskrc"
        taskrc.write_text(f"data.location = {taskdata}\n", encoding="utf-8")
        result = self.run_jot_with_env(
            "--json",
            "paths",
            extra_env={"TASKRC": str(taskrc)},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["root_dir"], str(taskdata / "jot"))
        self.assertEqual(payload["config_path"], str(taskdata / "jot" / "config-jot.toml"))

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
                Created on {date} at {time}
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
        self.assertRegex(task_note, r"Created on \d{4}-\d{2}-\d{2} at \d{2}:\d{2}:\d{2}Z")
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
        self.assertIn("Created:", task_note)

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

    def test_project_report_rolls_up_notes_tasks_recent_and_chains(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "annotations": [],
        }
        other_task = {
            "uuid": "3d6d7d7d-1111-2222-3333-444444444444",
            "description": "Other work",
            "project": "finance.other",
            "tags": [],
            "annotations": [],
        }
        self.write_state(
            {
                "version": "2.6.2",
                "single": [task],
                "1": [task],
                "tasks": [task, other_task],
                "annotate_key": "1",
            }
        )

        self.assertEqual(self.run_jot("project-append", "finance.audit", "project baseline").returncode, 0)
        self.assertEqual(self.run_jot("note-append", "1", "task baseline").returncode, 0)
        self.assertEqual(self.run_jot("chain-append", "1", "chain baseline").returncode, 0)
        self.assertEqual(self.run_jot("add", "--type", "status", "1", "waiting").returncode, 0)
        self.assertEqual(self.run_jot("timelog", "start", "1", "--at", "20260703T060000Z").returncode, 0)
        self.assertEqual(self.run_jot("timelog", "stop", "1", "--at", "20260703T064500Z").returncode, 0)

        result = self.run_jot(
            "--json", "project-report", "finance.audit", "--limit", "10", "--timelog-period", "all"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["project"], "finance.audit")
        self.assertTrue(payload["note"]["exists"])
        self.assertEqual([item["short_uuid"] for item in payload["tasks"]], ["2d6d7d7d"])
        self.assertEqual(payload["chains"][0]["chain_id"], "a4bf5egh")
        self.assertTrue(any(item["kind"] == "event" for item in payload["recent"]))
        self.assertEqual(payload["timelog"]["total_minutes"], 45)

        text_result = self.run_jot(
            "project-report", "finance.audit", "--limit", "5", "--timelog-period", "all"
        )
        self.assertEqual(text_result.returncode, 0, text_result.stderr)
        self.assertIn("Project finance.audit", text_result.stdout)
        self.assertIn("Tasks:", text_result.stdout)
        self.assertIn("Chains:", text_result.stdout)
        self.assertIn("Time (all):", text_result.stdout)

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

        trash_list = self.run_jot("--json", "trash-list")
        self.assertEqual(trash_list.returncode, 0, trash_list.stderr)
        trash_payload = json.loads(trash_list.stdout)
        self.assertEqual(len(trash_payload["items"]), 3)

        restore = self.run_jot("--json", "trash-restore", "1")
        self.assertEqual(restore.returncode, 0, restore.stderr)
        restored_payload = json.loads(restore.stdout)
        self.assertTrue(Path(restored_payload["path"]).exists())
        self.assertFalse(Path(restored_payload["trash_path"]).exists())

        after_restore = self.run_jot("--json", "trash-list")
        self.assertEqual(after_restore.returncode, 0, after_restore.stderr)
        after_payload = json.loads(after_restore.stdout)
        self.assertEqual(len(after_payload["items"]), 2)

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
        self.assertRegex(note_text, r"- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [^\]]+\] call vendor monday")

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
        self.assertRegex(note_text, r"- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [^\]]+\] vendor dependency")

    def test_headings_and_section_commands_read_note_structure(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        self.assertEqual(self.run_jot("note-append", "1", "baseline").returncode, 0)
        add_result = self.run_jot(
            "add-to",
            "task",
            "1",
            "--heading",
            "Next steps",
            "--text",
            "call vendor monday",
        )
        self.assertEqual(add_result.returncode, 0, add_result.stderr)

        headings = self.run_jot("--json", "headings", "task", "1")
        self.assertEqual(headings.returncode, 0, headings.stderr)
        headings_payload = json.loads(headings.stdout)
        self.assertIn("Next steps", [item["title"] for item in headings_payload["headings"]])

        section = self.run_jot("section", "task", "1", "next stps")
        self.assertEqual(section.returncode, 0, section.stderr)
        self.assertIn("call vendor monday", section.stdout)

    def test_task_resources_attach_list_open_and_detach(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        attach = self.run_jot("attach", "task", "1", "https://example.com/invoice", "--label", "invoice")
        self.assertEqual(attach.returncode, 0, attach.stderr)
        note_text = list((self.home / ".task" / "jot" / "tasks").glob("*.md"))[0].read_text(encoding="utf-8")
        self.assertIn("## References", note_text)
        self.assertIn("- [invoice](https://example.com/invoice)", note_text)

        listed = self.run_jot("--json", "resources", "task", "1")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        payload = json.loads(listed.stdout)
        self.assertEqual(payload["resources"][0]["label"], "invoice")
        self.assertEqual(payload["resources"][0]["target"], "https://example.com/invoice")
        self.assertEqual(payload["resources"][0]["kind"], "url")
        self.assertEqual(payload["resources"][0]["status"], "unchecked")

        opened = self.run_jot_with_env(
            "open-resource",
            "task",
            "1",
            "1",
            extra_env={"JOT_OPENER": "true"},
        )
        self.assertEqual(opened.returncode, 0, opened.stderr)

        detached = self.run_jot("--json", "detach-resource", "task", "1", "1")
        self.assertEqual(detached.returncode, 0, detached.stderr)
        detached_payload = json.loads(detached.stdout)
        self.assertEqual(detached_payload["resource"]["target"], "https://example.com/invoice")
        self.assertEqual(detached_payload["resources"], [])

    def test_project_resources_store_paths_in_project_note(self) -> None:
        existing = self.root / "audit-plan.md"
        existing.write_text("plan\n", encoding="utf-8")

        attach = self.run_jot("attach", "project", "finance.audit", str(existing))
        self.assertEqual(attach.returncode, 0, attach.stderr)
        missing = self.run_jot("attach", "project", "finance.audit", "~/docs/missing-audit-plan.md")
        self.assertEqual(missing.returncode, 0, missing.stderr)

        listed = self.run_jot("--json", "resources", "project", "finance.audit")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        payload = json.loads(listed.stdout)
        self.assertEqual(payload["project"], "finance.audit")
        self.assertEqual(payload["resources"][0]["target"], str(existing))
        self.assertEqual(payload["resources"][0]["label"], "audit-plan.md")
        self.assertEqual(payload["resources"][0]["status"], "exists")
        self.assertEqual(payload["resources"][1]["target"], "~/docs/missing-audit-plan.md")
        self.assertEqual(payload["resources"][1]["status"], "missing")

        text_listed = self.run_jot("resources", "project", "finance.audit")
        self.assertEqual(text_listed.returncode, 0, text_listed.stderr)
        self.assertIn("[file] exists", text_listed.stdout)
        self.assertIn("[file] missing", text_listed.stdout)

    def test_task_progress_tracks_state_history_and_clear(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Read a book",
            "project": "reading",
            "tags": [],
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        set_result = self.run_jot(
            "--json",
            "progress",
            "task",
            "1",
            "set",
            "100/200",
            "--unit",
            "pages",
            "--status",
            "active",
        )
        self.assertEqual(set_result.returncode, 0, set_result.stderr)
        set_payload = json.loads(set_result.stdout)
        self.assertEqual(set_payload["progress"]["current"], "100")
        self.assertEqual(set_payload["progress"]["target"], "200")
        self.assertEqual(set_payload["progress"]["percentage"], "50")
        self.assertEqual(set_payload["progress"]["unit"], "pages")
        self.assertEqual(set_payload["progress"]["status"], "active")

        self.assertEqual(self.run_jot("progress", "task", "1", "add", "25").returncode, 0)
        self.assertEqual(self.run_jot("progress", "task", "1", "subtract", "5").returncode, 0)
        self.assertEqual(self.run_jot("progress", "task", "1", "status", "paused").returncode, 0)

        shown = self.run_jot("--json", "progress", "task", "1", "show")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        shown_payload = json.loads(shown.stdout)
        self.assertEqual(shown_payload["progress"]["current"], "120")
        self.assertEqual(shown_payload["progress"]["percentage"], "60")
        self.assertEqual(shown_payload["progress"]["status"], "paused")
        self.assertEqual(shown_payload["trends"][0]["track"], "default")
        self.assertEqual(shown_payload["trends"][0]["delta"], "+20")
        self.assertEqual(shown_payload["trends"][0]["remaining"], "80")
        self.assertEqual(shown_payload["trends"][0]["last_change"], "-5")
        self.assertEqual(len(shown_payload["history"]), 4)
        self.assertEqual(shown_payload["history"][-1]["action"], "status")

        limited = self.run_jot("--json", "progress", "task", "1", "show", "--history", "2")
        self.assertEqual(limited.returncode, 0, limited.stderr)
        limited_payload = json.loads(limited.stdout)
        self.assertEqual(len(limited_payload["history"]), 2)
        self.assertEqual([item["action"] for item in limited_payload["history"]], ["adjust", "status"])

        text_shown = self.run_jot("progress", "task", "1", "show", "--history", "2")
        self.assertEqual(text_shown.returncode, 0, text_shown.stderr)
        self.assertIn("Trends", text_shown.stdout)
        self.assertIn("delta +20 pages", text_shown.stdout)
        self.assertIn("Recent history", text_shown.stdout)

        note_path = list((self.home / ".task" / "jot" / "tasks").glob("*.md"))[0]
        note_text = note_path.read_text(encoding="utf-8")
        self.assertIn("progress_current: 120", note_text)
        self.assertIn("progress_target: 200", note_text)
        self.assertIn("progress_unit: pages", note_text)
        self.assertIn("progress_status: paused", note_text)
        self.assertIn("## Progress", note_text)
        self.assertIn("set: 100/200 pages; status active", note_text)
        self.assertIn("change +25", note_text)
        self.assertIn("change -5", note_text)
        self.assertIn("status: 120/200 pages; status paused", note_text)

        rejected = self.run_jot("progress", "task", "1", "clear")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("requires --yes", rejected.stderr)

        cleared = self.run_jot("--json", "progress", "task", "1", "clear", "--yes")
        self.assertEqual(cleared.returncode, 0, cleared.stderr)
        self.assertIsNone(json.loads(cleared.stdout)["progress"])
        cleared_text = note_path.read_text(encoding="utf-8")
        self.assertNotIn("progress_current:", cleared_text)
        self.assertIn("cleared progress state", cleared_text)

    def test_project_and_chain_progress_support_decimals(self) -> None:
        project_set = self.run_jot(
            "--json",
            "progress",
            "project",
            "renovation",
            "set",
            "1.5/8",
            "--unit",
            "rooms",
        )
        self.assertEqual(project_set.returncode, 0, project_set.stderr)
        project_payload = json.loads(project_set.stdout)
        self.assertEqual(project_payload["progress"]["current"], "1.5")
        self.assertEqual(project_payload["progress"]["percentage"], "18.75")

        thirds = self.run_jot("--json", "progress", "project", "writing", "set", "1/3")
        self.assertEqual(thirds.returncode, 0, thirds.stderr)
        self.assertEqual(json.loads(thirds.stdout)["progress"]["percentage"], "33.33")

        task = {
            "uuid": "3d6d7d7d-1111-2222-3333-444444444444",
            "description": "Recurring practice",
            "project": "practice",
            "tags": [],
            "chainID": "b4bf5egh",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "2": [task]})
        chain_set = self.run_jot("--json", "progress", "chain", "2", "set", "2/10", "--unit", "sessions")
        self.assertEqual(chain_set.returncode, 0, chain_set.stderr)
        chain_payload = json.loads(chain_set.stdout)
        self.assertEqual(chain_payload["chain_id"], "b4bf5egh")
        self.assertEqual(chain_payload["progress"]["unit"], "sessions")

    def test_task_progress_supports_independent_named_tracks(self) -> None:
        task = {
            "uuid": "5d6d7d7d-1111-2222-3333-444444444444",
            "description": "Full body workout",
            "project": "fitness",
            "tags": [],
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "4": [task]})

        chest = self.run_jot(
            "--json",
            "progress",
            "task",
            "4",
            "set",
            "3/12",
            "--track",
            "chest",
            "--unit",
            "sets",
        )
        self.assertEqual(chest.returncode, 0, chest.stderr)
        legs = self.run_jot(
            "--json",
            "progress",
            "task",
            "4",
            "set",
            "4/12",
            "--track",
            "legs",
            "--unit",
            "sets",
        )
        self.assertEqual(legs.returncode, 0, legs.stderr)
        adjusted = self.run_jot("--json", "progress", "task", "4", "add", "2", "--track", "chest")
        self.assertEqual(adjusted.returncode, 0, adjusted.stderr)
        self.assertEqual(json.loads(adjusted.stdout)["progress"]["current"], "5")

        shown = self.run_jot("--json", "progress", "task", "4", "show")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        shown_payload = json.loads(shown.stdout)
        tracks = {item["track"]: item for item in shown_payload["tracks"]}
        self.assertEqual(tracks["chest"]["current"], "5")
        self.assertEqual(tracks["legs"]["current"], "4")
        trends = {item["track"]: item for item in shown_payload["trends"]}
        self.assertEqual(trends["chest"]["delta"], "+2")
        self.assertEqual(trends["legs"]["remaining"], "8")

        selected = self.run_jot("--json", "progress", "task", "4", "show", "--track", "legs")
        self.assertEqual(selected.returncode, 0, selected.stderr)
        selected_payload = json.loads(selected.stdout)
        self.assertEqual(selected_payload["progress"]["track"], "legs")
        self.assertEqual([item["track"] for item in selected_payload["trends"]], ["legs"])
        self.assertEqual([item["track"] for item in selected_payload["history"]], ["legs"])

        cleared = self.run_jot(
            "--json",
            "progress",
            "task",
            "4",
            "clear",
            "--track",
            "chest",
            "--yes",
        )
        self.assertEqual(cleared.returncode, 0, cleared.stderr)
        self.assertEqual([item["track"] for item in json.loads(cleared.stdout)["tracks"]], ["legs"])

        note_path = list((self.home / ".task" / "jot" / "tasks").glob("*.md"))[0]
        note_text = note_path.read_text(encoding="utf-8")
        self.assertIn("progress_tracks:", note_text)
        self.assertIn("[chest] set: 3/12 sets", note_text)
        self.assertIn("[legs] set: 4/12 sets", note_text)
        self.assertIn("[chest] cleared progress state", note_text)

    def test_progress_adjustment_infers_sole_named_track(self) -> None:
        task = {
            "uuid": "60aa7d7d-1111-2222-3333-444444444444",
            "description": "Workout",
            "project": "fitness",
            "tags": [],
            "chainID": "chain060",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "60": [task]})

        created = self.run_jot(
            "progress",
            "chain",
            "60",
            "set",
            "3/10",
            "--track",
            "chest",
            "--unit",
            "sets",
        )
        self.assertEqual(created.returncode, 0, created.stderr)

        adjusted = self.run_jot("--json", "prog", "c", "60", "add", "1")
        self.assertEqual(adjusted.returncode, 0, adjusted.stderr)
        payload = json.loads(adjusted.stdout)
        self.assertEqual(payload["track"], "chest")
        self.assertEqual(payload["progress"]["current"], "4")

    def test_concurrent_progress_commands_preserve_note_index_and_ops(self) -> None:
        task = {
            "uuid": "62aa7d7d-1111-2222-3333-444444444444",
            "description": "Concurrent workout",
            "project": "fitness",
            "tags": [],
            "chainID": "chain062",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "62": [task]})
        created = self.run_jot("progress", "chain", "62", "set", "0/20", "--track", "sets")
        self.assertEqual(created.returncode, 0, created.stderr)

        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(
                executor.map(
                    lambda _item: self.run_jot("prog", "c", "62", "add", "1"),
                    range(12),
                )
            )
        for result in results:
            self.assertEqual(result.returncode, 0, result.stderr)

        shown = self.run_jot("--json", "prog", "c", "62", "sh", "--track", "sets")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(json.loads(shown.stdout)["progress"]["current"], "12")

        jot_root = self.home / ".task" / "jot"
        index_data = json.loads((jot_root / "index.json").read_text(encoding="utf-8"))
        self.assertIn("chain062", index_data["chains"])
        ops = [
            json.loads(line)
            for line in (jot_root / "ops.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        progress_ops = [item for item in ops if item.get("op") == "chain_progress_add"]
        self.assertEqual(len(progress_ops), 12)

    def test_progress_adjustment_requires_track_when_multiple_named_tracks_exist(self) -> None:
        task = {
            "uuid": "61aa7d7d-1111-2222-3333-444444444444",
            "description": "Workout",
            "project": "fitness",
            "tags": [],
            "chainID": "chain061",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "61": [task]})
        for track in ("chest", "legs"):
            created = self.run_jot("progress", "chain", "61", "set", "3/10", "--track", track)
            self.assertEqual(created.returncode, 0, created.stderr)

        rejected = self.run_jot("prog", "c", "61", "add", "1")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("multiple progress tracks exist", rejected.stderr)
        self.assertIn("specify --track", rejected.stderr)

    def test_progress_show_compares_multiple_chain_references(self) -> None:
        tasks = [
            {
                "uuid": "53aa7d7d-1111-2222-3333-444444444444",
                "description": "Morning mobility",
                "project": "fitness",
                "tags": [],
                "chainID": "chain053",
                "annotations": [],
            },
            {
                "uuid": "986e9d97-1111-2222-3333-444444444444",
                "description": "Strength practice",
                "project": "fitness",
                "tags": [],
                "chainID": "chain986",
                "annotations": [],
            },
            {
                "uuid": "41aa7d7d-1111-2222-3333-444444444444",
                "description": "Evening stretch",
                "project": "fitness",
                "tags": [],
                "chainID": "chain041",
                "annotations": [],
            },
        ]
        self.write_state(
            {
                "version": "2.6.2",
                "single": [tasks[0]],
                "53": [tasks[0]],
                "uuid:986e9d97": [tasks[1]],
                "41": [tasks[2]],
            }
        )
        for reference, measurement in (("53", "2/5"), ("986e9d97", "3/5"), ("41", "4/5")):
            result = self.run_jot(
                "progress",
                "chain",
                reference,
                "set",
                measurement,
                "--unit",
                "sessions",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

        shown = self.run_jot("--json", "prog", "c", "53,986e9d97,41", "sh")
        self.assertEqual(shown.returncode, 0, shown.stderr)
        payload = json.loads(shown.stdout)
        self.assertEqual(payload["note_kind"], "chain")
        self.assertEqual([item["reference"] for item in payload["items"]], ["53", "986e9d97", "41"])
        self.assertEqual(
            [item["chain_id"] for item in payload["items"]],
            ["chain053", "chain986", "chain041"],
        )
        self.assertEqual(
            [item["progress"]["current"] for item in payload["items"]],
            ["2", "3", "4"],
        )
        self.assertEqual([item["trends"][0]["remaining"] for item in payload["items"]], ["3", "2", "1"])

        text = self.run_jot("prog", "c", "53,986e9d97,41", "sh")
        self.assertEqual(text.returncode, 0, text.stderr)
        self.assertIn("Progress for 3 chain notes", text.stdout)
        self.assertIn("chain053", text.stdout)
        self.assertIn("chain986", text.stdout)
        self.assertIn("chain041", text.stdout)
        self.assertGreaterEqual(text.stdout.count("【"), 3)

    def test_progress_show_does_not_create_missing_note(self) -> None:
        task = {
            "uuid": "4d6d7d7d-1111-2222-3333-444444444444",
            "description": "No progress yet",
            "project": "",
            "tags": [],
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "3": [task]})

        result = self.run_jot("progress", "task", "3", "show")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("task note does not exist", result.stderr)
        self.assertFalse(list((self.home / ".task" / "jot" / "tasks").glob("*.md")))

        add_result = self.run_jot("progress", "task", "3", "add", "1")
        self.assertNotEqual(add_result.returncode, 0)
        self.assertIn("task note does not exist", add_result.stderr)
        self.assertFalse(list((self.home / ".task" / "jot" / "tasks").glob("*.md")))

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

    def test_notes_lists_existing_notes_across_scopes_and_filters(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})
        self.assertEqual(self.run_jot("note-append", "1", "task context").returncode, 0)
        self.assertEqual(self.run_jot("chain-append", "1", "chain context").returncode, 0)
        self.assertEqual(self.run_jot("project-append", "finance.audit", "project context").returncode, 0)

        result = self.run_jot("--json", "notes")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(
            sorted(item["kind"] for item in payload["notes"]),
            ["chain-note", "project-note", "task-note"],
        )

        task_notes = self.run_jot("--json", "notes", "--kind", "task", "--project", "finance.audit")
        self.assertEqual(task_notes.returncode, 0, task_notes.stderr)
        task_payload = json.loads(task_notes.stdout)
        self.assertEqual([item["kind"] for item in task_payload["notes"]], ["task-note"])
        self.assertEqual(task_payload["notes"][0]["task_short_uuid"], "2d6d7d7d")

        project_scoped = self.run_jot("--json", "notes", "--project", "finance.audit")
        self.assertEqual(project_scoped.returncode, 0, project_scoped.stderr)
        self.assertEqual(
            sorted(item["kind"] for item in json.loads(project_scoped.stdout)["notes"]),
            ["chain-note", "project-note", "task-note"],
        )

        text = self.run_jot("notes", "--kind", "project")
        self.assertEqual(text.returncode, 0, text.stderr)
        self.assertIn("project-note finance.audit", text.stdout)

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
        alias = self.run_jot("--json", "recent", "--limit", "10")
        self.assertEqual(alias.returncode, 0, alias.stderr)
        self.assertEqual(json.loads(alias.stdout), payload)
        filtered = self.run_jot("--json", "report", "recent", "--kind", "event", "--limit", "10")
        self.assertEqual(filtered.returncode, 0, filtered.stderr)
        filtered_payload = json.loads(filtered.stdout)
        self.assertEqual(filtered_payload["kinds"], ["event"])
        self.assertTrue(filtered_payload["items"])
        self.assertEqual({item["kind"] for item in filtered_payload["items"]}, {"event"})

    def test_open_edit_and_cat_aliases_route_to_existing_note_commands(self) -> None:
        task = {
            "uuid": "2d6d7d7d-1111-2222-3333-444444444444",
            "description": "Fix billing discrepancy",
            "project": "finance.audit",
            "tags": ["ann"],
            "chainID": "a4bf5egh",
            "annotations": [],
        }
        self.write_state({"version": "2.6.2", "single": [task], "1": [task]})

        opened_chain = self.run_jot("--json", "open", "1")
        self.assertEqual(opened_chain.returncode, 0, opened_chain.stderr)
        self.assertTrue(json.loads(opened_chain.stdout)["path"].endswith("chains/a4bf5egh--fix-billing-discrepancy.md"))

        opened_task = self.run_jot("--json", "edit", "task", "1")
        self.assertEqual(opened_task.returncode, 0, opened_task.stderr)
        self.assertIn("tasks/2d6d7d7d--fix-billing-discrepancy.md", json.loads(opened_task.stdout)["path"])

        self.assertEqual(self.run_jot("note-append", "1", "task context").returncode, 0)
        self.assertEqual(self.run_jot("chain-append", "1", "chain context").returncode, 0)
        self.assertEqual(self.run_jot("project-append", "finance.audit", "project context").returncode, 0)

        task_cat = self.run_jot("cat", "1")
        self.assertEqual(task_cat.returncode, 0, task_cat.stderr)
        self.assertIn("task context", task_cat.stdout)
        chain_cat = self.run_jot("cat", "chain", "1")
        self.assertEqual(chain_cat.returncode, 0, chain_cat.stderr)
        self.assertIn("chain context", chain_cat.stdout)
        project_cat = self.run_jot("cat", "project", "finance.audit")
        self.assertEqual(project_cat.returncode, 0, project_cat.stderr)
        self.assertIn("project context", project_cat.stdout)

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
