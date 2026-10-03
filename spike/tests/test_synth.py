import csv

import pytest

from photoquiz import synth
from photoquiz.ingest import read_csv, read_parquet, write_parquet
from photoquiz.schema import CSV_HEADER, LABEL_HEADER, SchemaError


@pytest.fixture(scope="module")
def written(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    return synth.write(synth.generate(), out)


def test_csvs_pass_ingest_schema_check(written):
    for person in ("a", "b"):
        assert written[person].read_text().splitlines()[0] == CSV_HEADER
        assert len(read_csv(written[person])) > 100


def test_labels_hold_the_planted_trips(written):
    lines = written["labels"].read_text().splitlines()
    assert lines[0] == LABEL_HEADER
    assert [line.split(",")[0] for line in lines[1:]] == ["tahoe", "monterey", "napa", "santa-cruz"]


def test_parquet_round_trip(written, tmp_path):
    ps = read_csv(written["a"])
    write_parquet(ps, tmp_path / "a.parquet")
    assert read_parquet(tmp_path / "a.parquet") == ps


def test_deterministic():
    assert synth.generate(seed=3) == synth.generate(seed=3)


def test_fixture_contains_filter_fodder():
    d = synth.generate()
    assert any(p.is_screenshot for p in d.a)
    assert any(p.utc_epoch is None for p in d.a)
    assert sum(p.burst_id is not None for p in d.a) == 4
    assert sum(p.is_burst_pick for p in d.a) == 1
    assert any(not p.has_gps and p.utc_epoch is not None for p in d.b)


def test_ingest_rejects_shifted_columns(written, tmp_path):
    rows = list(csv.reader(written["a"].open()))
    rows[0][3], rows[0][4] = rows[0][4], rows[0][3]
    bad = tmp_path / "bad.csv"
    with bad.open("w", newline="") as f:
        csv.writer(f).writerows(rows)
    with pytest.raises(SchemaError):
        read_csv(bad)
