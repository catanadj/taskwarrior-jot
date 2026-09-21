import tempfile
import unittest
from pathlib import Path

from tools.check_release_metadata import validate_metadata


class ReleaseMetadataTests(unittest.TestCase):
    def _files(self, package_version="0.9.0", bootstrap_version="0.9.0"):
        root = Path(self._tmp.name)
        package = root / "__init__.py"
        bootstrap = root / "bootstrap.sh"
        package.write_text(f'__version__ = "{package_version}"\n', encoding="utf-8")
        bootstrap.write_text(
            f'VERSION="${{JOT_VERSION:-v{bootstrap_version}}}"\n',
            encoding="utf-8",
        )
        return package, bootstrap

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def test_matching_branch_metadata_is_valid(self):
        package, bootstrap = self._files()

        self.assertEqual(validate_metadata(package, bootstrap, "main"), [])

    def test_release_tag_must_match_package_and_bootstrap(self):
        package, bootstrap = self._files()

        self.assertEqual(validate_metadata(package, bootstrap, "v0.9.0"), [])
        self.assertTrue(validate_metadata(package, bootstrap, "v0.8.0"))

    def test_bootstrap_version_must_match_package_version(self):
        package, bootstrap = self._files(bootstrap_version="0.8.0")

        errors = validate_metadata(package, bootstrap, "main")

        self.assertEqual(len(errors), 1)
        self.assertIn("bootstrap", errors[0])


if __name__ == "__main__":
    unittest.main()
