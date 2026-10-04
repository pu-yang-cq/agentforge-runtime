#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python -m compileall -q src apps tests migrations
pytest -q tests/unit
alembic upgrade head --sql >/tmp/agentforge-stage31.sql

echo "Static validation passed. Offline PostgreSQL DDL: /tmp/agentforge-stage31.sql"
