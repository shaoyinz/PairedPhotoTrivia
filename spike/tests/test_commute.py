"""§1.6: the commute buffer on each home's km plane, shared home, and what counts as away."""

import datetime as dt
import math

import pygeohash as pgh
import pytest

from photoquiz import synth
from photoquiz.anchors import infer_anchors, local_day
from photoquiz.cli import _read_anchors, _write_anchors
from photoquiz.commute import commute_buffer, is_away, is_shared_home, resolve_shared_home
from photoquiz.filters import apply_all
from photoquiz.models import Anchors, LatLon
from photoquiz.project import KM_PER_DEG_LAT, KM_PER_DEG_LON, distance_km, to_km
from photoquiz.schema import SchemaError

HOME = LatLon(37.7600, -122.4400)
SF, NYC, CHICAGO = HOME, LatLon(40.7128, -74.0060), LatLon(41.8781, -87.6298)


def off(origin: LatLon, x: float, y: float) -> LatLon:
    """The point (x east, y north) km from `origin` on its plane: the inverse of to_km."""
    km_per_deg_lon = KM_PER_DEG_LON * math.cos(math.radians(origin.lat))
    return LatLon(origin.lat + y / KM_PER_DEG_LAT, origin.lon + x / km_per_deg_lon)


def anchors(home: LatLon, shared_home: bool | None = None, person: str = "a") -> Anchors:
    return Anchors(person, home, None, "", None, 90, 10, 0, shared_home)


def test_off_inverts_to_km():
    assert to_km(off(HOME, 12.5, -3.25), HOME) == pytest.approx((12.5, -3.25), abs=1e-9)


# commute_buffer


@pytest.mark.parametrize(
    ("x", "y", "inside"),
    [
        (0.0, 0.0, True),
        (4.9, 0.0, True),
        (0.0, -4.9, True),
        (3.4, 3.4, True),  # 4.81 km
        (5.1, 0.0, False),
        (0.0, 5.1, False),
        (3.7, 3.7, False),  # 5.23 km
    ],
)
def test_no_work_is_a_disc_around_home(x, y, inside):
    assert commute_buffer(HOME, None).covers(off(HOME, x, y)) is inside


@pytest.mark.parametrize(
    ("x", "y", "inside"),
    [
        (10.0, 4.9, True),  # beside the middle of the segment
        (10.0, -4.9, True),
        (10.0, 5.1, False),
        (10.0, -5.1, False),
        (24.9, 0.0, True),  # past the work end
        (25.1, 0.0, False),
        (-4.9, 0.0, True),  # past the home end
        (-5.1, 0.0, False),
        (23.5, 3.5, True),  # round end at work: 4.95 km from it
        (23.6, 3.6, False),  # 5.09 km
    ],
)
def test_buffer_follows_the_home_to_work_segment(x, y, inside):
    assert commute_buffer(HOME, off(HOME, 20.0, 0.0)).covers(off(HOME, x, y)) is inside


def test_buffer_width_is_km():
    work, p = off(HOME, 20.0, 0.0), off(HOME, 10.0, 7.0)
    assert not commute_buffer(HOME, work).covers(p)
    assert commute_buffer(HOME, work, km=8.0).covers(p)


def test_work_at_home_is_a_disc():
    buf = commute_buffer(HOME, HOME)
    assert buf.covers(off(HOME, 0.0, 4.9)) and not buf.covers(off(HOME, 0.0, 5.1))


def test_buffer_crosses_the_antimeridian():
    home, work = LatLon(0.0, 179.99), LatLon(0.0, -179.97)  # work ~4.5 km east, across the line
    buf = commute_buffer(home, work)
    assert buf.covers(LatLon(0.0, -179.95)) and buf.covers(LatLon(0.0, 179.95))
    assert not buf.covers(LatLon(0.0, -179.90)) and not buf.covers(LatLon(0.0, 179.90))


def test_each_buffer_uses_its_own_homes_plane():
    # 4,100 km apart: on SF's plane NYC's disc would be distorted; on its own it is round
    buf = commute_buffer(NYC, None)
    assert all(buf.covers(off(NYC, x, y)) for x, y in [(4.9, 0), (-4.9, 0), (0, 4.9), (0, -4.9)])
    assert not any(buf.covers(off(NYC, x, y)) for x, y in [(5.1, 0), (-5.1, 0), (0, 5.1), (0, -5.1)])


def test_the_planted_commutes_fit_their_buffers():
    # B's 43 km commute is the longest segment the flat plane has to carry
    for work in (synth.WORK_A, synth.WORK_B):
        buf = commute_buffer(synth.HOME, work)
        x, y = to_km(work, synth.HOME)
        assert all(buf.covers(off(synth.HOME, x * t / 10, y * t / 10)) for t in range(11))


# is_shared_home


@pytest.mark.parametrize(("km", "shared"), [(0.0, True), (0.99, True), (1.01, False), (40.0, False)])
def test_shared_home_is_under_1_km(km, shared):
    assert is_shared_home(HOME, off(HOME, km * 0.6, km * 0.8)) is shared


