"""Matched buckets -> trips (§1.7).

Device-local, like `buckets.py`. Four steps:

1. Keep the matched buckets that are away (§1.6), each tested at its geohash-6 cell center.
2. Sessionize them: a gap of more than GAP_HOURS starts a new session.
3. Join out-of-town sessions across the nights between them. A trip ends when either partner is
   seen back in their home city (CITY_KM around home->work), not when the photos pause.
4. Widen each trip by REACH_HOURS, backfill both partners' photos, keep it at >= MIN_PHOTOS.

Every test reduces to per-partner bits: is this bucket in my buffer, in my home city; in this
gap, was I seen back in my city, did I keep taking located photos. So in phase 2 each phone can
answer for itself, and neither needs the other's home, work or photos.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pygeohash as pgh

from photoquiz.commute import CommuteBuffer, commute_buffer, is_away, resolve_shared_home
from photoquiz.models import Anchors, BucketKey, LatLon, PhotoMeta, TripWindow

GAP_HOURS = 6  # away buckets further apart than this start a new session
REACH_HOURS = 3  # backfill reaches this far past a trip's first and last bucket; at most GAP_HOURS / 2
CITY_KM = 25.0  # home city: within this of the home->work segment
MAX_SILENCE_HOURS = 72  # a trip ends once each partner has gone this long without a located photo
MIN_PHOTOS = 5


def sessionize(matched: Sequence[BucketKey], *, gap_hours: int = GAP_HOURS) -> list[list[BucketKey]]:
    """Sort by hour; a gap > gap_hours starts a new session.

    The gap is the difference in hour_index between consecutive keys, so hours 10 and 16 share
    a session at 6 and hours 10 and 17 do not. Keys within a session are ordered by
    (hour_index, geohash6). `BucketKey`'s own ordering compares geohash first, so it is not used.
    Duplicate keys count once.
    """
    keys = sorted(set(matched), key=lambda k: (k.hour_index, k.geohash6))
    sessions: list[list[BucketKey]] = []
    for k in keys:
        if sessions and k.hour_index - sessions[-1][-1].hour_index <= gap_hours:
            sessions[-1].append(k)
        else:
            sessions.append([k])
    return sessions


def cell_center(k: BucketKey) -> LatLon:
    """The point that stands for a bucket in the away and home-city tests. Both devices hold the
    matched key, so both get the same answer without anyone's photo coordinates. A geohash-6 cell
    is at most about 1.2 km x 0.6 km, small against the 5 km buffer."""
    c = pgh.decode(k.geohash6)
    return LatLon(c.latitude, c.longitude)


def _out_of_town(ks: Sequence[BucketKey], city_a: CommuteBuffer, city_b: CommuteBuffer, shared_home: bool) -> list[LatLon]:
    """Cell centers of the buckets outside the home cities, by the same rule as away (§1.6):
    outside both cities with a shared home, outside either with different homes."""
    return [c for k in ks if is_away(c := cell_center(k), city_a, city_b, shared_home=shared_home)]


def _gap_bits(
    lo: int, hi: int, city: CommuteBuffer, ps: Sequence[PhotoMeta], trip: Sequence[LatLon], max_silence_s: int
) -> tuple[bool, bool]:
    """One partner's two bits for [lo, hi), the time between two sessions: (seen back in their own
    home city, never more than max_silence_s without a located photo).

    A photo in their own city does not count as back when the trip itself is there: B visiting A
    is not ended by A's photos at home. GPS-less photos say nothing either way.
    """
    trip_here = any(city.covers(q) for q in trip)
    times = [lo, hi]
    for p in ps:
        if p.has_gps and p.utc_epoch is not None and lo <= p.utc_epoch < hi:
            if not trip_here and city.covers(LatLon(p.lat, p.lon)):
                return True, False
            times.append(p.utc_epoch)
    times.sort()
    return False, all(b - a <= max_silence_s for a, b in zip(times, times[1:]))


def join_nights(
    sessions: Sequence[Sequence[BucketKey]],
    city_a: CommuteBuffer,
    city_b: CommuteBuffer,
    *,
    shared_home: bool,
    ps_a: Sequence[PhotoMeta],
    ps_b: Sequence[PhotoMeta],
    max_silence_hours: int = MAX_SILENCE_HOURS,
) -> list[list[BucketKey]]:
    """Join neighbouring out-of-town sessions across the nights between them.

    Two sessions join when both have a bucket out of town and, in the time between them, neither
    partner was seen back in their home city and at least one kept taking located photos (no
    stretch longer than max_silence_hours without one). Each partner's silence is timed alone, so
    each phone can answer for itself. Sessions in town never join: you sleep at home.
    """
    max_silence_s = max_silence_hours * 3600
    trips: list[list[BucketKey]] = []
    for s in sessions:
        if trips:
            prev = trips[-1]
            spots = _out_of_town(prev, city_a, city_b, shared_home)
            nxt = _out_of_town(s, city_a, city_b, shared_home)
            if spots and nxt:
                lo, hi = (prev[-1].hour_index + 1) * 3600, s[0].hour_index * 3600
                (back_a, steady_a), (back_b, steady_b) = (
                    _gap_bits(lo, hi, city, ps, spots + nxt, max_silence_s)
                    for city, ps in ((city_a, ps_a), (city_b, ps_b))
                )
                if not (back_a or back_b) and (steady_a or steady_b):
                    prev.extend(s)
                    continue
        trips.append(list(s))
    return trips


def window(trip: Sequence[BucketKey], *, reach_hours: int = REACH_HOURS) -> tuple[int, int]:
    """[start_utc, end_utc): the trip's first to last hour, widened by reach_hours on each side.

    Widened so that backfill reaches photos only one partner took, such as A's morning and
    afternoon around B's single matched photo at lunch. It also covers A's matched photos, which
    can sit an hour either side of the key they matched, provided reach_hours >= 1.
    """
    pad = reach_hours * 3600
    hours = [k.hour_index for k in trip]
    return min(hours) * 3600 - pad, (max(hours) + 1) * 3600 + pad


def photos_in(start_utc: int, end_utc: int, ps: Sequence[PhotoMeta]) -> list[PhotoMeta]:
    """Every photo taken in [start_utc, end_utc), matched or not, with or without GPS."""
    return [p for p in ps if p.utc_epoch is not None and start_utc <= p.utc_epoch < end_utc]


def backfill(w: TripWindow, ps_a: Sequence[PhotoMeta], ps_b: Sequence[PhotoMeta]) -> TripWindow:
    """Count every photo from both partners inside the window, unmatched and GPS-less included."""
    return replace(
        w,
        photo_count_a=len(photos_in(w.start_utc, w.end_utc, ps_a)),
        photo_count_b=len(photos_in(w.start_utc, w.end_utc, ps_b)),
    )


def _representative(ks: Sequence[BucketKey]) -> str:
    """The cell seen in the most matched hours. Ties go to the earliest, then the smallest."""
    hours: dict[str, int] = {}
    first: dict[str, int] = {}
    for k in ks:
        hours[k.geohash6] = hours.get(k.geohash6, 0) + 1
        first.setdefault(k.geohash6, k.hour_index)
    return min(hours, key=lambda g: (-hours[g], first[g], g))


def _reason(
    trip: Sequence[BucketKey], city_a: CommuteBuffer, city_b: CommuteBuffer, *, shared_home: bool, sessions: int
) -> str:
    """Which rule applied, where the trip's buckets fell relative to the home cities, and how many
    sessions it joined, e.g. "shared home: out of town, 3 sessions"."""
    seen = set()
    for k in trip:
        c = cell_center(k)
        seen.add((city_a.covers(c), city_b.covers(c)))
    if shared_home:
        places = [("out of town", {(False, False)}), ("in town", {(True, False), (False, True), (True, True)})]
    else:
        places = [
            ("out of town", {(False, False)}),
            ("in a's city", {(True, False)}),
            ("in b's city", {(False, True)}),
            ("in town", {(True, True)}),
        ]
    where = " + ".join(label for label, bits in places if seen & bits)
    rule = "shared home" if shared_home else "different homes"
    return f"{rule}: {where}, {sessions} {'session' if sessions == 1 else 'sessions'}"


def assemble(
    matched: Sequence[BucketKey],
    anchors_a: Anchors,
    anchors_b: Anchors,
    *,
    ps_a: Sequence[PhotoMeta],
    ps_b: Sequence[PhotoMeta],
    gap_hours: int = GAP_HOURS,
    reach_hours: int = REACH_HOURS,
    city_km: float = CITY_KM,
    max_silence_hours: int = MAX_SILENCE_HOURS,
    min_photos: int = MIN_PHOTOS,
) -> list[TripWindow]:
    """Matched keys -> trips: the away buckets, sessionized, joined across nights until someone is
    back in their home city, then widened, backfilled and kept at >= min_photos across both devices.

    Raises ValueError when the two anchors files set shared_home differently, or when
    2 * reach_hours > gap_hours: two windows could then overlap and a photo land in two trips.
    """
    if 2 * reach_hours > gap_hours:
        raise ValueError(f"reach_hours ({reach_hours}) must be at most half of gap_hours ({gap_hours})")
    shared_home = resolve_shared_home(anchors_a, anchors_b)
    buf_a, buf_b = (commute_buffer(x.home, x.work) for x in (anchors_a, anchors_b))
    city_a, city_b = (commute_buffer(x.home, x.work, city_km) for x in (anchors_a, anchors_b))

    away = [k for k in matched if is_away(cell_center(k), buf_a, buf_b, shared_home=shared_home)]
    sessions = sessionize(away, gap_hours=gap_hours)
    joined = join_nights(
        sessions, city_a, city_b, shared_home=shared_home, ps_a=ps_a, ps_b=ps_b, max_silence_hours=max_silence_hours
    )
    kept = []
    for trip in joined:
        start, end = window(trip, reach_hours=reach_hours)
        out = [k for k in trip if is_away(cell_center(k), city_a, city_b, shared_home=shared_home)]
        w = backfill(
            TripWindow(
                start_utc=start,
                end_utc=end,
                matched_bucket_count=len(trip),
                photo_count_a=0,
                photo_count_b=0,
                representative_geohash6=_representative(out or trip),
                away_reason=_reason(
                    trip, city_a, city_b, shared_home=shared_home, sessions=len(sessionize(trip, gap_hours=gap_hours))
                ),
            ),
            ps_a,
            ps_b,
        )
        if w.photo_count_a + w.photo_count_b >= min_photos:
            kept.append(w)
    return kept
