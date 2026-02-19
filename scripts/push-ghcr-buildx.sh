#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_DOCKERFILE="$ROOT/backend/Dockerfile"
DEFAULT_CONTEXT="$ROOT"

repo="${GITHUB_REPOSITORY:-}"
image_name="backend"
dockerfile="$DEFAULT_DOCKERFILE"
context="$DEFAULT_CONTEXT"
platforms="linux/amd64,linux/arm64"
builder=""
target=""
dry_run=0
no_cache=0
declare -a tags=()
declare -a build_args=()
declare -a labels=()

usage() {
  cat <<'EOF'
Usage:
  scripts/push-ghcr-buildx.sh [options]

Build and push a multi-arch image to GitHub Container Registry (GHCR).

Defaults:
  image:      ghcr.io/<owner>/<repo>/backend
  dockerfile: backend/Dockerfile
  context:    repo root
  platforms:  linux/amd64,linux/arm64
  tags:       latest

Options:
  --repo <owner/repo>        GitHub repo path (ex: razzamatazm/mustarrd)
  --image-name <name>        Image path segment after repo (default: backend)
  --tag <tag>                Tag to push (repeatable; default: latest)
  --platforms <list>         Comma-separated platforms for buildx
  --file <path>              Dockerfile path
  --context <path>           Build context path
  --builder <name>           Buildx builder name
  --target <stage>           Docker target stage
  --build-arg <k=v>          Build args (repeatable)
  --label <k=v>              OCI labels (repeatable)
  --no-cache                 Disable build cache
  --dry-run                  Print command only
  -h, --help                 Show this help

Examples:
  scripts/push-ghcr-buildx.sh --repo razzamatazm/mustarrd --tag latest --tag v1.2.3
  scripts/push-ghcr-buildx.sh --tag sha-$(git rev-parse --short HEAD)
EOF
}

lowercase() {
  printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

derive_repo_from_origin() {
  local origin
  local detected
  origin="$(git -C "$ROOT" config --get remote.origin.url || true)"

  if [[ "$origin" =~ ^git@github\.com:([^/]+/[^/]+)(\.git)?$ ]]; then
    detected="${BASH_REMATCH[1]}"
    printf '%s' "${detected%.git}"
    return 0
  fi

  if [[ "$origin" =~ ^https://github\.com/([^/]+/[^/]+)(\.git)?$ ]]; then
    detected="${BASH_REMATCH[1]}"
    printf '%s' "${detected%.git}"
    return 0
  fi

  return 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      repo="${2:-}"
      shift 2
      ;;
    --image-name)
      image_name="${2:-}"
      shift 2
      ;;
    --tag)
      tags+=("${2:-}")
      shift 2
      ;;
    --platforms)
      platforms="${2:-}"
      shift 2
      ;;
    --file)
      dockerfile="${2:-}"
      shift 2
      ;;
    --context)
      context="${2:-}"
      shift 2
      ;;
    --builder)
      builder="${2:-}"
      shift 2
      ;;
    --target)
      target="${2:-}"
      shift 2
      ;;
    --build-arg)
      build_args+=("${2:-}")
      shift 2
      ;;
    --label)
      labels+=("${2:-}")
      shift 2
      ;;
    --no-cache)
      no_cache=1
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$repo" ]]; then
  if ! repo="$(derive_repo_from_origin)"; then
    echo "Could not determine GitHub repo. Pass --repo owner/repo." >&2
    exit 1
  fi
fi

if [[ ${#tags[@]} -eq 0 ]]; then
  tags=("latest")
fi

repo="$(lowercase "$repo")"
image_name="$(lowercase "$image_name")"
image="ghcr.io/${repo}/${image_name}"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required but not installed." >&2
  exit 1
fi

if ! docker buildx version >/dev/null 2>&1; then
  echo "docker buildx is required but unavailable." >&2
  exit 1
fi

if [[ -n "${GHCR_USERNAME:-}" && -n "${GHCR_TOKEN:-}" ]]; then
  echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USERNAME" --password-stdin >/dev/null
fi

cmd=(docker buildx build --push --platform "$platforms" --file "$dockerfile")

if [[ -n "$builder" ]]; then
  cmd+=(--builder "$builder")
fi

if [[ -n "$target" ]]; then
  cmd+=(--target "$target")
fi

if [[ "$no_cache" -eq 1 ]]; then
  cmd+=(--no-cache)
fi

if [[ ${#build_args[@]} -gt 0 ]]; then
  for arg in "${build_args[@]}"; do
    cmd+=(--build-arg "$arg")
  done
fi

if [[ ${#labels[@]} -gt 0 ]]; then
  for label in "${labels[@]}"; do
    cmd+=(--label "$label")
  done
fi

for tag in "${tags[@]}"; do
  cmd+=(--tag "${image}:${tag}")
done

cmd+=("$context")

echo "Building and pushing:"
printf '  %q' "${cmd[@]}"
echo

if [[ "$dry_run" -eq 1 ]]; then
  exit 0
fi

"${cmd[@]}"
