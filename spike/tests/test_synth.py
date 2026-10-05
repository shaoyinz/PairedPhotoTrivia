import csv
import json
import re

import pytest
from typer.testing import CliRunner

from photoquiz import synth
from photoquiz.cli import app
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
    names = [line.split(",")[0] for line in lines[1:]]
    assert names == ["tahoe", "monterey", "napa", "santa-cruz", "yosemite", "mendocino"]


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


# the CLI never replaces files that are yours


def synth_cli(out, *args):
    return CliRunner().invoke(app, ["synth", "--out", str(out), *args])


def test_synth_reruns_over_its_own_files(tmp_path):
    assert synth_cli(tmp_path).exit_code == 0
    first = (tmp_path / "a_photos.csv").read_bytes()
    assert synth_cli(tmp_path).exit_code == 0
    assert synth_cli(tmp_path, "--seed", "3").exit_code == 0  # different bytes, still its own
    assert (tmp_path / "a_photos.csv").read_bytes() != first


def test_synth_refuses_a_real_export_and_writes_nothing(tmp_path):
    assert synth_cli(tmp_path).exit_code == 0
    real = (tmp_path / "a_photos.csv").read_text().replace("A-00000", "REAL-0")
    (tmp_path / "a_photos.csv").write_text(real)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}

    out = synth_cli(tmp_path, "--seed", "3")  # would rewrite b and labels too
    assert out.exit_code == 1 and "refusing to replace a_photos.csv" in out.output and "--force" in out.output
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before

    assert synth_cli(tmp_path, "--force").exit_code == 0
    assert "REAL-0" not in (tmp_path / "a_photos.csv").read_text()


def test_synth_refuses_hand_written_labels(tmp_path):
    assert synth_cli(tmp_path).exit_code == 0
    (tmp_path / "labels.csv").write_text(LABEL_HEADER + "\nbig-sur,2026-08-01,2026-08-02,Big Sur\n")
    out = synth_cli(tmp_path)
    assert out.exit_code == 1 and "labels.csv" in out.output
    assert "big-sur" in (tmp_path / "labels.csv").read_text()


def test_a_file_from_before_the_pipeline_is_yours_unless_identical(tmp_path):
    synth.write(synth.generate(), tmp_path)  # same bytes, but no generated.json yet
    assert synth_cli(tmp_path).exit_code == 0
    other = tmp_path / "other"
    other.mkdir()
    (other / "b_photos.csv").write_text(CSV_HEADER + "\n")
    assert synth_cli(other).exit_code == 1


def test_generated_json_holds_only_names_and_hashes(tmp_path):
    assert synth_cli(tmp_path).exit_code == 0
    own = json.loads((tmp_path / "generated.json").read_text())
    assert sorted(own) == ["a_photos.csv", "b_photos.csv", "labels.csv"]
    assert all(re.fullmatch(r"[0-9a-f]{64}", h) for h in own.values())
