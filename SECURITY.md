# Security policy

This skill exists to keep a human in the loop before an AI coding agent changes infrastructure. A way for the agent to apply, destroy or otherwise change infrastructure without the human is a security bug.

## Reporting a vulnerability

Report privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Please don't open a public issue for a bypass.

Include the agent (Claude Code, Codex, Cursor or Windsurf), the exact command or tool call, and what it achieved.

## Supported versions

Only the latest release gets fixes. Every fix ships with a test that proves the bypass is refused.

## What is in scope

- A command or tool call that gets past the agent hook (`skills/terraform-boundary/hooks/guard.py`) and changes infrastructure.
- A way for the agent to complete `boundary.sh apply` without the human typing the plan's fingerprint.
- A way to weaken the gates `boundary.sh check` runs, or to make apply use a tree or providers other than the gated copy.

## Known limits

The hook and the human-only apply run on the same machine as the agent, so they raise the bar rather than guarantee it. A script or variable that never names Terraform is invisible to any command guard. Read-only cloud credentials for the agent are the lock that holds; see the README.
