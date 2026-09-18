from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from jot_core.models import ProgressMutationResult
from jot_core.progress import ProgressResult
from jot_core.progress_cli import run_progress


def _mutation_result() -> ProgressMutationResult:
    return ProgressMutationResult.from_mapping(
        {
            "note_path": "/tmp/reading.md",
            "opened": True,
            "progress": {
                "track": "default",
                "current": "3",
                "target": "10",
                "unit": "books",
                "status": "active",
                "updated": "2026-09-18T10:00:00Z",
                "percentage": "30",
            },
            "track": "default",
            "tracks": [],
            "entry": "3/10 books",
        }
    )


class ProgressCliTests(unittest.TestCase):
    def test_project_set_parses_measurement_and_preserves_omitted_track(self) -> None:
        args = SimpleNamespace(
            note_kind="project",
            note_ref="reading",
            progress_command="set",
            track=None,
            measurement="3/10",
            unit="books",
            status="active",
            amount=None,
            value=None,
            yes=False,
        )
        ctx = SimpleNamespace(config=object())

        with mock.patch(
            "jot_core.progress_cli.mutate_project_progress_storage",
            return_value=_mutation_result(),
        ) as mutate:
            result = run_progress(ctx, args, lambda *_: (Path("/tmp/reading.md"), {}))

        mutate.assert_called_once()
        self.assertEqual(mutate.call_args.args, (ctx.config, "reading"))
        self.assertEqual(mutate.call_args.kwargs["operation"], "set")
        self.assertEqual(str(mutate.call_args.kwargs["current"]), "3")
        self.assertEqual(str(mutate.call_args.kwargs["target"]), "10")
        self.assertIsNone(mutate.call_args.kwargs["track"])
        self.assertEqual(result.data.to_payload()["project"], "reading")
        self.assertEqual(result.data.to_payload()["progress"]["current"], "3")

    def test_show_supports_multiple_references_and_deduplicates_paths(self) -> None:
        args = SimpleNamespace(
            note_kind="project",
            note_ref="reading,reading-alias",
            progress_command="show",
            track="default",
            history=0,
        )
        ctx = SimpleNamespace()
        path = Path("/tmp/reading.md")
        progress = ProgressResult(note_path=path, progress=None, tracks=())

        with (
            mock.patch("jot_core.progress_cli.read_note_progress", return_value=progress),
            mock.patch(
                "jot_core.progress_cli.read_note_progress_analysis",
                return_value={"history": [], "trends": []},
            ),
        ):
            result = run_progress(
                ctx,
                args,
                lambda _ctx, _kind, reference: (path, {"project": reference}),
            )

        payload = result.data.to_payload()
        self.assertEqual(payload["operation"], "show")
        self.assertEqual(len(payload["items"]), 1)

    def test_show_rejects_negative_history(self) -> None:
        args = SimpleNamespace(
            note_kind="task",
            note_ref="abc12345",
            progress_command="show",
            track=None,
            history=-1,
        )

        with self.assertRaisesRegex(RuntimeError, "history"):
            run_progress(SimpleNamespace(), args, lambda *_: (Path("/tmp/note.md"), {}))

    def test_clear_requires_explicit_confirmation(self) -> None:
        args = SimpleNamespace(
            note_kind="project",
            note_ref="reading",
            progress_command="clear",
            track=None,
            yes=False,
        )

        with self.assertRaisesRegex(RuntimeError, "--yes"):
            run_progress(SimpleNamespace(), args, lambda *_: (Path("/tmp/note.md"), {}))


if __name__ == "__main__":
    unittest.main()
