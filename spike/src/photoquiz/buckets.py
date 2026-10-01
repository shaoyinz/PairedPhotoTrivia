"""geohash6 x hour buckets, neighbor expansion, salting (§1.4)."""

from __future__ import annotations

from collections.abc import Iterable

from photoquiz.models import BucketHash, BucketKey, PhotoMeta


def bucket_key(p: PhotoMeta) -> BucketKey | None:
    """(geohash6, utc_epoch // 3600). None when no GPS — not an error."""
    raise NotImplementedError("§1.4")


def expand(k: BucketKey) -> frozenset[BucketKey]:
    """Self + 8 geohash-6 neighbors, x hours {h-1, h, h+1}: 27 keys normally.

    Neighbors come from `pygeohash.get_adjacent(gh, direction)` with the bare strings
    "right"/"left"/"top"/"bottom" (a typing.Literal, not an enum). At either pole it raises
    `ValueError: No adjacent geohash to the top…` — catch it and return the cells that exist.
    The antimeridian wraps on its own.
    """
    raise NotImplementedError("§1.4")


def salted(k: BucketKey, salt: bytes) -> BucketHash:
    """HMAC-SHA256(salt, f"{geohash6}|{hour_index}"), truncated to 16 bytes."""
    raise NotImplementedError("§1.4")


def salted_set(ks: Iterable[BucketKey], salt: bytes) -> frozenset[BucketHash]:
    raise NotImplementedError("§1.4")
