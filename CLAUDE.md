# CLAUDE.md

## Scope of this repository

This repository exists for one thing: human-in-the-loop deployment of agents built from Agentic-AI-Systems, with security review and regulated-environment evidence. Work here serves one of those three pillars, or it does not belong here.

- Keep every change on the task asked. Do not refactor, rename or "improve" anything else in the same change.
- Never weaken a lock. The hook in `hooks/guard.py`, the terminal check and fingerprint in `boundary.sh apply`, and the advice to give the agent read-only cloud credentials all stay.
- A request outside the three pillars gets one sentence saying so, and no work.
- Every change to `skills/terraform-boundary/scripts/` or `hooks/` runs `bash tests/test_boundary.sh` and `python3 -m unittest tests/test_guard.py tests/test_state.py` before it is committed.

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues, handled with the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
