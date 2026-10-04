#!/usr/bin/env sh
set -eu

cd /workspace

phase() {
  printf '%s\n' "==> Stage 3.1 container acceptance: $1"
}

fail() {
  printf '%s\n' "Stage 3.1 container acceptance FAILED: $*" >&2
  exit 1
}

phase "lockfile preflight"
[ -f uv.lock ] || fail "uv.lock is required and must be committed before acceptance"

phase "Python 3.14 / locked dependency environment"
python_minor="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
[ "$python_minor" = "3.14" ] || fail "validator image must provide Python 3.14; got $python_minor"
uv lock --check
uv sync --locked --all-groups

phase "installed project import"
uv run --locked python - <<'PY'
import agentforge
print(f"agentforge import: {agentforge.__file__}")
PY

phase "quality gates"
uv run --locked ruff check src apps tests migrations
uv run --locked ruff format --check src apps tests migrations
uv run --locked mypy --cache-dir /tmp/mypy-cache

phase "database identity"
uv run --locked python - <<'PY'
import os
import psycopg

url = os.environ["AGENTFORGE_TEST_DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)
with psycopg.connect(url) as connection:
    version_num = int(connection.execute("SELECT current_setting('server_version_num')").fetchone()[0])
if not 180000 <= version_num < 190000:
    raise SystemExit(f"PostgreSQL 18 required; server_version_num={version_num}")
print(f"PostgreSQL major validated: {version_num // 10000}")
PY

phase "Alembic online migration"
uv run --locked alembic upgrade head

phase "full test suite with mandatory PostgreSQL integration"
uv run --locked pytest -q -p no:cacheprovider

phase "acceptance complete"
printf '%s\n' "Stage 3.1 container acceptance PASSED"
