from pathlib import Path


def test_composition_roots_are_python_packages() -> None:
    root = Path(__file__).resolve().parents[2]
    for relative in (
        "apps/__init__.py",
        "apps/api/__init__.py",
        "apps/worker/__init__.py",
    ):
        assert (root / relative).is_file(), relative
