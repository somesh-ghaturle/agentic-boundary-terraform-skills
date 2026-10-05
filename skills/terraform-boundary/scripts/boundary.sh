#!/usr/bin/env bash
# Copy a pinned Agentic-AI-Systems Terraform tree into a project, then gate every change to it
# on that repository's own write-boundary checks.
#
#   boundary.sh fetch <aws|azure|gcp|snowflake> <dest>
#   boundary.sh check <dest>
#   boundary.sh apply <dest> <env>      human only, in a real terminal
#
# check stops at the first failing gate and exits non-zero. It never runs plan or apply.
#
# apply is the human step, and the second of three locks (hooks/guard.py is the first, read-only
# cloud credentials for the agent are the third). It refuses without a terminal, reruns every
# gate, snapshots the plan, shows it with the tool labels and permission changes, and applies
# only after the human types the snapshot's fingerprint. Approval binds that exact plan, is used
# once, and has no gap between approving and applying, which is the Hermes approval pattern from
# Agentic-AI-Systems applied to the deploy itself.
#
# Trust model. The project is what the gated agent edits, so check trusts nothing in it except
# the .tf and lock files it is there to judge. The release is pinned here, in the skill, by tag
# and commit. Every gate file (tests, policies, the provider-pin checker) comes from a fresh
# clone of that commit, and the project's .tf files are copied next to them in a scratch
# directory. Editing the project's own tests, its pin, or a __pycache__ changes nothing.
#
# The pinned tests read .tf files as text and do not follow symlinks. Terraform also reads
# .tf.json and override files and follows symlinks, so check refuses all three rather than pass
# something the tests never saw. Two things stay out of reach of any static gate: values in
# *.tfvars, including each tool's read/write label, and anything only known at plan time.
# A human reviewing the plan is the final check for those. This also does not defend against
# someone who can edit this script or the machine itself.
set -euo pipefail

REPO=https://github.com/somesh-ghaturle/Agentic-AI-Systems.git
TAG=v0.1.0
COMMIT=d9104144fb72c78d08ce096f1842584d63995a7e   # what TAG pointed at when this skill shipped

die() { echo "boundary: $*" >&2; exit 1; }
gate() { echo "== $1"; shift; "$@" || die "gate failed: see output above"; }
need() { command -v "$1" >/dev/null || die "$1 is not installed, and a skipped gate is not a passed gate. $2"; }
valid_cloud() { case $1 in aws|azure|gcp|snowflake) return 0;; *) return 1;; esac; }

# Clone the pinned release into $tmp/src and prove it is the commit this skill shipped against.
# $tmp is global so the EXIT trap can see it.
clone() {
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  git -c advice.detachedHead=false clone -q --depth 1 --branch "$TAG" "$REPO" "$tmp/src" 2>/dev/null \
    || die "could not clone $REPO at $TAG"
  [ "$(git -C "$tmp/src" rev-parse HEAD)" = "$COMMIT" ] \
    || die "$TAG no longer points at $COMMIT; refusing to trust it"
}

fetch() {
  local cloud=${1:-} dest=${2:-}
  valid_cloud "$cloud" && [ -n "$dest" ] || die "usage: boundary.sh fetch <aws|azure|gcp|snowflake> <dest>"
  [ ! -e "$dest/terraform-$cloud" ] || die "$dest/terraform-$cloud already exists; refusing to overwrite it"
  clone
  mkdir -p "$dest/.boundary"
  cp -R "$tmp/src/infra/terraform-$cloud" "$dest/"
  printf 'cloud=%s\n' "$cloud" > "$dest/.boundary/pin"
  echo "fetched terraform-$cloud at $TAG into $dest"
}

