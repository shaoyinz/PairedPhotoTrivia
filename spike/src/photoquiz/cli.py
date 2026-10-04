"""Thin typer shells over the pure modules. Each stage reads/writes data/ and prints its counts.

Pipeline: synth -> ingest -> filter -> buckets -> match -> anchors -> trips -> report
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import os
import secrets
import tempfile
import tomllib
from dataclasses import asdict, replace
from functools import partial
from pathlib import Path
from typing import Annotated

import typer

from photoquiz import anchors as anchors_mod
from photoquiz import buckets, commute, filters, matching, report, synth, trips
from photoquiz.ingest import read_csv, read_parquet, summarize, write_csv, write_parquet
from photoquiz.library import read_library
from photoquiz.models import TRIP, Anchors, BucketHash, Era, LatLon, PhotoMeta, TripWindow
from photoquiz.project import distance_km
from photoquiz.schema import LABEL_COLUMNS, SchemaError

# src/photoquiz/cli.py -> repo root; data/ is gitignored there
DEFAULT_DATA = Path(os.environ.get("PHOTOQUIZ_DATA", Path(__file__).resolve().parents[3] / "data"))

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Couples photo quiz: trip-detection spike.")

Person = Annotated[str, typer.Option("--person", "-p", help="a or b")]
DataDir = Annotated[Path, typer.Option("--data", help="Local data directory (gitignored).")]


def _fmt_utc(t: int | None) -> str:
    return "—" if t is None else dt.datetime.fromtimestamp(t, dt.UTC).strftime("%Y-%m-%d %H:%MZ")


def _fmt_day(t: int | None) -> str:
    return "" if t is None else dt.datetime.fromtimestamp(t, dt.UTC).strftime("%Y-%m-%d")


def _eras(ps: list[PhotoMeta], a: Anchors) -> list[Era]:
    """The partner's home history over the whole export, ending with the anchors file's home."""
    return anchors_mod.home_eras(ps, a, now_utc=max(p.utc_epoch for p in ps if p.utc_epoch is not None))


def _eras_line(person: str, eras: list[Era]) -> str:
    """Terminal only: when each home held and the evenings behind it, e.g.
    "past home ..2026-08-03 (412 evenings), current home 2026-08-03.. (9 evenings)". Dates, never places."""
    if len(eras) == 1:
        return f"  homes {person}: one home throughout"
    spans = [
        f"{'past' if e.inferred else 'current'} home {_fmt_day(e.since_utc)}..{_fmt_day(nxt)} ({e.nights} evenings)"
        for e, nxt in zip(eras, [e.since_utc for e in eras[1:]] + [None])
    ]
    return f"  homes {person}: " + ", ".join(spans)


def _salt(data: Path) -> bytes:
    path = data / "salt.key"
    if not path.exists():
        data.mkdir(parents=True, exist_ok=True)
        path.write_bytes(secrets.token_bytes(buckets.SALT_BYTES))
        path.chmod(0o600)
        typer.echo(f"generated {path}")
    return path.read_bytes()


def _write_hashes(hs: frozenset[BucketHash], path: Path) -> None:
    path.write_text("".join(f"{h.hex()}\n" for h in sorted(hs)))


def _read_hashes(path: Path) -> frozenset[BucketHash]:
    return frozenset(BucketHash(bytes.fromhex(line)) for line in path.read_text().split())


OWN = "generated.json"  # file name -> sha256 of the bytes the pipeline last wrote there


def _write_own(directory: Path, files: dict[str, bytes], *, force: bool, stage: str) -> None:
    """Write every file or none, never replacing one that is yours unless force (exit 1 otherwise).

    A file may be replaced when it is missing, already holds exactly these bytes, or is still what
    the pipeline last wrote there (its hash in generated.json). Anything else is yours: a real
    export copied in, labels written by hand, edited anchors. So `make skeleton` can rerun over
    its own synthetic files but stops before touching real ones.
    """
    manifest = directory / OWN
    own: dict[str, str] = json.loads(manifest.read_text()) if manifest.exists() else {}

    def replaceable(name: str, new: bytes) -> bool:
        path = directory / name
        if not path.exists():
            return True
        old = path.read_bytes()
        return old == new or own.get(name) == hashlib.sha256(old).hexdigest()

    yours = [name for name, b in files.items() if not replaceable(name, b)]
    if yours and not force:
        typer.echo(
            f"{stage}: refusing to replace {', '.join(yours)} in {directory}: changed since the pipeline wrote it "
            "(a real export, labels, hand edits?); pass --force to overwrite",
            err=True,
        )
        raise typer.Exit(1)
    directory.mkdir(parents=True, exist_ok=True)
    for name, b in files.items():
        (directory / name).write_bytes(b)
        own[name] = hashlib.sha256(b).hexdigest()
    manifest.write_text(json.dumps(own, indent=2, sort_keys=True) + "\n")


def _write_anchors(a: Anchors, path: Path) -> None:
    path.write_text(_anchors_toml(a))


def _anchors_toml(a: Anchors) -> str:
    def ll(p: LatLon | None) -> str:
        return "{}" if p is None else f"{{ lat = {p.lat:.6f}, lon = {p.lon:.6f} }}"

    if a.shared_home is None:
        shared = '# shared_home = true  # true/false in either file overrides "homes < 1 km apart"\n'
    else:
        shared = f"shared_home = {str(a.shared_home).lower()}\n"
    return (
        "# Inferred home/work. Edit by hand: this file stands in for the in-app confirm screen.\n"
        "# Edit home, work (work = {} means none) and shared_home; the rest records what inference saw.\n"
        f'person = "{a.person}"\n'
        f"home = {ll(a.home)}\n"
        f"work = {ll(a.work)}\n"
        f"{shared}"
        f'home_geohash7 = "{a.home_geohash7}"\n'
        f'work_geohash7 = "{a.work_geohash7 or ""}"\n'
        f"window_days = {a.window_days}\n"
        f"home_nights = {a.home_nights}\n"
        f"work_days = {a.work_days}\n"
    )


def _read_anchors(path: Path) -> Anchors:
    d = tomllib.loads(path.read_text())
    work = d.get("work") or None
    shared_home = d.get("shared_home")
    if shared_home is not None and not isinstance(shared_home, bool):
        raise SchemaError(f"{path}: shared_home must be true or false")
    return Anchors(
        person=d["person"],
        home=LatLon(**d["home"]),
        work=LatLon(**work) if work else None,
        home_geohash7=d["home_geohash7"],
        work_geohash7=d.get("work_geohash7") or None,
        window_days=d["window_days"],
        home_nights=d["home_nights"],
        work_days=d["work_days"],
        shared_home=shared_home,
    )


def _read_labels(path: Path) -> list[report.Label]:
    """Hand-written, so cells are stripped and blank lines skipped; a bad row raises SchemaError."""
    labels = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        if tuple(next(reader, ())) != LABEL_COLUMNS:
            raise SchemaError(f"{path}: header must be {','.join(LABEL_COLUMNS)}")
        for line_no, row in enumerate(reader, start=2):
            if not any(c.strip() for c in row):
                continue
            if len(row) != len(LABEL_COLUMNS):
                raise SchemaError(f"{path}:{line_no}: expected {len(LABEL_COLUMNS)} fields, got {len(row)}")
            lb = report.Label(*(c.strip() for c in row))
            try:
                report.label_span(lb)
            except ValueError as e:
                raise SchemaError(f"{path}:{line_no}: {e}") from e
            labels.append(lb)
    return labels


def _labels_or_exit(data: Path, stage: str) -> list[report.Label]:
    try:
        labels = _read_labels(data / "labels.csv")
    except SchemaError as e:
        typer.echo(f"{stage}: {e}", err=True)
        raise typer.Exit(2) from e
    if not labels:
        typer.echo(f"{stage}: labels.csv holds no trips; precision and recall mean nothing yet", err=True)
    return labels


SWEEP_INPUTS = (
    "labels.csv", "anchors_a.toml", "anchors_b.toml", "a_filtered.parquet", "b_filtered.parquet", "salt.key",
)  # fmt: skip


def _sweep_if_fresh(data: Path) -> tuple[list[report.SweepRow], str]:
    """sweep.json's rows when it is newer than everything it was computed from, so a sweep of
    other data (the synthetic run, say) never lands in this report. Also says which case held."""
    path = data / "sweep.json"
    if not path.exists():
        return [], "not run"
    if any((data / n).stat().st_mtime > path.stat().st_mtime for n in SWEEP_INPUTS if (data / n).exists()):
        return [], "stale, rerun sweep"
    return _read_sweep(path), "yes"


def _write_sweep(rows: list[report.SweepRow], path: Path) -> None:
    path.write_text(json.dumps([asdict(r) for r in rows], indent=2))


def _read_sweep(path: Path) -> list[report.SweepRow]:
    def row(d: dict) -> report.SweepRow:
        ev = {**d["ev"], "overlaps": tuple(tuple(o) for o in d["ev"]["overlaps"])}
        return report.SweepRow(report.Params(**d["params"]), d["trips"], report.Evaluation(**ev))

    return [row(d) for d in json.loads(path.read_text())]


def _hand_check(ws: list[TripWindow], labels: list[report.Label], ev: report.Evaluation) -> list[str]:
    """What to look at by hand: missed, split and merged labels, and windows no label covers.
    Terminal only; label names and dates never go into the report."""
    per_label = {j: [i for i, jj in ev.overlaps if jj == j] for j in range(len(labels))}
    per_trip = {i: [j for ii, j in ev.overlaps if ii == i] for i in range(len(ws))}

    def when(w: TripWindow) -> str:
        return f"{_fmt_utc(w.start_utc)}..{_fmt_utc(w.end_utc)}"

    return [
        *(f"missed: {labels[j].label}" for j, ts in per_label.items() if not ts),
        *(f"split: {labels[j].label} into {len(ts)} trips" for j, ts in per_label.items() if len(ts) > 1),
        *(
            f"merged: {when(ws[i])} covers {', '.join(labels[j].label for j in js)}"
            for i, js in per_trip.items()
            if len(js) > 1
        ),
        *(f"no label: {when(ws[i])} {ws[i].representative_geohash6}" for i, js in per_trip.items() if not js),
    ]


@app.command("synth")
def synth_cmd(
    out: Annotated[Path, typer.Option("--out")] = DEFAULT_DATA,
    seed: int = 7,
    force: Annotated[bool, typer.Option("--force", help="Overwrite real exports and labels too.")] = False,
) -> None:
    """Write synthetic a_photos.csv, b_photos.csv and labels.csv with planted trips.

    Refuses to replace any of them that the pipeline did not write, such as a real export or
    hand-written labels, unless --force; then it writes none.
    """
    data = synth.generate(seed)
    with tempfile.TemporaryDirectory() as tmp:
        files = {p.name: p.read_bytes() for p in synth.write(data, Path(tmp)).values()}
    _write_own(out, files, force=force, stage="synth")
    typer.echo(f"synth: a={len(data.a)} b={len(data.b)} labels={len(data.labels)} -> {out}")
    for name in files:
        typer.echo(f"  {out / name}")


@app.command()
def ingest(
    person: Person,
    csv_path: Annotated[Path | None, typer.Option("--csv", help="Exporter CSV (§1.2a).")] = None,
    library: Annotated[Path | None, typer.Option("--library", help="Mac Photos library (§1.2b).")] = None,
    out: Annotated[Path | None, typer.Option("--out")] = None,
    data: DataDir = DEFAULT_DATA,
) -> None:
    """Validate a metadata CSV against the schema and store it as parquet.

    With --library, first write the Mac library to data/<person>_photos.csv (osxphotos; needs Full
    Disk Access), then ingest that file exactly as if the iOS exporter had produced it.
    """
    if library is not None and csv_path is not None:
        typer.echo("ingest: --csv and --library are alternatives; pass one", err=True)
        raise typer.Exit(2)
    src = csv_path or data / f"{person}_photos.csv"
    dst = out or data / f"{person}_photos.parquet"
    if library is not None:
        write_csv(read_library(library), src)
        typer.echo(f"library {person}: {library} -> {src}")
    try:
        ps = read_csv(src)
    except SchemaError as e:
        typer.echo(f"ingest: {e}", err=True)
        raise typer.Exit(2) from e
    write_parquet(ps, dst)
    s = summarize(ps)
    typer.echo(
        f"ingest {person}: rows={s.rows} range={_fmt_utc(s.first_utc)}..{_fmt_utc(s.last_utc)} "
        f"no_timestamp={s.no_timestamp} no_gps={s.no_gps} -> {dst}"
    )


@app.command("filter")
def filter_cmd(person: Person, data: DataDir = DEFAULT_DATA) -> None:
    """Drop screenshots, timestamp-less rows and burst duplicates; report each rule's count."""
    ps = read_parquet(data / f"{person}_photos.parquet")
    kept, stats = filters.apply_all(ps)
    write_parquet(kept, data / f"{person}_filtered.parquet")
    (data / f"{person}_filter_stats.json").write_text(json.dumps([asdict(s) for s in stats], indent=2))
    typer.echo(f"filter {person}: in={len(ps)} kept={len(kept)}")
    for s in stats:
        typer.echo(f"  {s.rule}: -{s.dropped}")


