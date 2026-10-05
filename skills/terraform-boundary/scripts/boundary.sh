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
# cloud credentials for the agent are the third). It refuses without a terminal and reruns every
# gate. It then plans from the gated copy itself, with providers downloaded fresh into a private
# cache, so the human's credentials never run the agent's plan file or the agent's provider
# binaries, and what is applied is exactly what was gated. It shows the plan with the tool labels
# and permission changes, and applies only after the human types the plan's fingerprint.
# Approval binds that exact plan, is used once, and has no gap between approving and applying,
# which is the Hermes approval pattern from Agentic-AI-Systems applied to the deploy itself.
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
  chk=$tmp/check/terraform-$cloud   # global: apply plans from this gated copy
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
  # Constructs that run local commands, or send state somewhere else, under whoever applies.
  # None appear in the pinned release; boundary.sh apply keeps state in the project, local.
  gate "no provisioners, external data or backends" "${py[@]}" - "$chk" <<'PY'
import pathlib, re, sys
RISKY = re.compile(r'\bprovisioner\s+"|\bdata\s+"external"|\bbackend\s+"|^\s*cloud\s*\{', re.M)
# An empty local backend keeps state in the env directory, which is where apply expects it.
LOCAL = re.compile(r'\bbackend\s+"local"\s*\{\s*\}')
root = pathlib.Path(sys.argv[1])
def code(path):
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return LOCAL.sub("", "\n".join(l for l in lines if not l.lstrip().startswith(("#", "//"))))
bad = [f"{p.relative_to(root)}: {m.group(0).strip()}" for p in root.rglob("*.tf")
       for m in RISKY.finditer(code(p))]
for line in bad:
    print(line)
sys.exit(1 if bad else 0)
PY
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
  envdir=$dest/terraform-$cloud/envs/$env
  [ -d "$envdir" ] && [ ! -L "$envdir" ] || die "$envdir is missing or is a symlink"
  local f
  for f in terraform.tfstate terraform.tfstate.backup; do
    [ ! -L "$envdir/$f" ] || die "$envdir/$f is a symlink"
  done

  # A private provider cache, so no binary the agent downloaded or swapped runs with the
  # human's credentials. check honours it.
  export TF_PLUGIN_CACHE_DIR; TF_PLUGIN_CACHE_DIR=$(mktemp -d)
  check "$dest"
  run=$chk/envs/$env
  [ -d "$run" ] || die "no envs/$env in the gated copy"

  # State stays in the project. Copy it in, and copy it back whatever happens, because a
  # failed apply still changes real infrastructure and its state must not be lost.
  for f in terraform.tfstate terraform.tfstate.backup; do
    [ ! -f "$envdir/$f" ] || cp "$envdir/$f" "$run/$f"
  done
  trap 'for f in terraform.tfstate terraform.tfstate.backup; do
          [ ! -f "$run/$f" ] || cp "$run/$f" "$envdir/$f"
        done; rm -rf "$tmp" "$TF_PLUGIN_CACHE_DIR"' EXIT

  echo "== plan, from the gated copy"
  terraform -chdir="$run" init -input=false -no-color >/dev/null
  terraform -chdir="$run" plan -input=false -no-color -out="$tmp/tfplan" >/dev/null
  local digest
  digest=$(python3 -I -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$tmp/tfplan")

  terraform -chdir="$run" show -no-color "$tmp/tfplan"
  echo
  terraform -chdir="$run" show -json "$tmp/tfplan" | python3 -I -c "$SUMMARY"
  echo
  echo "plan fingerprint: $digest"
  printf 'Type the first 12 characters of the fingerprint to apply exactly this plan: '
  local answer; read -r answer </dev/tty
  [ "$answer" = "${digest:0:12}" ] || die "not approved; nothing was applied"
  terraform -chdir="$run" apply -input=false "$tmp/tfplan"
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
