"""§1.5: local hours, the window, the home/work vote by distinct days, and the home history."""

import datetime as dt
import math
from dataclasses import replace

import pygeohash as pgh
import pytest
from typer.testing import CliRunner

from photoquiz import synth
from photoquiz.anchors import (
    MIN_SUPPORT_DAYS,
    NoNightPhotosError,
    home_eras,
    infer_anchors,
    local_day,
    local_hour,
    weekday,
)
from photoquiz.cli import _read_anchors, _write_anchors, app
from photoquiz.filters import apply_all
from photoquiz.ingest import write_parquet
from photoquiz.models import Anchors, Era, LatLon, PhotoMeta
from photoquiz.project import to_km

PDT, PST, JST, HST, EDT = -7 * 3600, -8 * 3600, 9 * 3600, -10 * 3600, -4 * 3600
HOME = LatLon(37.7605, -122.4405)
WORK = LatLon(37.7900, -122.4000)
BAR = LatLon(37.7700, -122.4200)
FRI = dt.date(2026, 10, 2)
SAT, SUN = FRI + dt.timedelta(days=1), FRI + dt.timedelta(days=2)


def photo(**kw):
    base = PhotoMeta(
        asset_id="P-1",
        utc_epoch=0,
        tz_offset_s=PDT,
        lat=HOME.lat,
        lon=HOME.lon,
        is_screenshot=False,
        burst_id=None,
        is_burst_pick=False,
        camera_make="Apple",
        camera_model="iPhone 15",
        width=4032,
        height=3024,
    )
    return replace(base, **kw)


def at(day: dt.date, hour: float, spot: LatLon = HOME, tz: int = PDT) -> PhotoMeta:
    """A photo at local wall-clock `hour` on local `day`."""
    local = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp() + hour * 3600)
    return photo(utc_epoch=local - tz, tz_offset_s=tz, lat=spot.lat, lon=spot.lon)


def days_before(day: dt.date, n: int) -> list[dt.date]:
    return [day - dt.timedelta(days=i) for i in range(n)]


def weekdays_before(day: dt.date, n: int) -> list[dt.date]:
    out, d = [], day
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= dt.timedelta(days=1)
    return out


def cell(p: LatLon) -> str:
    return pgh.encode(p.lat, p.lon, precision=7)


def infer(ps, **kw):
    kw.setdefault("now_utc", max(p.utc_epoch for p in ps))
    return infer_anchors(ps, person="a", **kw)


def km(a: LatLon, b: LatLon) -> float:
    return math.hypot(*to_km(a, b))


# local time


def test_local_hour_and_day_west_of_utc():
    p = photo(utc_epoch=at(FRI, 3.0, tz=0).utc_epoch, tz_offset_s=PDT)  # 03:00Z Fri = 20:00 Thu PDT
    assert local_hour(p) == 20
    assert local_day(p) == (FRI - dt.date(1970, 1, 1)).days - 1


def test_local_hour_east_of_utc():
    p = photo(utc_epoch=at(FRI, 20.0, tz=0).utc_epoch, tz_offset_s=JST)  # 20:00Z Fri = 05:00 Sat JST
    assert local_hour(p) == 5
    assert weekday(local_day(p)) == 5


def test_dst_uses_each_photos_own_offset():
    # 09:30Z is 01:30 in winter (PST) and 02:30 in summer (PDT)
    winter = photo(utc_epoch=at(dt.date(2026, 1, 15), 9.5, tz=0).utc_epoch, tz_offset_s=PST)
    summer = photo(utc_epoch=at(dt.date(2026, 7, 15), 9.5, tz=0).utc_epoch, tz_offset_s=PDT)
    assert (local_hour(winter), local_hour(summer)) == (1, 2)


def test_no_time_zone_means_no_local_time():
    p = photo(utc_epoch=at(FRI, 3.0).utc_epoch, tz_offset_s=None)
    assert local_hour(p) is None and local_day(p) is None


def test_pre_1970_floors():
    p = photo(utc_epoch=-1, tz_offset_s=0)  # 1969-12-31 23:59:59, a Wednesday
    assert (local_hour(p), local_day(p), weekday(local_day(p))) == (23, -1, 2)


