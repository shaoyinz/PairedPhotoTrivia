"""Synthetic two-partner libraries with planted trips (§1.1.7).

Lets every downstream step run end to end before any real Photos export exists.

Scenario (fictional coordinates, PDT): a shared home, two different workplaces (A ~4.5 km,
B ~43 km from home), weekday commute noise inside both buffers, and
  - tahoe:     3-day trip, both partners shoot (A has a burst; B has a GPS-less run)
  - monterey:  1-day trip, only A really shoots — B has a single GPS photo, which is what
               lets the trip match at all; backfill must still pick up all of A's photos
  - near-trip: 4 matched photos away from home but inside the home city (Half Moon Bay) —
               must be rejected by the >= 5 rule
  - napa, then santa cruz two days later: two trips, out of town. The only photos between
               them are A's dinner in Oakland, outside both 5 km buffers but inside the 25 km
               home city, so it must split them (§1.7). Placed before the daily noise starts,
               with its own random stream, so it changes nothing else in the fixture
plus a screenshot, a row with no capture timestamp, and a few imported (camera-less) photos.
Every trip day has no photos overnight, so a trip must survive nights with no photos.
`labels.csv` holds exactly the four planted trips, so the near-trip would be a false positive.
"""

from __future__ import annotations

import csv
import datetime as dt
import random
from dataclasses import dataclass, field
from pathlib import Path

from photoquiz.ingest import write_csv
from photoquiz.models import LatLon, PhotoMeta
from photoquiz.project import KM_PER_DEG_LAT, KM_PER_DEG_LON
from photoquiz.report import Label
from photoquiz.schema import LABEL_COLUMNS

TZ = -7 * 3600  # PDT, fixed for the whole fixture
START = dt.date(2026, 4, 6)  # a Monday
DAYS = 120

HOME = LatLon(37.7600, -122.4400)
WORK_A = LatLon(37.7900, -122.4000)
WORK_B = LatLon(37.4430, -122.1610)

TAHOE = LatLon(39.0968, -120.0324)
MONTEREY = LatLon(36.6002, -121.8947)
HALF_MOON_BAY = LatLon(37.4636, -122.4286)
NAPA = LatLon(38.2975, -122.2869)
OAKLAND = LatLon(37.8044, -122.2712)
SANTA_CRUZ = LatLon(36.9741, -122.0308)

TAHOE_DAYS = (dt.date(2026, 7, 10), dt.date(2026, 7, 11), dt.date(2026, 7, 12))
MONTEREY_DAY = dt.date(2026, 6, 13)
NEAR_TRIP_DAY = dt.date(2026, 5, 23)
NAPA_DAY, DINNER_DAY, SANTA_CRUZ_DAY = dt.date(2026, 3, 28), dt.date(2026, 3, 29), dt.date(2026, 3, 30)  # Sat-Mon
AWAY_DATES = frozenset((*TAHOE_DAYS, MONTEREY_DAY, NEAR_TRIP_DAY, NAPA_DAY, DINNER_DAY, SANTA_CRUZ_DAY))


@dataclass
class _Lib:
    person: str
    photos: list[PhotoMeta] = field(default_factory=list)

    def add(
        self,
        utc: int | None,
        at: LatLon | None,
        *,
        screenshot: bool = False,
        burst_id: str | None = None,
        burst_pick: bool = False,
        camera: bool = True,
    ) -> None:
        self.photos.append(
            PhotoMeta(
                asset_id=f"{self.person.upper()}-{len(self.photos):05d}",
                utc_epoch=utc,
                tz_offset_s=TZ if utc is not None else None,
                lat=round(at.lat, 6) if at else None,
                lon=round(at.lon, 6) if at else None,
                is_screenshot=screenshot,
                burst_id=burst_id,
                is_burst_pick=burst_pick,
                camera_make="Apple" if camera else None,
                camera_model="iPhone 15" if camera else None,
                width=1179 if screenshot else 4032,
                height=2556 if screenshot else 3024,
            )
        )


@dataclass(frozen=True)
class SynthData:
    a: list[PhotoMeta]
    b: list[PhotoMeta]
    labels: list[Label]


def _utc(day: dt.date, local_hour: float) -> int:
    local_midnight = dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp()
    return int(local_midnight + local_hour * 3600) - TZ


def _jitter(rng: random.Random, p: LatLon, km: float) -> LatLon:
    dx, dy = rng.uniform(-km, km), rng.uniform(-km, km)
    return LatLon(p.lat + dy / KM_PER_DEG_LAT, p.lon + dx / KM_PER_DEG_LON)


def _lerp(a: LatLon, b: LatLon, t: float) -> LatLon:
    return LatLon(a.lat + (b.lat - a.lat) * t, a.lon + (b.lon - a.lon) * t)


