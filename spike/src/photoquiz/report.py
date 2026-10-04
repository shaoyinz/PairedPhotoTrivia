"""Coverage stats, evaluation against hand labels, and the parameter sweep (§1.8).

The reporting edge, not the algorithm: nothing here is ported to Swift. `render` writes numbers
only, with no rows, coordinates, timestamps, geohashes, label names or places, so its figures can
be quoted in a commit while data/spike_report.md itself stays local.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, fields, replace

from photoquiz.buckets import GEOHASH_PRECISION, matched_keys, own_keys, salted_set
from photoquiz.filters import FilterStats
from photoquiz.matching import match
from photoquiz.models import TRIP, Anchors, BucketKey, Era, PhotoMeta, TripWindow
from photoquiz.trips import CITY_KM, GAP_HOURS, MAX_SILENCE_HOURS, MIN_PHOTOS, REACH_HOURS, assemble

PRECISION_GATE = 0.9  # phase-1 gate
TIER2_COVERAGE = 0.6  # GPS coverage of travel photos below this pulls tier 2 into P0


@dataclass(frozen=True, slots=True)
class Label:
    label: str
    start_date: str  # UTC yyyy-mm-dd, inclusive
    end_date: str
    place: str


def label_span(lb: Label) -> tuple[int, int]:
    """[start, end) in UTC epoch seconds: start_date 00:00Z up to the midnight after end_date.
    Raises ValueError on a date that is not yyyy-mm-dd or an end before the start."""
    start, end = dt.date.fromisoformat(lb.start_date), dt.date.fromisoformat(lb.end_date)
    if end < start:
        raise ValueError(f"label {lb.label!r} ends ({lb.end_date}) before it starts ({lb.start_date})")
    return _midnight(start), _midnight(end + dt.timedelta(days=1))


def _midnight(d: dt.date) -> int:
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC).timestamp())


def _utc_year(t: int) -> int:
    return (dt.datetime(1970, 1, 1, tzinfo=dt.UTC) + dt.timedelta(seconds=t)).year


# coverage


@dataclass(frozen=True, slots=True)
class Coverage:
    total: int
    with_gps: int
    by_year: dict[int, tuple[int, int]]  # UTC year -> (with_gps, total); photos without a timestamp left out
    camera: tuple[int, int] | None  # (with_gps, total) where camera_make is set; None = unknown
    imported: tuple[int, int] | None  # (with_gps, total) where it is not; None = unknown


def _gps(ps: Sequence[PhotoMeta]) -> tuple[int, int]:
    return sum(p.has_gps for p in ps), len(ps)


def coverage(ps: Sequence[PhotoMeta]) -> Coverage:
    """GPS coverage overall, by UTC year, and by camera vs imported.

    The camera split rests on `camera_make`. The iOS exporter leaves it empty on every row
    (§1.2a), which means unknown, not imported. So when no photo carries a make, both halves are
    None (unavailable) rather than 0% camera.
    """
    years: dict[int, list[PhotoMeta]] = {}
    for p in ps:
        if p.utc_epoch is not None:
            years.setdefault(_utc_year(p.utc_epoch), []).append(p)
    camera = [p for p in ps if p.camera_make is not None]
    imported = [p for p in ps if p.camera_make is None]
    return Coverage(
        total=len(ps),
        with_gps=sum(p.has_gps for p in ps),
        by_year={y: _gps(years[y]) for y in sorted(years)},
        camera=_gps(camera) if camera else None,
        imported=_gps(imported) if camera else None,
    )


def in_labels(ps: Sequence[PhotoMeta], labels: Sequence[Label]) -> list[PhotoMeta]:
    """The photos taken inside a labeled trip: the travel photos the tier-2 trigger is about.
    Labels rather than detected trips, because detection needs GPS and would flatter coverage."""
    spans = [label_span(lb) for lb in labels]
    return [p for p in ps if p.utc_epoch is not None and any(lo <= p.utc_epoch < hi for lo, hi in spans)]


# evaluation


@dataclass(frozen=True, slots=True)
class Evaluation:
    precision: float  # true_positives / detected trips; 0 when nothing was detected
    recall: float  # labels found / labeled; 0 when nothing was labeled
    true_positives: int  # detected trips that overlap a label
    false_positives: int  # detected trips that overlap none
    false_negatives: int  # labels no detected trip overlaps
    splits: int  # labels overlapped by 2+ detected trips (n detected : 1 labeled)
    merges: int  # detected trips that overlap 2+ labels (1 detected : n labeled)
    labeled: int
    overlaps: tuple[tuple[int, int], ...] = ()  # (trip index, label index); names them on the terminal


def evaluate(trips: Sequence[TripWindow], labels: Sequence[Label]) -> Evaluation:
    """A detected trip is a true positive if it overlaps a labeled trip in time.

    Both intervals are half-open: the trip's window, and the label's UTC days. Precision counts
    detected trips and recall counts labels, so a label found as three trips is one label found
    and three true positives. Neither number sees a split or a merge, hence the two counts.
    """
    spans = [label_span(lb) for lb in labels]
    overlaps = tuple(
        (i, j) for i, w in enumerate(trips) for j, (lo, hi) in enumerate(spans) if w.start_utc < hi and lo < w.end_utc
    )
    per_trip = Counter(i for i, _ in overlaps)
    per_label = Counter(j for _, j in overlaps)
    return Evaluation(
        precision=len(per_trip) / len(trips) if trips else 0.0,
        recall=len(per_label) / len(labels) if labels else 0.0,
        true_positives=len(per_trip),
        false_positives=len(trips) - len(per_trip),
        false_negatives=len(labels) - len(per_label),
        splits=sum(n > 1 for n in per_label.values()),
        merges=sum(n > 1 for n in per_trip.values()),
        labeled=len(labels),
        overlaps=overlaps,
    )


# sweep


@dataclass(frozen=True, slots=True)
class Params:
    """One sweep point; the defaults are the pipeline's own. The reach stays at REACH_HOURS."""

    gap_hours: int = GAP_HOURS
    geohash_precision: int = GEOHASH_PRECISION
    min_photos: int = MIN_PHOTOS
    city_km: float = CITY_KM
    max_silence_hours: int = MAX_SILENCE_HOURS
    past_homes: bool = True  # judge each bucket against the homes of its hour (§1.5); False = anchors only


