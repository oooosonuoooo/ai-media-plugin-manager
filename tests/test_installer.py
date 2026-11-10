import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import install_skill


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.home = Path(self.temp_dir.name)
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.home / ".codex")})
        self.env.start()
        self.home_patch = patch.object(Path, "home", return_value=self.home)
        self.home_patch.start()

    def tearDown(self):
        self.home_patch.stop()
        self.env.stop()
        self.temp_dir.cleanup()

    def run_installer(self, *args):
        output = io.StringIO()
        with patch("sys.argv", ["install_skill.py", *args]), contextlib.redirect_stdout(output):
            code = install_skill.main()
        return code, output.getvalue()

    def test_install_and_verify_manage_cli_and_both_skill_links(self):
        code, output = self.run_installer("install")
        self.assertEqual(code, 0)
        self.assertIn("codex: linked:", output)
        self.assertIn("antigravity: linked:", output)
        self.assertIn("cli: linked:", output)

        targets = install_skill.install_targets()
        for target, source, _ in targets.values():
            self.assertTrue(target.is_symlink())
            self.assertEqual(target.resolve(strict=True), source)

        cli_target = targets["cli"][0]
        self.assertTrue(os.access(cli_target, os.X_OK))
        code, output = self.run_installer("verify")
        self.assertEqual(code, 0, output)
        self.assertEqual(output.count("verified:"), 3)

    def test_install_preserves_conflicting_cli_link_and_repair_replaces_it(self):
        target = install_skill.install_targets()["cli"][0]
        target.parent.mkdir(parents=True)
        unrelated = self.home / "other-media-assets"
        unrelated.write_text("user command\n", encoding="utf-8")
        target.symlink_to(unrelated)

        code, output = self.run_installer("install", "--scope", "cli")
        self.assertEqual(code, 0)
        self.assertIn("conflict preserved", output)
        self.assertEqual(target.resolve(strict=True), unrelated)

        code, output = self.run_installer("repair", "--scope", "cli")
        self.assertEqual(code, 0)
        self.assertIn("cli: linked:", output)
        self.assertEqual(target.resolve(strict=True), install_skill.CLI_SOURCE)
        self.assertTrue(unrelated.exists())

    def test_repair_never_replaces_a_real_directory(self):
        target = install_skill.install_targets()["cli"][0]
        target.mkdir(parents=True)
        sentinel = target / "keep.txt"
        sentinel.write_text("preserve", encoding="utf-8")

        code, output = self.run_installer("repair", "--scope", "cli")
        self.assertEqual(code, 0)
        self.assertIn("directory conflict preserved", output)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")

    def test_uninstall_removes_only_links_owned_by_this_source(self):
        self.run_installer("install")
        targets = install_skill.install_targets()
        code, output = self.run_installer("uninstall")
        self.assertEqual(code, 0)
        self.assertEqual(output.count("removed link:"), 3)
        self.assertTrue(all(not target.is_symlink() for target, _, _ in targets.values()))


if __name__ == "__main__":
    unittest.main()
