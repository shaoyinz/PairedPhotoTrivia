"""§1.3 rules, one at a time, then in order on the synthetic fixture."""

from dataclasses import replace

from photoquiz import synth
from photoquiz.filters import FilterStats, apply_all, collapse_bursts, drop_missing_timestamp, drop_screenshots
from photoquiz.models import PhotoMeta

T0 = 1_783_710_000


def photo(asset_id="P-1", **kw):
    base = PhotoMeta(
        asset_id=asset_id,
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


def ids(ps):
    return [p.asset_id for p in ps]


def test_screenshots_dropped_and_counted():
    ps = [photo("A"), photo("S", is_screenshot=True), photo("B")]
    kept, s = drop_screenshots(ps)
    assert ids(kept) == ["A", "B"]
    assert s == FilterStats("screenshot", 1)


def test_ios_rows_without_camera_make_are_not_screenshots():
    # The iOS exporter never fills camera_make; only the flag decides.
    ps = [photo("A", camera_make=None, camera_model=None), photo("B", camera_make=None, width=1179, height=2556)]
    kept, s = drop_screenshots(ps)
    assert ids(kept) == ["A", "B"] and s.dropped == 0


def test_missing_timestamp_dropped_and_counted():
    ps = [photo("A"), photo("N", utc_epoch=None, tz_offset_s=None), photo("B")]
    kept, s = drop_missing_timestamp(ps)
    assert ids(kept) == ["A", "B"]
    assert s == FilterStats("no_timestamp", 1)


def test_burst_keeps_the_pick():
    ps = [photo(f"B{k}", utc_epoch=T0 + k, burst_id="x", is_burst_pick=(k == 2)) for k in range(4)]
    kept, s = collapse_bursts(ps)
    assert ids(kept) == ["B2"]
    assert s == FilterStats("burst_duplicate", 3)


def test_burst_without_pick_keeps_earliest():
    ps = [photo("late", utc_epoch=T0 + 5, burst_id="x"), photo("early", utc_epoch=T0, burst_id="x")]
    assert ids(collapse_bursts(ps)[0]) == ["early"]


def test_burst_with_several_picks_keeps_earliest_pick():
    ps = [
        photo("first", utc_epoch=T0, burst_id="x"),
        photo("pick-late", utc_epoch=T0 + 3, burst_id="x", is_burst_pick=True),
        photo("pick-early", utc_epoch=T0 + 1, burst_id="x", is_burst_pick=True),
    ]
    assert ids(collapse_bursts(ps)[0]) == ["pick-early"]


def test_burst_tie_breaks_on_asset_id():
    ps = [photo("b", burst_id="x"), photo("a", burst_id="x")]
    assert ids(collapse_bursts(ps)[0]) == ["a"]


def test_burst_prefers_a_timestamp_over_none():
    ps = [photo("none", utc_epoch=None, burst_id="x"), photo("timed", utc_epoch=T0 + 9, burst_id="x")]
    assert ids(collapse_bursts(ps)[0]) == ["timed"]


def test_bursts_are_independent_and_order_is_kept():
    ps = [
        photo("y1", utc_epoch=T0 + 10, burst_id="y"),
        photo("solo", utc_epoch=T0 + 11),
        photo("x1", utc_epoch=T0 + 20, burst_id="x"),
        photo("y0", utc_epoch=T0 + 1, burst_id="y"),
        photo("x2", utc_epoch=T0 + 21, burst_id="x"),
    ]
    kept, s = collapse_bursts(ps)
    assert ids(kept) == ["solo", "x1", "y0"]
    assert s.dropped == 2


def test_duplicate_rows_collapse_to_one():
    p = photo("dup", burst_id="x")
    assert ids(collapse_bursts([p, p])[0]) == ["dup"]


def test_no_gps_photos_survive_every_rule():
    ps = [photo("A", lat=None, lon=None), photo("B", lat=None, lon=None, burst_id="x")]
    kept, stats = apply_all(ps)
    assert ids(kept) == ["A", "B"]
    assert all(s.dropped == 0 for s in stats)


def test_apply_all_counts_each_photo_once_in_rule_order():
    ps = [
        photo("ok"),
        photo("shot-no-time", is_screenshot=True, utc_epoch=None),
        photo("no-time-burst", utc_epoch=None, burst_id="x"),
        photo("burst", utc_epoch=T0 + 5, burst_id="x"),
    ]
    kept, stats = apply_all(ps)
    assert ids(kept) == ["ok", "burst"]
    assert stats == [FilterStats("screenshot", 1), FilterStats("no_timestamp", 1), FilterStats("burst_duplicate", 0)]


def test_empty_input():
    kept, stats = apply_all([])
    assert kept == [] and [s.dropped for s in stats] == [0, 0, 0]


def test_synth_fixture():
    d = synth.generate()
    kept_a, stats_a = apply_all(d.a)
    assert stats_a == [FilterStats("screenshot", 1), FilterStats("no_timestamp", 1), FilterStats("burst_duplicate", 3)]
    assert len(kept_a) == len(d.a) - 5
    burst = [p for p in kept_a if p.burst_id is not None]
    assert len(burst) == 1 and burst[0].is_burst_pick
    # B's GPS-less run at Tahoe is still there
    kept_b, stats_b = apply_all(d.b)
    assert all(s.dropped == 0 for s in stats_b)
    assert sum(not p.has_gps for p in kept_b) == sum(not p.has_gps for p in d.b) > 0
