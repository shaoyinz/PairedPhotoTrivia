"""Home / work inference from local hours (§1.5).

Device-local, like `buckets.py`: it sees coordinates and local times, and its output (the anchors
file) never leaves the device. Local time is `utc_epoch + tz_offset_s`, used here only for
"what hour was it where the photo was taken", never for matching.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Sequence

import pygeohash as pgh

from photoquiz.commute import BUFFER_KM
from photoquiz.models import Anchors, Era, LatLon, PhotoMeta
from photoquiz.project import distance_km

GEOHASH_PRECISION = 7  # ~150 m
NIGHT_HOURS = range(0, 6)  # local [00:00, 06:00)
WORK_HOURS = range(10, 16)  # local [10:00, 16:00), Mon–Fri only
SECONDS_PER_DAY = 86_400
MIN_SUPPORT_DAYS = 5  # below this the CLI warns; a guess until real libraries say otherwise

# The home history votes over evenings as well: a real library can have a located photo after
# midnight on only a few nights a year, but after 20:00 on many more evenings (§1.5).
EVENING_HOURS = (20, 21, 22, 23, 0, 1, 2, 3, 4, 5)  # local [20:00, 06:00)
ERA_WINDOW_DAYS = 180  # each home-history vote sees the nights within half of this either side of it
ERA_STEP_DAYS = 30  # one vote per step, back from the latest photo
MIN_ERA_VOTES = 3  # a past home must win this many votes in a row (votes without a winner skipped)
MOVE_KM = BUFFER_KM  # a winner this close to a home is that home: a move inside the buffer changes nothing


class NoNightPhotosError(ValueError):
    """No GPS photo at night inside the window, so there is nothing to call home."""


def local_hour(p: PhotoMeta) -> int | None:
    """0..23 from local_epoch; None without a timestamp or time zone. Never use for matching.

    Floor division and floor modulo, so a pre-1970 local time still gives 0..23. Swift's `/` and
    `%` truncate toward zero, so the port needs the floor versions.
    """
    return None if p.local_epoch is None else p.local_epoch // 3600 % 24


def local_day(p: PhotoMeta) -> int | None:
    """Local calendar day as a count of days since 1970-01-01 (floor, like `local_hour`)."""
    return None if p.local_epoch is None else p.local_epoch // SECONDS_PER_DAY


def weekday(day: int) -> int:
    """Monday = 0 … Sunday = 6, as in Python's `date.weekday()`. Day 0, 1970-01-01, was a Thursday."""
    return (day + 3) % 7


def _night(p: PhotoMeta) -> bool:
    return local_hour(p) in NIGHT_HOURS


def _evening(p: PhotoMeta) -> bool:
    return local_hour(p) in EVENING_HOURS


def _workday(p: PhotoMeta) -> bool:
    return local_hour(p) in WORK_HOURS and weekday(local_day(p)) < 5


def _most_frequent_cell(ps: Sequence[PhotoMeta]) -> tuple[str, LatLon, int] | None:
    """The geohash-7 cell seen on the most distinct local days, with the mean position of its
    photos and that day count. Ties go to more photos, then the smallest geohash, so the answer
    does not depend on input order.

    Days, not photos: one night out with 40 photos must not outvote six ordinary nights at home,
    and a week of weekday vacation photos must not become "work".
    """
    days: dict[str, set[int]] = {}
    members: dict[str, list[PhotoMeta]] = {}
    for p in ps:
        cell = pgh.encode(p.lat, p.lon, precision=GEOHASH_PRECISION)
        days.setdefault(cell, set()).add(local_day(p))
        members.setdefault(cell, []).append(p)
    if not members:
        return None
    best = min(members, key=lambda c: (-len(days[c]), -len(members[c]), c))
    m = members[best]
    center = LatLon(sum(p.lat for p in m) / len(m), sum(p.lon for p in m) / len(m))
    return best, center, len(days[best])


def infer_anchors(ps: Sequence[PhotoMeta], *, person: str, now_utc: int, window_days: int = 90) -> Anchors:
    """Home = the geohash-7 seen on the most nights at local [00:00, 06:00).
    Work = the geohash-7 seen on the most weekdays at local [10:00, 16:00), or None if there are
    no such photos. Only photos with GPS and a time zone, taken in [now_utc - window_days, now_utc].

    Raises NoNightPhotosError when there is no night photo to infer home from. A weak anchor is
    still returned: `home_nights` and `work_days` carry the support, and the caller decides.
    """
    lo = now_utc - window_days * SECONDS_PER_DAY
    recent = [p for p in ps if p.has_gps and p.local_epoch is not None and lo <= p.utc_epoch <= now_utc]
    night = [p for p in recent if _night(p)]
    workday = [p for p in recent if _workday(p)]

    home = _most_frequent_cell(night)
    if home is None:
        raise NoNightPhotosError(f"no GPS photo between 00:00 and 06:00 local in the last {window_days} days")
    work = _most_frequent_cell(workday)
    home_cell, home_at, home_nights = home
    work_cell, work_at, work_days = work if work is not None else (None, None, 0)
    return Anchors(
        person=person,
        home=home_at,
        work=work_at,
        home_geohash7=home_cell,
        work_geohash7=work_cell,
        window_days=window_days,
        home_nights=home_nights,
        work_days=work_days,
    )


# home history


