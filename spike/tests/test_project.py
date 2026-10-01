import math

import pytest

from photoquiz.models import LatLon
from photoquiz.project import to_km


def haversine_km(a: LatLon, b: LatLon) -> float:
    r = 6371.0088
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def test_origin_maps_to_zero():
    o = LatLon(37.76, -122.44)
    assert to_km(o, o) == (0.0, 0.0)


def test_commute_scale_error_under_half_a_percent():
    home, work = LatLon(37.7600, -122.4400), LatLon(37.4430, -122.1610)
    x, y = to_km(work, home)
    assert math.hypot(x, y) == pytest.approx(haversine_km(home, work), rel=0.005)


def test_antimeridian_takes_the_short_way():
    x, _ = to_km(LatLon(0.0, -179.99), LatLon(0.0, 179.99))
    assert x == pytest.approx(0.02 * 111.320, rel=1e-6)
