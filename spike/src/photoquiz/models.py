"""Plain value types shared by every stage. All frozen, all slots — they port to Swift structs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NewType


@dataclass(frozen=True, slots=True)
class PhotoMeta:
    """One row of the export CSV. Field order is `schema.CSV_COLUMNS`."""

    asset_id: str
    utc_epoch: int | None  # None = no capture timestamp; dropped by filters.drop_missing_timestamp
    tz_offset_s: int | None
    lat: float | None  # None = no GPS; a measurement, not a defect
    lon: float | None
    is_screenshot: bool
    burst_id: str | None
    is_burst_pick: bool
    camera_make: str | None
    camera_model: str | None
    width: int | None
    height: int | None

    @property
    def local_epoch(self) -> int | None:
        """utc_epoch + tz_offset_s. For local-hour reasoning ONLY, never for matching."""
        if self.utc_epoch is None or self.tz_offset_s is None:
            return None
        return self.utc_epoch + self.tz_offset_s

    @property
    def has_gps(self) -> bool:
        return self.lat is not None and self.lon is not None


@dataclass(frozen=True, slots=True, order=True)
class BucketKey:
    geohash6: str
    hour_index: int  # utc_epoch // 3600


BucketHash = NewType("BucketHash", bytes)  # HMAC-SHA256 truncated to 16 bytes


@dataclass(frozen=True, slots=True)
class LatLon:
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class Anchors:
    person: str
    home: LatLon
    work: LatLon | None
    home_geohash7: str
    work_geohash7: str | None
    window_days: int
    home_nights: int  # support: distinct local days behind each anchor, so a weak one can be flagged
    work_days: int


@dataclass(frozen=True, slots=True)
class TripWindow:
    start_utc: int
    end_utc: int
    matched_bucket_count: int
    photo_count_a: int
    photo_count_b: int
    representative_geohash6: str
    away_reason: str
