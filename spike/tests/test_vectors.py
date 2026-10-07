"""§1.9: the vectors the Swift port asserts against are current, and each case replays from its
JSON alone, the way the port reads it."""

import inspect
import json

import pytest
import vectorgen

FILES = sorted(vectorgen.OUT.glob("*.json"))
CASES = [(f.name, c) for f in FILES for c in json.loads(f.read_text())["cases"]]


def test_the_vectors_are_current():
    fresh, on_disk = vectorgen.files(), {f.name: f.read_text() for f in FILES}
    stale = sorted(n for n in fresh.keys() | on_disk.keys() if fresh.get(n) != on_disk.get(n))
    assert not stale, f"tests/vectors is stale ({', '.join(stale)}): run `make vectors` and commit the diff"


@pytest.mark.parametrize(("file", "case"), CASES, ids=[f"{f}:{c['name']}" for f, c in CASES])
def test_each_case_replays_from_its_json(file, case):
    assert vectorgen.run(case) == {k: case[k] for k in ("expected", "raises") if k in case}


def test_every_public_pure_function_has_a_vector():
    """`commute_buffer` and `Homes.of` build the args of other cases rather than having their own."""
    public = {
        f"{m.__name__.removeprefix('photoquiz.')}.{name}"
        for m in vectorgen.PURE
        for name, fn in vars(m).items()
        if inspect.isfunction(fn) and fn.__module__ == m.__name__ and not name.startswith("_")
    }
    built = {vectorgen.qualname(fn) for fn in vectorgen.BUILT.values()}
    assert public - built - {c["fn"] for _, c in CASES} == set()