def test_shared_home_is_by_distance_not_geohash():
    lat, lon, dlat, _ = pgh.decode_exactly(pgh.encode(HOME.lat, HOME.lon, precision=7))
    edge = lat + dlat  # the top edge of HOME's cell
    a, b = LatLon(edge - 1e-5, lon), LatLon(edge + 1e-5, lon)  # ~2 m apart
    assert pgh.encode(a.lat, a.lon, precision=7) != pgh.encode(b.lat, b.lon, precision=7)
    assert is_shared_home(a, b)


def test_far_homes_are_not_shared():
    assert not is_shared_home(SF, NYC) and not is_shared_home(NYC, SF)


# resolve_shared_home: the anchors-file override


@pytest.mark.parametrize(
    ("a_says", "b_says", "b_home", "shared"),
    [
        (None, None, off(HOME, 0.3, 0.0), True),  # by distance
        (None, None, NYC, False),
        (True, None, NYC, True),  # either file can override
        (None, True, NYC, True),
        (None, False, off(HOME, 0.3, 0.0), False),
        (False, False, off(HOME, 0.3, 0.0), False),  # both agree
    ],
)
def test_override_wins_over_distance(a_says, b_says, b_home, shared):
    assert resolve_shared_home(anchors(HOME, a_says), anchors(b_home, b_says, "b")) is shared


def test_disagreeing_overrides_raise():
    with pytest.raises(ValueError, match="differently"):
        resolve_shared_home(anchors(HOME, True), anchors(HOME, False, "b"))


@pytest.mark.parametrize("shared", [True, False, None])
def test_override_round_trips_through_the_anchors_file(tmp_path, shared):
    a = anchors(HOME, shared)
    _write_anchors(a, tmp_path / "anchors_a.toml")
    assert _read_anchors(tmp_path / "anchors_a.toml") == a


def test_uncommenting_the_hint_sets_the_override(tmp_path):
    path = tmp_path / "anchors_a.toml"
    _write_anchors(anchors(HOME), path)
    assert "# shared_home = true" in path.read_text()
    path.write_text(path.read_text().replace("# shared_home = true", "shared_home = true"))
    assert _read_anchors(path).shared_home is True


def test_override_must_be_a_bool(tmp_path):
    path = tmp_path / "anchors_a.toml"
    _write_anchors(anchors(HOME), path)
    path.write_text(path.read_text().replace("# shared_home = true", 'shared_home = "yes"'))
    with pytest.raises(SchemaError, match="true or false"):
        _read_anchors(path)


# is_away

# A's disc at HOME and B's disc 6 km east overlap between x = 1 and x = 5
BUF_A, BUF_B = commute_buffer(HOME, None), commute_buffer(off(HOME, 6.0, 0.0), None)
BOTH, ONLY_A, ONLY_B, NEITHER = off(HOME, 3.0, 0.0), off(HOME, -3.0, 0.0), off(HOME, 9.0, 0.0), off(HOME, 3.0, 20.0)


@pytest.mark.parametrize(
    ("p", "away_if_shared", "away_if_different"),
    [
        (BOTH, False, False),
        (ONLY_A, False, True),
        (ONLY_B, False, True),
        (NEITHER, True, True),
    ],
)
def test_away_rule_truth_table(p, away_if_shared, away_if_different):
    assert is_away(p, BUF_A, BUF_B, shared_home=True) is away_if_shared
    assert is_away(p, BUF_A, BUF_B, shared_home=False) is away_if_different


def test_visiting_each_other_counts():
    buf_sf, buf_nyc = commute_buffer(SF, None), commute_buffer(NYC, None)
    shared = is_shared_home(SF, NYC)
    assert not shared
    assert is_away(SF, buf_sf, buf_nyc, shared_home=shared)
    assert is_away(NYC, buf_sf, buf_nyc, shared_home=shared)
    assert is_away(CHICAGO, buf_sf, buf_nyc, shared_home=shared)


def test_a_shared_home_is_never_away():
    buf_a, buf_b = commute_buffer(HOME, off(HOME, 20.0, 0.0)), commute_buffer(HOME, off(HOME, 0.0, -30.0))
    for p in (HOME, off(HOME, 15.0, 1.0), off(HOME, 1.0, -25.0)):  # home, A's commute, B's commute
        assert not is_away(p, buf_a, buf_b, shared_home=True)
    assert is_away(off(HOME, 15.0, -15.0), buf_a, buf_b, shared_home=True)


# on the synthetic fixture


def test_synthetic_photos_are_away_exactly_on_the_planted_days():
    """Inferred anchors, every GPS photo of both partners: away <=> taken on a trip or near-trip day.
    The near-trip is away too; only the >= 5 rule (§1.7) may drop it."""
    data = synth.generate()
    libs = [apply_all(ps)[0] for ps in (data.a, data.b)]
    a, b = (infer_anchors(ps, person=n, now_utc=max(p.utc_epoch for p in ps)) for n, ps in zip("ab", libs))
    assert distance_km(a.home, b.home) < 0.2 and resolve_shared_home(a, b)

    buf_a, buf_b = commute_buffer(a.home, a.work), commute_buffer(b.home, b.work)
    away_days = {(d - dt.date(1970, 1, 1)).days for d in synth.AWAY_DATES}
    gps = [p for ps in libs for p in ps if p.has_gps]
    away = {p.asset_id for p in gps if is_away(LatLon(p.lat, p.lon), buf_a, buf_b, shared_home=True)}
    assert away == {p.asset_id for p in gps if local_day(p) in away_days}
    assert 0 < len(away) < len(gps)
