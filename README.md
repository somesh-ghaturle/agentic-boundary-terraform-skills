# Agentic Boundary Terraform Skills

A Claude Code skill for deploying an AI agent whose state-changing actions cannot reach production without a human approving that exact action. It adapts the Terraform in [Agentic-AI-Systems](https://github.com/somesh-ghaturle/Agentic-AI-Systems) instead of copying it by hand, and it gates every change on that repository's own write-boundary checks.

## Install

In a Claude Code session:

```text
/plugin marketplace add somesh-ghaturle/agentic-boundary-terraform-skills
/plugin install agentic-boundary-terraform@agentic-boundary
```

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
| Claude Code hook | `hooks/guard.py` | The agent running `terraform apply`, `destroy`, `-auto-approve` or `boundary.sh apply` |
| Human-only apply | `boundary.sh apply` | Applying without a terminal, or applying any plan other than the one whose fingerprint you typed |
| Read-only credentials | Your cloud account | Everything else. Give the agent's session a read-only identity and keep deploy credentials for your own terminal |

This is the same design Agentic-AI-Systems uses for the agents it deploys: the orchestrator holds read tools only, and a human approves each exact action.

## Status

Version 1.1.0. The skill works for all four clouds. A clean tree passes every gate on AWS, Azure, GCP and Snowflake.

Two test files prove it:

```bash
bash tests/test_boundary.sh        # every bypass tried is refused; apply needs a terminal and the exact fingerprint
python3 -m unittest tests/test_guard.py   # the hook blocks every state-changing command it can see
```

The gate trusts nothing in your project except the Terraform it judges. Its tests, policies and checker come from the pinned release on every run, so editing them in the project changes nothing.

## Limits

The gates read Terraform source as text. They refuse symlinks, `.tf.json` files and override files, because Terraform reads those and the tests do not. They cannot see values in `.tfvars`, including whether each tool is labelled `read` or `write`, or anything only known at plan time. That is why `boundary.sh apply` puts both in front of you before you type the fingerprint. The hook and the terminal check read text, so read-only credentials for the agent are the lock that holds when everything else is tricked.

Security review and regulated-environment evidence are sections of the one skill for now. They become separate skills when they have checks of their own to run.

## License

Apache License 2.0. See [LICENSE](LICENSE).
