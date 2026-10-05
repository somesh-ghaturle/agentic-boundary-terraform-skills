"""install.py puts the skill where Codex, Cursor and Windsurf load it, and wires the guard into
each agent's user-level hooks without disturbing hooks already there."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def install(agent, home):
    env = dict(os.environ, BOUNDARY_INSTALL_HOME=str(home))
    env.pop("CODEX_HOME", None)
    return subprocess.run([sys.executable, str(ROOT / "install.py"), agent], env=env,
                          capture_output=True, text=True)


class Install(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp())
        self.guard = self.home / ".agents/skills/terraform-boundary/hooks/guard.py"

    def config(self, path):
        return json.loads((self.home / path).read_text())

    def test_each_agent(self):
        cases = {
            "codex": (".codex/hooks.json", "PreToolUse"),
            "cursor": (".cursor/hooks.json", "beforeShellExecution"),
            "windsurf": (".codeium/windsurf/hooks.json", "pre_run_command"),
        }
        for agent, (path, event) in cases.items():
            with self.subTest(agent=agent):
                self.assertEqual(install(agent, self.home).returncode, 0)
                self.assertTrue((self.home / ".agents/skills/terraform-boundary/SKILL.md").is_file())
                self.assertTrue(self.guard.is_file())
                self.assertIn(str(self.guard), json.dumps(self.config(path)["hooks"][event]))

    def test_mcp_tool_calls_are_guarded_in_every_agent(self):
        install("cursor", self.home)
        install("windsurf", self.home)
        self.assertIn(str(self.guard), json.dumps(self.config(".cursor/hooks.json")["hooks"]["beforeMCPExecution"]))
        self.assertIn(str(self.guard), json.dumps(self.config(".codeium/windsurf/hooks.json")["hooks"]["pre_mcp_tool_use"]))

    def test_cursor_hook_fails_closed(self):
        install("cursor", self.home)
        entry = self.config(".cursor/hooks.json")["hooks"]["beforeShellExecution"][0]
        self.assertTrue(entry["failClosed"])

    def test_cursor_matcher_is_never_narrower_than_the_guard(self):
        # Cursor filters on the raw command before the guard runs; every spelling the shell
        # turns into terraform must still reach the guard.
        import re
        install("cursor", self.home)
        matcher = re.compile(self.config(".cursor/hooks.json")["hooks"]["beforeShellExecution"][0]["matcher"])
        for cmd in ["terraform apply", "TERRAFORM apply", '"terra""form" apply', "t\\erraform apply",
                    "{terraform,apply}", "tofu apply", "terragrunt apply", "cdktf deploy", "terraspace up",
                    "terraform_1.15.8 apply", "scripts/boundary.sh apply . dev",
                    "terraform plan -auto-approve", "$'\\x74erraform' apply", "ter\\\nraform apply"]:
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(matcher.search(cmd))
        self.assertIsNone(matcher.search("git status"))

    def test_keeps_existing_hooks_and_is_idempotent(self):
        existing = {"hooks": {"PreToolUse": [{"matcher": "^Bash$", "hooks": [{"type": "command", "command": "mine.sh"}]}]}}
        (self.home / ".codex").mkdir()
        (self.home / ".codex/hooks.json").write_text(json.dumps(existing))
        install("codex", self.home)
        install("codex", self.home)
        hooks = self.config(".codex/hooks.json")["hooks"]["PreToolUse"]
        self.assertEqual(len(hooks), 2)  # yours, and the guard on every tool call
        self.assertIn("mine.sh", json.dumps(hooks[0]))
        self.assertNotIn("matcher", hooks[1])
        self.assertTrue((self.home / ".codex/hooks.json.bak").is_file())

    def test_unknown_agent_is_refused(self):
        self.assertNotEqual(install("vim", self.home).returncode, 0)


if __name__ == "__main__":
    unittest.main()
