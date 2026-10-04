"""§1.8: coverage, evaluation against hand labels, the parameter sweep and the report."""

import datetime as dt
import json
import os
import re
from dataclasses import fields

import pytest
from typer.testing import CliRunner

from photoquiz import synth
from photoquiz.anchors import infer_anchors
from photoquiz.cli import _read_sweep, _write_sweep, app
from photoquiz.filters import FilterStats, apply_all
from photoquiz.models import OLD_HOME, Era, PhotoMeta, TripWindow
from photoquiz.report import (
    Coverage,
    Evaluation,
    Label,
    Params,
    SweepRow,
    best,
    coverage,
    evaluate,
    grid,
    in_labels,
    label_span,
    render,
    sweep,
    varied,
)

SALT = bytes(range(32))
DAY = 86_400
JUL_10 = int(dt.datetime(2026, 7, 10, tzinfo=dt.UTC).timestamp())


def photo(utc: int | None = JUL_10, *, gps: bool = True, make: str | None = "Apple") -> PhotoMeta:
    return PhotoMeta(
        asset_id="P",
        utc_epoch=utc,
        tz_offset_s=0,
        lat=39.1 if gps else None,
        lon=-120.0 if gps else None,
        is_screenshot=False,
        burst_id=None,
        is_burst_pick=False,
        camera_make=make,
        camera_model=None,
        width=None,
        height=None,
    )


def label(name: str, start: str, end: str) -> Label:
    return Label(name, start, end, "Somewhere")


def trip(start: int, end: int) -> TripWindow:
    return TripWindow(start, end, 1, 3, 2, "9qfwt1", "shared home: out of town, 1 session")


TAHOE = label("tahoe", "2026-07-10", "2026-07-12")  # [JUL_10, JUL_10 + 3 days)
NAPA = label("napa", "2026-07-20", "2026-07-20")
NAPA_0 = JUL_10 + 10 * DAY


# labels


def test_label_span_runs_to_the_midnight_after_end_date():
    assert label_span(TAHOE) == (JUL_10, JUL_10 + 3 * DAY)
    assert label_span(NAPA) == (NAPA_0, NAPA_0 + DAY)


@pytest.mark.parametrize(("start", "end"), [("2026-07-12", "2026-07-10"), ("2026-07-10", "12 July"), ("", "")])
def test_label_span_refuses_bad_dates(start, end):
    with pytest.raises(ValueError):
        label_span(label("x", start, end))


def test_in_labels_is_half_open_on_utc_days():
    ps = [photo(JUL_10 - 1), photo(JUL_10), photo(JUL_10 + 3 * DAY - 1), photo(JUL_10 + 3 * DAY), photo(None)]
    assert in_labels(ps, [TAHOE]) == ps[1:3]
    assert in_labels(ps, []) == []


# coverage


def test_coverage_overall_and_by_utc_year():
    new_year = int(dt.datetime(2026, 1, 1, tzinfo=dt.UTC).timestamp())
    ps = [photo(new_year - 1), photo(new_year - 1, gps=False), photo(new_year), photo(None)]
    c = coverage(ps)
    assert (c.with_gps, c.total) == (3, 4)
    assert c.by_year == {2025: (1, 2), 2026: (1, 1)}  # no timestamp, no year


def test_coverage_splits_camera_from_imported():
    ps = [photo(), photo(gps=False), photo(make=None, gps=False), photo(make=None)]
    c = coverage(ps)
    assert (c.camera, c.imported) == ((1, 2), (1, 2))


def test_an_export_without_any_camera_make_has_no_split_rather_than_0_percent_camera():
    """The iOS exporter leaves camera_make empty on every row: unknown, not imported (§1.2a)."""
    c = coverage([photo(make=None), photo(make=None, gps=False)])
    assert (c.camera, c.imported) == (None, None)
    assert (c.with_gps, c.total) == (1, 2)


def test_coverage_of_nothing():
    assert coverage([]) == Coverage(0, 0, {}, None, None)


# evaluation


