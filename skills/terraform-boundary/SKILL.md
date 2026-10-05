---
name: terraform-boundary
description: Deploy or change an AI agent's cloud infrastructure on AWS, Azure, GCP or Snowflake so that no state-changing tool can run without a human approving that exact action. Copies a pinned Agentic-AI-Systems Terraform tree, adapts it, and gates every edit on that repository's own write-boundary tests, provider-pin check, OPA policies and terraform validate. Includes a threat-model review and evidence capture for regulated environments. Use when the user wants to deploy an agent with human approval gates, pick a cloud for one, adapt the agentic Terraform, or check that a Terraform change keeps write tools away from the orchestrator. Stops at terraform plan; never runs apply.
---

# Terraform boundary

The property this skill protects: **the orchestrator can invoke read tools only. Write tools run only through the approval executor, after a human approves that specific action.** The cloud's identity platform enforces it, not the prompt.

Source of truth: [Agentic-AI-Systems at v0.1.0](https://github.com/somesh-ghaturle/Agentic-AI-Systems/tree/v0.1.0). The script pins that release by tag and commit, so the Terraform never drifts under you. `check` runs the tests, policies and provider-pin checker from a fresh copy of that release, never the copies in the project, so editing them cannot change a verdict. Moving to a newer release means updating this skill.

## The human stays in the loop: three locks

The skill applies Agentic-AI-Systems' own rule to itself. The agent is the orchestrator: it reads, checks and plans. Only a human changes infrastructure.

1. **Claude Code hook:** this plugin's `PreToolUse` hook blocks every `terraform` or `tofu` subcommand outside a read-only list, any `-auto-approve`, and `boundary.sh apply`. Claude Code enforces it, not this text.
2. **Human-only apply:** `boundary.sh apply` refuses to run without a real terminal. It reruns every gate and then makes its own plan from the gated copy, with providers downloaded fresh. The human's credentials never run the agent's plan file or provider binaries, and what gets applied is exactly what was gated. It shows the tool labels and every permission change, and applies only after the human types the plan's fingerprint. This is the Hermes approval pattern: bound to the exact action and used once.
3. **Read-only cloud credentials for the agent:** the first two locks read text and check for a terminal, so a determined process could get around them. Cloud credentials cannot be talked around. Tell the user to give the agent's session a read-only identity, such as AWS `ReadOnlyAccess`, GCP Viewer, Azure Reader or a Snowflake role without write grants, and to keep deploy credentials for the human's own terminal. Recommend this every time; it is the lock the other two exist to back up.

## Hard rules

1. **Never run `terraform apply`**, `destroy` or `boundary.sh apply`, and never try to get around the hook. Stop at `plan` and hand it to a human. An agent applying its own infrastructure is the exact failure this skill exists to prevent.
2. **Never edit anything under `terraform-<cloud>/tests/` or `.boundary/`** to make a gate pass. A failing gate means the change is wrong. Fix the change, or stop and tell the user which gate failed and why.
3. **Never widen what the orchestrator can invoke.** No write tool ARN, role, member or grant reaches the orchestrator's identity, directly or through inheritance.
4. **Never relabel a write tool as `read`**, in `.tf` or in `.tfvars`. Tool declarations, including each tool's `access` label, live in `terraform.tfvars`, which no gate can read. The label is trusted, so only a human can catch a wrong one.
5. **Say where the clouds differ.** Do not tell the user the guarantee is the same everywhere. It is not.

## Step 1: pick the cloud

Ask what the user already runs on, then use this table. It summarises [CHOOSING-A-TREE.md](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/infra/CHOOSING-A-TREE.md). Read that file when the choice is not obvious.

| If this is true | Use | Boundary |
| --- | --- | --- |
| Wants the strongest boundary and can get `roles/iam.denyAdmin` | `gcp` | Per-service Cloud Run IAM plus an IAM Deny policy. The only boundary that survives a later broad grant |
| Wants two independent locks with no prerequisites outside the account | `aws` | Orchestrator identity policy lists read tools only, and each write tool's resource policy admits only the executor |
| Already on Azure, or needs a first-class Terraform content filter | `azure` | One lock, `app_role_assignment_required = true`, plus two mitigations. Thinner than AWS and GCP. Tell the user |
| The agent's tools are queries over data already in Snowflake | `snowflake` | The role graph. Strong, but one inherited role grant undoes it. Approvals are polled, not called back |

If nothing decides it, use `aws`. The hybrid tree in that repo is an opt-in proof of concept. Do not offer it for production.

## Step 2: fetch the tree

```bash
scripts/boundary.sh fetch <aws|azure|gcp|snowflake> <project-dir>
```

This writes `<project-dir>/terraform-<cloud>/` and `<project-dir>/.boundary/pin`, which records the cloud. It refuses to overwrite an existing tree. Paths to `scripts/` are relative to this skill's directory.

Then run the gates once, before any edit, so you know the starting point is clean:

```bash
scripts/boundary.sh check <project-dir>
```

`check` needs `python3`, `terraform` and `conftest`. It fails, not skips, when one is missing.

## Step 3: adapt

Work in `envs/<env>/` first: names, regions, sizes, tags, variables. Each tree's `HOW-TO-DEPLOY.md` lists the inputs. Adding a **read** tool is ordinary work.

These are boundary-critical. Change them only when the user asks for exactly that, and explain the consequence before you do:

- **aws:** `tool_function_arns` in every env root must be built from `module.tools.read_tool_arns`, never `tool_arns_by_name`. Keep `aws_lambda_permission.write_tool_from_approval` naming the executor, and keep `read_tool_arns` filtered on `access == "read"`.
- **azure:** `app_role_assignment_required = true` on each tool's service principal in `modules/tools`. The Entra audit alert in `envs/tenant` watches it.
- **gcp:** each write tool's Cloud Run policy in `modules/tools` grants `roles/run.invoker` to the executor only. Keep `google_iam_deny_policy.write_boundary` in `modules/orchestration`.
- **snowflake:** no role grant, direct or inherited, may connect the orchestrator role to the executor role. Do not follow Snowflake's SYSADMIN convention here.
- **Adding a write tool:** on `aws`, `azure` and `gcp`, declare it with `access = "write"` so the tree routes it through approval. On `snowflake`, add it to the `write_tools` variable of `modules/tools`, which grants USAGE to the executor role alone, and make it idempotent on the approval ID it receives. Then rerun the gates.

Section 2 of each tree's `ARCHITECTURE.md` explains why each line matters. Read it before touching one.

## Step 4: gate

```bash
set -o pipefail; scripts/boundary.sh check <project-dir> 2>&1 | tee <project-dir>/.boundary/evidence-$(date +%F).log
```

`pipefail` matters: without it the pipeline reports `tee`'s success even when a gate failed. A non-zero exit means stop.

`check` copies the tree to a scratch folder first and judges only the copy, so nothing can be swapped in mid-check. It refuses symlinks, `.tf.json` files and override files, because Terraform reads them and the text-based tests do not. It also refuses module or provider sources that are remote, or that leave the tree, unless the pinned release already uses them. And it refuses provisioners, external data sources and any state backend except an empty local one, because each can run commands or send state elsewhere under whoever applies. Remote state is not supported by `boundary.sh apply` yet. The gates then run in order and stop at the first failure:

1. **write boundary:** the pinned release's tests for that tree, which read your `.tf` source and fail on the edits `terraform validate` accepts.
2. **provider pins:** every provider pins a major, and one tree agrees with itself.
3. **policies:** the OPA policies, such as a content filter that nothing references.
4. **validate:** `terraform init -backend=false` and `validate` on every env root.

All four must pass before Step 5. Keep the evidence log; the regulated section below uses it.

## Step 5: plan, then stop

For `aws`, `azure` and `gcp`, run `terraform-<cloud>/src/build.sh` first, because plan reads the function packages. If the user wants a preview and the agent has read-only cloud credentials, run `terraform -chdir=<project-dir>/terraform-<cloud>/envs/<env> plan`, show the summary, and stop. This preview is never applied.

Then tell the human to run this in their own terminal, with their own deploy credentials:

```bash
scripts/boundary.sh apply <project-dir> <env>
```

It plans again from the gated copy and shows them what no static gate can see: every tool's `access` label from `terraform.tfvars`, and every permission the plan changes. Every tool that changes state must say `write`, and the orchestrator must gain read tools only. On `snowflake`, tool labels live in `.tf` files, so the gates already check them. The human types the plan's fingerprint to apply, or anything else to stop.

## Security review

Before Step 5, answer these four questions in writing for the change you made. They come from [THREAT-MODEL.md](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/docs/THREAT-MODEL.md):

1. **Compromised orchestrator:** what can it invoke now that it could not before?
2. **Prompt-injected model:** can model output now reach a write tool without an approval?
3. **Leaked approval claim:** is it still single-use, bound to the exact arguments, and expiring?
4. **Terraform change:** would a later broad grant reopen the path? Only `gcp` survives that by design.

If any answer is "more than before", stop and tell the user before planning.

## Regulated environments

For a regulated deployment, also work through the [governance](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/docs/governance-checklist.md), [security](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/docs/security-checklist.md) and [privacy](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/docs/privacy-checklist.md) checklists, and read [COMPLIANCE.md](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/COMPLIANCE.md) for the evidence model.

Hand the user one evidence record per change: the Step 4 log, whose last line names the release and commit the gates ran against, the four security answers, the plan summary, and the name of the human who will apply it. These checklists support a compliance review. They do not certify one, and you must not say that they do.
