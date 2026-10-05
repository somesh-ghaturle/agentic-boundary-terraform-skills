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

# Nor by hiding Terraform where the text-based tests do not look.
"$b" fetch aws "$work/shapes"
printf '{}\n' > "$work/shapes/terraform-aws/envs/dev/widen.tf.json"
"$b" check "$work/shapes" >/dev/null 2>&1 && { echo "FAIL: check accepted a .tf.json file"; exit 1; }
rm "$work/shapes/terraform-aws/envs/dev/widen.tf.json"
mv "$work/shapes/terraform-aws/envs/dev" "$work/decoy-dev" && ln -s "$work/decoy-dev" "$work/shapes/terraform-aws/envs/dev"
if out=$("$b" check "$work/shapes" 2>&1); then
  echo "FAIL: check accepted a symlinked env root"; exit 1
fi
echo "$out" | grep -q 'cannot judge' || { echo "FAIL: symlink refused for the wrong reason:"; echo "$out"; exit 1; }

# Nor by pulling Terraform from somewhere the copy and the tests never see.
"$b" fetch aws "$work/src"
printf 'module "x" {\n  source = "git::https://example.com/widen.git"\n}\n' > "$work/src/terraform-aws/envs/dev/extra.tf"
out=$("$b" check "$work/src" 2>&1) && { echo "FAIL: check accepted a remote module source"; exit 1; }
echo "$out" | grep -q 'not a source the pinned release uses' || { echo "FAIL: remote source refused for the wrong reason:"; echo "$out"; exit 1; }
printf 'module "x" {\n  source = "../../../../outside"\n}\n' > "$work/src/terraform-aws/envs/dev/extra.tf"
out=$("$b" check "$work/src" 2>&1) && { echo "FAIL: check accepted a module path outside the tree"; exit 1; }
echo "$out" | grep -q 'leaves the tree' || { echo "FAIL: escaping path refused for the wrong reason:"; echo "$out"; exit 1; }
rm "$work/src/terraform-aws/envs/dev/extra.tf"

# The human step. Without a terminal, apply refuses outright, which is the position an agent is in.
printf 'fake plan bytes\n' > "$work/src/terraform-aws/envs/dev/tfplan"
out=$("$b" apply "$work/src" dev 2>&1 </dev/null) && { echo "FAIL: apply ran without a terminal"; exit 1; }
echo "$out" | grep -q 'must be run by a human' || { echo "FAIL: apply refused for the wrong reason:"; echo "$out"; exit 1; }

# With a terminal, drive the approval through a pseudo-terminal against a stand-in terraform
# that records which plan file it was asked to apply.
mkdir "$work/fakebin"
cat > "$work/fakebin/terraform" <<'FAKE'
#!/usr/bin/env bash
[ "${1#-chdir=}" != "$1" ] && shift
case $1 in
  init|validate) exit 0 ;;
  show) if [ "$2" = -json ]; then
          echo '{"variables":{"tools":{"value":{"retrieve":{"access":"read"},"restart":{"access":"write"}}}},"resource_changes":[{"type":"aws_iam_role_policy","address":"module.orchestration.aws_iam_role_policy.invoke","change":{"actions":["create"]}}]}'
        else echo "Plan: 1 to add, 0 to change, 0 to destroy."; fi ;;
  apply) for a; do last=$a; done
         python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$last" > "$FAKE_APPLIED" ;;
  *) exit 1 ;;
esac
FAKE
chmod +x "$work/fakebin/terraform"
cat > "$work/drive_tty.py" <<'PTY'
import os, pty, sys
answer = sys.argv[1].encode() + b"\n"
pid, fd = pty.fork()
if pid == 0:
    os.execvp(sys.argv[2], sys.argv[2:])
out, sent = b"", False
while True:
    try:
        chunk = os.read(fd, 4096)
    except OSError:
        break
    if not chunk:
        break
    out += chunk
    if not sent and b"apply exactly this plan" in out:
        os.write(fd, answer)
        sent = True
sys.stdout.write(out.decode(errors="replace"))
sys.exit(os.waitstatus_to_exitcode(os.waitpid(pid, 0)[1]))
PTY
digest=$(python3 -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$work/src/terraform-aws/envs/dev/tfplan")
export FAKE_APPLIED=$work/applied
out=$(PATH=$work/fakebin:$PATH python3 "$work/drive_tty.py" "not-the-fingerprint" "$b" apply "$work/src" dev 2>&1) \
  && { echo "FAIL: apply ran with the wrong fingerprint"; exit 1; }
[ ! -e "$FAKE_APPLIED" ] || { echo "FAIL: terraform apply was called after a wrong fingerprint"; exit 1; }
echo "$out" | grep -q 'write  restart' && echo "$out" | grep -q 'aws_iam_role_policy.invoke' \
  || { echo "FAIL: the human was not shown the tool labels and permission changes:"; echo "$out"; exit 1; }
PATH=$work/fakebin:$PATH python3 "$work/drive_tty.py" "${digest:0:12}" "$b" apply "$work/src" dev >/dev/null 2>&1 \
  || { echo "FAIL: apply refused the right fingerprint"; exit 1; }
[ "$(cat "$FAKE_APPLIED")" = "$digest" ] || { echo "FAIL: terraform applied a different plan than the one approved"; exit 1; }

echo "PASS: gates refuse every bypass tried; apply needs a terminal and the exact plan fingerprint"
