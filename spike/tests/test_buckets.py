"""§1.4 device-local half: bucket keys, neighbor expansion, salting."""

from dataclasses import replace

import pygeohash as pgh
import pytest

from photoquiz.buckets import HASH_BYTES, bucket_key, expand, salted, salted_set
from photoquiz.models import BucketKey, PhotoMeta

T0 = 1_783_710_000  # exactly on an hour boundary: hour 495475
SALT = bytes(range(32))


def photo(**kw):
    base = PhotoMeta(
        asset_id="P-1",
        utc_epoch=T0,
        tz_offset_s=-25200,
        lat=39.0968,
        lon=-120.0324,
        is_screenshot=False,
        burst_id=None,
        is_burst_pick=False,
        camera_make="Apple",
        camera_model="iPhone 15",
        width=4032,
        height=3024,
    )
    return replace(base, **kw)


# bucket_key


def test_bucket_key():
    assert bucket_key(photo()) == BucketKey("9qfwkt", 495475)


def test_hour_boundary():
    assert bucket_key(photo(utc_epoch=T0 - 1)).hour_index == 495474
    assert bucket_key(photo(utc_epoch=T0 + 3599)).hour_index == 495475


def test_hour_index_floors_before_1970():
    # Swift's `/` truncates toward zero and would say hour 0 here.
    assert bucket_key(photo(utc_epoch=-1)).hour_index == -1


def test_ignores_local_time():
    assert bucket_key(photo(tz_offset_s=3600)) == bucket_key(photo(tz_offset_s=None))


@pytest.mark.parametrize("missing", [{"lat": None, "lon": None}, {"lon": None}, {"utc_epoch": None}])
def test_no_gps_or_no_timestamp_is_none(missing):
    assert bucket_key(photo(**missing)) is None


def test_cell_edges_are_half_open():
    bb = pgh.get_bounding_box("9q8yyk")
    assert bucket_key(photo(lat=bb.min_lat, lon=bb.min_lon)).geohash6 == "9q8yyk"
    assert bucket_key(photo(lat=bb.max_lat, lon=bb.min_lon)).geohash6 == pgh.get_adjacent("9q8yyk", "top")


def test_photos_a_metre_apart_across_a_cell_edge_still_reach_each_other():
    bb = pgh.get_bounding_box("9q8yyk")
    below = bucket_key(photo(lat=bb.max_lat - 0.000005, lon=bb.min_lon + 0.001))
    above = bucket_key(photo(lat=bb.max_lat + 0.000005, lon=bb.min_lon + 0.001))
    assert below.geohash6 != above.geohash6
    assert above in expand(below)


# expand


def test_expand_is_27_cells_normally():
    assert len(expand(BucketKey("9q8yyk", 1000))) == 27


def test_expand_is_self_and_8_neighbors_times_3_hours():
    ks = expand(BucketKey("9q8yyk", 1000))
    assert {k.hour_index for k in ks} == {999, 1000, 1001}
    cells = {k.geohash6 for k in ks}
    assert "9q8yyk" in cells and len(cells) == 9
    assert {pgh.get_adjacent("9q8yyk", d) for d in ("top", "bottom", "left", "right")} < cells
    top = pgh.get_adjacent("9q8yyk", "top")
    assert pgh.get_adjacent(top, "right") in cells  # a diagonal


def test_expand_wraps_the_antimeridian():
    cells = {k.geohash6 for k in expand(BucketKey("800000", 1000))}  # lon -180
    assert len(cells) == 9 and "xbpbpb" in cells  # its left neighbor is at lon +180


@pytest.mark.parametrize("pole", ["zzzzzz", "000000"])
def test_expand_degrades_at_the_poles(pole):
    ks = expand(BucketKey(pole, 1000))
    cells = {k.geohash6 for k in ks}
    assert pole in cells and len(cells) == 6 and len(ks) == 18


def test_expand_is_symmetric():
    # b is within reach of a iff a is within reach of b, so it does not matter which side expands.
    a = BucketKey("9q8yyk", 1000)
    for b in expand(a):
        assert a in expand(b)


# salted


def test_salted_known_answer():
    # Pins the message format for the Swift port. Cross-checked with openssl:
    #   printf '9q8yyk|495475' | openssl dgst -sha256 -mac HMAC -macopt hexkey:000102…1e1f
    assert salted(BucketKey("9q8yyk", 495475), SALT).hex() == "51b474d370b9cd457d09cc95d334098d"
    assert salted(BucketKey("9q8yyk", -1), SALT).hex() == "5319a57ce6b91f855f0ff47accfee37a"


def test_salted_is_16_bytes_and_depends_on_the_salt():
    k = BucketKey("9q8yyk", 495475)
    h = salted(k, SALT)
    assert len(h) == HASH_BYTES == 16
    assert salted(k, bytes(32)) != h


@pytest.mark.parametrize("n", [0, 16, 31, 33])
def test_salted_rejects_a_salt_that_is_not_32_bytes(n):
    with pytest.raises(ValueError, match="32 bytes"):
        salted(BucketKey("9q8yyk", 495475), bytes(n))


def test_salted_set():
    ks = [BucketKey("9q8yyk", 1), BucketKey("9q8yyk", 2), BucketKey("9q8yyk", 1)]
    assert salted_set(ks, SALT) == {salted(ks[0], SALT), salted(ks[1], SALT)}
    assert salted_set([], SALT) == frozenset()
