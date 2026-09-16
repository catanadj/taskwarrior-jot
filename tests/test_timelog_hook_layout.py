from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class TimelogHookLayoutTests(unittest.TestCase):
    def test_jot_hooks_delegate_to_one_canonical_implementation(self) -> None:
        canonical = ROOT / "jot_core" / "timelog_hook.py"
        hook_paths = (
            ROOT / "hooks" / "on-modify_jot_timelog.py",
            ROOT / "jot_core" / "data" / "hooks" / "on-modify_jot_timelog.py",
        )

        self.assertTrue(canonical.is_file())
        for hook_path in hook_paths:
            source = hook_path.read_text(encoding="utf-8")
            self.assertIn("from jot_core.timelog_hook import main", source)
            self.assertNotIn("subprocess.run(", source)


if __name__ == "__main__":
    unittest.main()