def test_overlap_is_a_true_positive_and_the_rest_count():
    ws = [trip(JUL_10 + 3600, JUL_10 + 7200), trip(JUL_10 - 5 * DAY, JUL_10 - 4 * DAY)]
    ev = evaluate(ws, [TAHOE, NAPA])
    assert (ev.true_positives, ev.false_positives, ev.false_negatives) == (1, 1, 1)
    assert (ev.precision, ev.recall, ev.splits, ev.merges, ev.labeled) == (0.5, 0.5, 0, 0, 2)
    assert ev.overlaps == ((0, 0),)


@pytest.mark.parametrize(
    ("start", "end", "hit"),
    [
        (JUL_10 - DAY, JUL_10, False),  # ends at the label's first midnight
        (JUL_10 - DAY, JUL_10 + 1, True),
        (JUL_10 + 3 * DAY, JUL_10 + 4 * DAY, False),  # starts at the midnight after end_date
        (JUL_10 + 3 * DAY - 1, JUL_10 + 4 * DAY, True),
        (JUL_10 - DAY, JUL_10 + 4 * DAY, True),  # covers it
    ],
)
def test_overlap_is_of_half_open_intervals(start, end, hit):
    assert evaluate([trip(start, end)], [TAHOE]).true_positives == int(hit)


def test_a_label_found_as_two_trips_is_one_split():
    ws = [trip(JUL_10, JUL_10 + 3600), trip(JUL_10 + DAY, JUL_10 + DAY + 3600)]
    ev = evaluate(ws, [TAHOE])
    assert (ev.splits, ev.merges, ev.true_positives, ev.precision, ev.recall) == (1, 0, 2, 1.0, 1.0)


def test_a_trip_over_two_labels_is_one_merge():
    """Precision and recall are both perfect: only the merge count shows it."""
    ev = evaluate([trip(JUL_10, NAPA_0 + 3600)], [TAHOE, NAPA])
    assert (ev.merges, ev.splits, ev.precision, ev.recall) == (1, 0, 1.0, 1.0)


def test_nothing_detected_or_nothing_labeled_scores_zero():
    assert evaluate([], [TAHOE]) == Evaluation(0.0, 0.0, 0, 0, 1, 0, 0, 1)
    assert evaluate([trip(JUL_10, JUL_10 + 1)], []) == Evaluation(0.0, 0.0, 0, 1, 0, 0, 0, 0)


# sweep


def changed(p: Params) -> set[str]:
    return {f.name for f in fields(Params) if getattr(p, f.name) != getattr(Params(), f.name)}


def test_grid_varies_one_parameter_at_a_time_then_city_with_silence():
    points = grid()
    assert points[0] == Params()
    assert len(points) == len(set(points)) == 15
    assert [len(changed(p)) for p in points[1:]] == [1] * 10 + [2] * 4
    assert all(changed(p) == {"city_km", "max_silence_hours"} for p in points[11:])


def test_grid_holds_every_city_and_silence_pair():
    pairs = {(p.city_km, p.max_silence_hours) for p in grid()}
    assert pairs == {(c, h) for c in (15.0, 25.0, 50.0) for h in (24, 72, 168)}


def test_grid_without_joint_pairs_is_one_at_a_time():
    assert len(grid(joint=())) == 11


def test_grid_covers_the_planned_values():
    points = grid()
    assert {p.geohash_precision for p in points} == {5, 6, 7}
    assert {p.city_km for p in points} == {15.0, 25.0, 50.0}
    assert {p.max_silence_hours for p in points} == {24, 72, 168}


def test_varied_names_what_changed():
    assert varied(Params(), Params()) == "defaults"
    assert varied(Params(city_km=50.0), Params()) == "city_km=50"
    assert varied(Params(gap_hours=12, min_photos=3), Params()) == "gap_hours=12, min_photos=3"
    assert varied(Params(past_homes=False), Params()) == "past_homes=false"


def row(precision: float, recall: float, merges: int = 0, splits: int = 0, **params) -> SweepRow:
    return SweepRow(Params(**params), 1, Evaluation(precision, recall, 0, 0, 0, splits, merges, 1))


def test_best_needs_the_gate_before_recall():
    rows = [row(0.8, 1.0), row(0.9, 0.5, min_photos=8)]
    assert best(rows) is rows[1]


