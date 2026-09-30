from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import local_ci


class HookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("commit", "--allow-empty", "-qm", "initial")
        self.head = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], text=True, stderr=subprocess.PIPE,
        ).strip()

    def updates(self, sha=None):
        return f"refs/heads/test {sha or self.head} refs/heads/test {'0' * 40}\n"

    def test_install_preserves_other_hooks(self):
        self.git("config", "core.hooksPath", "custom-hooks")
        with self.assertRaisesRegex(RuntimeError, "existing"):
            local_ci.install(self.root)
        self.assertEqual(self.git("config", "core.hooksPath"), "custom-hooks")

    def test_install_is_idempotent(self):
        local_ci.install(self.root)
        local_ci.install(self.root)
        self.assertEqual(self.git("config", "core.hooksPath"), local_ci.HOOKS)

    def test_installed_hook_blocks_a_real_push_on_test_failure(self):
        hook = self.root / ".github/hooks/pre-push"
        hook.parent.mkdir(parents=True)
        shutil.copy2(local_ci.ROOT / ".github/hooks/pre-push", hook)
        hook.chmod(0o755)
        runner = self.root / ".github/scripts/local_ci.py"
        runner.parent.mkdir()
        runner.write_text(
            "import sys\nprint('fixture validation failed', file=sys.stderr)\n"
            "raise SystemExit(7)\n", encoding="utf-8",
        )
        self.git("add", ".github")
        self.git("commit", "-qm", "hook fixture")
        remote = self.root / "remote.git"
        self.git("init", "--bare", str(remote))
        local_ci.install(self.root)
        push = subprocess.run(
            ["git", "-C", str(self.root), "push", str(remote), "HEAD:refs/heads/test"],
            capture_output=True, text=True,
        )
        self.assertNotEqual(push.returncode, 0)
        self.assertIn("fixture validation failed", push.stderr)
        refs = self.git("--git-dir=" + str(remote), "for-each-ref", "--format=%(refname)")
        self.assertEqual(refs, "")

    def test_current_tip(self):
        self.assertEqual(local_ci.pushed_head(self.root, self.updates()), self.head)

    def test_deletion_only(self):
        self.assertIsNone(local_ci.pushed_head(self.root, self.updates("0" * 40)))

    def test_annotated_tag(self):
        self.git("tag", "-a", "v1", "-m", "release")
        tag = self.git("rev-parse", "v1")
        self.assertEqual(local_ci.pushed_head(self.root, self.updates(tag)), self.head)

    def test_other_tip_is_not_validated_as_head(self):
        self.git("commit", "--allow-empty", "-qm", "second")
        with self.assertRaisesRegex(RuntimeError, "Push tips"):
            local_ci.pushed_head(self.root, self.updates())

    def test_staged_unstaged_and_untracked_are_rejected(self):
        file = self.root / "source"
        file.write_text("one", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "clean"):
            local_ci.require_clean(self.root, self.head)
        self.git("add", "source")
        with self.assertRaisesRegex(RuntimeError, "clean"):
            local_ci.require_clean(self.root, self.head)
        self.git("commit", "-qm", "source")
        head = self.git("rev-parse", "HEAD")
        file.write_text("two", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "clean"):
            local_ci.require_clean(self.root, head)

    def test_head_changed(self):
        self.git("commit", "--allow-empty", "-qm", "changed")
        with self.assertRaisesRegex(RuntimeError, "HEAD changed"):
            local_ci.require_clean(self.root, self.head)

    def test_malformed_updates_fail_closed(self):
        for updates in ("bad", self.updates("--help"), self.updates("g" * 40)):
            with self.subTest(updates=updates), self.assertRaises(RuntimeError):
                local_ci.pushed_head(self.root, updates)

    def test_failure_blocks_and_output_streams(self):
        with patch("local_ci.subprocess.Popen") as popen, patch("local_ci.stop_process"), patch("local_ci_windows.WindowsJob"):
            popen.return_value.wait.return_value = 3
            with self.assertRaisesRegex(RuntimeError, "failed with exit code 3"):
                local_ci.run_step(self.root, {"name": "tests", "argv": ["{python}", "-V"]}, self.root)
            self.assertNotIn("stdout", popen.call_args.kwargs)
            self.assertNotIn("stderr", popen.call_args.kwargs)

    def test_timeout_stops_only_owned_process(self):
        with patch("local_ci.subprocess.Popen") as popen, patch("local_ci.stop_process") as stop, patch("local_ci_windows.WindowsJob"):
            popen.return_value.wait.side_effect = subprocess.TimeoutExpired("tests", 1)
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                local_ci.run_step(self.root, {"name": "tests", "argv": ["{python}", "-V"]}, self.root)
            self.assertEqual(stop.call_count, 1)
            self.assertIs(stop.call_args.args[0], popen.return_value)

    def test_native_environment_does_not_inherit_cross_target(self):
        with patch.dict("os.environ", GOOS="windows", GOARCH="386", GIT_DIR="foreign"), patch("local_ci.subprocess.Popen") as popen, patch("local_ci.stop_process"), patch("local_ci_windows.WindowsJob"):
            popen.return_value.wait.return_value = 0
            local_ci.run_step(self.root, {"name": "native", "argv": ["{python}", "-V"]}, self.root)
            self.assertNotIn("GOOS", popen.call_args.kwargs["env"])
            self.assertNotIn("GOARCH", popen.call_args.kwargs["env"])
            self.assertNotIn("GIT_DIR", popen.call_args.kwargs["env"])

    def test_validation_does_not_report_into_the_calling_pane(self):
        with patch.dict("os.environ", ZAI_AGENT_STATUS_ADDR="127.0.0.1:1", ZAI_AGENT_STATUS_TOKEN="fixture-token"), patch("local_ci.subprocess.Popen") as popen, patch("local_ci.stop_process"), patch("local_ci_windows.WindowsJob"):
            popen.return_value.wait.return_value = 0
            local_ci.run_step(self.root, {"name": "native", "argv": ["{python}", "-V"]}, self.root)
            self.assertNotIn("ZAI_AGENT_STATUS_ADDR", popen.call_args.kwargs["env"])
            self.assertNotIn("ZAI_AGENT_STATUS_TOKEN", popen.call_args.kwargs["env"])


if __name__ == "__main__":
    unittest.main()