def test_weekday_matches_python():
    epoch = dt.date(1970, 1, 1)
    for d in range(-800, 800, 37):
        assert weekday(d) == (epoch + dt.timedelta(days=d)).weekday()
    assert weekday(local_day(at(FRI, 12.0))) == 4


# hour and weekday rules


@pytest.mark.parametrize(("hour", "counts"), [(0.0, True), (5.99, True), (6.0, False), (23.99, False)])
def test_night_is_local_0_to_6(hour, counts):
    ps = [at(FRI, 3.0, HOME)] + [at(d, hour, BAR) for d in days_before(FRI - dt.timedelta(days=1), 2)]
    assert infer(ps).home_geohash7 == cell(BAR if counts else HOME)


@pytest.mark.parametrize(("hour", "counts"), [(9.99, False), (10.0, True), (15.99, True), (16.0, False)])
def test_work_is_local_10_to_16(hour, counts):
    ps = [at(FRI, 3.0), at(FRI, 12.0, WORK)] + [at(d, hour, BAR) for d in weekdays_before(FRI - dt.timedelta(days=1), 2)]
    assert infer(ps).work_geohash7 == cell(BAR if counts else WORK)


def test_weekends_do_not_count_as_work():
    ps = [at(FRI, 3.0), at(FRI, 12.0, WORK), at(SAT, 12.0, BAR), at(SUN, 12.0, BAR)]
    assert infer(ps).work_geohash7 == cell(WORK)


def test_weekday_is_local_not_utc():
    # 15:00 Sunday in Hawaii is 01:00Z Monday: still the weekend
    sundays = [SUN, SUN - dt.timedelta(days=7)]
    ps = [at(FRI, 3.0), at(FRI, 12.0, WORK)] + [at(d, 15.0, BAR, tz=HST) for d in sundays]
    assert infer(ps, now_utc=at(SUN, 23.0, tz=HST).utc_epoch).work_geohash7 == cell(WORK)


# the window


def test_window_bounds_are_inclusive():
    now = at(FRI, 3.0).utc_epoch
    oldest = at(FRI - dt.timedelta(days=90), 3.0, BAR)
    assert oldest.utc_epoch == now - 90 * 86400
    assert infer([oldest], now_utc=now).home_geohash7 == cell(BAR)
    for outside in (replace(oldest, utc_epoch=oldest.utc_epoch - 1), replace(oldest, utc_epoch=now + 1)):
        with pytest.raises(NoNightPhotosError):
            infer([outside], now_utc=now)


def test_window_days_widens():
    now = at(FRI, 3.0).utc_epoch
    old = at(FRI - dt.timedelta(days=120), 3.0)
    with pytest.raises(NoNightPhotosError, match="last 90 days"):
        infer([old], now_utc=now)
    a = infer([old], now_utc=now, window_days=180)
    assert (a.home_geohash7, a.window_days) == (cell(HOME), 180)


# the vote


def test_home_counts_nights_not_photos():
    ordinary_nights = [at(d, 2.0, HOME) for d in days_before(FRI, 6)]
    one_party = [replace(at(SAT, 2.0, BAR), utc_epoch=at(SAT, 2.0).utc_epoch + k) for k in range(40)]
    a = infer(ordinary_nights + one_party)
    assert (a.home_geohash7, a.home_nights) == (cell(HOME), 6)


def test_work_counts_weekdays_not_photos():
    ps = [at(FRI, 3.0)] + [at(d, 12.0, WORK) for d in weekdays_before(FRI, 5)]
    vacation_day = [replace(at(FRI, 11.0, BAR), utc_epoch=at(FRI, 11.0, BAR).utc_epoch + 60 * k) for k in range(40)]
    a = infer(ps + vacation_day)
    assert (a.work_geohash7, a.work_days) == (cell(WORK), 5)


def test_tie_on_days_goes_to_more_photos():
    ps = [at(d, 2.0, HOME) for d in days_before(FRI, 2)] + [at(d, h, BAR) for d in days_before(FRI, 2) for h in (1, 2)]
    assert infer(ps).home_geohash7 == cell(BAR)


def test_full_tie_goes_to_smallest_geohash_in_any_order():
    ps = [at(FRI, 2.0, HOME), at(FRI, 2.0, BAR)]
    want = min(cell(HOME), cell(BAR))
    assert infer(ps).home_geohash7 == want and infer(ps[::-1]).home_geohash7 == want