@app.command("buckets")
def buckets_cmd(
    person: Person,
    expand: Annotated[bool, typer.Option("--expand/--raw", help="Expand exactly one side (A).")] = False,
    data: DataDir = DEFAULT_DATA,
) -> None:
    """Bucket photos to geohash6 x hour and write the salted hashes (the only thing that leaves a device)."""
    ps = read_parquet(data / f"{person}_filtered.parquet")
    keys = buckets.own_keys(ps, expanded=expand)
    hs = buckets.salted_set(keys, _salt(data))
    _write_hashes(hs, data / f"{person}_hashes.txt")
    typer.echo(f"buckets {person}: photos={len(ps)} keys={len(keys)} expanded={expand} hashes={len(hs)}")


@app.command("match")
def match_cmd(data: DataDir = DEFAULT_DATA) -> None:
    """Intersect A's expanded hashes with B's raw hashes, then map the survivors back on each side."""
    expanded_a = _read_hashes(data / "a_hashes.txt")
    raw_b = _read_hashes(data / "b_hashes.txt")
    m = matching.match(expanded_a, raw_b)
    _write_hashes(m, data / "matched.txt")
    typer.echo(f"match: expanded_a={len(expanded_a)} raw_b={len(raw_b)} matched={len(m)}")
    # Device-local from here: each side sees only the survivors plus its own photos.
    salt = _salt(data)
    for person, expanded in (("a", True), ("b", False)):
        ps = read_parquet(data / f"{person}_filtered.parquet")
        keys = buckets.matched_keys(buckets.own_keys(ps, expanded=expanded), m, salt)
        photos = buckets.matched_photos(ps, keys, expanded=expanded)
        typer.echo(f"  {person}: keys={len(keys)} photos={len(photos)}")