def _daily_noise(rng: random.Random, lib: _Lib, work: LatLon) -> None:
    for i in range(DAYS):
        day = START + dt.timedelta(days=i)
        if day in AWAY_DATES:
            continue
        if rng.random() < 0.5:  # night at home -> home anchor
            lib.add(_utc(day, rng.uniform(0.5, 5.5)), _jitter(rng, HOME, 0.1))
        if day.weekday() < 5:
            if rng.random() < 0.4:  # morning commute, on the home->work segment
                at = _jitter(rng, _lerp(HOME, work, rng.uniform(0.2, 0.8)), 0.3)
                lib.add(_utc(day, rng.uniform(8.0, 9.0)), at)
            for _ in range(rng.randint(1, 2)):  # at work -> work anchor
                lib.add(_utc(day, rng.uniform(10.5, 15.5)), _jitter(rng, work, 0.15))
        else:
            for _ in range(rng.randint(2, 4)):  # weekend around home
                lib.add(_utc(day, rng.uniform(11.0, 19.0)), _jitter(rng, HOME, 2.0))
        if rng.random() < 0.03:  # imported (e.g. a messaging app): no camera, no GPS
            lib.add(_utc(day, rng.uniform(9.0, 22.0)), None, camera=False)


def _shoot(rng: random.Random, lib: _Lib, day: dt.date, hour: float, spot: LatLon, n: int) -> None:
    for _ in range(n):
        lib.add(_utc(day, hour + rng.uniform(-0.3, 0.3)), _jitter(rng, spot, 0.2))


def generate(seed: int = 7) -> SynthData:
    rng = random.Random(seed)
    a, b = _Lib("a"), _Lib("b")
    _daily_noise(rng, a, WORK_A)
    _daily_noise(rng, b, WORK_B)

    # tahoe: both shoot at three spots a day
    for d, day in enumerate(TAHOE_DAYS):
        for hour in (10.5, 13.5, 16.0):
            spot = _jitter(rng, TAHOE, 3.0)
            _shoot(rng, a, day, hour, spot, 2)
            if d == 1 and hour == 13.5:  # B's location services off for a while
                for k in range(3):
                    b.add(_utc(day, hour + 0.1 * k), None)
            else:
                _shoot(rng, b, day, hour, spot, rng.randint(1, 2))
    burst_spot, burst_t = _jitter(rng, TAHOE, 1.0), _utc(TAHOE_DAYS[0], 12.0)
    for k in range(4):
        a.add(burst_t + k, burst_spot, burst_id="burst-tahoe-1", burst_pick=(k == 2))

    # monterey: A shoots all day, B takes one photo
    for hour in (11.0, 13.0, 15.0):
        spot = _jitter(rng, MONTEREY, 2.0)
        _shoot(rng, a, MONTEREY_DAY, hour, spot, 3 if hour != 15.0 else 2)
        if hour == 13.0:
            _shoot(rng, b, MONTEREY_DAY, hour, spot, 1)

    # near-trip: 2 + 2 = 4 photos, one below the >= 5 rule
    _shoot(rng, a, NEAR_TRIP_DAY, 12.0, HALF_MOON_BAY, 2)
    _shoot(rng, b, NEAR_TRIP_DAY, 12.0, HALF_MOON_BAY, 2)

    # filter fodder
    a.add(_utc(START + dt.timedelta(days=9), 20.0), None, screenshot=True, camera=False)
    a.add(None, None)  # no capture timestamp

    # back to back, before START: its own random stream, so nothing above moves
    rng2 = random.Random(f"{seed}-back-to-back")
    for day, place in ((NAPA_DAY, NAPA), (SANTA_CRUZ_DAY, SANTA_CRUZ)):
        for hour in (11.0, 14.0):
            spot = _jitter(rng2, place, 2.0)
            _shoot(rng2, a, day, hour, spot, 2)
            _shoot(rng2, b, day, hour, spot, 2)
    _shoot(rng2, a, DINNER_DAY, 19.5, OAKLAND, 2)  # only A: evidence, not a match

    def key(p: PhotoMeta) -> tuple[bool, int]:
        return (p.utc_epoch is None, p.utc_epoch or 0)

    labels = [
        _label("tahoe", "Lake Tahoe", a.photos + b.photos, TAHOE_DAYS),
        _label("monterey", "Monterey", a.photos + b.photos, (MONTEREY_DAY,)),
        _label("napa", "Napa", a.photos + b.photos, (NAPA_DAY,)),
        _label("santa-cruz", "Santa Cruz", a.photos + b.photos, (SANTA_CRUZ_DAY,)),
    ]
    return SynthData(sorted(a.photos, key=key), sorted(b.photos, key=key), labels)


def _label(name: str, place: str, ps: list[PhotoMeta], days: tuple[dt.date, ...]) -> Label:
    """UTC dates spanning the planted photos on those local days."""
    lo, hi = _utc(days[0], 0), _utc(days[-1], 24)
    ts = [p.utc_epoch for p in ps if p.utc_epoch is not None and lo <= p.utc_epoch < hi]
    first, last = (dt.datetime.fromtimestamp(t, dt.UTC).date().isoformat() for t in (min(ts), max(ts)))
    return Label(name, first, last, place)


def write(data: SynthData, out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "a": out_dir / "a_photos.csv",
        "b": out_dir / "b_photos.csv",
        "labels": out_dir / "labels.csv",
    }
    write_csv(data.a, paths["a"])
    write_csv(data.b, paths["b"])
    with open(paths["labels"], "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(LABEL_COLUMNS)
        w.writerows((lb.label, lb.start_date, lb.end_date, lb.place) for lb in data.labels)
    return paths