def test_best_takes_recall_then_fewer_merges_then_fewer_splits():
    assert best([row(1.0, 0.5), row(0.9, 1.0, merges=3, city_km=50.0)]).params == Params(city_km=50.0)
    assert best([row(1.0, 1.0, merges=1), row(1.0, 1.0, splits=2, city_km=15.0)]).params == Params(city_km=15.0)
    assert best([row(1.0, 1.0, splits=1), row(0.95, 1.0, city_km=15.0)]).params == Params(city_km=15.0)


def test_best_short_of_the_gate_takes_precision_before_recall():
    """When no run passes, the run that detects everything at 40% precision must not win."""
    rows = [row(0.4, 1.0), row(0.85, 0.5, city_km=50.0), row(0.85, 0.6, city_km=15.0)]
    assert best(rows).params == Params(city_km=15.0)  # equal precision: then merges, splits, recall


def test_best_keeps_the_defaults_on_a_tie():
    rows = [row(1.0, 1.0), row(1.0, 1.0, city_km=50.0)]
    assert best(rows) is rows[0]


@pytest.fixture(scope="module")
def fixture():
    data = synth.generate()
    a, b = (apply_all(ps)[0] for ps in (data.a, data.b))
    an_a, an_b = (infer_anchors(ps, person=n, now_utc=max(p.utc_epoch for p in ps)) for n, ps in zip("ab", (a, b)))
    return a, b, an_a, an_b, data.labels


def run(fixture, points):
    a, b, an_a, an_b, labels = fixture
    return list(sweep(points, labels, an_a, an_b, ps_a=a, ps_b=b, salt=SALT))


def test_synthetic_sweep(fixture):
    rows = {varied(r.params, Params()): r for r in run(fixture, grid())}
    assert len(rows) == 15 and "city_km=15, max_silence_hours=168" in rows
    for name, r in rows.items():
        if name == "min_photos=3":  # the 2 + 2 near-trip gets in
            assert (r.trips, r.ev.false_positives, r.ev.precision, r.ev.recall) == (5, 1, 0.8, 1.0)
        else:
            assert (r.trips, r.ev.precision, r.ev.recall, r.ev.splits, r.ev.merges) == (4, 1.0, 1.0, 0, 0), name


def test_synthetic_merge_moves_with_the_home_city_radius(fixture):
    """With only the 5 km buffers as home, A's dinner in Oakland no longer splits Napa from Santa Cruz (§1.7)."""
    [r] = run(fixture, [Params(city_km=5.0)])
    assert (r.trips, r.ev.merges, r.ev.precision, r.ev.recall) == (3, 1, 1.0, 1.0)


def test_synthetic_silence_cap_splits_tahoe_by_night(fixture):
    [r] = run(fixture, [Params(max_silence_hours=12)])
    assert (r.ev.splits, r.ev.precision, r.ev.recall) == (1, 1.0, 1.0)


def test_sweep_leaves_old_home_days_out_of_the_score(fixture):
    """Pretend both partners lived at Lake Tahoe for the trip's days: Tahoe becomes old-home days,
    which are neither trips nor false positives, so only a missed label. Without past homes it is a trip."""
    a, b, an_a, an_b, labels = fixture
    lo, hi = label_span(labels[0])  # tahoe
    eras = {
        f"eras_{x.person}": [
            Era(None, x.home, x.work, False, 30),
            Era(lo, synth.TAHOE, None, True, 3),
            Era(hi, x.home, x.work, False, 30),
        ]
        for x in (an_a, an_b)
    }
    points = [Params(), Params(past_homes=False)]
    with_past, without = sweep(points, labels, an_a, an_b, ps_a=a, ps_b=b, salt=SALT, **eras)
    assert (with_past.trips, with_past.ev.precision, with_past.ev.false_negatives) == (3, 1.0, 1)
    assert (without.trips, without.ev.precision, without.ev.recall) == (4, 1.0, 1.0)


# report


