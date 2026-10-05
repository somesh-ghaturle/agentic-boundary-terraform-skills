"""The first lock: the hook blocks every way of changing infrastructure it can see."""
import json
import pathlib
import subprocess
import sys
import unittest

GUARD = pathlib.Path(__file__).resolve().parents[1] / "skills" / "terraform-boundary" / "hooks" / "guard.py"


def run(command, tool="Bash"):
    event = {"tool_name": tool, "tool_input": {"command": command}}
    return subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event),
                          capture_output=True, text=True).returncode


class Guard(unittest.TestCase):
    def test_blocks_state_changes(self):
        for cmd in [
            "terraform apply",
            "terraform -chdir=infra/envs/dev apply tfplan",
            "cd infra && terraform destroy",
            "terraform plan -out=x && terraform apply x",
            "/usr/local/bin/terraform import aws_iam_role.x y",
            "terraform state rm module.tools",
            "tofu apply",
            "terraform test",
            "terraform workspace delete prod",
            'sh -c "terraform apply -input=false tfplan"',
            "bash -lc 'cd x; terraform apply'",
            "terraform plan -auto-approve",
            "skills/terraform-boundary/scripts/boundary.sh apply ./infra dev",
            "terraform plan;terraform apply",
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(cmd), 2)

    def test_allows_reading_and_planning(self):
        for cmd in [
            "terraform init -backend=false",
            "terraform -chdir=infra/envs/dev plan -out=tfplan",
            "terraform validate && terraform fmt -check",
            "terraform show -json tfplan | python3 summarise.py",
            "terraform",
            "boundary.sh check ./infra",
            "echo apply",
            "git status",
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(cmd), 0)

    def test_blocks_what_the_shell_would_turn_into_terraform(self):
        for cmd in [
            "TERRAFORM apply",
            "Terraform destroy",
            '"terra""form" apply',
            "t\\erraform apply",
            "{terraform,apply}",
            "terraform${IFS}apply",
            "echo apply | xargs terraform",
            "alias tf=terraform; tf apply",
            "$'\\x74erraform' apply",
            "terraform -chdir=$DIR plan",
            "terraform plan -AUTO-APPROVE",
            "echo a#b; terraform apply",
            "terragrunt apply",
            "terragrunt run-all apply",
            "terragrunt run --all -- destroy",
            "cdktf deploy",
            "cdktf destroy",
            "perl -e 'system(\"terraform\",\"apply\")'",
            "terraform.exe apply",
            "terraform_1.15.8 apply",
            "~/.local/bin/terraform-1.15 apply",
            "terraspace up",
            "terraspace all down",
            "python3 -c 'import pty; pty.spawn([\"scripts/boundary.sh\",\"apply\",\"./infra\",\"dev\"])'",
            "script -q /dev/null scripts/boundary.sh apply ./infra dev",
            "/usr/bin/expect -c 'spawn scripts/boundary.sh apply ./infra dev'",
            "ter\\\nraform apply",
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(cmd), 2)

    def test_allows_the_commands_the_skill_itself_runs(self):
        for cmd in [
            "terraform -chdir=infra/terraform-aws/envs/dev plan",
            "infra/terraform-aws/src/build.sh",
            "ls terraform-gcp/envs",
            "set -o pipefail; scripts/boundary.sh check ./infra 2>&1 | tee ./infra/.boundary/evidence-2026-10-04.log",
            "scripts/boundary.sh fetch aws ./infra",
            "terragrunt plan",
            "terragrunt run-all plan",
            "cdktf synth",
            "cdktf diff",
            "ls infra/terraform/envs",
            "terraform -chdir=infra/terraform/envs/dev plan",
            'bash -lc "cd infra && terraform plan"',
            "terraform-docs markdown .",
            "terraspace plan",
        ]:
            with self.subTest(cmd=cmd):
                self.assertEqual(run(cmd), 0)

    def test_ignores_other_tools(self):
        self.assertEqual(run("terraform apply", tool="Read"), 0)


def raw(event):
    proc = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(event), capture_output=True, text=True)
    return proc.returncode, proc.stdout


