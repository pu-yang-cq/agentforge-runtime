import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOMAIN = ROOT / "src" / "agentforge" / "domain"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_domain_layer_does_not_import_transport_or_infrastructure_frameworks() -> None:
    forbidden_prefixes = (
        "fastapi",
        "sqlalchemy",
        "psycopg",
        "alembic",
        "agentforge.infrastructure",
        "agentforge.api",
    )
    violations: list[str] = []
    for path in DOMAIN.rglob("*.py"):
        for imported in _imports(path):
            if imported.startswith(forbidden_prefixes):
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert not violations, "domain dependency boundary violated:\n" + "\n".join(violations)


def test_application_layer_does_not_import_infrastructure_or_transport_frameworks() -> None:
    application = ROOT / "src" / "agentforge" / "application"
    forbidden_prefixes = (
        "fastapi",
        "sqlalchemy",
        "psycopg",
        "alembic",
        "agentforge.infrastructure",
        "agentforge.api",
    )
    violations: list[str] = []
    for path in application.rglob("*.py"):
        for imported in _imports(path):
            if imported.startswith(forbidden_prefixes):
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert not violations, "application dependency boundary violated:\n" + "\n".join(violations)
