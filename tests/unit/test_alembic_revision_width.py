import ast
from pathlib import Path


def _revision_from(path: Path) -> str:
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign):
            is_revision = any(
                isinstance(target, ast.Name) and target.id == "revision" for target in node.targets
            )
            if (
                is_revision
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                return node.value.value
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "revision"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise AssertionError(f"no revision id found in {path}")


def test_alembic_revision_ids_fit_default_version_column() -> None:
    root = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    migrations = sorted(root.glob("*.py"))
    assert migrations
    for migration in migrations:
        revision = _revision_from(migration)
        assert len(revision) <= 32, (migration.name, revision, len(revision))
