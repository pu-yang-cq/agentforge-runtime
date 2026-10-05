from __future__ import annotations

import ast
import json
from pathlib import Path

from agentforge.testing.fake_external_system import CrashBarrierPoint


def test_f3_recovery_matrix_covers_exact_frozen_crash_windows_and_real_tests() -> None:
    matrix = json.loads(Path("docs/acceptance/stage3.2-f3-recovery-matrix.json").read_text())
    windows = matrix["windows"]
    assert [item["id"] for item in windows] == list(range(1, 13))
    assert {item["barrier"] for item in windows} == {point.value for point in CrashBarrierPoint}

    functions_by_file: dict[str, set[str]] = {}
    for item in windows:
        assert item["pytest_nodes"]
        assert item["safety"]
        for node in item["pytest_nodes"]:
            file_name, function_name = node.split("::", 1)
            path = Path(file_name)
            assert path.exists(), node
            if file_name not in functions_by_file:
                tree = ast.parse(path.read_text())
                functions_by_file[file_name] = {
                    n.name
                    for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
            assert function_name in functions_by_file[file_name], node


def test_f3_matrix_has_effect_count_assertions_for_ambiguous_external_windows() -> None:
    source = Path("tests/integration/test_postgres_runtime.py").read_text()
    tree = ast.parse(source)
    helper_names = {
        "_f3_assert_pre_effect_crash_recovery",
        "_f3_assert_post_effect_crash_recovery",
    }
    helpers = {
        n.name: (ast.get_source_segment(source, n) or "")
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name in helper_names
    }
    assert set(helpers) == helper_names
    for helper_text in helpers.values():
        assert "effect_count" in helper_text
        assert "reconciliation_query_count" in helper_text
        assert "duplicate_request_count" in helper_text
