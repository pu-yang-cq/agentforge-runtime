from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_target_acceptance_gate_enforces_quality_and_real_postgres_suite() -> None:
    script = (ROOT / "scripts" / "validate_stage31_postgres.sh").read_text()
    assert "export UV_PYTHON=3.14" in script
    assert "export COMPOSE_PROJECT_NAME=agentforge_stage31_acceptance" in script
    assert "docker compose down -v --remove-orphans" in script
    assert "docker compose up -d postgres" in script
    assert "uv run --locked ruff check" in script
    assert "uv run --locked ruff format --check" in script
    assert "uv run --locked mypy" in script
    assert "export AGENTFORGE_REQUIRE_POSTGRES_INTEGRATION=1" in script
    assert "uv run --locked pytest -q" in script


def test_bootstrap_does_not_hide_lockfile_creation_inside_acceptance() -> None:
    bootstrap = (ROOT / "scripts" / "bootstrap_stage31_target.sh").read_text()
    acceptance = (ROOT / "scripts" / "validate_stage31_postgres.sh").read_text()
    assert "uv lock" in bootstrap
    assert "uv lock" not in acceptance
    assert "[[ ! -f uv.lock ]]" in acceptance


def test_target_acceptance_reports_phase_and_bounds_database_startup_wait() -> None:
    script = (ROOT / "scripts" / "validate_stage31_postgres.sh").read_text()
    assert 'CURRENT_PHASE="preflight"' in script
    assert "acceptance ${CURRENT_KIND} FAILURE during phase" in script
    assert "acceptance ENVIRONMENT FAILURE" in script
    assert 'phase "QUALITY" "Ruff lint"' in script
    assert 'phase "MIGRATION" "Alembic online migration"' in script
    assert 'phase "TEST" "PostgreSQL integration and full test suite"' in script
    assert "for _ in $(seq 1 60)" in script
    assert "did not become ready within 60 seconds" in script
    assert "acceptance PASSED" in script


def test_containerized_acceptance_uses_pinned_python314_and_postgres18_images() -> None:
    compose = (ROOT / "docker-compose.acceptance.yml").read_text()
    inside = (ROOT / "scripts" / "validate_stage31_inside_container.sh").read_text()
    outer = (ROOT / "scripts" / "validate_stage31_containerized.sh").read_text()
    assert "ghcr.io/astral-sh/uv:0.12.20-python3.14-trixie-slim" in compose
    assert "postgres:18.6-bookworm" in compose
    assert "AGENTFORGE_REQUIRE_POSTGRES_INTEGRATION" in compose
    assert "uv lock --check" in inside
    assert "uv sync --locked --all-groups" in inside
    assert "mypy --cache-dir /tmp/mypy-cache" in inside
    assert "pytest -q -p no:cacheprovider" in inside
    assert "RUFF_CACHE_DIR: /tmp/ruff-cache" in compose
    assert ".:/workspace:ro" in compose
    assert "PostgreSQL 18 required" in inside
    assert "--exit-code-from validator" in outer
    assert "uv.lock is required" in outer


def test_containerized_lock_bootstrap_does_not_hide_lock_generation_in_acceptance() -> None:
    bootstrap = (ROOT / "scripts" / "bootstrap_stage31_lock_containerized.sh").read_text()
    acceptance = (ROOT / "scripts" / "validate_stage31_containerized.sh").read_text()
    assert "uv lock" in bootstrap
    assert "uv lock" not in acceptance
    assert "python3.14-trixie-slim" in bootstrap


def test_manual_github_acceptance_workflow_delegates_to_same_container_gate() -> None:
    workflow = (ROOT / ".github" / "workflows" / "stage31-acceptance.yml").read_text()
    assert "workflow_dispatch" in workflow
    assert "pull_request:" not in workflow
    assert "./scripts/validate_stage31_containerized.sh" in workflow
    assert "test -f uv.lock" in workflow


def test_project_declares_build_system_for_src_layout_installability() -> None:
    import tomllib

    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["build-system"]["build-backend"] == "uv_build"
    assert any(req.startswith("uv_build>=0.12.20") for req in data["build-system"]["requires"])


def test_acceptance_compose_and_workflow_yaml_are_parseable() -> None:
    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.acceptance.yml").read_text())
    assert set(compose["services"]) == {"postgres", "validator"}
    assert (
        compose["services"]["validator"]["depends_on"]["postgres"]["condition"] == "service_healthy"
    )

    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "stage31-acceptance.yml").read_text()
    )
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["permissions"]["contents"] == "read"


def test_integration_schema_reset_uses_explicit_test_database_override() -> None:
    integration = (ROOT / "tests" / "integration" / "test_postgres_runtime.py").read_text()
    env_py = (ROOT / "migrations" / "env.py").read_text()
    host_gate = (ROOT / "scripts" / "validate_stage31_postgres.sh").read_text()
    assert 'config.attributes["agentforge_explicit_database_url"] = DATABASE_URL' in integration
    assert (
        'explicit_database_url = config.attributes.get("agentforge_explicit_database_url")'
        in env_py
    )
    assert 'explicit_database_url or os.getenv("AGENTFORGE_DATABASE_URL")' in env_py
    assert 'export AGENTFORGE_DATABASE_URL="$AGENTFORGE_TEST_DATABASE_URL"' in host_gate
    assert "${AGENTFORGE_TEST_DATABASE_URL:-" not in host_gate


def test_manual_github_lock_bootstrap_uploads_review_only_artifact() -> None:
    import yaml

    workflow_path = ROOT / ".github" / "workflows" / "stage31-lock-bootstrap.yml"
    workflow = workflow_path.read_text()
    parsed = yaml.safe_load(workflow)
    assert "workflow_dispatch" in parsed["on"]
    assert parsed["permissions"]["contents"] == "read"
    assert "./scripts/bootstrap_stage31_lock_containerized.sh" in workflow
    assert "sha256sum" in workflow
    assert "uv.lock" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "git push" not in workflow
    assert "contents: write" not in workflow