def test_photos_without_gps_or_time_zone_are_skipped():
    no_gps = [replace(at(d, 2.0), lat=None, lon=None) for d in days_before(SAT, 3)]
    no_tz = [replace(at(d, 2.0, BAR), tz_offset_s=None) for d in days_before(SAT, 3)]
    a = infer([*no_gps, *no_tz, at(FRI, 2.0, WORK)])
    assert (a.home_geohash7, a.home_nights) == (cell(WORK), 1)


def test_no_night_photo_raises():
    with pytest.raises(NoNightPhotosError):
        infer([at(FRI, 12.0, WORK)])


def test_no_work_photo_means_no_work():
    a = infer([at(FRI, 2.0)])
    assert (a.work, a.work_geohash7, a.work_days) == (None, None, 0)


def test_position_is_the_mean_of_the_winning_cell():
    lat, lon, dlat, dlon = pgh.decode_exactly(cell(HOME))
    near = [LatLon(lat - dlat / 2, lon), LatLon(lat + dlat / 2, lon - dlon / 2)]
    a = infer([at(FRI, 2.0, near[0]), at(SAT, 2.0, near[1]), at(SUN, 2.0, BAR)])
    assert a.home == LatLon((near[0].lat + near[1].lat) / 2, (near[0].lon + near[1].lon) / 2)
    assert cell(a.home) == a.home_geohash7


# home history

OLD = LatLon(40.7300, -73.9950)  # a home on the other coast
OLD_WORK = LatLon(40.7550, -73.9850)
FAR = LatLon(21.3000, -157.8500)  # a long stay away
MOVED = dt.date(2026, 8, 1)


def nights(spot: LatLon, first: dt.date, last: dt.date, every: int = 2, tz: int = PDT) -> list[PhotoMeta]:
    """A photo at 02:00 local every `every` days from first to last, inclusive."""
    return [at(first + dt.timedelta(days=d), 2.0, spot, tz) for d in range(0, (last - first).days + 1, every)]


def current(home: LatLon = HOME, work: LatLon | None = WORK) -> Anchors:
    return Anchors("a", home, work, cell(home), work and cell(work), 90, 10, 10)


def eras(ps, anchors=None, **kw):
    return home_eras(ps, anchors or current(), now_utc=max(p.utc_epoch for p in ps), **kw)


def moved_at(old: list[PhotoMeta], new: list[PhotoMeta]) -> int:
    """Halfway between just after the last night at the old home and the first at the new one."""
    return (old[-1].utc_epoch + 1 + new[0].utc_epoch) // 2


def test_one_home_throughout_is_one_era():
    ps = nights(HOME, MOVED - dt.timedelta(days=400), MOVED)
    assert eras(ps) == [Era(None, HOME, WORK, False, 201)]


def test_no_night_photo_is_one_era():
    assert eras([at(FRI, 12.0, OLD)]) == [Era(None, HOME, WORK, False, 0)]


def test_a_move_starts_the_current_era_between_the_two_homes():
    old = nights(OLD, MOVED - dt.timedelta(days=400), MOVED - dt.timedelta(days=4), tz=EDT)
    new = nights(HOME, MOVED + dt.timedelta(days=3), MOVED + dt.timedelta(days=150))
    past, now = eras(old + new)
    assert past.since_utc is None and past.inferred and km(past.home, OLD) < 0.2 and past.nights == len(old)
    assert now == Era(moved_at(old, new), HOME, WORK, False, len(new))


def test_a_move_too_recent_to_win_a_vote_still_ends_the_old_era():
    """The anchors file says home is the new place, but 90 days hold more nights at the old one."""
    old = nights(OLD, MOVED - dt.timedelta(days=400), MOVED, tz=EDT)
    new = nights(HOME, MOVED + dt.timedelta(days=2), MOVED + dt.timedelta(days=20))
    assert infer(old + new).home_geohash7 == cell(OLD)  # left alone, inference would keep the old home
    past, now = eras(old + new)
    assert past.inferred and km(past.home, OLD) < 0.2
    assert (now.since_utc, now.home, now.inferred) == (moved_at(old, new), HOME, False)


