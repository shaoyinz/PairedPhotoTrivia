"""§1.4 across the boundary: one-sided expansion, hash intersection, each side mapping back alone."""

import datetime as dt

import pygeohash as pgh
import pytest

from photoquiz import synth
from photoquiz.buckets import (
    bucket_key,
    expand,
    matched_keys,
    matched_photos,
    own_keys,
    salted_set,
)
from photoquiz.filters import apply_all
from photoquiz.matching import match
from photoquiz.models import BucketHash, BucketKey, PhotoMeta

SALT = bytes(range(32))
H = 495475
X = "9q8yyk"


def right(gh, n=1):
    for _ in range(n):
        gh = pgh.get_adjacent(gh, "right")
    return gh


def reaches(a: BucketKey, b: BucketKey) -> bool:
    return bool(match(salted_set(expand(a), SALT), salted_set([b], SALT)))


def at(asset_id: str, gh: str | None, hour: int) -> PhotoMeta:
    """A photo ten minutes into `hour`, at the center of cell `gh` (None: no GPS)."""
    c = pgh.decode(gh) if gh else None
    return PhotoMeta(
        asset_id=asset_id,
        utc_epoch=hour * 3600 + 600,
        tz_offset_s=-25200,
        lat=c.latitude if c else None,
        lon=c.longitude if c else None,
        is_screenshot=False,
        burst_id=None,
        is_burst_pick=False,
        camera_make=None,
        camera_model=None,
        width=4032,
        height=3024,
    )


def test_match_is_the_intersection():
    h = [BucketHash(bytes([i]) * 16) for i in range(4)]
    assert match(frozenset(h[:3]), frozenset(h[1:])) == {h[1], h[2]}
    assert match(frozenset(h[:1]), frozenset(h[1:])) == frozenset()


def test_reach_is_one_cell_and_one_hour():
    a = BucketKey(X, H)
    assert reaches(a, a)
    assert reaches(a, BucketKey(pgh.get_adjacent(right(X), "top"), H + 1))  # diagonal, next hour
    assert reaches(a, BucketKey(right(X), H - 1))
    assert not reaches(a, BucketKey(right(X, 2), H))
    assert not reaches(a, BucketKey(X, H + 2))


@pytest.mark.parametrize("b", [BucketKey(right(X, 2), H), BucketKey(X, H + 2), BucketKey(right(X, 2), H - 2)])
def test_expanding_both_sides_would_have_matched(b):
    # Why only A expands: this pair is two cells and/or two hours apart, and one-sided rejects it.
    a = BucketKey(X, H)
    assert not reaches(a, b)
    assert salted_set(expand(a), SALT) & salted_set(expand(b), SALT)


def test_each_side_maps_back_alone():
    ps_a = [at("a-near", X, H), at("a-far", right(X, 5), H)]
    ps_b = [at("b-near", right(X), H + 1), at("b-no-gps", None, H), at("b-later", X, H + 3)]
    m = match(salted_set(own_keys(ps_a, expanded=True), SALT), salted_set(own_keys(ps_b, expanded=False), SALT))

    # A sees only `m` and its own expanded keys; B only `m` and its own raw keys. Same answer.
    keys_a = matched_keys(own_keys(ps_a, expanded=True), m, SALT)
    keys_b = matched_keys(own_keys(ps_b, expanded=False), m, SALT)
    assert keys_a == keys_b == {bucket_key(ps_b[0])}

    assert [p.asset_id for p in matched_photos(ps_a, keys_a, expanded=True)] == ["a-near"]
    assert [p.asset_id for p in matched_photos(ps_b, keys_b, expanded=False)] == ["b-near"]


def test_nothing_matches_under_a_different_salt():
    ps = [at("p", X, H)]
    expanded_a = salted_set(own_keys(ps, expanded=True), SALT)
    assert not match(expanded_a, salted_set(own_keys(ps, expanded=False), bytes(32)))


# The synthetic pair end to end


@pytest.fixture(scope="module")
def pair():
    d = synth.generate()
    ps_a, ps_b = apply_all(d.a)[0], apply_all(d.b)[0]
    m = match(salted_set(own_keys(ps_a, expanded=True), SALT), salted_set(own_keys(ps_b, expanded=False), SALT))
    keys_a = matched_keys(own_keys(ps_a, expanded=True), m, SALT)
    keys_b = matched_keys(own_keys(ps_b, expanded=False), m, SALT)
    return {
        "m": m,
        "keys_a": keys_a,
        "keys_b": keys_b,
        "a": matched_photos(ps_a, keys_a, expanded=True),
        "b": matched_photos(ps_b, keys_b, expanded=False),
    }


def local_days(ps):
    return {dt.datetime.fromtimestamp(p.utc_epoch + synth.TZ, dt.UTC).date() for p in ps}


def test_synth_both_sides_recover_the_same_keys(pair):
    assert pair["keys_a"] == pair["keys_b"]
    assert len(pair["keys_a"]) == len(pair["m"]) > 0  # one key per surviving hash


def test_synth_every_planted_day_matches_on_both_sides(pair):
    planted = {*synth.TAHOE_DAYS, synth.MONTEREY_DAY, synth.NEAR_TRIP_DAY}
    assert planted <= local_days(pair["a"])
    assert planted <= local_days(pair["b"])


def test_synth_monterey_matches_through_bs_single_photo(pair):
    b_monterey = [p for p in pair["b"] if local_days([p]) == {synth.MONTEREY_DAY}]
    assert len(b_monterey) == 1


def test_synth_gps_less_photos_never_match(pair):
    # B's GPS-less Tahoe run comes back through backfill (§1.7), not through matching.
    assert all(p.has_gps for p in pair["a"] + pair["b"])
