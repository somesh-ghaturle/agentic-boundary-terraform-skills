#!/usr/bin/env bash
# Copy a pinned Agentic-AI-Systems Terraform tree into a project, then gate every change to it
# on that repository's own write-boundary checks.
#
#   boundary.sh fetch <aws|azure|gcp|snowflake> <dest>
#   boundary.sh check <dest>
#
# check stops at the first failing gate and exits non-zero. It never runs plan or apply.
#
# The gate files live in the project the agent is editing, so check first compares them with a
# fresh copy of the pinned release. A gate the agent can rewrite is not a gate.
set -euo pipefail

REPO=https://github.com/somesh-ghaturle/Agentic-AI-Systems.git
TAG=${AGENTIC_BOUNDARY_TAG:-v0.1.0}

die() { echo "boundary: $*" >&2; exit 1; }
gate() { echo "== $1"; shift; "$@" || die "gate failed: see output above"; }
need() { command -v "$1" >/dev/null || die "$1 is not installed, and a skipped gate is not a passed gate. $2"; }
valid_cloud() { case $1 in aws|azure|gcp|snowflake) return 0;; *) return 1;; esac; }

# Shallow-clone the pinned release into $tmp/src. $tmp is global so the EXIT trap can see it.
clone() {
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  git -c advice.detachedHead=false clone -q --depth 1 --branch "$1" "$REPO" "$tmp/src" 2>/dev/null \
    || die "could not clone $REPO at $1"
}

fetch() {
  local cloud=${1:-} dest=${2:-}
  valid_cloud "$cloud" || die "usage: boundary.sh fetch <aws|azure|gcp|snowflake> <dest>"
  [ -n "$dest" ] || die "usage: boundary.sh fetch <aws|azure|gcp|snowflake> <dest>"
  [ ! -e "$dest/terraform-$cloud" ] || die "$dest/terraform-$cloud already exists; refusing to overwrite it"
  clone "$TAG"
  mkdir -p "$dest/.boundary"
  cp -R "$tmp/src/infra/terraform-$cloud" "$dest/"
  cp -R "$tmp/src/infra/policies" "$dest/.boundary/policies"
  cp "$tmp/src/.github/scripts/tfconstraints.py" "$dest/.boundary/"
  printf 'tag=%s\ncommit=%s\ncloud=%s\n' "$TAG" "$(git -C "$tmp/src" rev-parse HEAD)" "$cloud" > "$dest/.boundary/pin"
  echo "fetched terraform-$cloud at $TAG into $dest"
}

check() {
  local dest=${1:-}
  [ -f "$dest/.boundary/pin" ] || die "no $dest/.boundary/pin; run boundary.sh fetch first"
  local cloud tag commit
  cloud=$(sed -n 's/^cloud=//p' "$dest/.boundary/pin")
  tag=$(sed -n 's/^tag=//p' "$dest/.boundary/pin")
  commit=$(sed -n 's/^commit=//p' "$dest/.boundary/pin")
  # Validated, because the pin decides which directory every gate runs against.
  valid_cloud "$cloud" || die "pin names an unknown cloud: '$cloud'"
  case $tag in v[0-9]*) ;; *) die "pin names an invalid tag: '$tag'";; esac
  local tree=$dest/terraform-$cloud
  need git ""
  need python3 ""
  need conftest "Install it from https://www.conftest.dev/install/"
  need terraform "Install it from https://developer.hashicorp.com/terraform/install"

  clone "$tag"
  [ "$(git -C "$tmp/src" rev-parse HEAD)" = "$commit" ] \
    || die "tag $tag no longer points at the pinned commit $commit"
  gate "gate files match $tag" sh -c 'diff -r -x __pycache__ "$1/infra/terraform-$3/tests" "$2/terraform-$3/tests" \
    && diff -r "$1/infra/policies" "$2/.boundary/policies" \
    && cmp "$1/.github/scripts/tfconstraints.py" "$2/.boundary/tfconstraints.py"' _ "$tmp/src" "$dest" "$cloud"

  gate "write boundary" python3 -m unittest discover -s "$tree/tests"
  gate "provider pins" python3 "$dest/.boundary/tfconstraints.py" "$tree"
  gate "policies" sh -c 'find "$1" -name "*.tf" -not -path "*/.terraform/*" -print0 \
    | xargs -0 conftest test --parser hcl2 --combine --policy "$2"' _ "$tree" "$dest/.boundary/policies"

  # One provider download shared by every env root instead of one per root.
  export TF_PLUGIN_CACHE_DIR=${TF_PLUGIN_CACHE_DIR:-$dest/.boundary/plugin-cache}
  mkdir -p "$TF_PLUGIN_CACHE_DIR"
  local env
  for env in "$tree"/envs/*/; do
    gate "validate ${env#"$dest"/}" sh -c 'terraform -chdir="$1" init -backend=false -input=false -no-color >/dev/null \
      && terraform -chdir="$1" validate -no-color' _ "$env"
  done
  echo "all gates passed for terraform-$cloud at $(sed -n 's/^tag=//p' "$dest/.boundary/pin")"
}

cmd=${1:-}; shift || true
case $cmd in
  fetch) fetch "$@" ;;
  check) check "$@" ;;
  *) die "usage: boundary.sh fetch <cloud> <dest> | boundary.sh check <dest>" ;;
esac