@app.command("anchors")
def anchors_cmd(
    person: Person,
    window_days: int = 90,
    force: Annotated[bool, typer.Option("--force", help="Overwrite the file even if edited by hand.")] = False,
    data: DataDir = DEFAULT_DATA,
) -> None:
    """Infer home/work over the export's last --window-days and write anchors_<person>.toml for hand
    editing. Refuses to replace a file edited by hand unless --force."""
    path = data / f"anchors_{person}.toml"
    ps = read_parquet(data / f"{person}_filtered.parquet")
    now_utc = max(p.utc_epoch for p in ps if p.utc_epoch is not None)
    try:
        a = anchors_mod.infer_anchors(ps, person=person, now_utc=now_utc, window_days=window_days)
    except anchors_mod.NoNightPhotosError as e:
        typer.echo(f"anchors {person}: {e}; rerun with a larger --window-days or write {path} by hand", err=True)
        raise typer.Exit(1) from e
    _write_own(data, {path.name: _anchors_toml(a).encode()}, force=force, stage=f"anchors {person}")
    typer.echo(
        f"anchors {person}: window={window_days}d home={a.home_geohash7} ({a.home_nights} nights) "
        f"work={a.work_geohash7 or '—'} ({a.work_days} weekdays) -> {path}"
    )
    for name, days in (("home", a.home_nights), ("work", a.work_days)):
        if days < anchors_mod.MIN_SUPPORT_DAYS:
            typer.echo(
                f"  warning: {name} rests on {days} day(s) (< {anchors_mod.MIN_SUPPORT_DAYS}); check it in "
                f"{path.name}, or rerun with --window-days {window_days * 2}",
                err=True,
            )


