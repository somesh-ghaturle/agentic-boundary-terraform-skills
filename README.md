# Agentic Boundary Terraform Skills

Claude Code skills for deploying an AI agent whose state-changing actions cannot reach production without a human approving that exact action. The skills adapt the Terraform in [Agentic-AI-Systems](https://github.com/somesh-ghaturle/Agentic-AI-Systems) instead of copying it, and they gate every change on that repository's own write-boundary checks.

## Planned skills

| Skill | What it does |
| --- | --- |
| `terraform-boundary` | Picks a cloud tree, adapts it, and keeps the read/write tool split intact across AWS, Azure, GCP and Snowflake |
| `regulated-environments` | Maps the deployment to the controls a regulated environment asks for, and records the evidence |
| `security` | Reviews a change against the threat model before it reaches `terraform plan` |

## Ground rules

- The skills stop at `terraform plan`. A human runs `apply`.
- They pin a release of Agentic-AI-Systems, starting with `v0.1.0`, so the Terraform they adapt does not drift.
- They say where the clouds differ instead of promising the same guarantee everywhere.

## Status

Scaffolding. No skill is usable yet.

## License

Apache License 2.0. See [LICENSE](LICENSE).
