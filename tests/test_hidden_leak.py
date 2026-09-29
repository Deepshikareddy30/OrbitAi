"""SPEC S3.3: only generator/, eval/ and simworld/ may read hidden/. Fails the build if
any other module under engine/, memory/, api/, ui/ or feedback/ references a hidden/
path.

AST-based (not a text/regex scan): flags real `import hidden...` / `from hidden...`
statements and string literals that look like a hidden/ path segment, while explicitly
ignoring module/class/function docstrings and comments - so writing "never reads the
ground-truth folder" in a docstring can't accidentally trip this check (it did, twice,
before this rewrite).
"""

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN_ROOTS = ["engine", "memory", "api", "ui", "feedback", "agent", "courtroom"]
PATH_LITERAL = re.compile(r"(^|[/\\])hidden([/\\]|$)")


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def _find_hidden_references(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = _docstring_node_ids(tree)
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            offenders += [f"import {a.name}" for a in node.names if a.name.split(".")[0] == "hidden"]
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] == "hidden":
                offenders.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if node.value == "hidden" or PATH_LITERAL.search(node.value):
                offenders.append(f"string literal {node.value!r}")
    return offenders


def test_no_forbidden_module_references_hidden():
    offenders = {}
    for root in FORBIDDEN_ROOTS:
        pkg = REPO_ROOT / root
        if not pkg.exists():
            continue  # package not built yet; nothing to check
        for path in pkg.rglob("*.py"):
            found = _find_hidden_references(path)
            if found:
                offenders[str(path.relative_to(REPO_ROOT))] = found
    assert not offenders, f"Modules referencing hidden/: {offenders}"


def test_generator_and_eval_are_allowed_hidden_readers():
    """Sanity check the rule itself isn't vacuous: generator's own code does read hidden/,
    and this check must not itself flag it."""
    gen_init = REPO_ROOT / "generator" / "__init__.py"
    refs = _find_hidden_references(gen_init)
    assert refs, "expected generator/__init__.py to genuinely reference hidden/ paths"


def test_check_catches_a_real_import(tmp_path):
    """Regression check for the checker itself: a real `from hidden...` import must
    still be flagged (this is what would have caught an actual leak)."""
    bad = tmp_path / "leaky.py"
    bad.write_text("from hidden.root_causes import ANSWER\n")
    assert _find_hidden_references(bad)


def test_check_ignores_docstring_mentions(tmp_path):
    ok = tmp_path / "clean.py"
    ok.write_text('"""This module never reads hidden/root_causes.json, ever."""\n'
                 "x = 1\n")
    assert _find_hidden_references(ok) == []