# Gaps start at 6 because assemble needs 2 * reach_hours <= gap_hours.
SWEEP: dict[str, tuple[int | float, ...]] = {
    "gap_hours": (6, 12, 24),
    "geohash_precision": (5, 6, 7),
    "min_photos": (3, 5, 8),
    "city_km": (15.0, 25.0, 50.0),
    "max_silence_hours": (24, 72, 168),
}

# Pairs that interact, so they are also swept over their full product. Each of these two can end
# a trip the other lets run: a 5 km home city merges Napa and Santa Cruz only from a 72 h cap (§1.7).
JOINT: tuple[tuple[str, str], ...] = (("city_km", "max_silence_hours"),)


@dataclass(frozen=True, slots=True)
class SweepRow:
    params: Params
    trips: int
    ev: Evaluation


def grid(
    base: Params = Params(),
    axes: Mapping[str, Sequence[int | float]] = SWEEP,
    joint: Sequence[tuple[str, str]] = JOINT,
) -> list[Params]:
    """The defaults first, then each axis varied alone around them, then each joint pair over the
    product of its two axes. No point appears twice: 15 runs rather than the full product's 243."""
    points = [replace(base, **{name: v}) for name, values in axes.items() for v in values]
    points += [replace(base, **{x: vx, y: vy}) for x, y in joint for vx in axes[x] for vy in axes[y]]
    return list(dict.fromkeys([base, *points]))


