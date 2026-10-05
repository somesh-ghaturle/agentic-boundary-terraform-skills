---
name: terraform-boundary
description: Human-in-the-loop deployment of an AI agent's cloud infrastructure, with security review and regulated-environment evidence. Adapts a pinned Agentic-AI-Systems Terraform tree on AWS, Azure, GCP or Snowflake so that no state-changing tool runs without a human approving that exact action, gates every edit on that repository's own write-boundary checks, and leaves apply to a human. Use only when the user wants to deploy, adapt or check an approval-gated agent built from Agentic-AI-Systems, or needs its security review or compliance evidence. Do not use for general Terraform, other infrastructure, application code or anything outside that scope.
---

# Terraform boundary

This skill does one job, built on three pillars. Every step below serves one of them.

| Pillar | What it guarantees |
| --- | --- |
| **1. Human in the loop** | Only a human changes infrastructure. The agent reads, checks and plans. Three independent locks hold that line |
| **2. Security** | The orchestrator can invoke read tools only. Write tools run only through the approval executor, after a human approves that exact action. Every change is reviewed against the threat model before it is planned |
| **3. Regulated environments** | Every change leaves an evidence record a reviewer can follow: what was gated, against which pinned release, what the security review found, and which human approved what |

The cloud's identity platform enforces the property, not the prompt.

## Scope: this work and nothing else

**In scope:**

- Picking a cloud tree from Agentic-AI-Systems, fetching it, and adapting it within the rules in Step 3.
- Running the gates, the security review and the evidence record for that tree.
- Previewing a plan with read-only credentials, and handing the apply to a human.

**Out of scope.** Do not do these under this skill, even if they look related or helpful:

- Applying, destroying or importing anything, or helping get around a lock.
- General Terraform, other infrastructure, or Terraform not from Agentic-AI-Systems.
- Application code, the agent's prompts or model choice, CI/CD pipelines, cost tuning or refactoring modules.
- The hybrid tree, remote state backends, or editing Agentic-AI-Systems itself.
- Tidying, renaming or "improving" files the task did not ask about.

**When a request is out of scope**, say in one sentence that it is outside this skill, name what it would need instead, and stop. Do not expand the task, start a side quest, or do it anyway. **When a request is in scope**, do exactly that change and nothing more, then run the gates.