@app.command("trips")
def trips_cmd(
    gap_hours: Annotated[int, typer.Option(help="Away buckets further apart start a new session.")] = trips.GAP_HOURS,
    reach_hours: Annotated[int, typer.Option(help="Backfill reach past a trip's ends; <= gap / 2.")] = trips.REACH_HOURS,
    city_km: Annotated[float, typer.Option(help="Home city: km around home->work.")] = trips.CITY_KM,
    max_silence_hours: Annotated[
        int, typer.Option(help="A trip ends once each partner goes this long without a located photo.")
    ] = trips.MAX_SILENCE_HOURS,
    min_photos: int = trips.MIN_PHOTOS,
    past_homes: Annotated[
        bool, typer.Option("--past-homes/--no-past-homes", help="Judge each hour against the homes you had then.")
    ] = True,
    data: DataDir = DEFAULT_DATA,
) -> None:
    """Map matched hashes back to A's own buckets, keep the away ones, join nights until someone is
    back in their home city, apply the >= 5 rule -> trips.json. Days at a home one of you has since
    left go in too, as kind "old_home"."""
    anchors_a, anchors_b = _read_anchors(data / "anchors_a.toml"), _read_anchors(data / "anchors_b.toml")
    try:
        shared = commute.resolve_shared_home(anchors_a, anchors_b)
    except ValueError as e:
        typer.echo(f"trips: {e}; fix shared_home in anchors_a.toml / anchors_b.toml", err=True)
        raise typer.Exit(2) from e
    by_hand = anchors_a.shared_home is not None or anchors_b.shared_home is not None
    if shared:
        rule = f"shared home, away = outside both buffers, out of town = outside both {city_km:g} km home cities"
    else:
        rule = f"different homes, away = outside either buffer, out of town = outside either {city_km:g} km home city"
    typer.echo(
        f"trips: homes {distance_km(anchors_a.home, anchors_b.home):.2f} km apart -> {rule}"
        + (" (shared_home set by hand)" if by_hand else "")
    )
    ps_a = read_parquet(data / "a_filtered.parquet")
    ps_b = read_parquet(data / "b_filtered.parquet")
    eras_a, eras_b = (_eras(ps_a, anchors_a), _eras(ps_b, anchors_b)) if past_homes else (None, None)
    if past_homes:
        for person, eras in (("a", eras_a), ("b", eras_b)):
            typer.echo(_eras_line(person, eras))
    salt = _salt(data)
    matched = _read_hashes(data / "matched.txt")
    # Device-local step: A knows which of its own expanded keys produced each surviving hash.
    matched_keys = sorted(buckets.matched_keys(buckets.own_keys(ps_a, expanded=True), matched, salt))

    assemble = partial(
        trips.assemble,
        matched_keys,
        anchors_a,
        anchors_b,
        ps_a=ps_a,
        ps_b=ps_b,
        gap_hours=gap_hours,
        reach_hours=reach_hours,
        city_km=city_km,
        max_silence_hours=max_silence_hours,
        eras_a=eras_a,
        eras_b=eras_b,
    )
    try:
        away, ws = assemble(min_photos=0), assemble(min_photos=min_photos)  # away: before the >= min_photos rule
    except ValueError as e:
        typer.echo(f"trips: {e}", err=True)
        raise typer.Exit(2) from e
    (data / "trips.json").write_text(json.dumps([asdict(w) for w in ws], indent=2))
    found = sum(w.kind == TRIP for w in ws)
    typer.echo(
        f"trips: matched_keys={len(matched_keys)} away={len(away)} trips={found} old_home={len(ws) - found} "
        f"(gap > {gap_hours} h, reach {reach_hours} h, silence <= {max_silence_hours} h, >= {min_photos} photos)"
    )
    for w in away:
        typer.echo(
            f"  {'' if w in ws else f'under {min_photos} photos: '}"
            f"{_fmt_utc(w.start_utc)}..{_fmt_utc(w.end_utc)} {w.representative_geohash6} "
            f"a={w.photo_count_a} b={w.photo_count_b} ({w.away_reason})"
        )


