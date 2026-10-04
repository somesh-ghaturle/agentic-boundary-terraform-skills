#!/usr/bin/env bash
# Copy a pinned Agentic-AI-Systems Terraform tree into a project, then gate every change to it
# on that repository's own write-boundary checks.
#
#   boundary.sh fetch <aws|azure|gcp|snowflake> <dest>
#   boundary.sh check <dest>
#
# check stops at the first failing gate and exits non-zero. It never runs plan or apply.
#
# Trust model. The project is what the gated agent edits, so check trusts nothing in it except
# the .tf and lock files it is there to judge. The release is pinned here, in the skill, by tag
# and commit. Every gate file (tests, policies, the provider-pin checker) comes from a fresh
# clone of that commit, and the project's .tf files are copied next to them in a scratch
# directory. Editing the project's own tests, its pin, or a __pycache__ changes nothing.
# This does not defend against someone who can edit this script or the machine itself.
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
  [ -d "$dest/terraform-$cloud" ] || die "no $dest/terraform-$cloud to check"
  need git ""
  need python3 ""
  need conftest "Install it from https://www.conftest.dev/install/"
  need terraform "Install it from https://developer.hashicorp.com/terraform/install"

  clone
  # The project's Terraform, minus its tests and any .terraform state, beside the pinned tests.
  local chk=$tmp/check/terraform-$cloud
  mkdir -p "$tmp/check"
  cp -R "$dest/terraform-$cloud" "$chk"
  rm -rf "$chk/tests"
  find "$chk" -name .terraform -prune -exec rm -rf {} +
  cp -R "$tmp/src/infra/terraform-$cloud/tests" "$chk/tests"

  # -I: ignore PYTHON* variables and the current directory. pycache_prefix: never read a
  # cached bytecode file that sits next to a source file.
  local py=(python3 -I -X "pycache_prefix=$tmp/pycache")
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

cmd=${1:-}; shift || true
case $cmd in
  fetch) fetch "$@" ;;
  check) check "$@" ;;
  *) die "usage: boundary.sh fetch <cloud> <dest> | boundary.sh check <dest>" ;;
esac