Source of truth: [Agentic-AI-Systems at v0.1.0](https://github.com/somesh-ghaturle/Agentic-AI-Systems/tree/v0.1.0). The script pins that release by tag and commit, so the Terraform never drifts under you. `check` runs the tests, policies and provider-pin checker from a fresh copy of that release, never the copies in the project, so editing them cannot change a verdict. Moving to a newer release means updating this skill.

## Pillar 1: human in the loop, three locks

The skill applies Agentic-AI-Systems' own rule to itself. The agent is the orchestrator: it reads, checks and plans. Only a human changes infrastructure.

1. **Agent hook:** the same guard, `hooks/guard.py` in this skill, runs before every shell command and every MCP tool call the agent makes in Claude Code, Codex, Cursor and Windsurf, and in Claude Code and Codex before every other tool that is not a pure file or prose tool. It fails closed. It blocks every `terraform` or `tofu` subcommand outside a read-only list, the same for wrappers that run them (`terragrunt`, `cdktf`, `terraspace`) and for versioned binaries such as `terraform_1.15.8`, any `-auto-approve`, Terraform named inside other code, and `boundary.sh apply`. The agent tool enforces it, not this text. In Cursor it also asks the human to confirm every Terraform command, read-only ones included. Read, copy and edit Terraform files such as `terraform.tfvars` with your file tools, not the shell: the guard treats any Terraform-like name in a shell command as the binary. Write every Terraform command out literally: a command that mentions Terraform is denied if it also uses `$`, backticks, braces, globs, `xargs`, `alias` or `eval`, because the shell could turn those into something the guard never saw.
2. **Human-only apply:** `boundary.sh apply` refuses to run without a real terminal, whichever agent is in use. It reruns every gate and then makes its own plan from the gated copy, with providers downloaded fresh. The human's credentials never run the agent's plan file or provider binaries, and what gets applied is exactly what was gated. It shows the tool labels and every permission change, and applies only after the human types the plan's fingerprint. This is the Hermes approval pattern: bound to the exact action and used once.
3. **Read-only cloud credentials for the agent:** the first two locks read text and check for a terminal, so a determined process could get around them. Cloud credentials cannot be talked around. Tell the user to give the agent's session a read-only identity, such as AWS `ReadOnlyAccess`, GCP Viewer, Azure Reader or a Snowflake role without write grants, and to keep deploy credentials for the human's own terminal. Recommend this every time; it is the lock the other two exist to back up.

## Pillar 2: security review

The boundary itself is the security property; the locks above and the gates in Step 4 protect it. On top of that, before Step 5, answer these four questions in writing for every change. They come from [THREAT-MODEL.md](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/docs/THREAT-MODEL.md):

1. **Compromised orchestrator:** what can it invoke now that it could not before?
2. **Prompt-injected model:** can model output now reach a write tool without an approval?
3. **Leaked approval claim:** is it still single-use, bound to the exact arguments, and expiring?
4. **Terraform change:** would a later broad grant reopen the path? Only `gcp` survives that by design.

If any answer is "more than before", stop and tell the user before planning.

## Pillar 3: regulated environments

For a regulated deployment, work through the [governance](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/docs/governance-checklist.md), [security](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/docs/security-checklist.md) and [privacy](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/docs/privacy-checklist.md) checklists, and read [COMPLIANCE.md](https://github.com/somesh-ghaturle/Agentic-AI-Systems/blob/v0.1.0/COMPLIANCE.md) for the evidence model.

Hand the user one evidence record per change, in this shape:

```text
Change:            <one line: what changed and why>
Cloud and env:     <aws|azure|gcp|snowflake> / <env>
Pinned release:    <last line of the Step 4 log: tag and commit>
Gates:             <pass, with the path to the Step 4 log>
Security review:   <the four answers from Pillar 2>
Checklists:        <governance, security, privacy: items reviewed, items open>
Plan preview:      <summary, or "not run: no read-only credentials">
Approver:          <the human who will run boundary.sh apply>
Applied:           <filled in by that human: date and plan fingerprint they typed>
```

The agent fills in everything above `Applied`. Only the human fills in `Applied`, because only the human applies. These checklists support a compliance review. They do not certify one, and you must not say that they do.

## Hard rules

1. **Never run `terraform apply`**, `destroy` or `boundary.sh apply`, and never try to get around the guard, in any agent tool. Stop at `plan` and hand it to a human. An agent applying its own infrastructure is the exact failure this skill exists to prevent.
2. **Never edit anything under `terraform-<cloud>/tests/` or `.boundary/`** to make a gate pass. A failing gate means the change is wrong. Fix the change, or stop and tell the user which gate failed and why.
3. **Never widen what the orchestrator can invoke.** No write tool ARN, role, member or grant reaches the orchestrator's identity, directly or through inheritance.
4. **Never relabel a write tool as `read`**, in `.tf` or in `.tfvars`. Tool declarations, including each tool's `access` label, live in `terraform.tfvars`, which no gate can read. The label is trusted, so only a human can catch a wrong one.
5. **Say where the clouds differ.** Do not tell the user the guarantee is the same everywhere. It is not.
6. **Stay in scope.** Do only the change asked for. If the request, or a fix you are tempted to make, falls outside the scope above, say so and stop.

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
set -o pipefail; scripts/boundary.sh check <project-dir> 2>&1 | tee <project-dir>/.boundary/evidence-<YYYY-MM-DD>.log
```

Type today's date into the file name: the guard denies shell expansion such as `$(date)` in any command that names `boundary.sh`. `pipefail` matters: without it the pipeline reports `tee`'s success even when a gate failed. A non-zero exit means stop.

`check` copies the tree to a scratch folder first and judges only the copy, so nothing can be swapped in mid-check. It runs `terraform fmt` on the copy, which quotes bare labels and fixes spacing so the text-based tests read what Terraform reads, and it refuses `/* */` block comments, which `fmt` keeps. It refuses symlinks, `.tf.json` files and override files, because Terraform reads them and the text-based tests do not. It also refuses module or provider sources that are remote, or that leave the tree, unless the pinned release already uses them. And it refuses provisioners, external data sources and any state backend except an empty local one, because each can run commands or send state elsewhere under whoever applies. Remote state is not supported by `boundary.sh apply` yet. The gates then run in order and stop at the first failure:

1. **write boundary:** the pinned release's tests for that tree, which read your `.tf` source and fail on the edits `terraform validate` accepts.
2. **provider pins:** every provider pins a major, and one tree agrees with itself.
3. **policies:** the OPA policies, such as a content filter that nothing references.
4. **validate:** `terraform init -backend=false` and `validate` on every env root.

All four must pass before Step 5. Keep the evidence log; Pillar 3 uses it.

## Step 5: plan, then stop

For `aws`, `azure` and `gcp`, run `terraform-<cloud>/src/build.sh` first, because plan reads the function packages. If the user wants a preview and the agent has read-only cloud credentials, run `terraform -chdir=<project-dir>/terraform-<cloud>/envs/<env> plan`, show the summary, and stop. This preview is never applied.

Then tell the human to run this in their own terminal, with their own deploy credentials:

```bash
scripts/boundary.sh apply <project-dir> <env>
```

It plans again from the gated copy and shows them what no static gate can see: every tool's `access` label from `terraform.tfvars`, and every permission the plan changes. Every tool that changes state must say `write`, and the orchestrator must gain read tools only. On `snowflake`, tool labels live in `.tf` files, so the gates already check them. The human types the plan's fingerprint to apply, or anything else to stop.