@app.command("report")
def report_cmd(
    min_precision: Annotated[float, typer.Option(help="Exit 1 below this (gate: 0.9).")] = 0.0,
    min_recall: Annotated[float, typer.Option(help="Exit 1 below this.")] = 0.0,
    data: DataDir = DEFAULT_DATA,
) -> None:
    """Gate, precision/recall/split/merge, GPS coverage, filter drops and the sweep (if run) ->
    spike_report.md. Lists what to hand-check on the terminal only."""
    labels = _labels_or_exit(data, "report")
    kept = {p: read_parquet(data / f"{p}_filtered.parquet") for p in ("a", "b")}
    cov = {p: report.coverage(ps) for p, ps in kept.items()}
    travel = {p: report.coverage(report.in_labels(ps, labels)) for p, ps in kept.items()}
    fstats = {
        p: [filters.FilterStats(**s) for s in json.loads((data / f"{p}_filter_stats.json").read_text())]
        for p in ("a", "b")
    }
    detected = [TripWindow(**w) for w in json.loads((data / "trips.json").read_text())]
    ws = [w for w in detected if w.kind == TRIP]  # old-home days are quiz material, not trips to score
    old_home = len(detected) - len(ws)
    ev = report.evaluate(ws, labels)
    rows, swept = _sweep_if_fresh(data)
    md = report.render(cov, fstats, ev, travel=travel, sweep=rows, old_home=old_home)
    (data / "spike_report.md").write_text(md)
    typer.echo(
        f"report: precision={ev.precision:.2f} recall={ev.recall:.2f} "
        f"tp={ev.true_positives} fp={ev.false_positives} fn={ev.false_negatives} "
        f"splits={ev.splits} merges={ev.merges} sweep={swept} -> {data / 'spike_report.md'}"
    )
    for line in _hand_check(ws, labels, ev):
        typer.echo(f"  {line}")
    if old_home:
        typer.echo(f"  old-home days: {old_home}, not scored")
    if ev.precision < min_precision or ev.recall < min_recall:
        typer.echo("report: below threshold", err=True)
        raise typer.Exit(1)


