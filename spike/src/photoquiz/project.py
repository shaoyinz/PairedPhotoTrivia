"""Pure lat/lon -> local km plane. Replaces pyproj (§1.1.0).

Flat equirectangular plane around `origin`: 188 m (0.4%) off haversine on a 44 km segment,
i.e. sub-50 m at the 5 km buffer edge. Ports to Swift as-is.
"""

from __future__ import annotations

import math

from photoquiz.models import LatLon

KM_PER_DEG_LAT = 110.574
KM_PER_DEG_LON = 111.320  # at the equator; scaled by cos(origin.lat)


def to_km(p: LatLon, origin: LatLon) -> tuple[float, float]:
    """(x east, y north) in km of `p` relative to `origin`."""
    dlon = (p.lon - origin.lon + 180.0) % 360.0 - 180.0  # shortest way across the antimeridian
    x = dlon * KM_PER_DEG_LON * math.cos(math.radians(origin.lat))
    y = (p.lat - origin.lat) * KM_PER_DEG_LAT
    return x, y