def test_a_past_home_has_its_own_work():
    first = MOVED - dt.timedelta(days=400)
    old = nights(OLD, first, MOVED - dt.timedelta(days=2), tz=EDT)
    office = [at(d, 12.0, OLD_WORK, EDT) for d in weekdays_before(MOVED - dt.timedelta(days=2), 100)]
    past, now = eras(old + office + nights(HOME, MOVED, MOVED + dt.timedelta(days=150)))
    assert km(past.work, OLD_WORK) < 0.2 and now.work == WORK


def test_a_home_typed_in_by_hand_need_not_be_exact():
    """A zip code's center a couple of km off is still the current home, not a move."""
    typed = LatLon(HOME.lat + 0.018, HOME.lon)  # 2 km north
    assert len(eras(nights(HOME, MOVED - dt.timedelta(days=400), MOVED), current(typed))) == 1


def test_a_stay_away_must_win_min_votes_in_a_row():
    """Two months away with sparse nights at home wins several votes: a past home at 3, not at 10.
    Either way, before and after it is the current home."""
    start, away, back = MOVED - dt.timedelta(days=500), MOVED - dt.timedelta(days=250), MOVED - dt.timedelta(days=190)
    ps = nights(HOME, start, away, every=7) + nights(FAR, away + dt.timedelta(days=1), back, every=1, tz=HST)
    ps += nights(HOME, back + dt.timedelta(days=1), MOVED, every=7)
    assert len(eras(ps, min_votes=10)) == 1
    before, stay, after = eras(ps, min_votes=3)
    assert (before.home, before.inferred, after.home, after.inferred) == (HOME, False, HOME, False)
    assert stay.inferred and km(stay.home, FAR) < 0.2


# on the synthetic fixture


@pytest.mark.parametrize("lib", ["a", "b"])
def test_synthetic_libraries_have_one_home(lib):
    ps, _ = apply_all(getattr(synth.generate(), lib))
    a = infer(ps)
    [era] = home_eras(ps, a, now_utc=max(p.utc_epoch for p in ps))
    assert (era.since_utc, era.home, era.work, era.inferred) == (None, a.home, a.work, False)


@pytest.mark.parametrize(("lib", "work"), [("a", synth.WORK_A), ("b", synth.WORK_B)])
def test_synthetic_anchors_land_on_the_planted_spots(lib, work):
    ps, _ = apply_all(getattr(synth.generate(), lib))
    a = infer(ps)
    assert km(a.home, synth.HOME) < 0.2 and km(a.work, work) < 0.2
    assert min(a.home_nights, a.work_days) >= MIN_SUPPORT_DAYS


# the anchors file


@pytest.mark.parametrize("work", [WORK, None])
def test_anchors_file_round_trips(tmp_path, work):
    a = Anchors("a", HOME, work, cell(HOME), work and cell(work), 90, 17, 0 if work is None else 27)
    _write_anchors(a, tmp_path / "anchors_a.toml")
    assert _read_anchors(tmp_path / "anchors_a.toml") == a


def test_cli_reruns_over_its_own_unedited_file(tmp_path):
    ps, _ = apply_all(synth.generate().a)
    write_parquet(ps, tmp_path / "a_filtered.parquet")
    run = CliRunner().invoke
    assert run(app, ["anchors", "-p", "a", "--data", str(tmp_path)]).exit_code == 0
    again = run(app, ["anchors", "-p", "a", "--window-days", "180", "--data", str(tmp_path)])
    assert again.exit_code == 0 and "window_days = 180" in (tmp_path / "anchors_a.toml").read_text()


def test_cli_keeps_hand_edits_unless_forced(tmp_path):
    ps, _ = apply_all(synth.generate().a)
    write_parquet(ps, tmp_path / "a_filtered.parquet")
    run = CliRunner().invoke
    path = tmp_path / "anchors_a.toml"

    assert run(app, ["anchors", "-p", "a", "--data", str(tmp_path)]).exit_code == 0
    edited = path.read_text() + "# hand-edited\n"
    path.write_text(edited)
    second = run(app, ["anchors", "-p", "a", "--data", str(tmp_path)])
    assert second.exit_code == 1 and "--force" in second.output and path.read_text() == edited
    assert run(app, ["anchors", "-p", "a", "--force", "--data", str(tmp_path)]).exit_code == 0
    assert path.read_text() != edited