@app.command("sweep")
def sweep_cmd(data: DataDir = DEFAULT_DATA) -> None:
    """Rerun buckets -> match -> trips one parameter at a time around the defaults (gap hours,
    geohash precision, min photos, home-city radius, silence cap), then home-city radius and
    silence cap together, and once without past homes if either partner has one. Score each run
    against labels.csv -> sweep.json, which `report` renders."""
    labels = _labels_or_exit(data, "sweep")
    anchors_a, anchors_b = _read_anchors(data / "anchors_a.toml"), _read_anchors(data / "anchors_b.toml")
    ps_a = read_parquet(data / "a_filtered.parquet")
    ps_b = read_parquet(data / "b_filtered.parquet")
    eras_a, eras_b = _eras(ps_a, anchors_a), _eras(ps_b, anchors_b)
    points = report.grid()
    if len(eras_a) > 1 or len(eras_b) > 1:
        points.append(replace(points[0], past_homes=False))
    rows = []
    try:
        for r in report.sweep(
            points, labels, anchors_a, anchors_b, ps_a=ps_a, ps_b=ps_b, salt=_salt(data), eras_a=eras_a, eras_b=eras_b
        ):
            rows.append(r)
            typer.echo(
                f"  {report.varied(r.params, points[0])}: trips={r.trips} precision={r.ev.precision:.2f} "
                f"recall={r.ev.recall:.2f} fp={r.ev.false_positives} fn={r.ev.false_negatives} "
                f"splits={r.ev.splits} merges={r.ev.merges}"
            )
    except ValueError as e:
        typer.echo(f"sweep: {e}", err=True)
        raise typer.Exit(2) from e
    _write_sweep(rows, data / "sweep.json")
    typer.echo(
        f"sweep: {len(rows)} runs, best {report.varied(report.best(rows).params, points[0])} -> {data / 'sweep.json'}"
    )

