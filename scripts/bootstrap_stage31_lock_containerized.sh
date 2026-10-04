#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."

IMAGE="ghcr.io/astral-sh/uv:0.12.20-python3.14-trixie-slim"

command -v docker >/dev/null 2>&1 || {
  echo "docker is required" >&2
  exit 2
}

if [[ -f uv.lock ]]; then
  echo "uv.lock already exists; remove it explicitly if you intend to regenerate it" >&2
  exit 2
fi

uid="$(id -u)"
gid="$(id -g)"

echo "==> generating uv.lock with pinned Python 3.14 validator image"
docker run --rm \
  --user "${uid}:${gid}" \
  -e HOME=/tmp \
  -e UV_CACHE_DIR=/tmp/uv-cache \
  -v "$PWD:/workspace" \
  -w /workspace \
  "$IMAGE" \
  uv lock

echo "uv.lock generated. Review it and commit it before running acceptance."
