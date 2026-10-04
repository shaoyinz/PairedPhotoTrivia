"""Matched buckets -> trips and old-home days (§1.7).

Device-local, like `buckets.py`. Four steps:

1. Keep the matched buckets that are away (§1.6), each tested at its geohash-6 cell center
   against the homes the two of you had at that hour (§1.5's home history).
2. Sessionize them: a gap of more than GAP_HOURS starts a new session.
3. Join out-of-town sessions across the nights between them. A trip ends when either partner is
   seen back in their home city (CITY_KM around home->work), not when the photos pause.
4. Widen each trip by REACH_HOURS, backfill both partners' photos, keep it at >= MIN_PHOTOS.

A bucket that was home then but is away now, at a home one of you has since left, goes into an
old-home day instead: sessionized the same way, never joined across nights, and dropped where
it would overlap a trip.

Every test reduces to per-partner bits: is this bucket in my buffer then and now, in my home
city; in this gap, was I seen back in my city, did I keep taking located photos. So in phase 2
each phone can answer for itself, and neither needs the other's home, work or photos.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace

import pygeohash as pgh

from photoquiz.commute import CommuteBuffer, commute_buffer, is_away, is_shared_home, resolve_shared_home
from photoquiz.models import OLD_HOME, Anchors, BucketKey, Era, LatLon, PhotoMeta, TripWindow

GAP_HOURS = 6  # away buckets further apart than this start a new session
REACH_HOURS = 3  # backfill reaches this far past a trip's first and last bucket; at most GAP_HOURS / 2
CITY_KM = 25.0  # home city: within this of the home->work segment
MAX_SILENCE_HOURS = 72  # a trip ends once each partner has gone this long without a located photo
MIN_PHOTOS = 5


@dataclass(frozen=True, slots=True)
class Setting:
    """Both partners' homes at one moment: commute buffers, home cities, and whether they shared one."""

    buf_a: CommuteBuffer
    buf_b: CommuteBuffer
    city_a: CommuteBuffer
    city_b: CommuteBuffer
    shared_home: bool
    past: bool  # either partner's home then is an inferred past home

    def away(self, p: LatLon) -> bool:
        return is_away(p, self.buf_a, self.buf_b, shared_home=self.shared_home)

    def out_of_town(self, p: LatLon) -> bool:
        """The away rule with the home cities in place of the buffers."""
        return is_away(p, self.city_a, self.city_b, shared_home=self.shared_home)


@dataclass(frozen=True, slots=True)
class Homes:
    """The Setting in force at any moment, from both partners' home histories (§1.5)."""

    changes: tuple[int, ...]  # settings[i] holds from changes[i - 1] (from the start for i = 0)
    settings: tuple[Setting, ...]  # one more than changes; the last is now

    def at(self, t_utc: int) -> Setting:
        return self.settings[bisect_right(self.changes, t_utc)]

    @property
    def now(self) -> Setting:
        return self.settings[-1]

    @staticmethod
    def of(
        anchors_a: Anchors,
        anchors_b: Anchors,
        *,
        eras_a: Sequence[Era] | None = None,
        eras_b: Sequence[Era] | None = None,
        city_km: float = CITY_KM,
    ) -> Homes:
        """From each partner's eras (`anchors.home_eras`), or from the anchors alone when None.

        While both homes are confirmed ones, the anchors files' shared_home override applies (§1.6).
        Once either is an inferred past home, sharing goes by distance, since nobody confirmed it.
        Raises ValueError when the two anchors files set shared_home differently.
        """
        shared_now = resolve_shared_home(anchors_a, anchors_b)
        ea, eb = (
            list(eras) if eras else [Era(None, x.home, x.work, False, x.home_nights)]
            for eras, x in ((eras_a, anchors_a), (eras_b, anchors_b))
        )
        changes = sorted({e.since_utc for e in (*ea, *eb) if e.since_utc is not None})
        settings = []
        for t in (None, *changes):
            a, b = _era_at(ea, t), _era_at(eb, t)
            past = a.inferred or b.inferred
            settings.append(
                Setting(
                    commute_buffer(a.home, a.work),
                    commute_buffer(b.home, b.work),
                    commute_buffer(a.home, a.work, city_km),
                    commute_buffer(b.home, b.work, city_km),
                    is_shared_home(a.home, b.home) if past else shared_now,
                    past,
                )
            )
        return Homes(tuple(changes), tuple(settings))


def _era_at(eras: Sequence[Era], t: int | None) -> Era:
    """The era holding at t; None = before every change, i.e. the first era (whose since_utc is None)."""
    return [e for e in eras if e.since_utc is None or (t is not None and e.since_utc <= t)][-1]


def _when(k: BucketKey) -> int:
    return k.hour_index * 3600


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