def home_eras(
    ps: Sequence[PhotoMeta],
    current: Anchors,
    *,
    now_utc: int,
    window_days: int = ERA_WINDOW_DAYS,
    step_days: int = ERA_STEP_DAYS,
    min_votes: int = MIN_ERA_VOTES,
) -> list[Era]:
    """Where this partner has lived, oldest first, ending with the confirmed `current` anchors.

    Votes like `infer_anchors` every step_days back from now_utc, but over EVENING_HOURS: each vote
    takes the evenings within window_days / 2 either side and needs MIN_SUPPORT_DAYS of them. A winner within
    MOVE_KM of the current home is the current home. Anywhere else must win min_votes votes in a
    row to be a past home: a stay away must outweigh the nights at home over several overlapping
    half-years, which with regular night photos at home a month away cannot. `_moved_at` dates
    each change of home, and a past home's position and work are voted again over its own era.

    Inferred only: the user confirms the current home and is never asked about past ones. A
    single era (`since_utc = None`) means no move was seen, and every stage then behaves exactly
    as with the anchors alone.
    """
    located = sorted((p for p in ps if p.has_gps and p.local_epoch is not None), key=lambda p: p.utc_epoch)
    nights = [p for p in located if _evening(p)]  # "nights" below: evenings included
    times = [p.utc_epoch for p in nights]
    half, step = window_days * SECONDS_PER_DAY // 2, step_days * SECONDS_PER_DAY

    centers, t = [], now_utc
    while times and t + half >= times[0]:
        centers.append(t)
        t -= step
    votes: list[tuple[int, LatLon | None]] = []  # (center, winner); None = the current home
    for c in reversed(centers):
        won = _most_frequent_cell(nights[bisect_left(times, c - half) : bisect_right(times, c + half)])
        if won is not None and won[2] >= MIN_SUPPORT_DAYS:
            votes.append((c, None if distance_km(current.home, won[1]) <= MOVE_KM else won[1]))
    runs = _runs([v for run in _runs(votes) if run[0][1] is None or len(run) >= min_votes for v in run])
    if all(run[0][1] is None for run in runs):
        return [Era(None, current.home, current.work, False, _nights_near(nights, current.home))]

    bounds: list[int] = []  # bounds[i] = when the home of runs[i] gave way to that of runs[i + 1]

    def home(run: list[tuple[int, LatLon | None]]) -> LatLon:
        return current.home if run[0][1] is None else run[0][1]

    def start(run: list[tuple[int, LatLon | None]]) -> int:
        """The earliest night the move out of `run` may be dated to: its last vote's window, and
        never before the previous move."""
        return max(run[-1][0] - half, bounds[-1]) if bounds else run[-1][0] - half

    for r1, r2 in zip(runs, runs[1:]):
        bounds.append(_moved_at(nights, home(r1), home(r2), start(r1), r2[0][0] + half))
    if runs[-1][0][1] is not None:  # the latest votes went elsewhere: a move too recent to win one
        bounds.append(_moved_at(nights, home(runs[-1]), current.home, start(runs[-1]), now_utc))
        runs.append([(now_utc, None)])

    eras = []
    for i, run in enumerate(runs):
        since, until = bounds[i - 1] if i else None, bounds[i] if i < len(bounds) else None
        span = _between(nights, since, until)
        if run[0][1] is None:
            eras.append(Era(since, current.home, current.work, False, _nights_near(span, current.home)))
            continue
        won = _most_frequent_cell(span)
        at = home(run) if won is None else won[1]
        work = _most_frequent_cell([p for p in _between(located, since, until) if _workday(p)])
        eras.append(Era(since, at, None if work is None else work[1], True, _nights_near(span, at)))
    return eras


def _between(ps: Sequence[PhotoMeta], since: int | None, until: int | None) -> list[PhotoMeta]:
    """Photos in [since, until); None leaves that end open."""
    return [p for p in ps if (since is None or since <= p.utc_epoch) and (until is None or p.utc_epoch < until)]


def _runs(votes: Sequence[tuple[int, LatLon | None]]) -> list[list[tuple[int, LatLon | None]]]:
    """Consecutive votes for the same home: both the current home, or both within MOVE_KM of the
    run's first winner."""
    runs: list[list[tuple[int, LatLon | None]]] = []
    for c, won in votes:
        if runs and _same_home(runs[-1][0][1], won):
            runs[-1].append((c, won))
        else:
            runs.append([(c, won)])
    return runs


def _same_home(a: LatLon | None, b: LatLon | None) -> bool:
    if a is None or b is None:
        return a is b
    return distance_km(a, b) <= MOVE_KM


def _near(p: PhotoMeta, home: LatLon) -> bool:
    return distance_km(home, LatLon(p.lat, p.lon)) <= MOVE_KM


def _nights_near(nights: Sequence[PhotoMeta], home: LatLon) -> int:
    return len({local_day(p) for p in nights if _near(p, home)})


def _moved_at(nights: Sequence[PhotoMeta], old: LatLon, new: LatLon, lo: int, hi: int) -> int:
    """When the move from `old` to `new` happened, judged on the nights in [lo, hi].

    A boundary t scores the distinct nights near `old` before t plus those near `new` from t on.
    The best scores form a range, from just after the last night at the old home to the first
    night at the new one when the move is clean; the middle of that range is returned. With no
    night near either home, the middle of [lo, hi].
    """
    seen = [(p.utc_epoch, local_day(p), _near(p, old), _near(p, new)) for p in nights if lo <= p.utc_epoch <= hi]
    seen = [s for s in seen if s[2] or s[3]]
    if not seen:
        return (lo + hi) // 2
    scores = {}
    for t in sorted({u + d for u, *_ in seen for d in (0, 1)}):
        before = {day for u, day, at_old, _ in seen if at_old and u < t}
        after = {day for u, day, _, at_new in seen if at_new and u >= t}
        scores[t] = len(before) + len(after)
    top = max(scores.values())
    best = [t for t, s in scores.items() if s == top]
    return (best[0] + best[-1]) // 2
