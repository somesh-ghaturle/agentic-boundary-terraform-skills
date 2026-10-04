#!/usr/bin/env bash
# The one check that matters: the gate passes on a clean tree and refuses the widening edit
# Agentic-AI-Systems warns about, where the orchestrator is handed every tool instead of
# only the read tools.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
b=$here/skills/terraform-boundary/scripts/boundary.sh
work=$(mktemp -d); trap 'rm -rf "$work"' EXIT

"$b" fetch aws "$work/proj"
"$b" check "$work/proj"

perl -0pi -e 's/module\.tools\.read_tool_arns,\n(\s*\[module\.approval\.validator_arn\])/values(module.tools.tool_arns_by_name),\n$1/' \
  "$work/proj/terraform-aws/envs/dev/main.tf"
grep -q 'values(module.tools.tool_arns_by_name),' "$work/proj/terraform-aws/envs/dev/main.tf" \
  || { echo "FAIL: mutation did not apply, so this test proves nothing"; exit 1; }

if out=$("$b" check "$work/proj" 2>&1); then
  echo "FAIL: check passed with write tools handed to the orchestrator"; exit 1
fi
echo "$out" | grep -q '^== write boundary' && echo "$out" | grep -q 'gate failed' \
  || { echo "FAIL: check failed for the wrong reason:"; echo "$out"; exit 1; }
echo "PASS: clean tree passes, widened orchestrator is refused"
