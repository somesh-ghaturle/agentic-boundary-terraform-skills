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
4. Runs four gates and stops at the first failure: the tree's write-boundary tests, the provider-pin check, the OPA policies, and `terraform validate` on every environment.
5. Reviews the change against the threat model, and records evidence for regulated environments.
6. Runs `terraform plan` if you ask, then stops. A human runs `apply`.

The script also works without Claude:

```bash
skills/terraform-boundary/scripts/boundary.sh fetch gcp ./infra
skills/terraform-boundary/scripts/boundary.sh check ./infra
```

## Status

Version 1.0.1. The skill works for all four clouds. A clean tree passes every gate on AWS, Azure, GCP and Snowflake.

`tests/test_boundary.sh` proves the gate works. It fetches the AWS tree, checks that it passes, then makes the one-word edit that hands every tool to the orchestrator and checks that the gate refuses it.

```bash
bash tests/test_boundary.sh
```

Security review and regulated-environment evidence are sections of the one skill for now. They become separate skills when they have checks of their own to run.

## License

Apache License 2.0. See [LICENSE](LICENSE).
