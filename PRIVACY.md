# Privacy

Terraform Boundary collects no data. It has no telemetry, no analytics and no server of its own.

Everything runs on your machine, inside your coding agent:

- The guard hook reads each tool call locally to decide whether to block it. Nothing is logged or sent anywhere.
- `boundary.sh fetch` and `boundary.sh check` download the pinned Agentic-AI-Systems release from GitHub, and Terraform downloads its providers from the Terraform registry. Those services' own privacy policies apply to those downloads.
- Your cloud credentials, Terraform state and plans stay where you keep them. The skill never sends them anywhere.

Questions: open an issue at https://github.com/somesh-ghaturle/agentic-boundary-terraform-skills/issues.