def _out_of_town(ks: Sequence[BucketKey], homes: Homes) -> list[LatLon]:
    """Cell centers of the buckets outside the home cities of their hour, by the same rule as away
    (§1.6): outside both cities with a shared home, outside either with different homes."""
    return [c for k in ks if homes.at(_when(k)).out_of_town(c := cell_center(k))]


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
    homes: Homes,
    *,
    ps_a: Sequence[PhotoMeta],
    ps_b: Sequence[PhotoMeta],
    max_silence_hours: int = MAX_SILENCE_HOURS,
) -> list[list[BucketKey]]:
    """Join neighbouring out-of-town sessions across the nights between them.

    Two sessions join when both have a bucket out of town and, in the time between them, neither
    partner was seen back in their home city and at least one kept taking located photos (no
    stretch longer than max_silence_hours without one). Each partner's silence is timed alone, so
    each phone can answer for itself. Sessions in town never join: you sleep at home. The gap is
    judged with the home cities in force at its start.
    """
    max_silence_s = max_silence_hours * 3600
    trips: list[list[BucketKey]] = []
    for s in sessions:
        if trips:
            prev = trips[-1]
            spots = _out_of_town(prev, homes)
            nxt = _out_of_town(s, homes)
            if spots and nxt:
                lo, hi = (prev[-1].hour_index + 1) * 3600, s[0].hour_index * 3600
                then = homes.at(lo)
                (back_a, steady_a), (back_b, steady_b) = (
                    _gap_bits(lo, hi, city, ps, spots + nxt, max_silence_s)
                    for city, ps in ((then.city_a, ps_a), (then.city_b, ps_b))
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


def _reason(trip: Sequence[BucketKey], homes: Homes, *, sessions: int) -> str:
    """Which rule applied, where the trip's buckets fell relative to the home cities of their hour,
    and how many sessions it joined, e.g. "shared home: out of town, 3 sessions". The rule is the
    one at the trip's start; "then" marks a trip measured against a past home."""
    seen = set()
    for k in trip:
        c, at = cell_center(k), homes.at(_when(k))
        seen.add((at.city_a.covers(c), at.city_b.covers(c)))
    first = homes.at(_when(trip[0]))
    if first.shared_home:
        places = [("out of town", {(False, False)}), ("in town", {(True, False), (False, True), (True, True)})]
    else:
        places = [
            ("out of town", {(False, False)}),
            ("in a's city", {(True, False)}),
            ("in b's city", {(False, True)}),
            ("in town", {(True, True)}),
        ]
    where = " + ".join(label for label, bits in places if seen & bits)
    rule = ("shared home" if first.shared_home else "different homes") + (" then" if first.past else "")
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
    eras_a: Sequence[Era] | None = None,
    eras_b: Sequence[Era] | None = None,
) -> list[TripWindow]:
    """Matched keys -> trips: the away buckets, sessionized, joined across nights until someone is
    back in their home city, then widened, backfilled and kept at >= min_photos across both devices.

    With home histories (`eras_a`, `eras_b` from `anchors.home_eras`), each bucket is judged against
    the homes of its hour. A bucket that was home then and is away now becomes part of an old-home
    day (kind OLD_HOME): sessionized the same way, never joined across nights, dropped if its window
    would overlap any trip's, then backfilled and kept at >= min_photos like a trip. Without them,
    or with a single era each, there are no old-home days. Sorted by start.

    Raises ValueError when the two anchors files set shared_home differently, or when
    2 * reach_hours > gap_hours: two windows could then overlap and a photo land in two trips.
    """
    if 2 * reach_hours > gap_hours:
        raise ValueError(f"reach_hours ({reach_hours}) must be at most half of gap_hours ({gap_hours})")
    homes = Homes.of(anchors_a, anchors_b, eras_a=eras_a, eras_b=eras_b, city_km=city_km)
    away: list[BucketKey] = []
    old: list[BucketKey] = []
    for k in matched:
        c = cell_center(k)
        if homes.at(_when(k)).away(c):
            away.append(k)
        elif homes.now.away(c):
            old.append(k)

    joined = join_nights(
        sessionize(away, gap_hours=gap_hours), homes, ps_a=ps_a, ps_b=ps_b, max_silence_hours=max_silence_hours
    )
    spans = [window(trip, reach_hours=reach_hours) for trip in joined]
    candidates = []
    for trip, (start, end) in zip(joined, spans):
        out = [k for k in trip if homes.at(_when(k)).out_of_town(cell_center(k))]
        reason = _reason(trip, homes, sessions=len(sessionize(trip, gap_hours=gap_hours)))
        candidates.append(TripWindow(start, end, len(trip), 0, 0, _representative(out or trip), reason))
    for day in sessionize(old, gap_hours=gap_hours):
        start, end = window(day, reach_hours=reach_hours)
        if any(start < e and s < end for s, e in spans):
            continue
        then = homes.at(_when(day[0]))
        reason = f"old home: {'shared home' if then.shared_home else 'different homes'} then"
        candidates.append(TripWindow(start, end, len(day), 0, 0, _representative(day), reason, OLD_HOME))

    kept = []
    for w in candidates:
        w = backfill(w, ps_a, ps_b)
        if w.photo_count_a + w.photo_count_b >= min_photos:
            kept.append(w)
    return sorted(kept, key=lambda w: w.start_utc)
