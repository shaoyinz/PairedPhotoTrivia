"""Home / work inference from local hours (§1.5).

Device-local, like `buckets.py`: it sees coordinates and local times, and its output (the anchors
file) never leaves the device. Local time is `utc_epoch + tz_offset_s`, used here only for
"what hour was it where the photo was taken", never for matching.
"""

from __future__ import annotations

from collections.abc import Sequence

import pygeohash as pgh

from photoquiz.models import Anchors, LatLon, PhotoMeta

GEOHASH_PRECISION = 7  # ~150 m
NIGHT_HOURS = range(0, 6)  # local [00:00, 06:00)
WORK_HOURS = range(10, 16)  # local [10:00, 16:00), Mon–Fri only
SECONDS_PER_DAY = 86_400
MIN_SUPPORT_DAYS = 5  # below this the CLI warns; a guess until real libraries say otherwise


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
    night = [p for p in recent if local_hour(p) in NIGHT_HOURS]
    workday = [p for p in recent if local_hour(p) in WORK_HOURS and weekday(local_day(p)) < 5]

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
