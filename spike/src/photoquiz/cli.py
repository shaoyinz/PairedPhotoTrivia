"""Thin typer shells over the pure modules. Each stage reads/writes data/ and prints its counts.

Pipeline: synth -> ingest -> filter -> buckets -> match -> anchors -> trips -> report
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import secrets
import tomllib
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from photoquiz import anchors as anchors_mod
from photoquiz import buckets, filters, matching, report, synth, trips
from photoquiz.ingest import read_csv, read_parquet, summarize, write_parquet
from photoquiz.models import Anchors, BucketHash, BucketKey, LatLon, TripWindow
from photoquiz.schema import LABEL_COLUMNS, SchemaError

# src/photoquiz/cli.py -> repo root; data/ is gitignored there
DEFAULT_DATA = Path(os.environ.get("PHOTOQUIZ_DATA", Path(__file__).resolve().parents[3] / "data"))

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Couples photo quiz: trip-detection spike.")

Person = Annotated[str, typer.Option("--person", "-p", help="a or b")]
DataDir = Annotated[Path, typer.Option("--data", help="Local data directory (gitignored).")]


def _fmt_utc(t: int | None) -> str:
    return "—" if t is None else dt.datetime.fromtimestamp(t, dt.UTC).strftime("%Y-%m-%d %H:%MZ")


def _salt(data: Path) -> bytes:
    path = data / "salt.key"
    if not path.exists():
        data.mkdir(parents=True, exist_ok=True)
        path.write_bytes(secrets.token_bytes(32))
        path.chmod(0o600)
        typer.echo(f"generated {path}")
    return path.read_bytes()


def _write_hashes(hs: frozenset[BucketHash], path: Path) -> None:
    path.write_text("".join(f"{h.hex()}\n" for h in sorted(hs)))


def _read_hashes(path: Path) -> frozenset[BucketHash]:
    return frozenset(BucketHash(bytes.fromhex(line)) for line in path.read_text().split())


def _write_anchors(a: Anchors, path: Path) -> None:
    def ll(p: LatLon | None) -> str:
        return "{}" if p is None else f"{{ lat = {p.lat:.6f}, lon = {p.lon:.6f} }}"

    path.write_text(
        "# Inferred home/work. Edit by hand: this file stands in for the in-app confirm screen.\n"
        f'person = "{a.person}"\n'
        f"home = {ll(a.home)}\n"
        f"work = {ll(a.work)}\n"
        f'home_geohash7 = "{a.home_geohash7}"\n'
        f'work_geohash7 = "{a.work_geohash7 or ""}"\n'
        f"window_days = {a.window_days}\n"
        f"n_night_photos = {a.n_night_photos}\n"
        f"n_work_photos = {a.n_work_photos}\n"
    )


def _read_anchors(path: Path) -> Anchors:
    d = tomllib.loads(path.read_text())
    work = d.get("work") or None
    return Anchors(
        person=d["person"],
        home=LatLon(**d["home"]),
        work=LatLon(**work) if work else None,
        home_geohash7=d["home_geohash7"],
        work_geohash7=d.get("work_geohash7") or None,
        window_days=d["window_days"],
        n_night_photos=d["n_night_photos"],
        n_work_photos=d["n_work_photos"],
    )


def _read_labels(path: Path) -> list[report.Label]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        if tuple(next(reader, ())) != LABEL_COLUMNS:
            raise SchemaError(f"{path}: header must be {','.join(LABEL_COLUMNS)}")
        return [report.Label(*row) for row in reader]


@app.command("synth")
def synth_cmd(
    out: Annotated[Path, typer.Option("--out")] = DEFAULT_DATA,
    seed: int = 7,
) -> None:
    """Write synthetic a_photos.csv, b_photos.csv and labels.csv with planted trips."""
    data = synth.generate(seed)
    paths = synth.write(data, out)
    typer.echo(f"synth: a={len(data.a)} b={len(data.b)} labels={len(data.labels)} -> {out}")
    for p in paths.values():
        typer.echo(f"  {p}")


@app.command()
def ingest(
    person: Person,
    csv_path: Annotated[Path | None, typer.Option("--csv", help="Exporter CSV (§1.2a).")] = None,
    library: Annotated[Path | None, typer.Option("--library", help="Mac Photos library (§1.2b).")] = None,
    out: Annotated[Path | None, typer.Option("--out")] = None,
    data: DataDir = DEFAULT_DATA,
) -> None:
    """Validate a metadata CSV against the schema and store it as parquet."""
    if library is not None:
        raise NotImplementedError("§1.2b osxphotos ingest")
    src = csv_path or data / f"{person}_photos.csv"
    dst = out or data / f"{person}_photos.parquet"
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
    keys = {k for p in ps if (k := buckets.bucket_key(p)) is not None}
    if expand:
        keys = {e for k in keys for e in buckets.expand(k)}
    hs = buckets.salted_set(keys, _salt(data))
    _write_hashes(hs, data / f"{person}_hashes.txt")
    typer.echo(f"buckets {person}: photos={len(ps)} keys={len(keys)} expanded={expand} hashes={len(hs)}")


@app.command("match")
def match_cmd(data: DataDir = DEFAULT_DATA) -> None:
    """Intersect A's expanded hashes with B's raw hashes."""
    expanded_a = _read_hashes(data / "a_hashes.txt")
    raw_b = _read_hashes(data / "b_hashes.txt")
    m = matching.match(expanded_a, raw_b)
    _write_hashes(m, data / "matched.txt")
    typer.echo(f"match: expanded_a={len(expanded_a)} raw_b={len(raw_b)} matched={len(m)}")


@app.command("anchors")
def anchors_cmd(
    person: Person,
    window_days: int = 90,
    data: DataDir = DEFAULT_DATA,
) -> None:
    """Infer home/work and write anchors_<person>.toml for hand editing."""
    ps = read_parquet(data / f"{person}_filtered.parquet")
    now_utc = max(p.utc_epoch for p in ps if p.utc_epoch is not None)
    a = anchors_mod.infer_anchors(ps, now_utc=now_utc, window_days=window_days)
    path = data / f"anchors_{person}.toml"
    _write_anchors(a, path)
    typer.echo(
        f"anchors {person}: home={a.home_geohash7} (n={a.n_night_photos}) "
        f"work={a.work_geohash7} (n={a.n_work_photos}) -> {path}"
    )


@app.command("trips")
def trips_cmd(
    gap_hours: int = 6,
    min_photos: int = 5,
    data: DataDir = DEFAULT_DATA,
) -> None:
    """Map matched hashes back to A's own buckets, sessionize, apply the away and >= 5 rules."""
    ps_a = read_parquet(data / "a_filtered.parquet")
    ps_b = read_parquet(data / "b_filtered.parquet")
    salt = _salt(data)
    matched = _read_hashes(data / "matched.txt")
    # Device-local step: A knows which of its own expanded keys produced each surviving hash.
    own = {k for p in ps_a if (k := buckets.bucket_key(p)) is not None}
    candidates = {e for k in own for e in buckets.expand(k)}
    matched_keys: list[BucketKey] = sorted(k for k in candidates if buckets.salted(k, salt) in matched)
    sessions = trips.sessionize(matched_keys, gap_hours=gap_hours)
    ws = trips.assemble(
        sessions,
        _read_anchors(data / "anchors_a.toml"),
        _read_anchors(data / "anchors_b.toml"),
        ps_a=ps_a,
        ps_b=ps_b,
        min_photos=min_photos,
    )
    (data / "trips.json").write_text(json.dumps([asdict(w) for w in ws], indent=2))
    typer.echo(f"trips: matched_keys={len(matched_keys)} sessions={len(sessions)} trips={len(ws)}")
    for w in ws:
        typer.echo(
            f"  {_fmt_utc(w.start_utc)}..{_fmt_utc(w.end_utc)} {w.representative_geohash6} "
            f"a={w.photo_count_a} b={w.photo_count_b} ({w.away_reason})"
        )


