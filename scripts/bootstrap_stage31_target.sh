#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required" >&2
  exit 2
fi

# The frozen baseline is Python 3.14. UV_PYTHON makes uv select that interpreter
# even when the host's default `python` command points at another version.
export UV_PYTHON=3.14
uv lock
uv sync --locked

minor="$(uv run --locked python - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
if [[ "$minor" != "3.14" ]]; then
  echo "uv did not select Python 3.14; got $minor" >&2
  exit 2
fi

echo "Target toolchain bootstrapped. Commit uv.lock before acceptance validation."
