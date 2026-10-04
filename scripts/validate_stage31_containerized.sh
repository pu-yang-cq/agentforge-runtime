#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="docker-compose.acceptance.yml"
PROJECT_NAME="agentforge_stage31_acceptance"

fail_env() {
  echo "Stage 3.1 acceptance ENVIRONMENT FAILURE: $*" >&2
  exit 2
}

command -v docker >/dev/null 2>&1 || fail_env "docker is required"
docker compose version >/dev/null 2>&1 || fail_env "docker compose v2 is required"
[[ -f uv.lock ]] || fail_env "uv.lock is required; generate/review/commit it before acceptance"

cleanup() {
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

echo "==> Stage 3.1 acceptance: isolated Python 3.14 + PostgreSQL 18 environment"
docker compose \
  -p "$PROJECT_NAME" \
  -f "$COMPOSE_FILE" \
  up \
  --abort-on-container-exit \
  --exit-code-from validator \
  validator

echo "Stage 3.1 containerized target acceptance PASSED"