def reported(*, make: str | None = "Apple", rows=(), old_home: int = 0) -> str:
    ps = [photo(make=make), photo(JUL_10 - DAY, gps=False, make=make)]
    cov = {"a": coverage(ps), "b": coverage(ps[:1])}
    travel = {p: coverage(in_labels([photo(make=make)], [TAHOE])) for p in "ab"}
    stats = {
        "a": [FilterStats("screenshot", 2), FilterStats("burst_duplicate", 0)],
        "b": [FilterStats("screenshot", 0)],  # a rule b lacks still gets a row
    }
    ev = evaluate([trip(JUL_10, JUL_10 + 3600), trip(0, 1)], [TAHOE])
    return render(cov, stats, ev, travel=travel, sweep=rows, old_home=old_home)


def test_report_holds_the_gate_and_the_counts():
    md = reported()
    assert "| Precision | 50.0% | ≥ 90% | fail |" in md
    assert "| GPS coverage of travel photos | 100.0% | < 60% | tier 2 stays P1 |" in md
    assert "| Exported | 4 | 1 |" in md and "| screenshot | 2 (50.0%) | 0 (0.0%) |" in md
    assert "| burst_duplicate | 0 (0.0%) | 0 (0.0%) |" in md
    assert "| Kept | 2 (50.0%) | 1 (100.0%) |" in md
    assert "| All photos | 50.0% (1 / 2) | 100.0% (1 / 1) |" in md
    assert "| 2026 | 50.0% (1 / 2) | 100.0% (1 / 1) |" in md
    assert "Not run, or older" in md and "unavailable" not in md
    assert "| Old-home days (not scored) | 0 |" in md
    assert "| Old-home days (not scored) | 3 |" in reported(old_home=3)


def test_report_says_unavailable_for_an_ios_export():
    md = reported(make=None)
    assert "| Camera (camera_make set) | unavailable | unavailable |" in md
    assert "unknown, not imported" in md


def test_report_flags_low_travel_coverage():
    ps = [photo(gps=False), photo(gps=False), photo()]
    cov = {"a": coverage(ps)}
    md = render(cov, {"a": []}, evaluate([], [TAHOE]), travel={"a": coverage(in_labels(ps, [TAHOE]))})
    assert "| GPS coverage of travel photos | 33.3% | < 60% | pull tier 2 into P0 |" in md


def test_report_holds_the_sweep_and_its_best_run():
    md = reported(rows=[row(1.0, 0.5), row(1.0, 1.0, city_km=50.0)])
    assert "| city_km=50 | 1 |" in md
    assert "**city_km=50**" in md


def test_report_is_numbers_only():
    md = reported(rows=[row(1.0, 1.0)])
    for leak in ("tahoe", "Somewhere", "9qfwt1", "2026-07", str(JUL_10)):
        assert leak not in md
    assert not re.search(r"\d{9,}", md)  # nothing shaped like an epoch


# cli


@pytest.fixture
def pipeline(tmp_path):
    run, d = CliRunner().invoke, ["--data", str(tmp_path)]
    steps = [
        ["synth", "--out", str(tmp_path)],
        *(["ingest", "-p", p, *d] for p in "ab"),
        *(["filter", "-p", p, *d] for p in "ab"),
        ["buckets", "-p", "a", "--expand", *d],
        ["buckets", "-p", "b", "--raw", *d],
        ["match", *d],
        *(["anchors", "-p", p, *d] for p in "ab"),
        ["trips", *d],
    ]
    for args in steps:
        assert run(app, args).exit_code == 0, args
    return tmp_path


def test_cli_sweep_then_report(pipeline):
    run, d = CliRunner().invoke, ["--data", str(pipeline)]
    out = run(app, ["sweep", *d])
    assert out.exit_code == 0 and "sweep: 15 runs, best defaults" in out.output
    assert len(json.loads((pipeline / "sweep.json").read_text())) == 15
    out = run(app, ["report", "--min-precision", "1.0", "--min-recall", "1.0", *d])
    assert out.exit_code == 0, out.output
    assert "precision=1.00 recall=1.00 tp=4 fp=0 fn=0 splits=0 merges=0 sweep=yes" in out.output
    md = (pipeline / "spike_report.md").read_text()
    assert "| min_photos=3 | 5 | 80.0% | 100.0% | 1 | 0 | 0 | 0 |" in md
    assert "Not run, or older" not in md


