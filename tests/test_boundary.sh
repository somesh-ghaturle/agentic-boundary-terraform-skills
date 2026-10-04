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

# The agent being gated must not be able to pass by weakening the gate itself: deleting the
# project's copy of the test changes nothing, because check runs the pinned release's tests.
"$b" fetch aws "$work/tamper"
rm "$work/tamper/terraform-aws/tests/test_write_boundary.py"
perl -0pi -e 's/module\.tools\.read_tool_arns,\n(\s*\[module\.approval\.validator_arn\])/values(module.tools.tool_arns_by_name),\n$1/' \
  "$work/tamper/terraform-aws/envs/dev/main.tf"
if out=$("$b" check "$work/tamper" 2>&1); then
  echo "FAIL: check passed with the project's test deleted and the boundary widened"; exit 1
fi
echo "$out" | grep -q '^== write boundary' && echo "$out" | grep -q 'gate failed' \
  || { echo "FAIL: tamper refused for the wrong reason:"; echo "$out"; exit 1; }

# Nor by pointing the pin at another directory.
printf 'cloud=../decoy\n' > "$work/tamper/.boundary/pin"
if out=$("$b" check "$work/tamper" 2>&1); then
  echo "FAIL: check accepted a pin that names a path"; exit 1
fi
echo "$out" | grep -q 'unknown cloud' || { echo "FAIL: bad pin refused for the wrong reason:"; echo "$out"; exit 1; }

echo "PASS: clean tree passes; widened orchestrator is refused, even with the project's test deleted; redirected pin is refused"
