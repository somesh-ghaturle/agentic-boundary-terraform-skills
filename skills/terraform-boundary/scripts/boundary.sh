#!/usr/bin/env bash
# Copy a pinned Agentic-AI-Systems Terraform tree into a project, then gate every change to it
# on that repository's own write-boundary checks.
#
#   boundary.sh fetch <aws|azure|gcp|snowflake> <dest>
#   boundary.sh check <dest>
#
# check stops at the first failing gate and exits non-zero. It never runs plan or apply.
set -euo pipefail

REPO=${AGENTIC_BOUNDARY_REPO:-https://github.com/somesh-ghaturle/Agentic-AI-Systems.git}
TAG=${AGENTIC_BOUNDARY_TAG:-v0.1.0}

die() { echo "boundary: $*" >&2; exit 1; }
gate() { echo "== $1"; shift; "$@" || die "gate failed: see output above"; }
need() { command -v "$1" >/dev/null || die "$1 is not installed, and a skipped gate is not a passed gate. $2"; }

fetch() {
  local cloud=${1:-} dest=${2:-}
  case $cloud in aws|azure|gcp|snowflake) ;; *) die "usage: boundary.sh fetch <aws|azure|gcp|snowflake> <dest>";; esac
  [ -n "$dest" ] || die "usage: boundary.sh fetch <aws|azure|gcp|snowflake> <dest>"
  [ ! -e "$dest/terraform-$cloud" ] || die "$dest/terraform-$cloud already exists; refusing to overwrite it"
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
  git -c advice.detachedHead=false clone -q --depth 1 --branch "$TAG" "$REPO" "$tmp/src"
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
  local cloud; cloud=$(sed -n 's/^cloud=//p' "$dest/.boundary/pin")
  local tree=$dest/terraform-$cloud
  need python3 ""
  need conftest "Install it from https://www.conftest.dev/install/"
  need terraform "Install it from https://developer.hashicorp.com/terraform/install"

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
