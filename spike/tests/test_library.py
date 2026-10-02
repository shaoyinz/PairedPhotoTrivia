"""§1.2b mapping, on stand-in PhotoInfo objects — no real library in tests."""

import datetime as dt
from types import SimpleNamespace

from photoquiz.ingest import read_csv, write_csv
from photoquiz.library import photo_meta, photo_metas

PDT = dt.timezone(dt.timedelta(hours=-7))
APPLE = SimpleNamespace(camera_make="Apple", camera_model="iPhone 15")


def info(**kw):
    base = dict(
        uuid="U-1",
        date=dt.datetime(2026, 7, 10, 12, 0, tzinfo=PDT),
        tzoffset=-7 * 3600,
        latitude=39.0968,
        longitude=-120.0324,
        screenshot=False,
        uti="public.heic",
        burst=False,
        burst_selected=False,
        burst_photos=[],
        exif_info=APPLE,
        width=4032,
        height=3024,
        hidden=False,
        shared=False,
    )
    return SimpleNamespace(**(base | kw))


def test_utc_epoch_and_offset_from_tz_aware_date():
    p = photo_meta(info())
    assert p.utc_epoch == int(dt.datetime(2026, 7, 10, 19, 0, tzinfo=dt.UTC).timestamp())
    assert p.tz_offset_s == -25200
    assert p.local_epoch == int(dt.datetime(2026, 7, 10, 12, 0, tzinfo=dt.UTC).timestamp())


def test_missing_gps_and_exif_become_empty():
    p = photo_meta(info(latitude=None, longitude=None, exif_info=None))
    assert not p.has_gps
    assert p.camera_make is None and p.camera_model is None


def test_screenshot_flag_is_kept():
    assert photo_meta(info(screenshot=True)).is_screenshot


def test_png_without_camera_make_counts_as_screenshot():
    assert photo_meta(info(uti="public.png", exif_info=None)).is_screenshot
    assert photo_meta(info(uti="public.png", exif_info=SimpleNamespace(camera_make="", camera_model=""))).is_screenshot


def test_png_from_a_camera_is_not_a_screenshot():
    assert not photo_meta(info(uti="public.png")).is_screenshot


def test_burst_members_share_one_id():
    key = info(uuid="B-2", burst=True, burst_photos=[SimpleNamespace(uuid="B-1"), SimpleNamespace(uuid="B-3")])
    pick = info(uuid="B-3", burst=True, burst_selected=True, burst_photos=[SimpleNamespace(uuid="B-1"), key])
    assert photo_meta(key).burst_id == photo_meta(pick).burst_id == "B-1"
    assert photo_meta(pick).is_burst_pick and not photo_meta(key).is_burst_pick
    assert photo_meta(info()).burst_id is None


def test_hidden_and_shared_album_photos_are_skipped():
    ps = photo_metas([info(uuid="keep"), info(uuid="hid", hidden=True), info(uuid="shr", shared=True)])
    assert [p.asset_id for p in ps] == ["keep"]


def test_rows_sorted_by_time():
    later = info(uuid="A", date=dt.datetime(2026, 7, 11, tzinfo=PDT))
    assert [p.asset_id for p in photo_metas([later, info(uuid="Z")])] == ["Z", "A"]


def test_same_csv_as_the_ios_exporter(tmp_path):
    ps = photo_metas([info(), info(uuid="U-2", latitude=None, longitude=None, exif_info=None, uti="public.png")])
    write_csv(ps, tmp_path / "a_photos.csv")
    assert read_csv(tmp_path / "a_photos.csv") == ps
