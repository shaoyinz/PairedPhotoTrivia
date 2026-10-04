"""§1.7: away buckets in sessions, joined across nights until someone is back in their home city,
then the reach, backfill and the >= 5 rule; each hour judged against the homes you had then, and
old-home days."""

import datetime as dt
import json

import pygeohash as pgh
import pytest
from typer.testing import CliRunner

from photoquiz import synth
from photoquiz.anchors import home_eras, infer_anchors
from photoquiz.buckets import bucket_key, expand, matched_keys, matched_photos, own_keys, salted_set
from photoquiz.cli import app
from photoquiz.commute import commute_buffer
from photoquiz.filters import apply_all
from photoquiz.matching import match
from photoquiz.models import OLD_HOME, TRIP, Anchors, BucketKey, Era, LatLon, PhotoMeta, TripWindow
from photoquiz.trips import (
    CITY_KM,
    Homes,
    assemble,
    backfill,
    cell_center,
    join_nights,
    photos_in,
    sessionize,
    window,
)

SALT = bytes(range(32))
H = 495475  # an hour index
HOME = LatLon(37.7600, -122.4400)
WORK = LatLon(37.7900, -122.4000)
IN_TOWN = LatLon(37.8044, -122.2712)  # Oakland: ~15 km out, past the 5 km buffers, inside the 25 km city
B_HOME = LatLon(37.4430, -122.1610)  # 43 km from HOME
NAPA = LatLon(38.2975, -122.2869)  # ~60 km: out of town
TAHOE = LatLon(39.0968, -120.0324)
TAHOE_2 = LatLon(39.0500, -120.1000)  # ~7 km away, another cell


def cell(p: LatLon) -> str:
    return pgh.encode(p.lat, p.lon, precision=6)


def key(p: LatLon, hour: int) -> BucketKey:
    return BucketKey(cell(p), hour)


def photo(asset_id: str, utc: int | None, at: LatLon | None = TAHOE) -> PhotoMeta:
    return PhotoMeta(
        asset_id=asset_id,
        utc_epoch=utc,
        tz_offset_s=synth.TZ,
        lat=at.lat if at else None,
        lon=at.lon if at else None,
        is_screenshot=False,
        burst_id=None,
        is_burst_pick=False,
        camera_make="Apple",
        camera_model="iPhone 15",
        width=4032,
        height=3024,
    )


def shots(person: str, n: int, hour: int = H) -> list[PhotoMeta]:
    return [photo(f"{person}-{i}", hour * 3600 + 600 + i) for i in range(n)]


def anchors(person: str, home: LatLon, work: LatLon | None = None, shared_home: bool | None = None) -> Anchors:
    return Anchors(person, home, work, "", None, 90, 10, 0, shared_home)


SHARED = anchors("a", HOME, WORK), anchors("b", HOME)
APART = anchors("a", HOME), anchors("b", B_HOME)


def test_the_test_places_sit_where_they_say():
    buf, city = commute_buffer(HOME, WORK), commute_buffer(HOME, WORK, CITY_KM)
    assert not buf.covers(IN_TOWN) and city.covers(IN_TOWN)
    assert not city.covers(NAPA) and not commute_buffer(B_HOME, None, CITY_KM).covers(HOME)


# sessionize


def test_no_matches_no_sessions():
    assert sessionize([]) == []


@pytest.mark.parametrize("gap", [2, 6, 24])
def test_a_gap_over_gap_hours_starts_a_new_session(gap):
    k = key(TAHOE, H)
    assert sessionize([k, key(TAHOE, H + gap)], gap_hours=gap) == [[k, key(TAHOE, H + gap)]]
    assert sessionize([k, key(TAHOE, H + gap + 1)], gap_hours=gap) == [[k], [key(TAHOE, H + gap + 1)]]


def test_short_gaps_chain_past_gap_hours():
    ks = [key(TAHOE, H + 5 * i) for i in range(4)]  # spans 15 h, no gap over 6
    assert sessionize(ks, gap_hours=6) == [ks]


def test_sessions_are_ordered_by_hour_not_by_bucket_key():
    late_low, early_high = BucketKey("000000", H + 10), BucketKey("zzzzzz", H)
    assert sorted([late_low, early_high]) == [late_low, early_high]  # the trap: BucketKey sorts by geohash
    assert sessionize([late_low, early_high], gap_hours=6) == [[early_high], [late_low]]
    same_hour = [BucketKey("9qfwm5", H), BucketKey("9qfwm4", H)]
    assert sessionize(same_hour) == [sorted(same_hour)]