def sweep(
    points: Sequence[Params],
    labels: Sequence[Label],
    anchors_a: Anchors,
    anchors_b: Anchors,
    *,
    ps_a: Sequence[PhotoMeta],
    ps_b: Sequence[PhotoMeta],
    salt: bytes,
    eras_a: Sequence[Era] | None = None,
    eras_b: Sequence[Era] | None = None,
) -> Iterator[SweepRow]:
    """Run buckets -> match -> trips at each point and score it, one row at a time.

    The pipeline's own path: A expanded, B raw, both salted, intersected blind, mapped back on
    A's side. Matching is redone once per geohash precision; the other parameters only re-assemble.
    The home histories apply where `past_homes` is set. Old-home days are left out of the score
    and of the trip count.
    """
    keys: dict[int, list[BucketKey]] = {}
    for p in points:
        if p.geohash_precision not in keys:
            own_a = own_keys(ps_a, expanded=True, precision=p.geohash_precision)
            raw_b = own_keys(ps_b, expanded=False, precision=p.geohash_precision)
            m = match(salted_set(own_a, salt), salted_set(raw_b, salt))
            keys[p.geohash_precision] = sorted(matched_keys(own_a, m, salt))
        ws = assemble(
            keys[p.geohash_precision],
            anchors_a,
            anchors_b,
            ps_a=ps_a,
            ps_b=ps_b,
            gap_hours=p.gap_hours,
            city_km=p.city_km,
            max_silence_hours=p.max_silence_hours,
            min_photos=p.min_photos,
            eras_a=eras_a if p.past_homes else None,
            eras_b=eras_b if p.past_homes else None,
        )
        trips = [w for w in ws if w.kind == TRIP]
        yield SweepRow(p, len(trips), evaluate(trips, labels))


def best(rows: Sequence[SweepRow]) -> SweepRow:
    """The run to take defaults from. Runs past the precision gate beat every run short of it.
    Past the gate: the highest recall, then the fewest merges (the failure a quiz round feels
    most), then the fewest splits, then precision. Short of it, precision comes first instead of
    recall, so a run that detects everything and fails the gate badly does not win.
    Ties keep the earlier row, so the current defaults stand unless a run beats them."""

    def rank(r: SweepRow) -> tuple[bool, float, int, int, float]:
        ev = r.ev
        passed = ev.precision >= PRECISION_GATE
        first, last = (ev.recall, ev.precision) if passed else (ev.precision, ev.recall)
        return passed, first, -ev.merges, -ev.splits, last

    return max(rows, key=rank)


def varied(p: Params, base: Params) -> str:
    """What sets `p` apart from `base`, e.g. "city_km=50"; "defaults" when nothing does."""
    return _describe(p, lambda name: getattr(p, name) != getattr(base, name)) or "defaults"


def every(p: Params) -> str:
    """All of `p`, e.g. "gap_hours=6, geohash_precision=6, ..."."""
    return _describe(p, lambda name: True)


def _describe(p: Params, keep: Callable[[str], bool]) -> str:
    def value(v: float | bool) -> str:
        return str(v).lower() if isinstance(v, bool) else f"{v:g}"

    return ", ".join(f"{f.name}={value(getattr(p, f.name))}" for f in fields(Params) if keep(f.name))


# rendering


def _pct(n: int, d: int) -> str:
    return "—" if d == 0 else f"{100 * n / d:.1f}%"


def _count(n: int, d: int) -> str:
    return f"{n} ({_pct(n, d)})"


def _cell(c: tuple[int, int] | None) -> str:
    return "unavailable" if c is None else f"{_pct(*c)} ({c[0]} / {c[1]})"


