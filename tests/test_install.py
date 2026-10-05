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

    def test_cursor_hook_fails_closed_and_only_matches_terraform(self):
        install("cursor", self.home)
        entry = self.config(".cursor/hooks.json")["hooks"]["beforeShellExecution"][0]
        self.assertTrue(entry["failClosed"])
        self.assertIn("terraform", entry["matcher"])

    def test_keeps_existing_hooks_and_is_idempotent(self):
        existing = {"hooks": {"PreToolUse": [{"matcher": "^Bash$", "hooks": [{"type": "command", "command": "mine.sh"}]}]}}
        (self.home / ".codex").mkdir()
        (self.home / ".codex/hooks.json").write_text(json.dumps(existing))
        install("codex", self.home)
        install("codex", self.home)
        hooks = self.config(".codex/hooks.json")["hooks"]["PreToolUse"]
        self.assertEqual(len(hooks), 2)
        self.assertIn("mine.sh", json.dumps(hooks[0]))
        self.assertTrue((self.home / ".codex/hooks.json.bak").is_file())

    def test_unknown_agent_is_refused(self):
        self.assertNotEqual(install("vim", self.home).returncode, 0)


if __name__ == "__main__":
    unittest.main()