def test_cli_report_leaves_out_a_sweep_older_than_its_inputs(pipeline):
    """A sweep of other data, such as the synthetic run, must never land in this report."""
    run, d = CliRunner().invoke, ["--data", str(pipeline)]
    assert run(app, ["sweep", *d]).exit_code == 0
    later = (pipeline / "sweep.json").stat().st_mtime + 10
    os.utime(pipeline / "a_filtered.parquet", (later, later))
    out = run(app, ["report", *d])
    assert out.exit_code == 0 and "sweep=stale, rerun sweep" in out.output
    assert "Not run, or older" in (pipeline / "spike_report.md").read_text()


def test_cli_report_names_what_to_hand_check_on_the_terminal_only(pipeline):
    labels = pipeline / "labels.csv"
    extra = "\n tahoe-2 , 2026-07-11 ,2026-07-11, Lake Tahoe\nbig-sur,2026-08-01,2026-08-02,Big Sur\n"  # blank, padded
    labels.write_text(labels.read_text() + extra)
    out = CliRunner().invoke(app, ["report", "--min-recall", "1.0", "--data", str(pipeline)])
    assert out.exit_code == 1  # big-sur is missed
    assert "missed: big-sur" in out.output
    assert "merged: 2026-07-10 14:00Z..2026-07-13 02:00Z covers tahoe, tahoe-2" in out.output
    md = (pipeline / "spike_report.md").read_text()
    assert "big-sur" not in md and "| Merges (1 detected : n labeled) | 1 |" in md


def test_cli_report_leaves_old_home_days_out_of_the_score(pipeline):
    path = pipeline / "trips.json"
    ws = json.loads(path.read_text())
    day = {**ws[0], "start_utc": 0, "end_utc": 3600, "away_reason": "old home: shared home then", "kind": OLD_HOME}
    path.write_text(json.dumps([*ws, day]))
    out = CliRunner().invoke(app, ["report", "--min-precision", "1.0", "--data", str(pipeline)])
    assert out.exit_code == 0 and "precision=1.00 recall=1.00 tp=4 fp=0" in out.output
    assert "old-home days: 1, not scored" in out.output and "no label:" not in out.output
    assert "| Old-home days (not scored) | 1 |" in (pipeline / "spike_report.md").read_text()


def test_cli_report_names_a_detection_no_label_covers(pipeline):
    labels = pipeline / "labels.csv"
    labels.write_text("\n".join(line for line in labels.read_text().splitlines() if not line.startswith("monterey")))
    out = CliRunner().invoke(app, ["report", "--min-precision", "0.9", "--data", str(pipeline)])
    assert out.exit_code == 1 and "precision=0.75" in out.output
    assert "no label: 2026-06-13 17:00Z..2026-06-14 00:00Z 9q923f" in out.output


@pytest.mark.parametrize(
    ("line", "error"),
    [
        ("tahoe,2026-07-12,2026-07-10,Lake Tahoe", "ends (2026-07-10) before it starts"),
        ("tahoe,2026-07-10,Lake Tahoe", "expected 4 fields, got 3"),
        ("tahoe,July 10,2026-07-12,Lake Tahoe", "Invalid isoformat"),
    ],
)
def test_cli_refuses_bad_labels(pipeline, line, error):
    (pipeline / "labels.csv").write_text(f"label,start_date,end_date,place\n{line}\n")
    for cmd in ("report", "sweep"):
        out = CliRunner().invoke(app, [cmd, "--data", str(pipeline)])
        assert out.exit_code == 2 and "labels.csv:2:" in out.output and error in out.output, cmd


def test_cli_warns_on_empty_labels(pipeline):
    (pipeline / "labels.csv").write_text("label,start_date,end_date,place\n\n")
    out = CliRunner().invoke(app, ["report", "--data", str(pipeline)])
    assert out.exit_code == 0 and "labels.csv holds no trips" in out.output


def test_sweep_rows_round_trip_through_json(pipeline):
    run, d = CliRunner().invoke, ["--data", str(pipeline)]
    assert run(app, ["sweep", *d]).exit_code == 0
    rows = _read_sweep(pipeline / "sweep.json")
    _write_sweep(rows, pipeline / "again.json")
    assert _read_sweep(pipeline / "again.json") == rows
    assert rows[0].ev.overlaps == ((0, 2), (1, 3), (2, 1), (3, 0))  # tuples again, not JSON lists