class FailClosedAndEveryTool(unittest.TestCase):
    """Anything the guard cannot read blocks; any tool that is not known to be harmless is checked."""

    def run_raw(self, text):
        return subprocess.run([sys.executable, str(GUARD)], input=text, capture_output=True, text=True).returncode

    def test_unreadable_or_unrecognised_input_blocks(self):
        self.assertEqual(self.run_raw("not json"), 2)
        self.assertEqual(self.run_raw(json.dumps({"something": "else"})), 2)

    def test_other_tools_that_run_commands_are_checked(self):
        self.assertEqual(raw({"tool_name": "Monitor", "tool_input": {"command": "terraform apply -input=false"}})[0], 2)
        self.assertEqual(raw({"tool_name": "PowerShell", "tool_input": {"command": "terraform destroy"}})[0], 2)
        self.assertEqual(raw({"tool_name": "Monitor", "tool_input": {"command": "tail -f app.log"}})[0], 0)

    def test_content_tools_may_mention_terraform_apply(self):
        self.assertEqual(raw({"tool_name": "Write", "tool_input": {"file_path": "README.md", "content": "Run terraform apply yourself."}})[0], 0)
        self.assertEqual(raw({"tool_name": "Read", "tool_input": {"file_path": "docs/terraform-apply.md"}})[0], 0)


class McpTools(unittest.TestCase):
    """An MCP tool that runs commands is a second shell; every agent's MCP hook is checked."""

    def test_claude_and_codex(self):
        self.assertEqual(raw({"tool_name": "mcp__shell__run", "tool_input": {"cmd": "terraform apply -input=false"}})[0], 2)
        self.assertEqual(raw({"tool_name": "mcp__shell__run", "tool_input": {"args": {"line": ["cd x", "terragrunt apply"]}}})[0], 2)
        self.assertEqual(raw({"tool_name": "mcp__github__create_issue", "tool_input": {"title": "Review the plan"}})[0], 0)

    def test_windsurf(self):
        event = lambda args: {"agent_action_name": "pre_mcp_tool_use",
                              "tool_info": {"mcp_server_name": "shell", "mcp_tool_name": "run", "mcp_tool_arguments": args}}
        self.assertEqual(raw(event({"command": "terraform destroy"}))[0], 2)
        self.assertEqual(raw(event({"command": "ls"}))[0], 0)

    def test_cursor_denies_asks_or_steps_aside(self):
        event = lambda args: {"tool_name": "run", "tool_input": json.dumps(args), "mcp_server_name": "shell"}
        code, out = raw(event({"command": "terraform apply"}))
        self.assertEqual((code, json.loads(out)["permission"]), (2, "deny"))
        code, out = raw(event({"command": "terraform plan"}))
        self.assertEqual((code, json.loads(out)["permission"]), (0, "ask"))
        # Unrelated: exit 1 means Cursor's normal flow, never an automatic allow.
        self.assertEqual(raw(event({"query": "list issues"})), (1, ""))


class OtherAgents(unittest.TestCase):
    """The same guard, fed each agent's own hook payload."""

    def test_codex_argv_list(self):
        self.assertEqual(raw({"tool_name": "Bash", "tool_input": {"command": ["bash", "-lc", "terraform apply"]}})[0], 2)
        self.assertEqual(raw({"tool_name": "Bash", "tool_input": {"command": ["terraform", "plan"]}})[0], 0)

    def test_windsurf_pre_run_command(self):
        event = lambda c: {"agent_action_name": "pre_run_command", "tool_info": {"command_line": c, "cwd": "/x"}}
        self.assertEqual(raw(event("terraform -chdir=infra destroy"))[0], 2)
        self.assertEqual(raw(event("terraform plan"))[0], 0)
        self.assertEqual(raw(event("ls"))[0], 0)

    def test_cursor_denies_with_json_and_exit_2(self):
        code, out = raw({"command": "terraform apply tfplan", "cwd": "/x", "sandbox": False})
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(out)["permission"], "deny")

    def test_cursor_never_auto_allows(self):
        code, out = raw({"command": "terraform plan", "cwd": "/x", "sandbox": False})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["permission"], "ask")


if __name__ == "__main__":
    unittest.main()
