"""The privacy boundary as a test: matching.py sees salted hashes and nothing else."""

import ast
from pathlib import Path

import photoquiz.matching

SOURCE = Path(photoquiz.matching.__file__).read_text()
TREE = ast.parse(SOURCE)

ALLOWED_MODULES = {"__future__", "typing", "collections.abc"}
ALLOWED_FROM_MODELS = {"BucketHash"}
FORBIDDEN_NAMES = {"PhotoMeta", "BucketKey", "LatLon", "Anchors", "TripWindow"}


def test_imports_only_hash_types():
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name in ALLOWED_MODULES, f"matching.py imports {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            names = {a.name for a in node.names}
            if node.module == "photoquiz.models":
                assert names <= ALLOWED_FROM_MODELS, f"matching.py imports {names - ALLOWED_FROM_MODELS}"
            else:
                assert node.module in ALLOWED_MODULES, f"matching.py imports from {node.module}"


def test_never_names_coordinate_or_timestamp_types():
    used = {n.id for n in ast.walk(TREE) if isinstance(n, ast.Name)}
    used |= {n.attr for n in ast.walk(TREE) if isinstance(n, ast.Attribute)}
    assert not used & FORBIDDEN_NAMES


def test_match_parameters_name_the_one_sided_expansion():
    (fn,) = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "match"]
    assert [a.arg for a in fn.args.args] == ["expanded_a", "raw_b"]
