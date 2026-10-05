# Agentic Boundary Terraform Skills

A Claude Code skill for deploying an AI agent whose state-changing actions cannot reach production without a human approving that exact action. It adapts the Terraform in [Agentic-AI-Systems](https://github.com/somesh-ghaturle/Agentic-AI-Systems) instead of copying it by hand, and it gates every change on that repository's own write-boundary checks.

It is built on three pillars, and does nothing outside them:

| Pillar | What you get |
| --- | --- |
| **Human in the loop** | Only you change infrastructure. The agent reads, checks and plans; three independent locks stop it from applying |
| **Security** | The agent's orchestrator can call read tools only. Every change runs your repo's write-boundary gates and a four-question threat-model review before it is planned |
| **Regulated environments** | Every change produces an evidence record: the pinned release it was gated against, the gate results, the security review, the governance, security and privacy checklists, and the human who approved it |

**What it will not do.** It never applies, destroys or imports anything. It does not write general Terraform, application code, CI/CD pipelines or cost tuning, and it does not touch files the task did not ask about. Asked for any of that, it says the request is out of scope and stops.

## Install

It works in Claude Code, Codex, Cursor and Windsurf. The skill, the gates and the human-only apply are the same everywhere; each agent gets the same guard through its own hook system.

**Claude Code**, in a session:

```text
/plugin marketplace add somesh-ghaturle/agentic-boundary-terraform-skills
/plugin install agentic-boundary-terraform@agentic-boundary
```

**Codex, Cursor or Windsurf**, from a clone of this repository:

```bash
git clone https://github.com/somesh-ghaturle/agentic-boundary-terraform-skills.git
cd agentic-boundary-terraform-skills
python3 install.py codex      # or: cursor, windsurf
```

`install.py` copies the skill to `~/.agents/skills/terraform-boundary`, which all three load skills from, and adds the guard to that agent's user-level hooks:

| Agent | Hook file | Hook events | Behaviour |
| --- | --- | --- | --- |
| Codex | `~/.codex/hooks.json` | `PreToolUse`, every tool | Blocks state-changing Terraform commands from the shell, an MCP tool or any other tool that runs commands |
| Cursor | `~/.cursor/hooks.json` | `beforeShellExecution`, `beforeMCPExecution` | Blocks them, and asks you to confirm every other Terraform-related call. The shell hook fails closed. On unrelated MCP calls the guard steps aside with exit code 1, which Cursor logs as a hook failure and lets through its normal approval flow, so nothing is ever auto-approved |
| Windsurf | `~/.codeium/windsurf/hooks.json` | `pre_run_command`, `pre_mcp_tool_use` | Blocks state-changing Terraform commands, from the shell or an MCP tool |

It keeps any hooks you already have, backs up the file it changes, and does nothing the second time. It installs at user level on purpose: a hook file inside a project is one the agent can edit.

The gates need `python3`, `terraform` and [`conftest`](https://www.conftest.dev/install/) on your machine.

## Use

Ask Claude to deploy or change an agent with human approval gates, for example "set up the approval-gated agent on GCP in ./infra". The `terraform-boundary` skill then:

1. Picks a cloud with you: AWS, Azure, GCP or Snowflake, and says where their guarantees differ.
2. Copies that tree from Agentic-AI-Systems at the pinned tag `v0.1.0`.
3. Adapts it, without touching the lines that keep write tools away from the orchestrator.
4. Runs four gates and stops at the first failure: the pinned release's write-boundary tests, provider-pin check and OPA policies, and `terraform validate` on every environment.
5. Reviews the change against the threat model, and records evidence for regulated environments.
6. Runs `terraform plan` if you ask, then stops. You apply it yourself with `boundary.sh apply`, after reading the tool labels and permission changes and typing the plan's fingerprint.

The script also works without Claude:

```bash
skills/terraform-boundary/scripts/boundary.sh fetch gcp ./infra
skills/terraform-boundary/scripts/boundary.sh check ./infra
skills/terraform-boundary/scripts/boundary.sh apply ./infra dev   # human only, in a terminal
```

## Human in the loop

The agent can read, check and plan. Only you can change infrastructure, and three independent locks hold that line:

| Lock | Where | What it stops |
| --- | --- | --- |
| Agent hook | `skills/terraform-boundary/hooks/guard.py` | The agent running `terraform apply`, `destroy`, `-auto-approve` or `boundary.sh apply`, directly, through `terragrunt`, `cdktf` or `terraspace`, or through an MCP tool, in Claude Code, Codex, Cursor or Windsurf |
| Human-only apply | `boundary.sh apply` | Applying without a terminal, applying anything but a fresh plan of the gated copy, or applying a plan whose fingerprint you did not type. Your credentials never run the agent's plan file or provider binaries |
| Read-only credentials | Your cloud account | Everything else. Give the agent's session a read-only identity and keep deploy credentials for your own terminal |

This is the same design Agentic-AI-Systems uses for the agents it deploys: the orchestrator holds read tools only, and a human approves each exact action.

## Security

Every change runs the pinned release's own gates: the write-boundary tests, the provider-pin check, the OPA policies and `terraform validate`. The gates trust nothing in your project except the Terraform they judge. Before anything is planned, the skill answers four questions from the [threat model](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/docs/THREAT-MODEL.md): what a compromised orchestrator, a prompt-injected model, a leaked approval claim and a later Terraform change could now reach. If any answer is "more than before", it stops.

## Regulated environments

The skill works through the [governance](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/docs/governance-checklist.md), [security](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/docs/security-checklist.md) and [privacy](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/docs/privacy-checklist.md) checklists and hands you one evidence record per change. You fill in its last line, the date and the plan fingerprint you typed, because only you apply. The record supports a compliance review; it does not certify one.

## Status

Version 1.5.0. The skill works for all four clouds. A clean tree passes every gate on AWS, Azure, GCP and Snowflake.

Two test files prove it:

```bash
bash tests/test_boundary.sh        # every bypass tried is refused; apply needs a terminal and the exact fingerprint
python3 -m unittest tests/test_guard.py tests/test_state.py tests/test_install.py   # the guard in all four agents, state handling, the installer
```

The gate trusts nothing in your project except the Terraform it judges. Its tests, policies and checker come from the pinned release on every run, so editing them in the project changes nothing.

## Limits

The gates read Terraform source as text. They run `terraform fmt` on a copy first, so spacing and label quoting match what the tests expect, and they refuse symlinks, `.tf.json` files, override files and `/* */` block comments, because Terraform reads or ignores those differently from the tests. They also refuse remote module sources, provisioners, external data sources and any state backend except an empty local one. Remote state is not supported by `boundary.sh apply` yet. They cannot see values in `.tfvars`, including whether each tool is labelled `read` or `write`, or anything only known at plan time. That is why `boundary.sh apply` puts both in front of you before you type the fingerprint. The guard denies any command that mentions Terraform and also uses shell expansion or indirection, and compares names case-insensitively, but a script, a variable or code that builds the name at runtime is invisible to it in every agent. In Claude Code and Codex every tool call is checked except tools that only carry file content or prose, and in Cursor and Windsurf every MCP call. String arguments are read as commands, so a message that merely quotes `terraform apply` is denied too. The guard fails closed: input it cannot read blocks the call. Driving `boundary.sh apply` through a terminal the agent controls, such as `script`, `expect` or a Python pty, is denied, but lock 2 cannot tell a human from a program at a terminal, which is one more reason lock 3 matters. The hook and the terminal check read text, so read-only credentials for the agent are the lock that holds when everything else is tricked.

## License

Apache License 2.0. See [LICENSE](LICENSE).