def _table(head: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    return [
        "| " + " | ".join(head) + " |",
        "|" + "|".join(" --- " for _ in head) + "|",
        *("| " + " | ".join(r) + " |" for r in rows),
        "",
    ]


def render(
    cov: Mapping[str, Coverage],
    filter_stats: Mapping[str, Sequence[FilterStats]],
    ev: Evaluation,
    *,
    travel: Mapping[str, Coverage],
    sweep: Sequence[SweepRow] = (),
    old_home: int = 0,
) -> str:
    """Markdown for data/spike_report.md: numbers only, no raw rows.

    `cov` and `travel` are per person and cover the photos the filters kept; `travel` only those
    inside a labeled trip. `sweep` is empty until `photoquiz sweep` has run. `old_home` counts the
    old-home days found next to the trips, which `ev` leaves out.
    """
    people = list(cov)
    travel_gps = sum(c.with_gps for c in travel.values())
    travel_total = sum(c.total for c in travel.values())
    detected = ev.true_positives + ev.false_positives
    out = ["# Spike report", "", "Written by `photoquiz report`. Numbers only: no rows, coordinates or timestamps.", ""]

    out += ["## Gate", ""]
    if travel_total == 0:
        tier2 = "no labeled travel photos"
    elif travel_gps / travel_total < TIER2_COVERAGE:
        tier2 = "pull tier 2 into P0"
    else:
        tier2 = "tier 2 stays P1"
    passed = "pass" if ev.precision >= PRECISION_GATE else "fail"
    out += _table(
        ("Check", "Result", "Threshold", "Status"),
        [
            ("Precision", _pct(ev.true_positives, detected), f"≥ {PRECISION_GATE:.0%}", passed),
            ("GPS coverage of travel photos", _pct(travel_gps, travel_total), f"< {TIER2_COVERAGE:.0%}", tier2),
        ],
    )

    out += ["## Trips against hand labels", ""]
    found = ev.labeled - ev.false_negatives
    out += _table(
        ("Measure", "Value"),
        [
            ("Labeled trips", str(ev.labeled)),
            ("Detected trips", str(detected)),
            ("Precision", f"{_pct(ev.true_positives, detected)} ({ev.true_positives} of {detected} overlap a label)"),
            ("Recall", f"{_pct(found, ev.labeled)} ({found} of {ev.labeled} labels found)"),
            ("False positives", str(ev.false_positives)),
            ("Missed labels", str(ev.false_negatives)),
            ("Splits (n detected : 1 labeled)", str(ev.splits)),
            ("Merges (1 detected : n labeled)", str(ev.merges)),
            ("Old-home days (not scored)", str(old_home)),
        ],
    )

    out += ["## GPS coverage", "", "Share of photos with coordinates, after filters. Years are UTC.", ""]
    years = sorted({y for c in cov.values() for y in c.by_year})
    rows = [
        ("All photos", *(_cell((cov[p].with_gps, cov[p].total)) for p in people)),
        ("Travel photos (inside a labeled trip)", *(_cell((travel[p].with_gps, travel[p].total)) for p in people)),
        *((str(y), *(_cell(cov[p].by_year.get(y, (0, 0))) for p in people)) for y in years),
        ("Camera (camera_make set)", *(_cell(cov[p].camera) for p in people)),
        ("Imported (no camera_make)", *(_cell(cov[p].imported) for p in people)),
    ]
    out += _table(("Photos", *people), rows)
    if any(cov[p].camera is None for p in people):
        out += [
            "Camera vs imported is unavailable where no row has a camera make, as in every iOS export: "
            "empty there means unknown, not imported.",
            "",
        ]

    out += ["## Filters", "", "Photos each rule dropped, as a share of the export.", ""]
    exported = {p: cov[p].total + sum(s.dropped for s in filter_stats[p]) for p in people}
    rules = list(dict.fromkeys(s.rule for p in people for s in filter_stats[p]))
    dropped = {p: {s.rule: s.dropped for s in filter_stats[p]} for p in people}
    out += _table(
        ("Rule", *people),
        [
            ("Exported", *(str(exported[p]) for p in people)),
            *((r, *(_count(dropped[p].get(r, 0), exported[p]) for p in people)) for r in rules),
            ("Kept", *(_count(cov[p].total, exported[p]) for p in people)),
        ],
    )

    out += ["## Parameter sweep", ""]
    if not sweep:
        out += ["Not run, or older than its inputs: run `photoquiz sweep`, then `photoquiz report` again.", ""]
        return "\n".join(out)
    base = sweep[0].params
    out += [
        f"Each parameter alone around the defaults ({every(base)}), then "
        + "; ".join(f"{x} with {y}" for x, y in JOINT)
        + f" over every pair of their values. Reach {REACH_HOURS} h throughout.",
        "",
    ]
    out += _table(
        ("Run", "Trips", "Precision", "Recall", "FP", "Missed", "Splits", "Merges"),
        [
            (
                varied(r.params, base),
                str(r.trips),
                _pct(r.ev.true_positives, r.trips),
                _pct(r.ev.labeled - r.ev.false_negatives, r.ev.labeled),
                *(str(n) for n in (r.ev.false_positives, r.ev.false_negatives, r.ev.splits, r.ev.merges)),
            )
            for r in sweep
        ],
    )
    out += [
        f"Best run (past the {PRECISION_GATE:.0%} precision gate: recall, then fewest merges, fewest splits, "
        f"precision; short of it, precision first): "
        f"**{varied(best(sweep).params, base)}**.",
        "",
    ]
    return "\n".join(out)