def test_duplicate_keys_count_once():
    k = key(TAHOE, H)
    assert sessionize([k, k, key(TAHOE_2, H)]) == [sorted([k, key(TAHOE_2, H)])]


@pytest.mark.parametrize("p", [TAHOE, LatLon(-33.8688, 151.2093), LatLon(64.0, 179.999), LatLon(0.0, 0.0)])
def test_cell_center_lies_in_its_cell(p):
    assert cell(cell_center(key(p, H))) == cell(p)


# join_nights: a trip ends back in the home city, not when the photos pause

DAY_1 = [key(TAHOE, H), key(TAHOE, H + 2)]
DAY_2 = [key(TAHOE_2, H + 20)]
NIGHT = (H + 10) * 3600


def join(sessions, ps_a=(), ps_b=(), *, apart=False, **kw):
    return join_nights(sessions, Homes.of(*(APART if apart else SHARED)), ps_a=ps_a, ps_b=ps_b, **kw)


def test_a_silent_night_out_of_town_joins_the_days():
    assert join([DAY_1, DAY_2]) == [DAY_1 + DAY_2]


@pytest.mark.parametrize("where", [HOME, WORK, IN_TOWN])
@pytest.mark.parametrize("who", ["a", "b"])
def test_either_partner_seen_back_in_the_home_city_ends_the_trip(who, where):
    seen = [photo(who, NIGHT, at=where)]
    ps = {"ps_a": seen} if who == "a" else {"ps_b": seen}
    assert join([DAY_1, DAY_2], **ps) == [DAY_1, DAY_2]


def test_photos_elsewhere_or_without_gps_keep_the_trip():
    elsewhere, no_gps = photo("a", NIGHT, at=NAPA), photo("b", NIGHT, at=None)
    assert join([DAY_1, DAY_2], [elsewhere], [no_gps]) == [DAY_1 + DAY_2]


def test_sessions_in_town_never_join():
    in_town = [key(IN_TOWN, H + 20)]
    assert join([[key(IN_TOWN, H)], in_town]) == [[key(IN_TOWN, H)], in_town]
    assert join([DAY_1, in_town]) == [DAY_1, in_town]


def test_the_trip_ends_after_max_silence_hours_without_a_located_photo():
    far = [key(TAHOE, H + 101)]  # 100 h after DAY_1's hour ends
    lo = (H + 1) * 3600
    assert join([[key(TAHOE, H)], far]) == [[key(TAHOE, H)], far]
    assert join([[key(TAHOE, H)], far], max_silence_hours=100) == [[key(TAHOE, H)] + far]
    steady = [photo("a", lo + h * 3600) for h in (40, 80)]  # never 72 h without one
    assert join([[key(TAHOE, H)], far], steady) == [[key(TAHOE, H)] + far]
    no_gps = [photo("a", lo + h * 3600, at=None) for h in (40, 80)]
    assert join([[key(TAHOE, H)], far], no_gps) == [[key(TAHOE, H)], far]


def test_each_partners_silence_is_timed_alone():
    """So each phone can answer alone. Taken together, these two never leave 72 h without a photo."""
    far = [key(TAHOE, H + 121)]
    lo = (H + 1) * 3600
    a, b = [photo("a", lo + 40 * 3600)], [photo("b", lo + 80 * 3600)]  # each alone: an 80 h silence
    assert join([[key(TAHOE, H)], far], a, b) == [[key(TAHOE, H)], far]


def test_the_hosts_photos_at_home_do_not_end_a_visit():
    """Different homes, together at B's place: B at home is the visit; A back home ends it."""
    day_1, day_2 = [key(B_HOME, H)], [key(B_HOME, H + 20)]
    assert join([day_1, day_2], ps_b=[photo("b", NIGHT, at=B_HOME)], apart=True) == [day_1 + day_2]
    assert join([day_1, day_2], ps_a=[photo("a", NIGHT, at=HOME)], apart=True) == [day_1, day_2]


# window


def test_window_is_the_trip_plus_the_reach():
    assert window([key(TAHOE, H), key(TAHOE, H + 2)], reach_hours=3) == ((H - 3) * 3600, (H + 6) * 3600)
    assert window([key(TAHOE, H)], reach_hours=0) == (H * 3600, (H + 1) * 3600)


