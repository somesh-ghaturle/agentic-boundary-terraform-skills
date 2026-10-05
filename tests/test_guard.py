"""The first lock: the hook blocks every way of changing infrastructure it can see."""
import json
import pathlib
import subprocess
import sys
import unittest

GUARD = pathlib.Path(__file__).resolve().parents[1] / "hooks" / "guard.py"


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

    def test_ignores_other_tools(self):
        self.assertEqual(run("terraform apply", tool="Read"), 0)


if __name__ == "__main__":
    unittest.main()
