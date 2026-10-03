"""Commute buffer and the "counts as away" rule (§1.6).

Each partner's buffer lives on the `project.to_km` plane centered at their own home, so a
buffer carries its origin and a point is projected onto that plane before it is tested. One
plane per partner, not one for the pair: a long-distance pair's homes can be a continent
apart, far beyond the range where a single flat plane is accurate.
"""

from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

from photoquiz.models import Anchors, LatLon
from photoquiz.project import distance_km, to_km

BUFFER_KM = 5.0
SHARED_HOME_KM = 1.0  # homes strictly closer than this are one home


@dataclass(frozen=True, slots=True)
class CommuteBuffer:
    """`area` is in km on the plane centered at `origin` (the partner's home)."""

    origin: LatLon
    area: BaseGeometry

    def covers(self, p: LatLon) -> bool:
        """Inside or on the edge."""
        return self.area.covers(Point(to_km(p, self.origin)))


def commute_buffer(home: LatLon, work: LatLon | None, km: float = BUFFER_KM) -> CommuteBuffer:
    """Everything within `km` of the straight home->work segment (a disc around home when work
    is None or sits on home).

    Shapely draws the round ends as polygons inscribed in the true circle, at most 6 m inside
    it at 5 km. A Swift port testing point-to-segment distance <= km agrees everywhere else.
    """
    seg = Point(0.0, 0.0) if work is None else LineString([(0.0, 0.0), to_km(work, home)])
    return CommuteBuffer(home, seg.buffer(km))


def is_shared_home(a: LatLon, b: LatLon, km: float = SHARED_HOME_KM) -> bool:
    """Homes strictly less than `km` apart. By distance, never by geohash: two homes 10 m
    apart can sit in neighboring cells (§1.5's fixture does)."""
    return distance_km(a, b) < km


def resolve_shared_home(a: Anchors, b: Anchors, km: float = SHARED_HOME_KM) -> bool:
    """The hand override if either anchors file sets `shared_home`, else `is_shared_home`.
    Raises ValueError when the two files set it differently."""
    overrides = {x.shared_home for x in (a, b) if x.shared_home is not None}
    if len(overrides) > 1:
        raise ValueError(f"anchors for {a.person} and {b.person} set shared_home differently")
    return overrides.pop() if overrides else is_shared_home(a.home, b.home, km)


def is_away(p: LatLon, buf_a: CommuteBuffer, buf_b: CommuteBuffer, *, shared_home: bool) -> bool:
    """Shared home -> outside BOTH buffers. Different homes -> outside EITHER (visits count).

    Depends on `p` only through the two "inside" bits, so in phase 2 each phone can answer for
    its own buffer and neither needs the other's home or work.
    """
    in_a, in_b = buf_a.covers(p), buf_b.covers(p)
    return not (in_a or in_b) if shared_home else not (in_a and in_b)
