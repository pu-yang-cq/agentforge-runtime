#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$0")/.."

CURRENT_PHASE="preflight"
CURRENT_KIND="ENVIRONMENT"
on_error() {
  local code=$?
  echo "Stage 3.1 acceptance ${CURRENT_KIND} FAILURE during phase: ${CURRENT_PHASE} (exit=${code})" >&2
  exit "$code"
}
trap on_error ERR

die_env() {
  echo "Stage 3.1 acceptance ENVIRONMENT FAILURE: $*" >&2
  exit 2
}

phase() {
  CURRENT_KIND="$1"
  CURRENT_PHASE="$2"
  echo "==> Stage 3.1 acceptance [${CURRENT_KIND}]: ${CURRENT_PHASE}"
}

phase "ENVIRONMENT" "preflight tools"
command -v uv >/dev/null 2>&1 || die_env "uv is required"
command -v docker >/dev/null 2>&1 || die_env "docker is required for PostgreSQL 18 validation"
if [[ ! -f uv.lock ]]; then
  die_env "uv.lock is an acceptance artifact; run bootstrap and commit it first"
fi

phase "ENVIRONMENT" "locked Python 3.14 environment"
export UV_PYTHON=3.14
uv sync --locked
python_minor="$(uv run --locked python - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
[[ "$python_minor" == "3.14" ]] || die_env "Python 3.14 required; uv selected ${python_minor}"

export COMPOSE_PROJECT_NAME=agentforge_stage31_acceptance
cleanup() {
  docker compose down -v --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

phase "ENVIRONMENT" "PostgreSQL 18 startup"
docker compose up -d postgres
ready=0
for _ in $(seq 1 60); do
  if docker compose exec -T postgres pg_isready -U agentforge -d agentforge >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done
[[ "$ready" == "1" ]] || die_env "PostgreSQL did not become ready within 60 seconds"

# The integration suite performs destructive downgrade/upgrade resets. The
# host-native acceptance path is therefore intentionally hard-bound to the
# disposable local Compose database and ignores ambient database URLs.
export AGENTFORGE_TEST_DATABASE_URL="postgresql+psycopg://agentforge:agentforge@localhost:5432/agentforge"
export AGENTFORGE_DATABASE_URL="$AGENTFORGE_TEST_DATABASE_URL"

phase "QUALITY" "Ruff lint"
uv run --locked ruff check src apps tests migrations
phase "QUALITY" "Ruff format"
uv run --locked ruff format --check src apps tests migrations
phase "QUALITY" "mypy strict"
uv run --locked mypy
phase "MIGRATION" "Alembic online migration"
uv run --locked alembic upgrade head
phase "TEST" "PostgreSQL integration and full test suite"
export AGENTFORGE_REQUIRE_POSTGRES_INTEGRATION=1
uv run --locked pytest -q

CURRENT_KIND="COMPLETE"
CURRENT_PHASE="complete"
echo "Stage 3.1 target acceptance PASSED: Python 3.14 + PostgreSQL 18 + quality + migration + integration."