@pytest.mark.parametrize("gap", range(0, 31))
def test_neighbouring_windows_never_overlap_at_half_the_gap(gap):
    first, second = sessionize([key(TAHOE, H), key(TAHOE, H + gap + 1)], gap_hours=gap)
    assert window(first, reach_hours=gap // 2)[1] <= window(second, reach_hours=gap // 2)[0]


def test_a_reach_over_half_the_gap_is_refused():
    with pytest.raises(ValueError, match="half"):
        assemble([key(TAHOE, H)], *SHARED, ps_a=[], ps_b=[], gap_hours=4, reach_hours=3)


@pytest.mark.parametrize("reach", [1, 3, 12])
def test_window_holds_every_photo_that_matched(reach):
    """A matches B's key from one cell and one hour away, so A's photo can sit in hour H-1 or H+1."""
    k = key(TAHOE, H)
    start, end = window([k], reach_hours=reach)
    for t in ((H - 1) * 3600, (H + 2) * 3600 - 1):  # the first and last second A can match from
        p = photo("a", t)
        assert k in expand(bucket_key(p))
        assert start <= t < end


# backfill


def test_window_is_half_open_and_takes_any_photo_in_it():
    start, end = 1_000_000, 1_003_600
    ps = [
        photo("before", start - 1),
        photo("first", start),
        photo("no-gps", start + 60, at=None),
        photo("last", end - 1),
        photo("after", end),
        photo("no-time", None),
    ]
    assert [p.asset_id for p in photos_in(start, end, ps)] == ["first", "no-gps", "last"]


def test_backfill_counts_each_partner():
    w = TripWindow(H * 3600, (H + 1) * 3600, 1, 0, 0, cell(TAHOE), "")
    ps_b = [photo("b-0", H * 3600), photo("b-1", H * 3600 + 5, at=None), photo("b-2", (H + 1) * 3600)]
    got = backfill(w, shots("a", 3), ps_b)
    assert (got.photo_count_a, got.photo_count_b) == (3, 2)
    assert got.start_utc == w.start_utc and got.away_reason == w.away_reason


# assemble


def test_a_trip_at_home_is_never_a_trip():
    matched = [key(HOME, H), key(WORK, H + 1)]  # inside A's commute buffer, shared home
    assert assemble(matched, *SHARED, ps_a=shots("a", 20), ps_b=shots("b", 20)) == []


def test_home_buckets_never_join_a_trip():
    [w] = assemble([key(HOME, H - 2), key(TAHOE, H)], *SHARED, ps_a=shots("a", 3), ps_b=shots("b", 2))
    assert w.matched_bucket_count == 1
    assert (w.start_utc, w.end_utc) == window([key(TAHOE, H)])
    assert w.representative_geohash6 == cell(TAHOE)


def test_nights_join_into_one_trip():
    matched = DAY_1 + DAY_2
    [w] = assemble(matched, *SHARED, ps_a=shots("a", 3), ps_b=shots("b", 2))
    assert w.matched_bucket_count == 3 and (w.start_utc, w.end_utc) == window(matched)
    assert w.away_reason == "shared home: out of town, 2 sessions"


@pytest.mark.parametrize(
    ("matched", "homes", "reason"),
    [
        ([key(IN_TOWN, H)], SHARED, "shared home: in town, 1 session"),
        ([key(B_HOME, H)], APART, "different homes: in b's city, 1 session"),  # A visiting B
        (
            [key(TAHOE, H), key(HOME, H + 1), key(B_HOME, H + 2)],
            APART,
            "different homes: out of town + in a's city + in b's city, 1 session",
        ),
    ],
)
def test_reason_says_where_the_trip_was(matched, homes, reason):
    [w] = assemble(matched, *homes, ps_a=shots("a", 5), ps_b=[])
    assert w.away_reason == reason


def test_told_they_live_together_a_visit_is_home():
    told = anchors("a", HOME, shared_home=True), APART[1]
    assert assemble([key(B_HOME, H)], *told, ps_a=shots("a", 3), ps_b=shots("b", 2)) == []


def test_representative_is_the_out_of_town_cell_with_the_most_hours():
    matched = [key(IN_TOWN, H + i) for i in range(3)] + [key(TAHOE, H + 3)]  # in town has more hours
    [w] = assemble(matched, *SHARED, ps_a=shots("a", 5), ps_b=[])
    assert w.representative_geohash6 == cell(TAHOE)
    tie = [key(TAHOE, H + 1), key(TAHOE_2, H)]  # one hour each: the earlier wins
    [w] = assemble(tie, *SHARED, ps_a=shots("a", 5), ps_b=[])
    assert w.representative_geohash6 == cell(TAHOE_2)


def test_disagreeing_shared_home_raises():
    a, b = anchors("a", HOME, shared_home=True), anchors("b", HOME, shared_home=False)
    with pytest.raises(ValueError, match="differently"):
        assemble([key(TAHOE, H)], a, b, ps_a=[], ps_b=[])


@pytest.mark.parametrize(
    ("n_a", "n_b", "min_photos", "kept"),
    [
        (3, 2, 5, True),
        (5, 0, 5, True),  # one partner alone can carry it
        (2, 2, 5, False),
        (4, 0, 5, False),
        (2, 2, 4, True),
    ],
)
def test_min_photos_across_both_devices(n_a, n_b, min_photos, kept):
    ws = assemble([key(TAHOE, H)], *SHARED, ps_a=shots("a", n_a), ps_b=shots("b", n_b), min_photos=min_photos)
    assert bool(ws) is kept


def test_backfill_reaches_what_one_partner_shot_alone():
    """B's single GPS photo makes the match; A's unmatched photos and B's GPS-less ones make the trip."""
    start, end = window([key(TAHOE, H)])  # H-3 .. H+4
    ps_a = [photo("a-first", start), photo("a-last", end - 1), photo("a-early", start - 1), photo("a-late", end)]
    ps_b = [photo("b-gps", H * 3600 + 600), photo("b-0", H * 3600 + 900, at=None), photo("b-1", H * 3600 + 960, at=None)]
    [w] = assemble([key(TAHOE, H)], *SHARED, ps_a=ps_a, ps_b=ps_b)
    assert (w.photo_count_a, w.photo_count_b) == (2, 3)


# home history: a home in OLD_CITY until MOVE, then the anchors' homes

OLD_CITY = LatLon(47.6062, -122.3321)  # ~1,100 km from HOME
MOVE = H + 1000  # an hour index; H and the days after it come before the move


def lived(then_a: LatLon = OLD_CITY, then_b: LatLon = OLD_CITY, homes=SHARED, move: int = MOVE) -> dict:
    """Each partner's eras: a past home until `move`, then their anchors' home."""
    return {
        f"eras_{x.person}": [Era(None, then, None, True, 30), Era(move * 3600, x.home, x.work, False, 30)]
        for x, then in zip(homes, (then_a, then_b))
    }


def test_a_day_at_a_home_you_have_since_left_is_an_old_home_day():
    [w] = assemble([key(OLD_CITY, H)], *SHARED, ps_a=shots("a", 3), ps_b=shots("b", 2), **lived())
    assert (w.kind, w.away_reason) == (OLD_HOME, "old home: shared home then")
    assert (w.start_utc, w.end_utc, w.representative_geohash6) == (*window([key(OLD_CITY, H)]), cell(OLD_CITY))


def test_without_a_home_history_the_old_home_is_a_trip():
    [w] = assemble([key(OLD_CITY, H)], *SHARED, ps_a=shots("a", 3), ps_b=shots("b", 2))
    assert (w.kind, w.away_reason) == (TRIP, "shared home: out of town, 1 session")


@pytest.mark.parametrize(
    ("place", "hour", "reason"),
    [
        (TAHOE, H, "shared home then: out of town, 1 session"),  # a trip while living in the old city
        (HOME, H, "shared home then: out of town, 1 session"),  # a visit to the city you later moved to
        (OLD_CITY, MOVE + 10, "shared home: out of town, 1 session"),  # back for a visit after the move
    ],
)
def test_each_hour_is_judged_against_the_homes_you_had_then(place, hour, reason):
    [w] = assemble([key(place, hour)], *SHARED, ps_a=shots("a", 5, hour), ps_b=[], **lived())
    assert (w.kind, w.away_reason) == (TRIP, reason)


def test_home_now_is_neither_a_trip_nor_an_old_home_day():
    assert assemble([key(HOME, MOVE + 10)], *SHARED, ps_a=shots("a", 5, MOVE + 10), ps_b=[], **lived()) == []


def test_old_home_days_never_join_across_nights():
    days = [key(OLD_CITY, H), key(OLD_CITY, H + 20)]
    ws = assemble(days, *SHARED, ps_a=shots("a", 5, H) + shots("a", 5, H + 20), ps_b=[], **lived())
    assert [(w.kind, w.matched_bucket_count) for w in ws] == [(OLD_HOME, 1), (OLD_HOME, 1)]


def test_where_an_old_home_day_would_overlap_a_trip_the_trip_wins():
    """Back from a day trip, photos at home that evening: windows H-3..H+4 and H+2..H+9."""
    trip_day, evening = [key(TAHOE, H)], [key(OLD_CITY, H + 5)]
    ps_a = shots("a", 5, H) + shots("a", 5, H + 5)
    assert [w.kind for w in assemble(trip_day + evening, *SHARED, ps_a=ps_a, ps_b=[], **lived())] == [TRIP]
    assert [w.kind for w in assemble(evening, *SHARED, ps_a=ps_a, ps_b=[], **lived())] == [OLD_HOME]


@pytest.mark.parametrize(("n", "kept"), [(4, False), (5, True)])
def test_an_old_home_day_needs_min_photos_too(n, kept):
    assert bool(assemble([key(OLD_CITY, H)], *SHARED, ps_a=shots("a", n), ps_b=[], **lived())) is kept


@pytest.mark.parametrize(("where", "joined"), [(OLD_CITY, False), (HOME, True)])
def test_a_trip_from_a_past_home_ends_back_in_that_city(where, joined):
    """Before the move, a night at today's home is just somewhere else; a night in the old city is home."""
    homes = Homes.of(*SHARED, **lived())
    got = join_nights([DAY_1, DAY_2], homes, ps_a=[photo("a", NIGHT, at=where)], ps_b=[])
    assert got == ([DAY_1 + DAY_2] if joined else [DAY_1, DAY_2])


def test_the_shared_home_override_holds_only_for_confirmed_homes():
    """Told they live together now, though 43 km apart; their past homes, never confirmed, go by distance."""
    told = anchors("a", HOME, shared_home=True), anchors("b", B_HOME)
    homes = Homes.of(*told, **lived(then_b=LatLon(OLD_CITY.lat + 0.4, OLD_CITY.lon), homes=told))  # 44 km then
    assert homes.now.shared_home and not homes.now.past
    assert not homes.at(H * 3600).shared_home and homes.at(H * 3600).past
    assert Homes.of(*told, **lived(homes=told)).at(H * 3600).shared_home  # one old home: shared then


def test_each_partner_moves_on_their_own_date():
    later = Era((MOVE + 100) * 3600, HOME, None, False, 30)
    homes = Homes.of(*SHARED, **(lived() | {"eras_b": [Era(None, OLD_CITY, None, True, 30), later]}))
    assert homes.changes == (MOVE * 3600, (MOVE + 100) * 3600)
    between = homes.at((MOVE + 50) * 3600)
    assert between.past and not between.shared_home  # A home already, B still in the old city
    assert homes.at(MOVE * 3600 - 1).shared_home and homes.now.shared_home and not homes.now.past


# on the synthetic fixture


@pytest.fixture(scope="module")
def fixture():
    data = synth.generate()
    a, b = (apply_all(ps)[0] for ps in (data.a, data.b))
    an_a, an_b = (infer_anchors(ps, person=n, now_utc=max(p.utc_epoch for p in ps)) for n, ps in zip("ab", (a, b)))
    own_a = own_keys(a, expanded=True)
    keys = matched_keys(own_a, match(salted_set(own_a, SALT), salted_set(own_keys(b, expanded=False), SALT)), SALT)
    return a, b, an_a, an_b, sorted(keys)


def local_date(utc: int) -> dt.date:
    return dt.date(1970, 1, 1) + dt.timedelta(days=(utc + synth.TZ) // 86_400)


def dates(w: TripWindow) -> tuple[dt.date, dt.date]:
    return local_date(w.start_utc), local_date(w.end_utc - 1)


def test_synthetic_trips_are_the_planted_trips(fixture):
    a, b, an_a, an_b, keys = fixture
    ws = assemble(keys, an_a, an_b, ps_a=a, ps_b=b)
    assert [dates(w) for w in ws] == [
        (synth.NAPA_DAY, synth.NAPA_DAY),
        (synth.SANTA_CRUZ_DAY, synth.SANTA_CRUZ_DAY),
        (synth.MONTEREY_DAY, synth.MONTEREY_DAY),
        (synth.TAHOE_DAYS[0], synth.TAHOE_DAYS[-1]),
    ]
    assert [w.away_reason for w in ws] == ["shared home: out of town, 1 session"] * 3 + [
        "shared home: out of town, 3 sessions"
    ]

    away = assemble(keys, an_a, an_b, ps_a=a, ps_b=b, min_photos=0)
    [near] = [w for w in away if dates(w)[0] == synth.NEAR_TRIP_DAY]
    assert (near.photo_count_a, near.photo_count_b) == (2, 2)
    assert near.away_reason == "shared home: in town, 1 session"
    assert [w for w in away if w != near] == ws


def test_synthetic_tahoe_is_one_trip_through_two_silent_nights(fixture):
    a, b, an_a, an_b, keys = fixture
    [w] = [w for w in assemble(keys, an_a, an_b, ps_a=a, ps_b=b) if dates(w)[0] == synth.TAHOE_DAYS[0]]
    assert (w.photo_count_a, w.photo_count_b) == (19, 16)
    assert w.photo_count_a == sum(local_date(p.utc_epoch) in synth.TAHOE_DAYS for p in a)


def test_synthetic_oakland_dinner_splits_napa_from_santa_cruz(fixture):
    """With only the 5 km buffers as home, A's dinner 15 km out is no evidence and the two trips merge."""
    a, b, an_a, an_b, keys = fixture
    merged = assemble(keys, an_a, an_b, ps_a=a, ps_b=b, city_km=5.0)[0]
    assert dates(merged) == (synth.NAPA_DAY, synth.SANTA_CRUZ_DAY)


def test_synthetic_monterey_backfills_all_of_as_photos(fixture):
    a, b, an_a, an_b, keys = fixture
    [w] = [w for w in assemble(keys, an_a, an_b, ps_a=a, ps_b=b) if dates(w)[0] == synth.MONTEREY_DAY]
    monterey = frozenset(k for k in keys if local_date(k.hour_index * 3600) == synth.MONTEREY_DAY)
    assert w.matched_bucket_count == len(monterey) == 1 and (w.photo_count_a, w.photo_count_b) == (8, 1)
    in_window = photos_in(w.start_utc, w.end_utc, a)
    assert w.photo_count_a == sum(local_date(p.utc_epoch) == synth.MONTEREY_DAY for p in a) == len(in_window)
    assert len(matched_photos(a, monterey, expanded=True)) == 3  # A's other 5 come from backfill


def test_synthetic_home_history_changes_nothing(fixture):
    """One home each, so judging each hour against the homes of the time is judging it against the anchors."""
    a, b, an_a, an_b, keys = fixture
    eras = {
        f"eras_{an.person}": home_eras(ps, an, now_utc=max(p.utc_epoch for p in ps))
        for ps, an in ((a, an_a), (b, an_b))
    }
    assert assemble(keys, an_a, an_b, ps_a=a, ps_b=b, **eras) == assemble(keys, an_a, an_b, ps_a=a, ps_b=b)


def test_synthetic_windows_never_overlap(fixture):
    a, b, an_a, an_b, keys = fixture
    ws = assemble(keys, an_a, an_b, ps_a=a, ps_b=b, min_photos=0)
    assert all(prev.end_utc <= nxt.start_utc for prev, nxt in zip(ws, ws[1:]))


def test_cli_writes_trips_json(tmp_path):
    run, d = CliRunner().invoke, ["--data", str(tmp_path)]
    steps = [
        ["synth", "--out", str(tmp_path)],
        *(["ingest", "-p", p, *d] for p in "ab"),
        *(["filter", "-p", p, *d] for p in "ab"),
        ["buckets", "-p", "a", "--expand", *d],
        ["buckets", "-p", "b", "--raw", *d],
        ["match", *d],
        *(["anchors", "-p", p, *d] for p in "ab"),
    ]
    for args in steps:
        assert run(app, args).exit_code == 0, args
    out = run(app, ["trips", *d])
    assert out.exit_code == 0
    assert "away=5 trips=4 old_home=0" in out.output and out.output.count("under 5 photos:") == 1
    assert "homes a: one home throughout" in out.output and "homes b: one home throughout" in out.output
    ws = [TripWindow(**w) for w in json.loads((tmp_path / "trips.json").read_text())]
    assert [dates(w)[0] for w in ws] == [synth.NAPA_DAY, synth.SANTA_CRUZ_DAY, synth.MONTEREY_DAY, synth.TAHOE_DAYS[0]]
    assert run(app, ["trips", "--gap-hours", "4", *d]).exit_code == 2  # reach 3 > half of 4
    out = run(app, ["trips", "--no-past-homes", *d])
    assert out.exit_code == 0 and "trips=4" in out.output and "homes a:" not in out.output