@app.command("report")
def report_cmd(
    min_precision: Annotated[float, typer.Option(help="Exit 1 below this (gate: 0.9).")] = 0.0,
    min_recall: Annotated[float, typer.Option(help="Exit 1 below this.")] = 0.0,
    data: DataDir = DEFAULT_DATA,
) -> None:
    """Coverage, filter drops, precision/recall/split/merge -> spike_report.md."""
    cov = {p: report.coverage(read_parquet(data / f"{p}_photos.parquet")) for p in ("a", "b")}
    fstats = {
        p: [filters.FilterStats(**s) for s in json.loads((data / f"{p}_filter_stats.json").read_text())]
        for p in ("a", "b")
    }
    ws = [TripWindow(**w) for w in json.loads((data / "trips.json").read_text())]
    ev = report.evaluate(ws, _read_labels(data / "labels.csv"))
    (data / "spike_report.md").write_text(report.render(cov, fstats, ev))
    typer.echo(
        f"report: precision={ev.precision:.2f} recall={ev.recall:.2f} "
        f"tp={ev.true_positives} fp={ev.false_positives} fn={ev.false_negatives} "
        f"splits={ev.splits} merges={ev.merges} -> {data / 'spike_report.md'}"
    )
    if ev.precision < min_precision or ev.recall < min_recall:
        typer.echo("report: below threshold", err=True)
        raise typer.Exit(1)


@app.command("sweep")
def sweep_cmd(data: DataDir = DEFAULT_DATA) -> None:
    """Sweep gap hours, geohash precision (5/6/7) and min photos against the labels."""
    raise NotImplementedError("§1.8")

