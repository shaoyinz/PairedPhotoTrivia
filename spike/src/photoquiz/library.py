"""osxphotos -> PhotoMeta (§1.2b): the alternative to the iOS exporter where a Mac library is synced.

`ingest --library` writes these rows through the same CSV the iOS exporter emits and reads them
back with the same reader, so the two paths are interchangeable. Reads Photos' database only
(through osxphotos), never image files; the terminal needs Full Disk Access.

Selection mirrors the exporter's PhotoKit fetch: images only, nothing trashed or hidden, bursts
as Photos shows them (key or user-selected frames only — osxphotos drops the rest), and nothing
from shared albums, which hold other people's photos and would fake "together".
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from photoquiz.models import PhotoMeta


def photo_meta(info: Any) -> PhotoMeta:
    """One osxphotos `PhotoInfo` -> one CSV row. Duck-typed, so tests pass plain objects."""
    exif = info.exif_info
    make = (exif.camera_make or None) if exif else None
    return PhotoMeta(
        asset_id=info.uuid,
        utc_epoch=math.floor(info.date.timestamp()),  # `date` is tz-aware
        tz_offset_s=info.tzoffset,
        lat=info.latitude,  # osxphotos already maps Photos' -180/-180 "no location" to None
        lon=info.longitude,
        # Photos' own flag, plus §1.3's fallback for screenshots it never flagged: a PNG with no
        # camera make. The CSV has no UTI column, so this is the only place the UTI can count.
        is_screenshot=bool(info.screenshot) or (info.uti == "public.png" and make is None),
        burst_id=_burst_id(info),
        is_burst_pick=bool(info.burst_selected),
        camera_make=make,
        camera_model=(exif.camera_model or None) if exif else None,
        width=info.width,
        height=info.height,
    )


def _burst_id(info: Any) -> str | None:
    """osxphotos keeps the burst UUID private; the smallest member uuid names the set just as well."""
    if not info.burst:
        return None
    return min([info.uuid, *(p.uuid for p in info.burst_photos)])


def photo_metas(infos: Iterable[Any]) -> list[PhotoMeta]:
    """Hidden and shared-album photos dropped; sorted, so re-running gives the same CSV."""
    ps = [photo_meta(i) for i in infos if not i.hidden and not i.shared]
    return sorted(ps, key=lambda p: (p.utc_epoch, p.asset_id))


def read_library(path: Path) -> list[PhotoMeta]:
    import osxphotos  # slow to import, and only this path needs it

    db = osxphotos.PhotosDB(dbfile=str(path.expanduser()))
    return photo_metas(db.photos(images=True, movies=False))