check() {
  local dest=${1:-}
  [ -f "$dest/.boundary/pin" ] || die "no $dest/.boundary/pin; run boundary.sh fetch first"
  local cloud; cloud=$(sed -n 's/^cloud=//p' "$dest/.boundary/pin")
  valid_cloud "$cloud" || die "pin names an unknown cloud: '$cloud'"
  local tree=$dest/terraform-$cloud
  [ -d "$tree" ] && [ ! -L "$tree" ] || die "$tree is missing or is a symlink"
  need git ""
  need python3 ""
  need conftest "Install it from https://www.conftest.dev/install/"
  need terraform "Install it from https://developer.hashicorp.com/terraform/install"

  clone
  # Copy first, then judge only the copy. Scanning the project and copying it afterwards would
  # leave a window to swap a file in between. cp -R keeps symlinks as symlinks, so the scan
  # below still sees them.
  local chk=$tmp/check/terraform-$cloud
  mkdir -p "$tmp/check"
  cp -R "$tree" "$chk"
  [ ! -L "$chk" ] || die "$tree became a symlink while being copied"
  rm -rf "$chk/tests"
  find "$chk" -name .terraform -prune -exec rm -rf {} +
  local odd
  odd=$(find "$chk" \( -type l -o -name '*.tf.json' -o -name 'override.tf' -o -name '*_override.tf' \) -print | head -5)
  [ -z "$odd" ] || die "refusing files the pinned tests cannot judge (symlinks, .tf.json, override files):
${odd//$chk/$tree}"
  cp -R "$tmp/src/infra/terraform-$cloud/tests" "$chk/tests"

  # -I: ignore PYTHON* variables and the current directory. pycache_prefix: never read a
  # cached bytecode file that sits next to a source file.
  local py=(python3 -I -X "pycache_prefix=$tmp/pycache")
  # Remote module code is fetched at init and never seen by the text-based tests, and a local
  # path that leaves the tree is not in the copy. Sources must be local and inside the tree,
  # or exactly ones the pinned release already uses.
  gate "module and provider sources" "${py[@]}" - "$chk" "$tmp/src/infra/terraform-$cloud" <<'PY'
import pathlib, re, sys
SOURCE = re.compile(r'\bsource\s*=\s*"([^"]*)"')
chk, pinned = (pathlib.Path(a).resolve() for a in sys.argv[1:3])
def sources(root):
    for path in root.rglob("*.tf"):
        for value in SOURCE.findall(path.read_text(encoding="utf-8", errors="replace")):
            yield path, value
allowed = {value for _, value in sources(pinned)}
bad = []
for path, value in sources(chk):
    if value.startswith(("./", "../")):
        target = (path.parent / value).resolve()
        if target != chk and chk not in target.parents:
            bad.append(f"{path.relative_to(chk)}: {value} leaves the tree")
    elif value not in allowed:
        bad.append(f"{path.relative_to(chk)}: {value} is not a source the pinned release uses")
for line in bad:
    print(line)
sys.exit(1 if bad else 0)
PY
  gate "write boundary ($TAG tests)" "${py[@]}" -m unittest discover -s "$chk/tests"
  gate "provider pins" "${py[@]}" "$tmp/src/.github/scripts/tfconstraints.py" "$chk"
  gate "policies" sh -c 'cd "$1" && find "$2" -name "*.tf" -print0 \
    | xargs -0 conftest test --parser hcl2 --combine --policy "$1/src/infra/policies"' _ "$tmp" "$chk"

  # One provider download shared by every run, kept outside the project.
  export TF_PLUGIN_CACHE_DIR=${TF_PLUGIN_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/agentic-boundary/plugin-cache}
  mkdir -p "$TF_PLUGIN_CACHE_DIR"
  local env
  for env in "$chk"/envs/*/; do
    gate "validate envs/$(basename "$env")" sh -c 'terraform -chdir="$1" init -backend=false -input=false -no-color >/dev/null \
      && terraform -chdir="$1" validate -no-color' _ "$env"
  done
  echo "all gates passed for terraform-$cloud against $TAG ($COMMIT)"
}

apply() {
  local dest=${1:-} env=${2:-}
  [ -t 0 ] && [ -t 1 ] || die "apply must be run by a human in a terminal. An agent cannot apply, by design."
  [ -f "$dest/.boundary/pin" ] || die "no $dest/.boundary/pin; run boundary.sh fetch first"
  local cloud; cloud=$(sed -n 's/^cloud=//p' "$dest/.boundary/pin")
  valid_cloud "$cloud" || die "pin names an unknown cloud: '$cloud'"
  case $env in ''|*[!a-z0-9_-]*) die "usage: boundary.sh apply <dest> <env>";; esac
  local envdir=$dest/terraform-$cloud/envs/$env
  [ -d "$envdir" ] && [ ! -L "$envdir" ] || die "$envdir is missing or is a symlink"
  [ -f "$envdir/tfplan" ] && [ ! -L "$envdir/tfplan" ] \
    || die "no plan at $envdir/tfplan; run: terraform -chdir=$envdir plan -out=tfplan"

  ( check "$dest" ) || die "the gates must pass before anything is applied"

  # Snapshot the plan once. Everything after this reads the snapshot, so the plan cannot change
  # between what the human sees, what they approve and what terraform applies.
  snap=$(mktemp -d); trap 'rm -rf "$snap"' EXIT
  cp "$envdir/tfplan" "$snap/tfplan"
  local digest
  digest=$(python3 -I -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$snap/tfplan")

  terraform -chdir="$envdir" show -no-color "$snap/tfplan"
  echo
  terraform -chdir="$envdir" show -json "$snap/tfplan" | python3 -I -c "$SUMMARY"
  echo
  echo "plan fingerprint: $digest"
  printf 'Type the first 12 characters of the fingerprint to apply exactly this plan: '
  local answer; read -r answer </dev/tty
  [ "$answer" = "${digest:0:12}" ] || die "not approved; nothing was applied"
  terraform -chdir="$envdir" apply -input=false "$snap/tfplan"
}

# What the human checks before typing the fingerprint: every tool's label, which no static gate
# can see because it lives in terraform.tfvars, and every permission the plan changes.
SUMMARY='
import json, re, sys
plan = json.load(sys.stdin)
tools = ((plan.get("variables") or {}).get("tools") or {}).get("value") or {}
if tools:
    print("== tools and their labels (every tool that changes state must say write)")
    for name in sorted(tools):
        print("  %-6s %s" % (tools[name].get("access", "?"), name))
risky = [r for r in plan.get("resource_changes", [])
         if re.search(r"iam|permission|grant|role|deny|polic|principal", r.get("type", ""))
         and r.get("change", {}).get("actions") != ["no-op"]]
print("== permission changes (the orchestrator must gain read tools only)")
for r in risky:
    print("  %-14s %s" % ("/".join(r["change"]["actions"]), r["address"]))
if not risky:
    print("  none")
'

cmd=${1:-}; shift || true
case $cmd in
  fetch) fetch "$@" ;;
  check) check "$@" ;;
  apply) apply "$@" ;;
  *) die "usage: boundary.sh fetch <cloud> <dest> | check <dest> | apply <dest> <env>" ;;
esac
